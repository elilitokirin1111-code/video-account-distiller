"""Bounded account media enrichment from retained Provider evidence."""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any, Literal, Protocol
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from pydantic import ValidationError

from video_account_distiller.distillation import AccountDistillationService
from video_account_distiller.errors import DistillerError, ErrorCode
from video_account_distiller.features import VideoAnalysisService
from video_account_distiller.media.backend import MediaBackend
from video_account_distiller.media.pipeline import (
    MEDIA_ANALYSIS_VERSION,
    LocalMediaAnalysisService,
)
from video_account_distiller.media.providers import VisionModelProvider
from video_account_distiller.models import (
    AccountCollectionBatch,
    AccountMediaEnrichment,
    MediaAnalysis,
    MediaFeatureRecord,
    SingleVideoAnalysis,
    TranscriptionSummary,
    TranscriptSegment,
    VideoMediaEnrichment,
)
from video_account_distiller.normalization import NormalizationService
from video_account_distiller.storage.parquet import read_models
from video_account_distiller.storage.project import ProjectLayout
from video_account_distiller.transcripts import TranscriptImportService
from video_account_distiller.utils.hashing import sha256_file, sha256_json
from video_account_distiller.utils.ids import stable_id
from video_account_distiller.utils.io import atomic_write_json, read_json
from video_account_distiller.utils.lookup import resolve_video

ACCOUNT_MEDIA_ADAPTER_VERSION = "0.1.0"
CLAUDE_VIDEO_UPSTREAM_COMMIT = "83da59fa78c3eee9e20f515fe75c438bb5166efd"
SELECTION_POLICY = "provider_order_unanalyzed_first"
ALLOWED_MEDIA_HOST_SUFFIXES = (".douyinvod.com", ".douyin.com")
MAX_MEDIA_BYTES = 512 * 1024 * 1024
DEFAULT_DOWNLOAD_TIMEOUT_SECONDS = 120
EnrichmentProgress = Callable[[float, str], None]


def _ignore_enrichment_progress(value: float, message: str) -> None:
    del value, message


DEFAULT_TRANSCRIPTION_TIMEOUT_SECONDS = 3600
MODEL_NAME_RE = re.compile(r"^[A-Za-z0-9._-]{1,64}$")


@dataclass(frozen=True)
class ProviderVideoSource:
    """Internal source resolution that is never serialized with signed URLs."""

    video_id: str
    platform_video_id: str
    candidates: tuple[str, ...]


@dataclass(frozen=True)
class DownloadedMedia:
    """Safe metadata about a downloaded public media response."""

    path: Path
    host: str
    size_bytes: int


@dataclass(frozen=True)
class TranscribedMedia:
    """Normalized local transcript file produced by a transcriber."""

    path: Path
    provider: str
    model: str
    language: str
    segment_count: int


class MediaDownloader(Protocol):
    """Mockable bounded media downloader."""

    def download(
        self,
        candidates: Sequence[str],
        destination: Path,
    ) -> DownloadedMedia: ...


class LocalTranscriber(Protocol):
    """Mockable local speech-to-text provider."""

    provider_name: str
    model_name: str

    @property
    def available(self) -> bool: ...

    def transcribe(
        self,
        source: Path,
        destination: Path,
        *,
        language: str,
    ) -> TranscribedMedia: ...


def _allowed_media_host(host: str) -> bool:
    normalized = host.casefold().rstrip(".")
    return normalized in {"douyin.com", "douyinvod.com"} or any(
        normalized.endswith(suffix) for suffix in ALLOWED_MEDIA_HOST_SUFFIXES
    )


def _validated_media_url(value: str) -> tuple[str, str]:
    if len(value) > 8192:
        raise ValueError("media URL exceeds the accepted length")
    parsed = urlparse(value)
    host = (parsed.hostname or "").casefold().rstrip(".")
    if (
        parsed.scheme != "https"
        or not host
        or parsed.username
        or parsed.password
        or parsed.port is not None
        or not _allowed_media_host(host)
    ):
        raise ValueError("media URL is outside the approved Douyin CDN boundary")
    return value, host


