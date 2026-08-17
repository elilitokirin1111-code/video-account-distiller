"""Content-addressed local media analysis with graceful decoder degradation."""

from __future__ import annotations

import json
import math
import shutil
import sys
from array import array
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path
from statistics import fmean, pvariance
from tempfile import TemporaryDirectory
from typing import Any, Literal

from jinja2 import Environment, StrictUndefined

from video_account_distiller.config import load_config
from video_account_distiller.distillation.craft import PACING_FAST_MS, PACING_MEDIUM_MS
from video_account_distiller.errors import DistillerError, ErrorCode
from video_account_distiller.media.backend import (
    FFmpegMediaBackend,
    MediaBackend,
    MediaBackendFailure,
)
from video_account_distiller.media.providers import (
    StructuredVisionFileProvider,
    VisionModelProvider,
    VisionProviderUnavailable,
    VisionSchemaFailure,
)
from video_account_distiller.models import (
    AudioFeatures,
    KeyframeEvidence,
    MediaAnalysis,
    MediaEvidenceIndex,
    MediaEvidenceItem,
    MediaFeatureRecord,
    MediaMetadata,
    MediaVisionAnnotation,
    MediaVisionBundle,
    ShotSegment,
    ShotVisualAnnotation,
    SilenceInterval,
    VisionInputKeyframe,
    VisionInputShot,
    VisionTaskTrace,
)
from video_account_distiller.storage.parquet import read_models, write_models
from video_account_distiller.storage.project import ProjectLayout
from video_account_distiller.utils.hashing import sha256_file, sha256_json
from video_account_distiller.utils.ids import stable_id
from video_account_distiller.utils.io import atomic_write_json, atomic_write_text, read_json
from video_account_distiller.utils.lookup import resolve_video

MEDIA_ANALYSIS_VERSION = "1.1.1"


def _pacing_tags(average_shot_duration_ms: float | None) -> list[str]:
    """Derive an editing-rhythm tag from the measured average shot duration."""
    if average_shot_duration_ms is None:
        return []
    if average_shot_duration_ms < PACING_FAST_MS:
        return ["快节奏剪辑"]
    if average_shot_duration_ms <= PACING_MEDIUM_MS:
        return ["中等节奏剪辑"]
    return ["慢节奏剪辑"]


def _opening_technique_tags(annotation: ShotVisualAnnotation | None) -> list[str]:
    """Derive opening-technique tags from the first shot's visible craft labels.

    The opening is the strongest expression-form signal for short-video hooks:
    which shot scale, camera motion, and text style a video leads with. Tags stay
    readable Chinese labels such as 特写开场 / 固定机位开场 / 开场大字标题.
    """
    if annotation is None:
        return []
    tags: list[str] = []
    tags.extend(f"{value}开场" for value in annotation.shot_scale)
    tags.extend(f"{value}开场" for value in annotation.camera_movement)
    tags.extend(f"开场{value}" for value in annotation.text_overlay_styles)
    if annotation.ocr_observation_ids:
        tags.append("开场即出字幕")
    return sorted(dict.fromkeys(tags))


CRAFT_TAG_ATTRIBUTES: tuple[tuple[str, str], ...] = (
    ("景别", "shot_scale"),
    ("运镜手法", "camera_movement"),
    ("机位角度", "camera_angle"),
    ("构图", "composition"),
    ("光线", "lighting"),
    ("字幕与艺术字", "text_overlay_styles"),
    ("动效与贴纸", "motion_graphics"),
    ("品牌露出", "branding"),
)


def _media_craft_summary(analysis: MediaAnalysis) -> dict[str, Any]:
    """Count visible craft labels per category for the per-video media report."""
    summary: dict[str, Any] = {"categories": {}, "opening_techniques": [], "pacing_tags": []}
    annotations = analysis.vision.shot_annotations if analysis.vision else []
    first = None
    if analysis.shots:
        first_shot = min(analysis.shots, key=lambda item: (item.start_ms, item.index))
        first = next(
            (item for item in annotations if item.shot_id == first_shot.shot_id),
            None,
        )
    for label, attribute in CRAFT_TAG_ATTRIBUTES:
        counts: dict[str, int] = {}
        for annotation in annotations:
            for value in getattr(annotation, attribute):
                counts[value] = counts.get(value, 0) + 1
        summary["categories"][label] = sorted(counts.items(), key=lambda pair: (-pair[1], pair[0]))
    opening = _opening_technique_tags(first)
    if opening:
        summary["opening_techniques"] = opening
    pacing = _pacing_tags(
        fmean(item.duration_ms for item in analysis.shots) if analysis.shots else None
    )
    if pacing:
        summary["pacing_tags"] = pacing
    return summary


