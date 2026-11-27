"""Bounded account media enrichment from retained Provider evidence."""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from functools import lru_cache
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any, Literal, Protocol
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from pydantic import ValidationError

from video_account_distiller.distillation import AccountDistillationService
from video_account_distiller.errors import DistillerError, ErrorCode
from video_account_distiller.features import TextModelProvider, VideoAnalysisService
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

ACCOUNT_MEDIA_ADAPTER_VERSION = "0.2.0"
CLAUDE_VIDEO_UPSTREAM_COMMIT = "83da59fa78c3eee9e20f515fe75c438bb5166efd"
SELECTION_POLICY = "provider_order_unanalyzed_first"
MAX_ACCOUNT_MEDIA_VIDEOS = 20_000
ALLOWED_MEDIA_HOST_SUFFIXES = (".douyinvod.com", ".douyin.com")
MAX_MEDIA_BYTES = 512 * 1024 * 1024
DEFAULT_DOWNLOAD_TIMEOUT_SECONDS = 120
EnrichmentProgress = Callable[[float, str], None]


def _ignore_enrichment_progress(value: float, message: str) -> None:
    del value, message


DEFAULT_TRANSCRIPTION_TIMEOUT_SECONDS = 3600
MODEL_NAME_RE = re.compile(r"^[A-Za-z0-9._-]{1,64}$")
NO_SPEECH_DETECTED = "no_speech_detected"
RETAINED_SOURCE_UNAVAILABLE = "retained_source_unavailable"
RETAINED_NON_VIDEO_POST = "retained_non_video_post"


@dataclass(frozen=True)
class ProviderVideoSource:
    """Internal source resolution that is never serialized with signed URLs."""

    video_id: str
    platform_video_id: str
    candidates: tuple[str, ...]
    skip_reason: str | None = None


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
            atomic_write_json(
                destination,
                {
                    "provider": self.provider_name,
                    "model": self.model_name,
                    "language": language,
                    "segments": segments,
                    "warnings": [NO_SPEECH_DETECTED] if not segments else [],
                },
            )
        return TranscribedMedia(
            path=destination,
            provider=self.provider_name,
            model=self.model_name,
            language=language,
            segment_count=len(segments),
        )


def _faster_whisper_python_candidates(
    command: str | Path | None,
    python_executable: str | Path | None,
) -> tuple[str, ...]:
    candidates: list[str] = []

    def add(value: str | Path | None) -> None:
        if value is None:
            return
        raw = str(value)
        discovered = shutil.which(raw)
        path = Path(discovered or raw).expanduser()
        if not path.is_file():
            return
        resolved = str(path.resolve())
        if resolved not in candidates:
            candidates.append(resolved)

    add(python_executable)
    add(os.environ.get("DISTILLER_FASTER_WHISPER_PYTHON"))

    configured_whisper = str(command or os.environ.get("DISTILLER_WHISPER_COMMAND") or "whisper")
    whisper_path = shutil.which(configured_whisper)
    if whisper_path is None:
        candidate = Path(configured_whisper).expanduser()
        whisper_path = str(candidate.resolve()) if candidate.is_file() else None
    if whisper_path is not None:
        parent = Path(whisper_path).parent
        add(parent / ("python.exe" if os.name == "nt" else "python"))

    add(sys.executable)
    add(shutil.which("python"))
    return tuple(candidates)