class HttpMediaDownloader:
    """Download only allowlisted HTTPS Douyin media with a hard byte limit."""

    def __init__(
        self,
        *,
        max_bytes: int = MAX_MEDIA_BYTES,
        timeout_seconds: int = DEFAULT_DOWNLOAD_TIMEOUT_SECONDS,
    ) -> None:
        self.max_bytes = max_bytes
        self.timeout_seconds = timeout_seconds

    def download(
        self,
        candidates: Sequence[str],
        destination: Path,
    ) -> DownloadedMedia:
        destination = destination.expanduser().resolve()
        destination.parent.mkdir(parents=True, exist_ok=True)
        failures: list[str] = []
        for value in candidates:
            try:
                url, requested_host = _validated_media_url(value)
            except ValueError:
                failures.append("rejected_unapproved_source")
                continue
            request = Request(
                url,
                headers={
                    "User-Agent": (
                        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                        "AppleWebKit/537.36 Chrome/138 Safari/537.36"
                    ),
                    "Referer": "https://www.douyin.com/",
                    "Accept": "video/*,application/octet-stream;q=0.9,*/*;q=0.1",
                },
            )
            try:
                with urlopen(request, timeout=self.timeout_seconds) as response:  # noqa: S310
                    final_url = response.geturl()
                    _, final_host = _validated_media_url(final_url)
                    content_length = response.headers.get("Content-Length")
                    if content_length is not None and int(content_length) > self.max_bytes:
                        raise DistillerError(
                            ErrorCode.MEDIA_DOWNLOAD_FAILED,
                            "Public media exceeds the configured download limit",
                            details={"host": final_host, "max_bytes": self.max_bytes},
                        )
                    size = 0
                    with destination.open("wb") as target:
                        while chunk := response.read(1024 * 1024):
                            size += len(chunk)
                            if size > self.max_bytes:
                                raise DistillerError(
                                    ErrorCode.MEDIA_DOWNLOAD_FAILED,
                                    "Public media exceeded the configured download limit",
                                    details={"host": final_host, "max_bytes": self.max_bytes},
                                )
                            target.write(chunk)
                if size <= 0:
                    raise DistillerError(
                        ErrorCode.MEDIA_DOWNLOAD_FAILED,
                        "Public media response was empty",
                        details={"host": final_host},
                    )
                return DownloadedMedia(path=destination, host=final_host, size_bytes=size)
            except DistillerError:
                destination.unlink(missing_ok=True)
                raise
            except (HTTPError, URLError, OSError, TimeoutError, ValueError) as exc:
                destination.unlink(missing_ok=True)
                failures.append(f"{requested_host}:{type(exc).__name__}")
        raise DistillerError(
            ErrorCode.MEDIA_DOWNLOAD_FAILED,
            "No retained public media source could be downloaded",
            details={"attempts": len(candidates), "failures": failures[-5:]},
        )