def _preserve_provider_responses(
    project: ProjectLayout,
    responses: list[Any],
    response_hashes: list[str],
) -> list[Path]:
    paths: list[Path] = []
    for response, response_hash in zip(responses, response_hashes, strict=True):
        path = project.root / "raw" / "vision-outputs" / f"{response_hash}.json"
        if not path.exists():
            atomic_write_text(
                path,
                json.dumps(
                    response,
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                ),
            )
        if sha256_file(path) != response_hash:
            raise DistillerError(
                ErrorCode.RAW_INTEGRITY,
                "Vision Provider raw output hash mismatch",
            )
        paths.append(path)
    return paths


def _resolve_media_path(
    project: ProjectLayout, configured: str | None, supplied: Path | None
) -> Path:
    if supplied is not None:
        source = supplied.expanduser().resolve()
    elif configured:
        candidate = Path(configured).expanduser()
        source = (
            (project.root / candidate).resolve()
            if not candidate.is_absolute()
            else candidate.resolve()
        )
    else:
        raise DistillerError(
            ErrorCode.INPUT_MISSING,
            "No local media file was supplied and the normalized video has no media_path",
            details={"next": "pass --file <local-video>"},
        )
    if not source.is_file():
        raise DistillerError(ErrorCode.INPUT_MISSING, f"Local media file not found: {source}")
    return source


def _selected_shot_indexes(count: int, maximum: int) -> list[int]:
    if count <= maximum:
        return list(range(count))
    if maximum == 1:
        return [0]
    return sorted({round(index * (count - 1) / (maximum - 1)) for index in range(maximum)})