@lru_cache(maxsize=16)
def _probe_faster_whisper_runtime(
    python_executable: str,
    runner_path: str,
) -> dict[str, Any]:
    child_env = os.environ.copy()
    child_env["PYTHONIOENCODING"] = "utf-8"
    try:
        completed = subprocess.run(
            [python_executable, runner_path, "--probe"],
            capture_output=True,
            check=False,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=child_env,
            timeout=30,
            creationflags=(
                subprocess.CREATE_NO_WINDOW
                if os.name == "nt" and hasattr(subprocess, "CREATE_NO_WINDOW")
                else 0
            ),
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {"available": False, "reason": type(exc).__name__}
    if completed.returncode != 0:
        reason = (completed.stderr or completed.stdout or "").strip().splitlines()
        return {
            "available": False,
            "reason": reason[-1][:300] if reason else f"exit_{completed.returncode}",
        }
    try:
        payload = json.loads(completed.stdout)
    except json.JSONDecodeError:
        return {"available": False, "reason": "invalid_probe_output"}
    return payload if isinstance(payload, dict) else {"available": False}


class FasterWhisperTranscriber:
    """Use CTranslate2 faster-whisper with CUDA preference and CPU fallback."""

    provider_name = "faster-whisper"

    def __init__(
        self,
        *,
        command: str | Path | None = None,
        python_executable: str | Path | None = None,
        model: str = "base",
        device: Literal["auto", "cuda", "cpu"] = "auto",
        compute_type: str = "auto",
        batch_size: int = 8,
        vad_filter: bool = True,
        timeout_seconds: int = DEFAULT_TRANSCRIPTION_TIMEOUT_SECONDS,
    ) -> None:
        if not MODEL_NAME_RE.fullmatch(model):
            raise DistillerError(
                ErrorCode.SCHEMA_INVALID,
                "Whisper model must contain only letters, digits, dot, underscore, or hyphen",
            )
        if not 1 <= batch_size <= 32:
            raise DistillerError(
                ErrorCode.SCHEMA_INVALID,
                "faster-whisper batch size must be between 1 and 32",
            )
        self.model_name = model
        self.requested_device = device
        self.requested_compute_type = compute_type
        self.batch_size = batch_size
        self.vad_filter = vad_filter
        self.timeout_seconds = timeout_seconds
        self.runner_path = Path(__file__).with_name("_faster_whisper_runner.py").resolve()
        self.python_executable: str | None = None
        self.probe: dict[str, Any] = {"available": False, "reason": "runtime_not_found"}
        for candidate in _faster_whisper_python_candidates(command, python_executable):
            probe = _probe_faster_whisper_runtime(candidate, str(self.runner_path))
            if probe.get("available"):
                self.python_executable = candidate
                self.probe = probe
                break
            self.probe = probe

        detected_device = str(self.probe.get("device") or "cpu")
        self.device_name = detected_device if device == "auto" else device
        if compute_type == "auto":
            self.compute_type = "int8_float16" if self.device_name == "cuda" else "int8"
        else:
            self.compute_type = compute_type

    @property
    def available(self) -> bool:
        return self.python_executable is not None and bool(self.probe.get("available"))

    @property
    def diagnostics(self) -> dict[str, Any]:
        return {
            "python": self.python_executable,
            "device": self.device_name,
            "compute_type": self.compute_type,
            "batch_size": self.batch_size,
            "vad_filter": self.vad_filter,
            "faster_whisper_version": self.probe.get("faster_whisper_version"),
            "ctranslate2_version": self.probe.get("ctranslate2_version"),
            "cuda_devices": self.probe.get("cuda_devices", 0),
            "reason": self.probe.get("reason"),
        }

    def _command(
        self,
        source: Path,
        output: Path,
        *,
        language: str,
        device: str,
        compute_type: str,
    ) -> list[str]:
        assert self.python_executable is not None
        command = [
            self.python_executable,
            str(self.runner_path),
            "--source",
            str(source),
            "--output",
            str(output),
            "--model",
            self.model_name,
            "--language",
            language,
            "--device",
            device,
            "--compute-type",
            compute_type,
            "--batch-size",
            str(self.batch_size),
        ]
        command.append("--vad-filter" if self.vad_filter else "--no-vad-filter")
        return command

    def _execute(
        self,
        source: Path,
        output: Path,
        *,
        language: str,
        device: str,
        compute_type: str,
    ) -> subprocess.CompletedProcess[str]:
        child_env = os.environ.copy()
        child_env["PYTHONIOENCODING"] = "utf-8"
        return subprocess.run(
            self._command(
                source,
                output,
                language=language,
                device=device,
                compute_type=compute_type,
            ),
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

    def transcribe(
        self,
        source: Path,
        destination: Path,
        *,
        language: str,
    ) -> TranscribedMedia:
        if not self.available:
            raise DistillerError(
                ErrorCode.TRANSCRIPTION_UNAVAILABLE,
                "faster-whisper runtime is unavailable",
                details={
                    "next": (
                        "install faster-whisper or set DISTILLER_FASTER_WHISPER_PYTHON "
                        "to a compatible Python executable"
                    ),
                    **self.diagnostics,
                },
            )
        source = source.expanduser().resolve()
        destination = destination.expanduser().resolve()
        if not source.is_file():
            raise DistillerError(ErrorCode.INPUT_MISSING, f"Media file not found: {source}")
        destination.parent.mkdir(parents=True, exist_ok=True)

        attempts = [(self.device_name, self.compute_type)]
        if self.requested_device == "auto" and self.device_name == "cuda":
            attempts.append(("cpu", "int8"))
        failures: list[str] = []
        with TemporaryDirectory(prefix="distiller-faster-whisper-") as output_name:
            output = Path(output_name) / "transcript.json"
            for device, compute_type in attempts:
                output.unlink(missing_ok=True)
                try:
                    completed = self._execute(
                        source,
                        output,
                        language=language,
                        device=device,
                        compute_type=compute_type,
                    )
                except subprocess.TimeoutExpired as exc:
                    raise DistillerError(
                        ErrorCode.TRANSCRIPTION_FAILED,
                        "faster-whisper transcription timed out",
                        details={"timeout_seconds": self.timeout_seconds},
                    ) from exc
                except OSError as exc:
                    raise DistillerError(
                        ErrorCode.TRANSCRIPTION_UNAVAILABLE,
                        "faster-whisper runtime could not be started",
                        details={"reason": type(exc).__name__},
                    ) from exc
                if completed.returncode != 0:
                    reason = (completed.stderr or completed.stdout or "").strip().splitlines()
                    failures.append(reason[-1][:300] if reason else f"exit_{completed.returncode}")
                    continue
                if not output.is_file():
                    failures.append("transcript_output_missing")
                    continue
                try:
                    payload = json.loads(output.read_text(encoding="utf-8-sig"))
                except (UnicodeError, json.JSONDecodeError) as exc:
                    failures.append(type(exc).__name__)
                    continue
                raw_segments = payload.get("segments") if isinstance(payload, dict) else None
                if not isinstance(raw_segments, list):
                    failures.append("segment_list_missing")
                    continue
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
                self.device_name = device
                self.compute_type = compute_type
                atomic_write_json(
                    destination,
                    {
                        "provider": self.provider_name,
                        "model": self.model_name,
                        "language": language,
                        "segments": segments,
                        "warnings": [NO_SPEECH_DETECTED] if not segments else [],
                    },
                )
                return TranscribedMedia(
                    path=destination,
                    provider=self.provider_name,
                    model=self.model_name,
                    language=language,
                    segment_count=len(segments),
                )

        raise DistillerError(
            ErrorCode.TRANSCRIPTION_FAILED,
            "faster-whisper transcription failed",
            details={"attempts": len(attempts), "failures": failures},
        )


def build_local_transcriber(
    *,
    backend: str = "auto",
    command: str | Path | None = None,
    model: str = "base",
    batch_size: int = 8,
) -> LocalTranscriber:
    """Prefer faster-whisper when available and retain the original CLI fallback."""
    normalized = backend.strip().casefold()
    if normalized not in {"auto", "faster-whisper", "openai-whisper"}:
        raise DistillerError(
            ErrorCode.SCHEMA_INVALID,
            "Whisper backend must be auto, faster-whisper, or openai-whisper",
        )
    if normalized != "openai-whisper":
        faster = FasterWhisperTranscriber(
            command=command,
            model=model,
            batch_size=batch_size,
        )
        if normalized == "faster-whisper" or faster.available:
            return faster
    return WhisperCliTranscriber(command=command, model=model)


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
    if _is_retained_non_video_post(payload):
        # Douyin image posts expose their slideshow background audio under
        # video.play_addr. It is audio/mp4 or MP3, not a decodable video stream.
        return ()
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


def _is_retained_non_video_post(payload: dict[str, Any]) -> bool:
    images = payload.get("images")
    if not isinstance(images, list) or not images:
        return False
    video = _dict_at(payload, "video")
    duration = video.get("duration")
    try:
        duration_ms = float(duration or 0)
    except (TypeError, ValueError):
        return False
    return duration_ms <= 0


def _retained_video_payloads(payload: dict[str, Any]) -> tuple[dict[str, Any], ...]:
    """Return video records retained in detail and account-list response shapes."""

    candidates: list[object] = [payload, payload.get("aweme_detail")]
    aweme_list = payload.get("aweme_list")
    if isinstance(aweme_list, list):
        candidates.extend(aweme_list)
    return tuple(
        item
        for item in candidates
        if isinstance(item, dict)
        and str(item.get("aweme_id") or "").strip()
        and isinstance(item.get("video"), dict)
    )


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
    details: dict[str, list[dict[str, Any]]] = {}
    for page in batch.raw_pages:
        for payload in _retained_video_payloads(page.payload):
            platform_video_id = str(payload.get("aweme_id") or "").strip()
            details.setdefault(platform_video_id, []).append(payload)
    sources: list[ProviderVideoSource] = []
    for collected in batch.videos:
        video = resolve_video(project, collected.platform_video_id)
        if video.account_id != account_id:
            raise DistillerError(
                ErrorCode.RAW_INTEGRITY,
                "Retained media source resolved to a different normalized account",
                details={"video_id": video.video_id},
            )
        retained_payloads = details.get(collected.platform_video_id, [])
        candidates = tuple(
            dict.fromkeys(
                candidate
                for payload in retained_payloads
                for candidate in _media_candidates(payload)
            )
        )
        non_video_post = bool(retained_payloads) and all(
            _is_retained_non_video_post(payload) for payload in retained_payloads
        )
        sources.append(
            ProviderVideoSource(
                video_id=video.video_id,
                platform_video_id=collected.platform_video_id,
                candidates=candidates,
                skip_reason=RETAINED_NON_VIDEO_POST if non_video_post else None,
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
    *,
    mode: Literal["new", "failed_or_degraded", "selected", "all"] = "new",
    video_ids: Sequence[str] = (),
    account_id: str | None = None,
) -> list[ProviderVideoSource]:
    if mode == "all":
        return list(sources[:limit])
    if mode == "selected":
        requested = {value.strip() for value in video_ids if value.strip()}
        if not requested:
            raise DistillerError(
                ErrorCode.SCHEMA_INVALID,
                "Select at least one video before requesting selected media reparse",
            )
        matched = [
            source
            for source in sources
            if source.video_id in requested or source.platform_video_id in requested
        ]
        matched_ids = {
            identifier
            for source in matched
            for identifier in (source.video_id, source.platform_video_id)
        }
        unknown = sorted(requested - matched_ids)
        if unknown:
            raise DistillerError(
                ErrorCode.SCHEMA_INVALID,
                "Selected videos are not present in the retained account batch",
                details={"unknown_video_ids": unknown},
            )
        return matched[:limit]
    if mode == "failed_or_degraded":
        latest = _latest_enrichment_items(project, account_id)
        retry_sources: list[ProviderVideoSource] = []
        for source in sources:
            entry = latest.get(source.video_id)
            if _retry_recommended(project, entry[1] if entry is not None else None):
                retry_sources.append(source)
        return retry_sources[:limit]
    ordered = sorted(
        enumerate(sources),
        key=lambda item: (_has_existing_video_analysis(project, item[1].video_id), item[0]),
    )
    return [item[1] for item in ordered[:limit]]


def _latest_enrichment_items(
    project: ProjectLayout,
    account_id: str | None,
) -> dict[str, tuple[datetime, VideoMediaEnrichment]]:
    if account_id is None:
        return {}
    latest: dict[str, tuple[datetime, VideoMediaEnrichment]] = {}
    root = project.root / "analyses" / "accounts" / account_id / "media-enrichments"
    for path in root.glob("*/enrichment.json"):
        try:
            enrichment = AccountMediaEnrichment.model_validate(read_json(path))
        except (OSError, ValidationError, ValueError):
            continue
        for item in enrichment.videos:
            previous = latest.get(item.video_id)
            if previous is None or enrichment.generated_at >= previous[0]:
                latest[item.video_id] = (enrichment.generated_at, item)
    return latest


def _retry_recommended(project: ProjectLayout, item: VideoMediaEnrichment | None) -> bool:
    if item is None:
        return False
    if RETAINED_NON_VIDEO_POST in item.warnings:
        return False
    direct_retry = (
        item.status in {"failed", "degraded"}
        or item.transcription.status == "failed"
        or item.vision_status == "degraded"
        or item.text_analysis_status == "degraded"
    )
    if direct_retry or item.media_analysis_path is None:
        return direct_retry
    analysis_path = project.root / item.media_analysis_path
    try:
        analysis = MediaAnalysis.model_validate(read_json(analysis_path))
    except (OSError, ValidationError, ValueError):
        return True
    return analysis.status == "degraded"


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
        text_provider: TextModelProvider | None = None,
    ) -> None:
        self.project = project
        self.downloader = downloader or HttpMediaDownloader()
        self.transcriber = transcriber or WhisperCliTranscriber()
        self.media_backend = media_backend
        self.vision_provider = vision_provider
        self.text_provider = text_provider

    def reparse_candidates(self, *, account_id: str) -> dict[str, Any]:
        """List retained videos and the latest known parsing outcome for each one."""

        batch, batch_path, batch_hash = _load_matching_batch(self.project, account_id)
        sources = _provider_sources(self.project, account_id, batch)
        latest = _latest_enrichment_items(self.project, account_id)
        candidates: list[dict[str, Any]] = []
        for source in sources:
            entry = latest.get(source.video_id)
            item = entry[1] if entry is not None else None
            candidates.append(
                {
                    "video_id": source.video_id,
                    "platform_video_id": source.platform_video_id,
                    "status": item.status if item is not None else "not_analyzed",
                    "transcription_status": (
                        item.transcription.status if item is not None else "not_analyzed"
                    ),
                    "vision_status": item.vision_status if item is not None else None,
                    "text_analysis_status": (
                        item.text_analysis_status if item is not None else None
                    ),
                    "retry_recommended": _retry_recommended(self.project, item),
                    "warnings": item.warnings if item is not None else [],
                }
            )
        return {
            "ok": True,
            "account_id": account_id,
            "source_batch_hash": batch_hash,
            "source_batch_path": self.project.relative(batch_path),
            "candidate_count": len(candidates),
            "retry_recommended_count": sum(bool(item["retry_recommended"]) for item in candidates),
            "candidates": candidates,
        }

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
        text_provider: TextModelProvider | None = None,
        selection_mode: Literal["new", "failed_or_degraded", "selected", "all"] = "new",
        video_ids: Sequence[str] = (),
        refresh_media: bool = False,
        progress: EnrichmentProgress = _ignore_enrichment_progress,
    ) -> dict[str, Any]:
        """Enrich a bounded sample using only retained, approved Provider evidence."""

        if limit < 1 or limit > MAX_ACCOUNT_MEDIA_VIDEOS:
            raise DistillerError(
                ErrorCode.SCHEMA_INVALID,
                f"media enrichment limit must be between 1 and {MAX_ACCOUNT_MEDIA_VIDEOS}",
            )
        batch, batch_path, batch_hash = _load_matching_batch(self.project, account_id)
        sources = _provider_sources(self.project, account_id, batch)
        selected = _select_sources(
            self.project,
            sources,
            limit,
            mode=selection_mode,
            video_ids=video_ids,
            account_id=account_id,
        )
        selection_policy = (
            SELECTION_POLICY if selection_mode == "new" else f"media_reparse_{selection_mode}"
        )
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
                        "skip_reason": source.skip_reason,
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
                "selection_policy": selection_policy,
                "refresh_media": refresh_media,
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

        if not selected:
            return {
                "ok": True,
                "account_id": account_id,
                "no_changes": True,
                "selection_policy": selection_policy,
                "requested_limit": limit,
                "selected_count": 0,
                "message": "No failed or degraded videos currently require reparsing",
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
                                not refresh_media
                                and stored_analysis.status == "complete"
                                and stored_analysis.analysis_version == MEDIA_ANALYSIS_VERSION
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
                                source_gap_reason = (
                                    source.skip_reason or RETAINED_SOURCE_UNAVAILABLE
                                )
                                raise DistillerError(
                                    ErrorCode.MEDIA_DOWNLOAD_FAILED,
                                    (
                                        "Retained Provider item is not a video"
                                        if source_gap_reason == RETAINED_NON_VIDEO_POST
                                        else "Retained Provider detail has no usable video source"
                                    ),
                                    details={
                                        "video_id": source.video_id,
                                        "platform_video_id": source.platform_video_id,
                                        "reason": source_gap_reason,
                                    },
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
                            if generated.segment_count == 0:
                                item_warnings.append(NO_SPEECH_DETECTED)
                                transcription = TranscriptionSummary(
                                    status="complete",
                                    provider=generated.provider,
                                    model=generated.model,
                                    language=generated.language,
                                    segment_count=0,
                                    warnings=[NO_SPEECH_DETECTED],
                                )
                            else:
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
                        nonfatal_source_gap = (
                            exc.code == ErrorCode.MEDIA_DOWNLOAD_FAILED
                            and exc.details.get("reason")
                            in {RETAINED_SOURCE_UNAVAILABLE, RETAINED_NON_VIDEO_POST}
                        )
                        if strict and not nonfatal_source_gap:
                            raise
                        if media_result is None:
                            item_status: Literal["degraded", "failed"] = "failed"
                        else:
                            item_status = "degraded"
                        item_warnings.append(exc.code.value)
                        item_warnings.append(exc.message)
                        if nonfatal_source_gap:
                            item_warnings.append(str(exc.details["reason"]))
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
                    if media_analysis.status == "degraded":
                        item_warnings = list(
                            dict.fromkeys(
                                [
                                    *item_warnings,
                                    "media_analysis_degraded",
                                    *media_analysis.warnings,
                                ]
                            )
                        )
                    items.append(
                        VideoMediaEnrichment(
                            video_id=source.video_id,
                            platform_video_id=source.platform_video_id,
                            status=(
                                "degraded" if media_analysis.status == "degraded" else "complete"
                            ),
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
                if item.transcription.segment_count == 0:
                    items[index] = item.model_copy(
                        update={
                            "warnings": list(
                                dict.fromkeys([*item.warnings, "text_analysis_skipped_no_speech"])
                            )
                        }
                    )
                    continue
                try:
                    text_result = VideoAnalysisService(self.project).analyze(
                        video_id=item.video_id,
                        provider=text_provider or self.text_provider,
                    )
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
                "selection_policy": selection_policy,
                "refresh_media": refresh_media,
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
                selection_policy=selection_policy,
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