class WhisperCliTranscriber:
    """Use a local OpenAI Whisper CLI and convert its JSON into project segments."""

    provider_name = "openai-whisper-cli"

    def __init__(
        self,
        *,
        command: str | Path | None = None,
        model: str = "base",
        timeout_seconds: int = DEFAULT_TRANSCRIPTION_TIMEOUT_SECONDS,
    ) -> None:
        if not MODEL_NAME_RE.fullmatch(model):
            raise DistillerError(
                ErrorCode.SCHEMA_INVALID,
                "Whisper model must contain only letters, digits, dot, underscore, or hyphen",
            )
        configured = str(command or os.environ.get("DISTILLER_WHISPER_COMMAND") or "whisper")
        discovered = shutil.which(configured)
        candidate = Path(configured).expanduser()
        self.command = discovered or (str(candidate.resolve()) if candidate.is_file() else None)
        self.model_name = model
        self.timeout_seconds = timeout_seconds

    @property
    def available(self) -> bool:
        return self.command is not None

    def transcribe(
        self,
        source: Path,
        destination: Path,
        *,
        language: str,
    ) -> TranscribedMedia:
        if self.command is None:
            raise DistillerError(
                ErrorCode.TRANSCRIPTION_UNAVAILABLE,
                "Local Whisper CLI is unavailable",
                details={
                    "next": (
                        "install openai-whisper or set DISTILLER_WHISPER_COMMAND to its executable"
                    )
                },
            )
        source = source.expanduser().resolve()
        destination = destination.expanduser().resolve()
        if not source.is_file():
            raise DistillerError(ErrorCode.INPUT_MISSING, f"Media file not found: {source}")
        destination.parent.mkdir(parents=True, exist_ok=True)
        with TemporaryDirectory(prefix="distiller-whisper-") as output_name:
            output_dir = Path(output_name)
            command = [
                self.command,
                str(source),
                "--model",
                self.model_name,
                "--language",
                language,
                "--task",
                "transcribe",
                "--output_format",
                "json",
                "--output_dir",
                str(output_dir),
                "--verbose",
                "False",
                "--fp16",
                "False",
            ]
            try:
                child_env = os.environ.copy()
                # Windows may otherwise expose a legacy console encoding (for
                # example GBK) to Whisper. One undecodable transcript glyph can
                # then make the CLI exit before it writes its JSON result.
                child_env["PYTHONIOENCODING"] = "utf-8"
                completed = subprocess.run(
                    command,
                    capture_output=True,
                    check=False,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    env=child_env,
                    timeout=self.timeout_seconds,
                    creationflags=(
                        subprocess.CREATE_NO_WINDOW
                        if os.name == "nt" and hasattr(subprocess, "CREATE_NO_WINDOW")
                        else 0
                    ),
                )
            except subprocess.TimeoutExpired as exc:
                raise DistillerError(
                    ErrorCode.TRANSCRIPTION_FAILED,
                    "Local Whisper transcription timed out",
                    details={"timeout_seconds": self.timeout_seconds},
                ) from exc
            except OSError as exc:
                raise DistillerError(
                    ErrorCode.TRANSCRIPTION_UNAVAILABLE,
                    "Local Whisper CLI could not be started",
                    details={"reason": type(exc).__name__},
                ) from exc
            if completed.returncode != 0:
                reason = (completed.stderr or completed.stdout or "").strip().splitlines()
                raise DistillerError(
                    ErrorCode.TRANSCRIPTION_FAILED,
                    "Local Whisper transcription failed",
                    details={
                        "return_code": completed.returncode,
                        "reason": (reason[-1][:300] if reason else "unknown"),
                    },
                )
            candidates = sorted(output_dir.glob("*.json"))
            if not candidates:
                raise DistillerError(
                    ErrorCode.TRANSCRIPTION_FAILED,
                    "Local Whisper produced no JSON transcript",
                )
            try:
                payload = json.loads(candidates[0].read_text(encoding="utf-8-sig"))
            except (UnicodeError, json.JSONDecodeError) as exc:
                raise DistillerError(
                    ErrorCode.TRANSCRIPTION_FAILED,
                    "Local Whisper JSON transcript could not be parsed",
                    details={"reason": type(exc).__name__},
                ) from exc
            raw_segments = payload.get("segments") if isinstance(payload, dict) else None
            if not isinstance(raw_segments, list):
                raise DistillerError(
                    ErrorCode.TRANSCRIPTION_FAILED,
                    "Local Whisper JSON has no segment list",
                )
            segments: list[dict[str, Any]] = []
            for index, raw in enumerate(raw_segments, start=1):
                if not isinstance(raw, dict):
                    continue
                text = str(raw.get("text") or "").strip()
                if not text:
                    continue
                start = raw.get("start")
                end = raw.get("end")
                segments.append(
                    {
                        "segment_id": str(raw.get("id") or index),
                        "start": float(start) if start is not None else None,
                        "end": float(end) if end is not None else None,
                        "text": text,
                    }
                )
            if not segments:
                raise DistillerError(
                    ErrorCode.TRANSCRIPTION_FAILED,
                    "Local Whisper returned no usable transcript segments",
                )
            atomic_write_json(
                destination,
                {
                    "provider": self.provider_name,
                    "model": self.model_name,
                    "language": language,
                    "segments": segments,
                },
            )
        return TranscribedMedia(
            path=destination,
            provider=self.provider_name,
            model=self.model_name,
            language=language,
            segment_count=len(segments),
        )


def _dict_at(value: object, *keys: str) -> dict[str, Any]:
    current = value
    for key in keys:
        if not isinstance(current, dict):
            return {}
        current = current.get(key)
    return current if isinstance(current, dict) else {}


def _strings_at(value: object, *keys: str) -> list[str]:
    current: object = value
    for key in keys:
        if not isinstance(current, dict):
            return []
        current = current.get(key)
    if not isinstance(current, list):
        return []
    return [item for item in current if isinstance(item, str) and item.strip()]