def _keyframe_points(
    shots: Sequence[ShotSegment],
    *,
    duration_ms: int,
    maximum: int,
) -> list[tuple[int, int]]:
    """Keep scene midpoints and add uniform coverage when long clips have few cuts."""

    if not shots or maximum < 1:
        return []
    selected_indexes = _selected_shot_indexes(len(shots), maximum)
    points = {
        (index, shots[index].start_ms + shots[index].duration_ms // 2) for index in selected_indexes
    }
    if duration_ms >= 10_000:
        target = (
            6
            if duration_ms <= 30_000
            else 8
            if duration_ms <= 60_000
            else 12
            if duration_ms <= 180_000
            else 16
        )
        target = min(maximum, target)
        if len(points) < target:
            uniform_candidates: list[tuple[int, int]] = []
            for position in range(target):
                timestamp_ms = min(
                    max(0, duration_ms - 1),
                    round((position + 0.5) * duration_ms / target),
                )
                shot_index = next(
                    (
                        index
                        for index, shot in enumerate(shots)
                        if shot.start_ms <= timestamp_ms < shot.end_ms
                    ),
                    len(shots) - 1,
                )
                if any(abs(existing - timestamp_ms) < 250 for _, existing in points):
                    continue
                uniform_candidates.append((shot_index, timestamp_ms))
            remaining = target - len(points)
            for candidate_index in _selected_shot_indexes(
                len(uniform_candidates),
                min(remaining, len(uniform_candidates)),
            ):
                points.add(uniform_candidates[candidate_index])
    ordered = sorted(points, key=lambda item: (item[1], item[0]))
    if len(ordered) > maximum:
        ordered = [ordered[index] for index in _selected_shot_indexes(len(ordered), maximum)]
    return ordered


def _jpeg_dimensions(path: Path) -> tuple[int, int] | None:
    """Read dimensions from JPEG SOF markers without adding an image-library dependency."""

    payload = path.read_bytes()
    if len(payload) < 4 or payload[:2] != b"\xff\xd8":
        return None
    offset = 2
    start_of_frame = {
        0xC0,
        0xC1,
        0xC2,
        0xC3,
        0xC5,
        0xC6,
        0xC7,
        0xC9,
        0xCA,
        0xCB,
        0xCD,
        0xCE,
        0xCF,
    }
    while offset + 4 <= len(payload):
        if payload[offset] != 0xFF:
            offset += 1
            continue
        marker = payload[offset + 1]
        offset += 2
        if marker in {0xD8, 0xD9}:
            continue
        if offset + 2 > len(payload):
            return None
        length = int.from_bytes(payload[offset : offset + 2], "big")
        if length < 2 or offset + length > len(payload):
            return None
        if marker in start_of_frame and length >= 7:
            height = int.from_bytes(payload[offset + 3 : offset + 5], "big")
            width = int.from_bytes(payload[offset + 5 : offset + 7], "big")
            return (width, height) if width > 0 and height > 0 else None
        offset += length
    return None


def _dbfs(amplitude: float) -> float:
    return -100.0 if amplitude <= 0 else max(-100.0, 20 * math.log10(amplitude / 32768.0))


def _silence_intervals(
    silent: Sequence[bool], *, window_ms: int, analyzed_duration_ms: int
) -> list[SilenceInterval]:
    intervals: list[SilenceInterval] = []
    start: int | None = None
    for index, is_silent in enumerate([*silent, False]):
        if is_silent and start is None:
            start = index * window_ms
        elif not is_silent and start is not None:
            intervals.append(
                SilenceInterval(
                    start_ms=start,
                    end_ms=min(index * window_ms, analyzed_duration_ms),
                )
            )
            start = None
    return intervals


def _audio_features(
    payload: bytes,
    *,
    sample_rate: int,
    window_ms: int,
    silence_threshold_dbfs: float,
) -> AudioFeatures:
    if not payload:
        return AudioFeatures(
            status="skipped",
            has_audio=False,
            sample_rate=sample_rate,
            warnings=["no_decodable_audio_stream"],
        )
    samples = array("h")
    samples.frombytes(payload[: len(payload) - len(payload) % 2])
    if sys.byteorder != "little":
        samples.byteswap()
    if not samples:
        return AudioFeatures(
            status="skipped",
            has_audio=False,
            sample_rate=sample_rate,
            warnings=["decoded_audio_was_empty"],
        )
    window_size = max(1, round(sample_rate * window_ms / 1000))
    window_dbfs: list[float] = []
    for offset in range(0, len(samples), window_size):
        values = samples[offset : offset + window_size]
        if not values:
            continue
        rms = math.sqrt(sum(float(value) * float(value) for value in values) / len(values))
        window_dbfs.append(_dbfs(rms))
    overall_rms = math.sqrt(sum(float(value) * float(value) for value in samples) / len(samples))
    peak = max(abs(value) for value in samples)
    rms_dbfs = _dbfs(overall_rms)
    peak_dbfs = _dbfs(float(peak))
    silent = [value <= silence_threshold_dbfs for value in window_dbfs]
    analyzed_duration_ms = round(len(samples) * 1000 / sample_rate)
    silence_ratio = sum(silent) / len(silent) if silent else None
    return AudioFeatures(
        status="complete",
        has_audio=True,
        analyzed_duration_ms=analyzed_duration_ms,
        sample_rate=sample_rate,
        rms_dbfs=round(rms_dbfs, 6),
        peak_dbfs=round(peak_dbfs, 6),
        dynamic_range_db=round(max(0.0, peak_dbfs - rms_dbfs), 6),
        loudness_variance=round(pvariance(window_dbfs), 6) if len(window_dbfs) > 1 else 0.0,
        silence_ratio=round(silence_ratio, 6) if silence_ratio is not None else None,
        activity_ratio=round(1 - silence_ratio, 6) if silence_ratio is not None else None,
        silence_intervals=_silence_intervals(
            silent, window_ms=window_ms, analyzed_duration_ms=analyzed_duration_ms
        ),
    )


def _validate_vision_annotation(
    value: MediaVisionAnnotation, *, valid_shots: set[str], valid_keyframes: set[str]
) -> None:
    annotation_ids = [item.annotation_id for item in value.shot_annotations]
    observation_ids = [item.observation_id for item in value.ocr_observations]
    if len(annotation_ids) != len(set(annotation_ids)):
        raise VisionSchemaFailure("visual annotation IDs must be unique")
    if len(observation_ids) != len(set(observation_ids)):
        raise VisionSchemaFailure("OCR observation IDs must be unique")
    if any(item.shot_id not in valid_shots for item in value.shot_annotations):
        raise VisionSchemaFailure("visual annotation referenced an unknown shot")
    if any(
        item.shot_id not in valid_shots or item.keyframe_id not in valid_keyframes
        for item in value.ocr_observations
    ):
        raise VisionSchemaFailure("OCR observation referenced unknown timestamp evidence")
    observations = {item.observation_id: item for item in value.ocr_observations}
    for annotation in value.shot_annotations:
        for observation_id in annotation.ocr_observation_ids:
            observation = observations.get(observation_id)
            if observation is None or observation.shot_id != annotation.shot_id:
                raise VisionSchemaFailure("visual annotation referenced invalid OCR evidence")


def _generate_vision(
    *,
    bundle: MediaVisionBundle,
    provider: VisionModelProvider | None,
    max_attempts: int,
    strict: bool,
) -> tuple[MediaVisionAnnotation | None, VisionTaskTrace]:
    bundle_hash = sha256_json(
        {
            "video_id": bundle.video_id,
            "media_hash": bundle.media_hash,
            "shots": [item.model_dump(mode="json") for item in bundle.shots],
            "keyframes": [
                {
                    "keyframe_id": item.keyframe_id,
                    "shot_id": item.shot_id,
                    "timestamp_ms": item.timestamp_ms,
                    "sha256": item.sha256,
                }
                for item in bundle.keyframes
            ],
        }
    )
    if provider is None:
        return None, VisionTaskTrace(
            provider="none",
            model="none",
            input_hash=bundle_hash,
            attempts=0,
            status="skipped",
            errors=["visual/OCR provider not supplied; fields remain unknown"],
        )
    errors: list[str] = []
    provider_unavailable = False
    valid_shots = {item.shot_id for item in bundle.shots}
    valid_keyframes = {item.keyframe_id for item in bundle.keyframes}
    for attempt in range(1, max_attempts + 1):
        try:
            value = provider.analyze(bundle)
            _validate_vision_annotation(
                value, valid_shots=valid_shots, valid_keyframes=valid_keyframes
            )
            return value, VisionTaskTrace(
                provider=provider.provider_name,
                model=provider.model_name,
                input_hash=getattr(provider, "input_hash", None) or bundle_hash,
                attempts=attempt,
                status="success",
                errors=errors,
            )
        except VisionProviderUnavailable as exc:
            provider_unavailable = True
            errors.append(str(exc)[:500])
        except (VisionSchemaFailure, ValueError, TypeError) as exc:
            errors.append(str(exc)[:500])
    if strict:
        if provider_unavailable:
            raise DistillerError(
                ErrorCode.MODEL_UNAVAILABLE,
                f"Vision model service remained unavailable after {max_attempts} attempts",
                details={
                    "provider": provider.provider_name,
                    "model": provider.model_name,
                    "attempts": max_attempts,
                    "errors": errors,
                },
            )
        raise DistillerError(
            ErrorCode.MODEL_SCHEMA_INVALID,
            f"Vision output remained invalid after {max_attempts} attempts",
            details={"attempts": max_attempts, "errors": errors},
        )
    return None, VisionTaskTrace(
        provider=provider.provider_name,
        model=provider.model_name,
        input_hash=getattr(provider, "input_hash", None) or bundle_hash,
        attempts=max_attempts,
        status="degraded",
        errors=errors,
    )


def _attach_visuals(
    shots: list[ShotSegment], vision: MediaVisionAnnotation | None
) -> list[ShotSegment]:
    if vision is None:
        return shots
    by_shot = {item.shot_id: item.annotation_id for item in vision.shot_annotations}
    return [
        item.model_copy(update={"visual_annotation_id": by_shot.get(item.shot_id)})
        for item in shots
    ]


def _evidence_items(
    *,
    analysis_id: str,
    video_record_id: str,
    raw_media_path: str,
    media_hash: str,
    shots: list[ShotSegment],
    keyframes: list[KeyframeEvidence],
    audio: AudioFeatures,
    vision: MediaVisionAnnotation | None,
) -> list[MediaEvidenceItem]:
    items = [
        MediaEvidenceItem(
            evidence_id=stable_id("evi_", analysis_id, "media"),
            kind="media",
            path=raw_media_path,
            sha256=media_hash,
            source_ids=[video_record_id],
        )
    ]
    items.extend(
        MediaEvidenceItem(
            evidence_id=stable_id("evi_", analysis_id, "shot", shot.shot_id),
            kind="shot",
            start_ms=shot.start_ms,
            end_ms=shot.end_ms,
            source_ids=[shot.shot_id],
        )
        for shot in shots
    )
    items.extend(
        MediaEvidenceItem(
            evidence_id=stable_id("evi_", analysis_id, "keyframe", frame.keyframe_id),
            kind="keyframe",
            start_ms=frame.timestamp_ms,
            end_ms=frame.timestamp_ms,
            path=frame.path,
            sha256=frame.sha256,
            source_ids=[frame.shot_id, frame.keyframe_id],
        )
        for frame in keyframes
    )
    if audio.has_audio is not None:
        items.append(
            MediaEvidenceItem(
                evidence_id=stable_id("evi_", analysis_id, "audio"),
                kind="audio",
                start_ms=0,
                end_ms=audio.analyzed_duration_ms,
                source_ids=[video_record_id],
            )
        )
    if vision is not None:
        items.extend(
            MediaEvidenceItem(
                evidence_id=stable_id("evi_", analysis_id, "visual", item.annotation_id),
                kind="visual",
                source_ids=[item.shot_id, item.annotation_id],
            )
            for item in vision.shot_annotations
        )
        items.extend(
            MediaEvidenceItem(
                evidence_id=stable_id("evi_", analysis_id, "ocr", item.observation_id),
                kind="ocr",
                start_ms=item.start_ms,
                end_ms=item.end_ms,
                source_ids=[item.shot_id, item.keyframe_id, item.observation_id],
            )
            for item in vision.ocr_observations
        )
    return items


class LocalMediaAnalysisService:
    """Analyze user-provided local media without uploading it or opening a browser."""

    def __init__(self, project: ProjectLayout, *, backend: MediaBackend | None = None) -> None:
        self.project = project
        self.backend = backend

    def analyze(
        self,
        *,
        video_id: str,
        file: Path | None = None,
        vision_output: Path | None = None,
        provider: VisionModelProvider | None = None,
        strict_media: bool = False,
        strict_vision: bool = False,
        scene_threshold: float | None = None,
        max_keyframes: int | None = None,
        dry_run: bool = False,
    ) -> dict[str, Any]:
        """Extract metadata, shots, frames, audio features, and optional visual labels."""

        video = resolve_video(self.project, video_id)
        source = _resolve_media_path(self.project, video.media_path, file)
        media_hash = sha256_file(source)
        config = load_config(self.project.config_path)
        backend = self.backend or FFmpegMediaBackend(config.media)
        if provider is not None and vision_output is not None:
            raise DistillerError(
                ErrorCode.SCHEMA_INVALID, "Pass either provider or vision_output, not both"
            )
        file_provider = StructuredVisionFileProvider(vision_output) if vision_output else None
        selected_provider = provider or file_provider
        effective_strict_media = strict_media or not config.media.allow_degraded_without_ffmpeg
        threshold = scene_threshold if scene_threshold is not None else config.media.scene_threshold
        keyframe_limit = max_keyframes if max_keyframes is not None else config.media.max_keyframes
        if not 0 < threshold < 1:
            raise DistillerError(
                ErrorCode.SCHEMA_INVALID, "scene_threshold must be between 0 and 1"
            )
        if keyframe_limit < 1 or keyframe_limit > 100:
            raise DistillerError(
                ErrorCode.SCHEMA_INVALID, "max_keyframes must be between 1 and 100"
            )
        provider_hash = getattr(selected_provider, "input_hash", None)
        if dry_run:
            return {
                "ok": True,
                "dry_run": True,
                "video_id": video.video_id,
                "media_hash": media_hash,
                "backend": backend.name,
                "backend_available": backend.available,
                "would_write": [
                    f"raw/media/{media_hash}{source.suffix.lower() or '.bin'}",
                    f"analyses/media/{video.video_id}/mda_*/",
                    "normalized/media_features.parquet",
                ],
            }
        warnings: list[str] = []
        if not backend.available and effective_strict_media:
            raise DistillerError(
                ErrorCode.MEDIA_DECODE,
                "FFmpeg/FFprobe is unavailable",
                details={"next": "install FFmpeg or disable strict media mode"},
            )

        temp_frames: dict[str, Path] = {}
        frame_dimensions: dict[str, tuple[int, int] | None] = {}
        keyframe_specs: list[tuple[str, str, int, str]] = []
        degraded = False
        with TemporaryDirectory(prefix="distiller-media-") as temp_dir_name:
            temp_dir = Path(temp_dir_name)
            if not backend.available:
                degraded = True
                warnings.append("ffmpeg_unavailable_media_analysis_degraded")
                metadata = MediaMetadata(
                    media_hash=media_hash,
                    file_size_bytes=source.stat().st_size,
                    backend=backend.name,
                    backend_version=backend.version,
                )
                shots: list[ShotSegment] = []
                audio = AudioFeatures(
                    status="degraded",
                    has_audio=None,
                    warnings=["ffmpeg_unavailable_audio_unknown"],
                )
            else:
                try:
                    metadata = backend.probe(source, media_hash)
                except MediaBackendFailure as exc:
                    if effective_strict_media:
                        raise DistillerError(
                            ErrorCode.MEDIA_DECODE,
                            "Could not decode media metadata",
                            details={"reason": str(exc)},
                        ) from exc
                    degraded = True
                    warnings.append(f"metadata_decode_failed:{str(exc)[:300]}")
                    metadata = MediaMetadata(
                        media_hash=media_hash,
                        file_size_bytes=source.stat().st_size,
                        backend=backend.name,
                        backend_version=backend.version,
                    )
                duration_ms = metadata.duration_ms or 0
                if metadata.duration_ms is None:
                    degraded = True
                    warnings.append("media_duration_unknown")
                try:
                    scene_result = backend.detect_scenes(
                        source,
                        duration_ms=duration_ms,
                        threshold=threshold,
                        max_shots=config.media.max_shots,
                    )
                    boundaries = sorted(set(scene_result.boundaries_ms))
                    warnings.extend(scene_result.warnings)
                except MediaBackendFailure as exc:
                    degraded = True
                    warnings.append(f"scene_detection_failed_single_shot_fallback:{str(exc)[:300]}")
                    boundaries = [0, duration_ms]
                if len(boundaries) < 2:
                    boundaries = [0, duration_ms]
                shots = []
                for index, (start_ms, end_ms) in enumerate(
                    zip(boundaries, boundaries[1:], strict=False)
                ):
                    shot_id = stable_id("shot_", media_hash, str(index), str(start_ms), str(end_ms))
                    shots.append(
                        ShotSegment(
                            shot_id=shot_id,
                            index=index,
                            start_ms=start_ms,
                            end_ms=end_ms,
                            duration_ms=end_ms - start_ms,
                        )
                    )
                for index, timestamp_ms in _keyframe_points(
                    shots,
                    duration_ms=duration_ms,
                    maximum=keyframe_limit,
                ):
                    shot = shots[index]
                    keyframe_id = stable_id("key_", media_hash, shot.shot_id, str(timestamp_ms))
                    temp_path = temp_dir / f"{keyframe_id}.jpg"
                    try:
                        backend.extract_frame(
                            source,
                            timestamp_ms=timestamp_ms,
                            width=config.media.keyframe_width,
                            output=temp_path,
                        )
                    except MediaBackendFailure as exc:
                        degraded = True
                        warnings.append(
                            f"keyframe_extraction_failed:{shot.shot_id}:{str(exc)[:200]}"
                        )
                        continue
                    frame_hash = sha256_file(temp_path)
                    temp_frames[keyframe_id] = temp_path
                    frame_dimensions[keyframe_id] = _jpeg_dimensions(temp_path)
                    keyframe_specs.append((keyframe_id, shot.shot_id, timestamp_ms, frame_hash))
                    shots[index] = shot.model_copy(
                        update={"keyframe_ids": [*shot.keyframe_ids, keyframe_id]}
                    )
                if metadata.audio_codec is None:
                    audio = AudioFeatures(
                        status="skipped",
                        has_audio=False,
                        sample_rate=config.media.audio_sample_rate,
                        warnings=["no_audio_stream_in_metadata"],
                    )
                else:
                    try:
                        pcm = backend.decode_audio_pcm(
                            source,
                            sample_rate=config.media.audio_sample_rate,
                            max_seconds=config.media.max_audio_analysis_seconds,
                        )
                        if metadata.duration_ms is not None:
                            expected_bytes = (
                                round(
                                    min(
                                        metadata.duration_ms,
                                        config.media.max_audio_analysis_seconds * 1000,
                                    )
                                    * config.media.audio_sample_rate
                                    / 1000
                                )
                                * 2
                            )
                            pcm = pcm[:expected_bytes]
                        audio = _audio_features(
                            pcm,
                            sample_rate=config.media.audio_sample_rate,
                            window_ms=config.media.audio_window_ms,
                            silence_threshold_dbfs=config.media.silence_threshold_dbfs,
                        )
                    except MediaBackendFailure as exc:
                        degraded = True
                        warnings.append(f"audio_analysis_failed:{str(exc)[:300]}")
                        audio = AudioFeatures(
                            status="degraded",
                            has_audio=None,
                            warnings=["audio_decode_failed"],
                        )

            provisional_keyframes = [
                VisionInputKeyframe(
                    keyframe_id=item[0],
                    shot_id=item[1],
                    timestamp_ms=item[2],
                    path=str(temp_frames[item[0]]),
                    sha256=item[3],
                )
                for item in keyframe_specs
            ]
            vision_bundle = MediaVisionBundle(
                video_id=video.video_id,
                media_hash=media_hash,
                shots=[
                    VisionInputShot(
                        shot_id=item.shot_id,
                        start_ms=item.start_ms,
                        end_ms=item.end_ms,
                        keyframe_ids=item.keyframe_ids,
                    )
                    for item in shots
                ],
                keyframes=provisional_keyframes,
            )
            vision, vision_trace = _generate_vision(
                bundle=vision_bundle,
                provider=selected_provider,
                max_attempts=config.models.max_schema_attempts,
                strict=strict_vision,
            )
            provider_responses = list(
                getattr(selected_provider, "raw_responses", [])
                if selected_provider is not None
                else []
            )
            provider_output_hashes = [sha256_json(response) for response in provider_responses]
            if vision_trace.status == "degraded":
                degraded = True
                warnings.extend(f"vision_schema:{item}" for item in vision_trace.errors)
            elif vision_trace.status == "skipped":
                warnings.extend(vision_trace.errors)
            shots = _attach_visuals(shots, vision)
            analysis_fingerprint = sha256_json(
                {
                    "analysis_version": MEDIA_ANALYSIS_VERSION,
                    "video_id": video.video_id,
                    "media_hash": media_hash,
                    "metadata": metadata.model_dump(mode="json"),
                    "shots": [item.model_dump(mode="json") for item in shots],
                    "keyframe_hashes": keyframe_specs,
                    "audio": audio.model_dump(mode="json"),
                    "vision": vision.model_dump(mode="json") if vision else None,
                    "vision_trace": vision_trace.model_dump(mode="json"),
                    "scene_threshold": threshold,
                    "provider_hash": provider_hash,
                    "provider_output_hashes": provider_output_hashes,
                }
            )
            analysis_id = stable_id("mda_", analysis_fingerprint)
            output_dir = self.project.root / "analyses" / "media" / video.video_id / analysis_id
            keyframe_dir = output_dir / "keyframes"
            keyframes = [
                KeyframeEvidence(
                    keyframe_id=keyframe_id,
                    shot_id=shot_id,
                    timestamp_ms=timestamp_ms,
                    path=self.project.relative(keyframe_dir / f"{keyframe_id}.jpg"),
                    sha256=frame_hash,
                    width=(frame_dimensions[keyframe_id] or (None, None))[0],
                    height=(frame_dimensions[keyframe_id] or (None, None))[1],
                )
                for keyframe_id, shot_id, timestamp_ms, frame_hash in keyframe_specs
            ]
            suffix = source.suffix.lower() or ".bin"
            raw_media_path = self.project.root / "raw" / "media" / f"{media_hash}{suffix}"
            paths = {
                "analysis": output_dir / "media-analysis.json",
                "timeline": output_dir / "timeline.json",
                "report": output_dir / "report.md",
                "evidence": output_dir / "evidence-index.json",
                "warnings": output_dir / "warnings.json",
            }
            relative_paths = [self.project.relative(path) for path in paths.values()]
            raw_provider_outputs = _preserve_provider_responses(
                self.project,
                provider_responses,
                provider_output_hashes,
            )
            if paths["analysis"].is_file():
                # Raw videos are intentionally pruned after successful distillation.
                # A later targeted reparse may download the same blob again; restore
                # the verified raw copy for the duration of that new processing run.
                if not raw_media_path.is_file():
                    raw_media_path.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copyfile(source, raw_media_path)
                if sha256_file(raw_media_path) != media_hash:
                    raise DistillerError(
                        ErrorCode.RAW_INTEGRITY,
                        "Restored raw media hash mismatch",
                    )
                return {
                    "ok": True,
                    "dry_run": False,
                    "already_generated": True,
                    "analysis": read_json(paths["analysis"]),
                    "outputs": [
                        *relative_paths,
                        *(self.project.relative(path) for path in raw_provider_outputs),
                    ],
                }
            manifest = self.project.begin_run(
                "analyze media",
                input_hashes=sorted(
                    {
                        media_hash,
                        *([provider_hash] if provider_hash else []),
                        *provider_output_hashes,
                    }
                ),
            )
            generated_at = datetime.now(UTC)
            evidence = MediaEvidenceIndex(
                analysis_id=analysis_id,
                video_id=video.video_id,
                run_id=manifest.run_id,
                generated_at=generated_at,
                media_hash=media_hash,
                items=_evidence_items(
                    analysis_id=analysis_id,
                    video_record_id=video.record_id,
                    raw_media_path=self.project.relative(raw_media_path),
                    media_hash=media_hash,
                    shots=shots,
                    keyframes=keyframes,
                    audio=audio,
                    vision=vision,
                ),
            )
            status: Literal["complete", "degraded"] = "degraded" if degraded else "complete"
            warnings = list(dict.fromkeys(warnings))
            analysis = MediaAnalysis(
                analysis_id=analysis_id,
                analysis_version=MEDIA_ANALYSIS_VERSION,
                video_id=video.video_id,
                account_id=video.account_id,
                generated_at=generated_at,
                run_id=manifest.run_id,
                status=status,
                raw_media_path=self.project.relative(raw_media_path),
                metadata=metadata,
                shots=shots,
                keyframes=keyframes,
                audio=audio,
                vision=vision,
                vision_trace=vision_trace,
                timeline_path=self.project.relative(paths["timeline"]),
                evidence_index_path=self.project.relative(paths["evidence"]),
                warnings_path=self.project.relative(paths["warnings"]),
                warnings=warnings,
            )
            raw_media_path.parent.mkdir(parents=True, exist_ok=True)
            if not raw_media_path.exists():
                shutil.copyfile(source, raw_media_path)
            if sha256_file(raw_media_path) != media_hash:
                raise DistillerError(ErrorCode.RAW_INTEGRITY, "Immutable raw media hash mismatch")
            if file_provider is not None:
                raw_vision = (
                    self.project.root
                    / "raw"
                    / "vision-outputs"
                    / f"{file_provider.input_hash}.json"
                )
                if not raw_vision.exists():
                    shutil.copyfile(file_provider.path, raw_vision)
                if sha256_file(raw_vision) != file_provider.input_hash:
                    raise DistillerError(ErrorCode.RAW_INTEGRITY, "Vision output raw hash mismatch")
            keyframe_dir.mkdir(parents=True, exist_ok=True)
            for keyframe_id, temp_path in temp_frames.items():
                destination = keyframe_dir / f"{keyframe_id}.jpg"
                if not destination.exists():
                    shutil.copyfile(temp_path, destination)
            atomic_write_json(paths["analysis"], analysis.model_dump(mode="json"))
            atomic_write_json(
                paths["timeline"],
                {
                    "schema_version": analysis.schema_version,
                    "analysis_id": analysis_id,
                    "video_id": video.video_id,
                    "shots": [item.model_dump(mode="json") for item in shots],
                    "keyframes": [item.model_dump(mode="json") for item in keyframes],
                    "audio": audio.model_dump(mode="json"),
                    "vision": vision.model_dump(mode="json") if vision else None,
                },
            )
            atomic_write_json(paths["evidence"], evidence.model_dump(mode="json"))
            atomic_write_json(paths["warnings"], warnings)
            template_path = (
                Path(__file__).resolve().parents[1]
                / "reports"
                / "templates"
                / "media-analysis.md.j2"
            )
            template = Environment(undefined=StrictUndefined, autoescape=False).from_string(
                template_path.read_text(encoding="utf-8")
            )
            atomic_write_text(
                paths["report"],
                template.render(
                    analysis=analysis.model_dump(mode="python"),
                    craft_summary=_media_craft_summary(analysis),
                ).strip()
                + "\n",
            )
            feature_id = stable_id("mdf_", analysis_id)
            visual_annotations = vision.shot_annotations if vision else []
            annotations_by_shot = {item.shot_id: item for item in visual_annotations}
            first_annotation = None
            if shots:
                first_shot = min(shots, key=lambda item: (item.start_ms, item.index))
                first_annotation = annotations_by_shot.get(first_shot.shot_id)
            average_shot_duration_ms = fmean(item.duration_ms for item in shots) if shots else None
            feature = MediaFeatureRecord(
                record_id=feature_id,
                media_feature_id=feature_id,
                analysis_id=analysis_id,
                video_id=video.video_id,
                media_hash=media_hash,
                duration_ms=metadata.duration_ms,
                width=metadata.width,
                height=metadata.height,
                shot_count=len(shots),
                keyframe_count=len(keyframes),
                average_shot_duration_ms=average_shot_duration_ms,
                silence_ratio=audio.silence_ratio,
                rms_dbfs=audio.rms_dbfs,
                ocr_observation_count=len(vision.ocr_observations) if vision else 0,
                visual_annotation_count=len(visual_annotations),
                visual_labels=sorted(
                    {value for item in visual_annotations for value in item.labels}
                ),
                dominant_colors=sorted(
                    {value for item in visual_annotations for value in item.dominant_colors}
                ),
                visual_style_tags=sorted(
                    {
                        value
                        for item in visual_annotations
                        for value in [*item.composition, *item.camera, *item.lighting]
                    }
                ),
                text_overlay_style_tags=sorted(
                    {value for item in visual_annotations for value in item.text_overlay_styles}
                ),
                motion_graphic_tags=sorted(
                    {value for item in visual_annotations for value in item.motion_graphics}
                ),
                branding_tags=sorted(
                    {value for item in visual_annotations for value in item.branding}
                ),
                shot_scale_tags=sorted(
                    {value for item in visual_annotations for value in item.shot_scale}
                ),
                camera_movement_tags=sorted(
                    {value for item in visual_annotations for value in item.camera_movement}
                ),
                camera_angle_tags=sorted(
                    {value for item in visual_annotations for value in item.camera_angle}
                ),
                composition_tags=sorted(
                    {value for item in visual_annotations for value in item.composition}
                ),
                lighting_tags=sorted(
                    {value for item in visual_annotations for value in item.lighting}
                ),
                opening_technique_tags=_opening_technique_tags(first_annotation),
                pacing_tags=_pacing_tags(average_shot_duration_ms),
                analysis_status=status,
                analysis_path=self.project.relative(paths["analysis"]),
                source_platform=video.source_platform,
                source_type="local_media",
                source_uri=video.source_uri,
                source_record_id=video.source_record_id,
                collected_at=video.collected_at,
                run_id=manifest.run_id,
                raw_hash=media_hash,
                data_quality_flags=video.data_quality_flags,
            )
            feature_path = self.project.normalized_dir / "media_features.parquet"
            features = read_models(feature_path, MediaFeatureRecord)
            features = [item for item in features if item.analysis_id != analysis_id]
            features.append(feature)
            features.sort(key=lambda item: (item.video_id, item.analysis_id))
            write_models(feature_path, features)
            state = self.project.load_state()
            state.last_media_analysis_at = datetime.now(UTC)
            self.project.save_state(state)
            output_files = [
                *relative_paths,
                *(self.project.relative(path) for path in raw_provider_outputs),
                self.project.relative(feature_path),
            ]
            self.project.finish_run(
                manifest,
                success=True,
                processed_counts={
                    "shots": len(shots),
                    "keyframes": len(keyframes),
                    "ocr_observations": len(vision.ocr_observations) if vision else 0,
                },
                output_files=output_files,
                warnings=warnings,
            )
            return {
                "ok": True,
                "dry_run": False,
                "already_generated": False,
                "analysis": analysis.model_dump(mode="json"),
                "outputs": output_files,
            }
