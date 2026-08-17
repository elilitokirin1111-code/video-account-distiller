from __future__ import annotations

from array import array
from pathlib import Path

import pytest

from video_account_distiller.errors import DistillerError, ErrorCode
from video_account_distiller.media import LocalMediaAnalysisService, SceneDetectionResult
from video_account_distiller.models import (
    MediaAnalysis,
    MediaMetadata,
    MediaVisionAnnotation,
    MediaVisionBundle,
    OcrObservation,
    ShotVisualAnnotation,
)
from video_account_distiller.status import project_status
from video_account_distiller.storage.duckdb_store import DuckDBStore
from video_account_distiller.storage.project import ProjectLayout
from video_account_distiller.utils.hashing import sha256_file
from video_account_distiller.utils.io import read_json
from video_account_distiller.validation import validate_project


class FakeMediaBackend:
    available = True
    name = "fake-ffmpeg"
    version = "fixture-1"

    def probe(self, source: Path, media_hash: str) -> MediaMetadata:
        return MediaMetadata(
            media_hash=media_hash,
            container="mp4",
            duration_ms=3000,
            width=1080,
            height=1920,
            frame_rate=25,
            video_codec="h264",
            audio_codec="aac",
            audio_channels=1,
            audio_sample_rate=8000,
            file_size_bytes=source.stat().st_size,
            backend=self.name,
            backend_version=self.version,
        )

    def detect_scenes(
        self, source: Path, *, duration_ms: int, threshold: float, max_shots: int
    ) -> SceneDetectionResult:
        del source, duration_ms, threshold, max_shots
        return SceneDetectionResult([0, 1000, 3000], [])

    def extract_frame(self, source: Path, *, timestamp_ms: int, width: int, output: Path) -> None:
        del source, width
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes(f"jpeg-{timestamp_ms}".encode())

    def decode_audio_pcm(self, source: Path, *, sample_rate: int, max_seconds: int) -> bytes:
        del source, sample_rate, max_seconds
        values = array("h", [0] * 800 + [1200] * 800)
        return values.tobytes()


class UnavailableMediaBackend:
    available = False
    name = "ffmpeg"
    version = None

    def probe(self, source: Path, media_hash: str) -> MediaMetadata:
        raise AssertionError("unavailable backend must not be called")

    def detect_scenes(
        self, source: Path, *, duration_ms: int, threshold: float, max_shots: int
    ) -> SceneDetectionResult:
        raise AssertionError("unavailable backend must not be called")

    def extract_frame(self, source: Path, *, timestamp_ms: int, width: int, output: Path) -> None:
        raise AssertionError("unavailable backend must not be called")

    def decode_audio_pcm(self, source: Path, *, sample_rate: int, max_seconds: int) -> bytes:
        raise AssertionError("unavailable backend must not be called")


class NoAudioMediaBackend(FakeMediaBackend):
    def probe(self, source: Path, media_hash: str) -> MediaMetadata:
        return (
            super()
            .probe(source, media_hash)
            .model_copy(
                update={"audio_codec": None, "audio_channels": None, "audio_sample_rate": None}
            )
        )

    def decode_audio_pcm(self, source: Path, *, sample_rate: int, max_seconds: int) -> bytes:
        raise AssertionError("media without an audio stream must not be decoded")


class FixtureVisionProvider:
    provider_name = "fixture-vision"
    model_name = "fixture-v1"

    def __init__(self) -> None:
        self.raw_responses = [
            {
                "message": {
                    "content": "fixture local visual response",
                }
            }
        ]

    @property
    def input_hash(self) -> str | None:
        return None

    def analyze(self, bundle: MediaVisionBundle) -> MediaVisionAnnotation:
        shot = bundle.shots[0]
        frame = bundle.keyframes[0]
        return MediaVisionAnnotation(
            shot_annotations=[
                ShotVisualAnnotation(
                    annotation_id="ann_lobby",
                    shot_id=shot.shot_id,
                    summary="酒店大堂全景",
                    labels=["lobby", "hotel"],
                    shot_scale=["全景"],
                    camera_movement=["固定机位"],
                    camera_angle=["平视"],
                    composition=["对称构图"],
                    lighting=["自然光"],
                    text_overlay_styles=["金色标题字"],
                    ocr_observation_ids=["ocr_title"],
                    confidence=0.9,
                )
            ],
            ocr_observations=[
                OcrObservation(
                    observation_id="ocr_title",
                    text="欢迎入住",
                    shot_id=shot.shot_id,
                    keyframe_id=frame.keyframe_id,
                    start_ms=shot.start_ms,
                    end_ms=shot.end_ms,
                    confidence=0.95,
                )
            ],
        )