def _media_candidates(payload: dict[str, Any]) -> tuple[str, ...]:
    video = _dict_at(payload, "video")
    candidates = [
        *_strings_at(video, "play_addr_h264", "url_list"),
        *_strings_at(video, "play_addr", "url_list"),
    ]
    bit_rates = video.get("bit_rate")
    if isinstance(bit_rates, list):
        for item in bit_rates:
            candidates.extend(_strings_at(item, "play_addr", "url_list"))
    candidates.extend(_strings_at(video, "download_addr", "url_list"))
    return tuple(dict.fromkeys(candidates))


def _load_matching_batch(
    project: ProjectLayout,
    account_id: str,
) -> tuple[AccountCollectionBatch, Path, str]:
    candidates: list[tuple[datetime, AccountCollectionBatch, Path, str]] = []
    root = project.root / "raw" / "account-collections" / "mediacrawler"
    for path in root.glob("*/provider-batch.json"):
        try:
            batch = AccountCollectionBatch.model_validate(read_json(path))
        except (OSError, ValidationError, ValueError):
            continue
        candidate_account_id = stable_id("acc_", "douyin", batch.platform_account_id)
        if candidate_account_id != account_id:
            continue
        candidates.append((batch.fetched_at, batch, path, sha256_file(path)))
    if not candidates:
        raise DistillerError(
            ErrorCode.INPUT_MISSING,
            f"No retained MediaCrawler batch found for account: {account_id}",
            details={
                "next": "run account analyze with --provider mediacrawler before media enrichment"
            },
        )
    _, batch, path, batch_hash = max(candidates, key=lambda item: item[0])
    return batch, path, batch_hash


def _provider_sources(
    project: ProjectLayout,
    account_id: str,
    batch: AccountCollectionBatch,
) -> list[ProviderVideoSource]:
    details: dict[str, dict[str, Any]] = {}
    for page in batch.raw_pages:
        payload = page.payload
        platform_video_id = str(payload.get("aweme_id") or "").strip()
        if platform_video_id and isinstance(payload.get("video"), dict):
            details[platform_video_id] = payload
    sources: list[ProviderVideoSource] = []
    for collected in batch.videos:
        video = resolve_video(project, collected.platform_video_id)
        if video.account_id != account_id:
            raise DistillerError(
                ErrorCode.RAW_INTEGRITY,
                "Retained media source resolved to a different normalized account",
                details={"video_id": video.video_id},
            )
        payload = details.get(collected.platform_video_id, {})
        sources.append(
            ProviderVideoSource(
                video_id=video.video_id,
                platform_video_id=collected.platform_video_id,
                candidates=_media_candidates(payload),
            )
        )
    return sources


def _has_existing_video_analysis(project: ProjectLayout, video_id: str) -> bool:
    """Return whether a valid single-video analysis already exists.

    Selection is a work-avoidance concern, not a semantic-quality gate. A
    completed analysis whose deterministic fallback leaves ``primary_pillar``
    as ``unknown`` has still consumed the retained media and transcript. Treat
    it as analyzed so later bounded batches can advance to unseen videos.
    """

    for path in (project.root / "analyses" / "videos" / video_id).glob("*/analysis.json"):
        try:
            SingleVideoAnalysis.model_validate(read_json(path))
        except (OSError, ValidationError, ValueError):
            continue
        return True
    return False


def _select_sources(
    project: ProjectLayout,
    sources: Sequence[ProviderVideoSource],
    limit: int,
) -> list[ProviderVideoSource]:
    ordered = sorted(
        enumerate(sources),
        key=lambda item: (_has_existing_video_analysis(project, item[1].video_id), item[0]),
    )
    return [item[1] for item in ordered[:limit]]


def _existing_transcripts(project: ProjectLayout) -> dict[str, list[TranscriptSegment]]:
    grouped: dict[str, list[TranscriptSegment]] = {}
    for segment in read_models(
        project.normalized_dir / "transcripts.parquet",
        TranscriptSegment,
    ):
        grouped.setdefault(segment.video_id, []).append(segment)
    return grouped


def _existing_media(
    project: ProjectLayout,
) -> dict[str, tuple[MediaAnalysis, Path, str]]:
    grouped: dict[str, tuple[MediaAnalysis, Path, str]] = {}
    features = read_models(
        project.normalized_dir / "media_features.parquet",
        MediaFeatureRecord,
    )
    for feature in features:
        analysis_path = project.root / feature.analysis_path
        if not analysis_path.is_file():
            continue
        try:
            analysis = MediaAnalysis.model_validate(read_json(analysis_path))
        except (OSError, ValidationError, ValueError):
            continue
        raw_path = project.root / analysis.raw_media_path
        if not raw_path.is_file():
            continue
        if sha256_file(raw_path) != analysis.metadata.media_hash:
            raise DistillerError(
                ErrorCode.RAW_INTEGRITY,
                f"Stored raw media hash mismatch: {analysis.raw_media_path}",
            )
        previous = grouped.get(feature.video_id)
        if previous is None or (analysis.generated_at, analysis.analysis_id) > (
            previous[0].generated_at,
            previous[0].analysis_id,
        ):
            grouped[feature.video_id] = (analysis, raw_path, feature.analysis_path)
    return grouped


def _reused_transcription(segments: Sequence[TranscriptSegment]) -> TranscriptionSummary:
    hashes = sorted({item.raw_hash for item in segments})
    paths = sorted({item.source_uri for item in segments if item.source_uri is not None})
    source_name = segments[0].source or "existing_transcript"
    provider, separator, model = source_name.partition(":")
    return TranscriptionSummary(
        status="reused",
        provider=provider,
        model=model if separator and model else None,
        language=segments[0].language,
        segment_count=len(segments),
        raw_hash=hashes[0] if len(hashes) == 1 else sha256_json(hashes),
        raw_path=paths[0] if len(paths) == 1 else None,
        warnings=(["multiple_transcript_sources_reused"] if len(hashes) > 1 else []),
    )