def test_local_media_analysis_is_traceable_queryable_and_idempotent(
    phase3_project: ProjectLayout, tmp_path: Path
) -> None:
    source = tmp_path / "hotel.mp4"
    source.write_bytes(b"offline-hotel-media")
    service = LocalMediaAnalysisService(phase3_project, backend=FakeMediaBackend())
    result = service.analyze(
        video_id="p2-01",
        file=source,
        provider=FixtureVisionProvider(),
    )
    analysis = MediaAnalysis.model_validate(result["analysis"])
    outputs = [phase3_project.root / path for path in result["outputs"]]
    assert all(path.is_file() for path in outputs)
    assert analysis.status == "complete"
    assert [(item.start_ms, item.end_ms) for item in analysis.shots] == [(0, 1000), (1000, 3000)]
    assert len(analysis.keyframes) == 2
    assert analysis.audio.silence_ratio == 0.5
    assert analysis.vision is not None
    assert analysis.vision.ocr_observations[0].text == "欢迎入住"
    raw_media = phase3_project.root / analysis.raw_media_path
    assert sha256_file(raw_media) == sha256_file(source)
    raw_vision_outputs = [path for path in outputs if path.parent.name == "vision-outputs"]
    assert len(raw_vision_outputs) == 1
    assert sha256_file(raw_vision_outputs[0]) == raw_vision_outputs[0].stem

    with DuckDBStore(phase3_project.normalized_dir) as store:
        assert store.count("media_features") == 1
        row = store.query("SELECT shot_count, ocr_observation_count FROM media_features")[0]
    assert row == {"shot_count": 2, "ocr_observation_count": 1}

    # The media feature row carries shooting-technique and expression-form tags.
    from video_account_distiller.models import MediaFeatureRecord
    from video_account_distiller.storage.parquet import read_models

    features = read_models(
        phase3_project.normalized_dir / "media_features.parquet", MediaFeatureRecord
    )
    assert len(features) == 1
    feature = features[0]
    assert feature.shot_scale_tags == ["全景"]
    assert feature.camera_movement_tags == ["固定机位"]
    assert feature.camera_angle_tags == ["平视"]
    assert feature.composition_tags == ["对称构图"]
    assert feature.lighting_tags == ["自然光"]
    assert feature.text_overlay_style_tags == ["金色标题字"]
    assert feature.opening_technique_tags == [
        "全景开场",
        "固定机位开场",
        "开场即出字幕",
        "开场金色标题字",
    ]
    assert feature.pacing_tags == ["中等节奏剪辑"]
    report = (phase3_project.root / result["outputs"][2]).read_text(encoding="utf-8")
    assert "## 拍摄手法与表现形式" in report
    assert "全景×1" in report

    status = project_status(phase3_project)
    assert status["artifacts"]["media_analyses"] == 1
    assert status["last_media_analysis_at"] is not None
    assert status["normalized"]["media_features"] == 1

    repeated = service.analyze(video_id="p2-01", file=source, provider=FixtureVisionProvider())
    assert repeated["already_generated"] is True
    assert repeated["analysis"]["analysis_id"] == analysis.analysis_id
    validation = validate_project(phase3_project)
    assert validation.error_count == 0
    assert validation.stats["phase6_artifacts"] == 1
    assert validation.stats["raw_media"] == 1


def test_media_validation_detects_tampered_keyframe(
    phase3_project: ProjectLayout, tmp_path: Path
) -> None:
    source = tmp_path / "hotel.mp4"
    source.write_bytes(b"offline-hotel-media")
    result = LocalMediaAnalysisService(phase3_project, backend=FakeMediaBackend()).analyze(
        video_id="p2-01", file=source
    )
    analysis = MediaAnalysis.model_validate(read_json(phase3_project.root / result["outputs"][0]))
    (phase3_project.root / analysis.keyframes[0].path).write_bytes(b"tampered")
    validation = validate_project(phase3_project)
    assert validation.error_count == 1
    assert validation.issues[0].code == "media_artifact_invalid"
    assert "keyframe" in validation.issues[0].message


def test_missing_ffmpeg_degrades_or_fails_stably(
    phase3_project: ProjectLayout, tmp_path: Path
) -> None:
    source = tmp_path / "hotel.mp4"
    source.write_bytes(b"offline-hotel-media")
    service = LocalMediaAnalysisService(phase3_project, backend=UnavailableMediaBackend())
    degraded = MediaAnalysis.model_validate(
        service.analyze(video_id="p2-01", file=source)["analysis"]
    )
    assert degraded.status == "degraded"
    assert degraded.metadata.duration_ms is None
    assert degraded.audio.has_audio is None
    with pytest.raises(DistillerError) as caught:
        service.analyze(video_id="p2-01", file=source, strict_media=True)
    assert caught.value.code == ErrorCode.MEDIA_DECODE


def test_media_without_audio_is_skipped_without_fabricating_silence(
    phase3_project: ProjectLayout, tmp_path: Path
) -> None:
    source = tmp_path / "silent-video.mp4"
    source.write_bytes(b"offline-video-without-audio")
    result = LocalMediaAnalysisService(phase3_project, backend=NoAudioMediaBackend()).analyze(
        video_id="p2-01", file=source
    )
    analysis = MediaAnalysis.model_validate(result["analysis"])
    assert analysis.status == "complete"
    assert analysis.audio.status == "skipped"
    assert analysis.audio.has_audio is False
    assert analysis.audio.silence_ratio is None


class LongSingleShotBackend(FakeMediaBackend):
    def probe(self, source: Path, media_hash: str) -> MediaMetadata:
        return super().probe(source, media_hash).model_copy(update={"duration_ms": 120_000})

    def detect_scenes(
        self, source: Path, *, duration_ms: int, threshold: float, max_shots: int
    ) -> SceneDetectionResult:
        del source, threshold, max_shots
        return SceneDetectionResult([0, duration_ms], [])


def test_long_single_shot_adds_uniform_keyframe_coverage(
    phase3_project: ProjectLayout,
    tmp_path: Path,
) -> None:
    source = tmp_path / "long-talking-head.mp4"
    source.write_bytes(b"offline-long-media")
    result = LocalMediaAnalysisService(
        phase3_project,
        backend=LongSingleShotBackend(),
    ).analyze(
        video_id="p2-01",
        file=source,
        max_keyframes=16,
    )
    analysis = MediaAnalysis.model_validate(result["analysis"])

    assert len(analysis.shots) == 1
    assert len(analysis.keyframes) == 12
    assert len(analysis.shots[0].keyframe_ids) == 12
    assert [item.timestamp_ms for item in analysis.keyframes] == sorted(
        item.timestamp_ms for item in analysis.keyframes
    )