class AccountMediaEnrichmentService:
    """Complete media, transcript, single-video analysis, and re-distillation."""

    def __init__(
        self,
        project: ProjectLayout,
        *,
        downloader: MediaDownloader | None = None,
        transcriber: LocalTranscriber | None = None,
        media_backend: MediaBackend | None = None,
        vision_provider: VisionModelProvider | None = None,
    ) -> None:
        self.project = project
        self.downloader = downloader or HttpMediaDownloader()
        self.transcriber = transcriber or WhisperCliTranscriber()
        self.media_backend = media_backend
        self.vision_provider = vision_provider

    def enrich(
        self,
        *,
        account_id: str,
        limit: int = 3,
        strict: bool = False,
        strict_vision: bool = False,
        scene_threshold: float | None = None,
        max_keyframes: int | None = None,
        dry_run: bool = False,
        progress: EnrichmentProgress = _ignore_enrichment_progress,
    ) -> dict[str, Any]:
        """Enrich a bounded sample using only retained, approved Provider evidence."""

        if limit < 1 or limit > 20:
            raise DistillerError(
                ErrorCode.SCHEMA_INVALID,
                "media enrichment limit must be between 1 and 20",
            )
        batch, batch_path, batch_hash = _load_matching_batch(self.project, account_id)
        sources = _provider_sources(self.project, account_id, batch)
        selected = _select_sources(self.project, sources, limit)
        if dry_run:
            source_preview = []
            for source in selected:
                hosts: list[str] = []
                for value in source.candidates:
                    try:
                        _, host = _validated_media_url(value)
                    except ValueError:
                        continue
                    hosts.append(host)
                source_preview.append(
                    {
                        "video_id": source.video_id,
                        "platform_video_id": source.platform_video_id,
                        "candidate_count": len(source.candidates),
                        "candidate_hosts": sorted(set(hosts)),
                    }
                )
            return {
                "ok": True,
                "dry_run": True,
                "account_id": account_id,
                "source_batch_hash": batch_hash,
                "source_batch_path": self.project.relative(batch_path),
                "adapter_version": ACCOUNT_MEDIA_ADAPTER_VERSION,
                "upstream_commit": CLAUDE_VIDEO_UPSTREAM_COMMIT,
                "selection_policy": SELECTION_POLICY,
                "requested_limit": limit,
                "selected": source_preview,
                "transcriber": {
                    "provider": self.transcriber.provider_name,
                    "model": self.transcriber.model_name,
                    "available": self.transcriber.available,
                },
                "vision": {
                    "provider": (
                        self.vision_provider.provider_name if self.vision_provider else "none"
                    ),
                    "model": self.vision_provider.model_name if self.vision_provider else None,
                },
                "would_write": [
                    "raw/media/<sha256>.mp4",
                    "raw/imports/transcripts/<sha256>.json",
                    "staging/transcripts/",
                    "normalized/transcripts.parquet",
                    "normalized/media_features.parquet",
                    "analyses/media/",
                    "analyses/videos/",
                    "analyses/accounts/<account>/media-enrichments/",
                    "reports/accounts/",
                ],
            }

        manifest = self.project.begin_run("account enrich media", input_hashes=[batch_hash])
        items: list[VideoMediaEnrichment] = []
        warnings: list[str] = []
        new_transcript_count = 0
        transcript_normalization_required = False
        existing_transcripts = _existing_transcripts(self.project)
        existing_media = _existing_media(self.project)
        try:
            with TemporaryDirectory(prefix="distiller-account-media-") as temp_name:
                temp_root = Path(temp_name)
                selected_total = max(len(selected), 1)
                for source_index, source in enumerate(selected):
                    progress(
                        source_index / selected_total * 0.68,
                        (
                            f"正在处理视频 {source_index + 1}/{len(selected)}："
                            "下载、画面、声音与字幕"
                        ),
                    )
                    item_warnings: list[str] = []
                    source_host: str | None = None
                    media_result: dict[str, Any] | None = None
                    transcription = TranscriptionSummary(
                        status="skipped",
                        provider=self.transcriber.provider_name,
                        model=self.transcriber.model_name,
                        language="zh",
                        warnings=["transcription_not_started"],
                    )
                    media_path: Path | None = None
                    try:
                        existing = existing_media.get(source.video_id)
                        if existing is not None:
                            stored_analysis, media_path, stored_analysis_path = existing
                            vision_is_current = self.vision_provider is None or (
                                stored_analysis.vision_trace.status == "success"
                                and stored_analysis.vision_trace.provider
                                == self.vision_provider.provider_name
                                and stored_analysis.vision_trace.model
                                == self.vision_provider.model_name
                            )
                            if (
                                stored_analysis.analysis_version == MEDIA_ANALYSIS_VERSION
                                and vision_is_current
                            ):
                                media_result = {
                                    "ok": True,
                                    "already_generated": True,
                                    "analysis": stored_analysis.model_dump(mode="json"),
                                    "outputs": [stored_analysis_path],
                                }
                                item_warnings.append("existing_media_analysis_reused")
                            else:
                                media_result = LocalMediaAnalysisService(
                                    self.project,
                                    backend=self.media_backend,
                                ).analyze(
                                    video_id=source.video_id,
                                    file=media_path,
                                    strict_media=strict,
                                    provider=self.vision_provider,
                                    strict_vision=strict_vision,
                                    scene_threshold=scene_threshold,
                                    max_keyframes=max_keyframes,
                                )
                                item_warnings.append("media_analysis_version_refreshed")
                        else:
                            if not source.candidates:
                                raise DistillerError(
                                    ErrorCode.MEDIA_DOWNLOAD_FAILED,
                                    "Retained Provider detail has no usable video source",
                                    details={"video_id": source.video_id},
                                )
                            video_temp = temp_root / source.video_id
                            downloaded = self.downloader.download(
                                source.candidates,
                                video_temp / "source.mp4",
                            )
                            media_path = downloaded.path
                            source_host = downloaded.host
                            media_result = LocalMediaAnalysisService(
                                self.project,
                                backend=self.media_backend,
                            ).analyze(
                                video_id=source.video_id,
                                file=media_path,
                                strict_media=strict,
                                provider=self.vision_provider,
                                strict_vision=strict_vision,
                                scene_threshold=scene_threshold,
                                max_keyframes=max_keyframes,
                            )
                        segments = existing_transcripts.get(source.video_id, [])
                        if segments:
                            transcription = _reused_transcription(segments)
                        else:
                            if not self.transcriber.available:
                                raise DistillerError(
                                    ErrorCode.TRANSCRIPTION_UNAVAILABLE,
                                    "Local transcription is unavailable",
                                    details={
                                        "next": (
                                            "install openai-whisper or configure "
                                            "DISTILLER_WHISPER_COMMAND"
                                        )
                                    },
                                )
                            assert media_path is not None
                            transcript_temp = temp_root / source.video_id / "transcript.json"
                            generated = self.transcriber.transcribe(
                                media_path,
                                transcript_temp,
                                language="zh",
                            )
                            receipt, report, already_imported = TranscriptImportService(
                                self.project
                            ).import_file(
                                video_id=source.video_id,
                                source=generated.path,
                                language="zh-CN",
                                source_name=f"{generated.provider}:{generated.model}",
                            )
                            if report.error_count:
                                raise DistillerError(
                                    ErrorCode.SCHEMA_INVALID,
                                    "Generated transcript failed project validation",
                                    details={"errors": report.error_count},
                                )
                            if receipt is None:
                                raise DistillerError(
                                    ErrorCode.INTERNAL,
                                    "Transcript import did not produce a receipt",
                                )
                            transcript_normalization_required = True
                            new_transcript_count += int(not already_imported)
                            transcription = TranscriptionSummary(
                                status="reused" if already_imported else "complete",
                                provider=generated.provider,
                                model=generated.model,
                                language=generated.language,
                                segment_count=report.stats["accepted_rows"],
                                raw_hash=receipt.raw_hash,
                                raw_path=receipt.raw_path,
                                warnings=report.warnings,
                            )
                    except DistillerError as exc:
                        if strict:
                            raise
                        if media_result is None:
                            item_status: Literal["degraded", "failed"] = "failed"
                        else:
                            item_status = "degraded"
                        item_warnings.append(exc.code.value)
                        item_warnings.append(exc.message)
                        if exc.code in {
                            ErrorCode.TRANSCRIPTION_FAILED,
                            ErrorCode.TRANSCRIPTION_UNAVAILABLE,
                        }:
                            transcription = TranscriptionSummary(
                                status="failed",
                                provider=self.transcriber.provider_name,
                                model=self.transcriber.model_name,
                                language="zh",
                                warnings=[exc.code.value, exc.message],
                            )
                        media_analysis = (
                            MediaAnalysis.model_validate(media_result["analysis"])
                            if media_result is not None
                            else None
                        )
                        items.append(
                            VideoMediaEnrichment(
                                video_id=source.video_id,
                                platform_video_id=source.platform_video_id,
                                status=item_status,
                                source_host=source_host,
                                media_hash=(
                                    media_analysis.metadata.media_hash if media_analysis else None
                                ),
                                media_analysis_id=(
                                    media_analysis.analysis_id if media_analysis else None
                                ),
                                media_analysis_path=(
                                    media_result["outputs"][0] if media_result is not None else None
                                ),
                                vision_status=(
                                    media_analysis.vision_trace.status
                                    if media_analysis is not None
                                    else None
                                ),
                                transcription=transcription,
                                warnings=item_warnings,
                            )
                        )
                        continue
                    assert media_result is not None
                    media_analysis = MediaAnalysis.model_validate(media_result["analysis"])
                    items.append(
                        VideoMediaEnrichment(
                            video_id=source.video_id,
                            platform_video_id=source.platform_video_id,
                            status="complete",
                            source_host=source_host,
                            media_hash=media_analysis.metadata.media_hash,
                            media_analysis_id=media_analysis.analysis_id,
                            media_analysis_path=media_result["outputs"][0],
                            vision_status=media_analysis.vision_trace.status,
                            transcription=transcription,
                            warnings=item_warnings,
                        )
                    )

            progress(0.7, "视频下载、画面、声音与字幕处理完成")
            if transcript_normalization_required:
                progress(0.72, "正在标准化新生成的字幕")
                NormalizationService(self.project).normalize()
            for index, item in enumerate(items):
                progress(
                    0.75 + (index / max(len(items), 1) * 0.17),
                    f"正在生成视频文本分析 {index + 1}/{len(items)}",
                )
                if item.status == "failed" or item.transcription.status == "failed":
                    continue
                try:
                    text_result = VideoAnalysisService(self.project).analyze(video_id=item.video_id)
                    text_analysis = text_result["analysis"]
                    text_status = str(text_analysis["status"])
                    updated_warnings = list(item.warnings)
                    if text_status == "degraded":
                        updated_warnings.append("text_analysis_degraded_local_heuristic")
                    items[index] = item.model_copy(
                        update={
                            "text_analysis_id": str(text_analysis["analysis_id"]),
                            "text_analysis_path": str(text_result["outputs"][0]),
                            "text_analysis_status": text_status,
                            "warnings": list(dict.fromkeys(updated_warnings)),
                        }
                    )
                except DistillerError as exc:
                    if strict:
                        raise
                    items[index] = item.model_copy(
                        update={
                            "status": "degraded",
                            "warnings": list(
                                dict.fromkeys([*item.warnings, exc.code.value, exc.message])
                            ),
                        }
                    )

            progress(0.94, "正在用新增视频证据重建账号蒸馏")
            distillation = AccountDistillationService(self.project).distill(account_id=account_id)
            distillation_payload = distillation["distillation"]
            seed = {
                "adapter_version": ACCOUNT_MEDIA_ADAPTER_VERSION,
                "upstream_commit": CLAUDE_VIDEO_UPSTREAM_COMMIT,
                "account_id": account_id,
                "source_batch_hash": batch_hash,
                "selection_policy": SELECTION_POLICY,
                "requested_limit": limit,
                "videos": [
                    {
                        "video_id": item.video_id,
                        "media_hash": item.media_hash,
                        "media_analysis_id": item.media_analysis_id,
                        "transcript_hash": item.transcription.raw_hash,
                        "text_analysis_id": item.text_analysis_id,
                    }
                    for item in items
                ],
                "distillation_id": distillation_payload["distillation_id"],
            }
            enrichment_id = stable_id("ame_", sha256_json(seed))
            output_dir = (
                self.project.root
                / "analyses"
                / "accounts"
                / account_id
                / "media-enrichments"
                / enrichment_id
            )
            enrichment_path = output_dir / "enrichment.json"
            warning_path = output_dir / "warnings.json"
            completed_count = sum(item.status == "complete" for item in items)
            degraded_count = sum(item.status == "degraded" for item in items)
            failed_count = sum(item.status == "failed" for item in items)
            if failed_count:
                warnings.append(f"media_enrichment_failed_videos:{failed_count}")
            if degraded_count:
                warnings.append(f"media_enrichment_degraded_videos:{degraded_count}")
            if any(item.transcription.status == "failed" for item in items):
                warnings.append("transcript_coverage_incomplete")
            warnings = list(dict.fromkeys(warnings))
            enrichment = AccountMediaEnrichment(
                enrichment_id=enrichment_id,
                account_id=account_id,
                generated_at=datetime.now(UTC),
                run_id=manifest.run_id,
                adapter_version=ACCOUNT_MEDIA_ADAPTER_VERSION,
                upstream_commit=CLAUDE_VIDEO_UPSTREAM_COMMIT,
                source_provider=batch.provider.value,
                source_batch_hash=batch_hash,
                source_batch_path=self.project.relative(batch_path),
                selection_policy=SELECTION_POLICY,
                requested_limit=limit,
                selected_count=len(items),
                completed_count=completed_count,
                degraded_count=degraded_count,
                failed_count=failed_count,
                videos=items,
                distillation_id=str(distillation_payload["distillation_id"]),
                distillation_path=str(distillation["outputs"][0]),
                warnings=warnings,
            )
            already_generated = enrichment_path.is_file()
            if already_generated:
                existing_payload = AccountMediaEnrichment.model_validate(read_json(enrichment_path))
                enrichment = existing_payload
            else:
                output_dir.mkdir(parents=True, exist_ok=True)
                atomic_write_json(enrichment_path, enrichment.model_dump(mode="json"))
                atomic_write_json(warning_path, warnings)
            outputs = [
                self.project.relative(enrichment_path),
                self.project.relative(warning_path),
                str(distillation["outputs"][0]),
            ]
            self.project.finish_run(
                manifest,
                success=True,
                processed_counts={
                    "selected_videos": len(items),
                    "completed_videos": completed_count,
                    "degraded_videos": degraded_count,
                    "failed_videos": failed_count,
                    "new_transcripts": new_transcript_count,
                },
                output_files=outputs,
                warnings=warnings,
            )
            progress(1.0, "视频内容增强完成")
            return {
                "ok": failed_count == 0,
                "dry_run": False,
                "already_generated": already_generated,
                "enrichment": enrichment.model_dump(mode="json"),
                "outputs": outputs,
            }
        except Exception as exc:
            self.project.finish_run(
                manifest,
                success=False,
                errors=[type(exc).__name__],
            )
            raise
