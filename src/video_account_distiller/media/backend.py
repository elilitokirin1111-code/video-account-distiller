"""Local FFmpeg/FFprobe adapter behind a small mockable contract."""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from video_account_distiller.config import MediaSection
from video_account_distiller.models import MediaMetadata


class MediaBackendFailure(Exception):
    """A local decoder command failed or returned an invalid result."""


@dataclass(frozen=True)
class SceneDetectionResult:
    """Timestamp boundaries and any recoverable local warnings."""

    boundaries_ms: list[int]
    warnings: list[str]


class MediaBackend(Protocol):
    """Contract used by the media pipeline and offline tests."""

    @property
    def available(self) -> bool: ...

    @property
    def name(self) -> str: ...

    @property
    def version(self) -> str | None: ...

    def probe(self, source: Path, media_hash: str) -> MediaMetadata: ...

    def detect_scenes(
        self, source: Path, *, duration_ms: int, threshold: float, max_shots: int
    ) -> SceneDetectionResult: ...

    def extract_frame(
        self, source: Path, *, timestamp_ms: int, width: int, output: Path
    ) -> None: ...

    def decode_audio_pcm(self, source: Path, *, sample_rate: int, max_seconds: int) -> bytes: ...


def _number(value: object) -> float | None:
    if not isinstance(value, (str, int, float)) or isinstance(value, bool):
        return None
    try:
        return float(value) if value not in (None, "", "N/A") else None
    except (TypeError, ValueError):
        return None


def _integer(value: object) -> int | None:
    number = _number(value)
    return int(number) if number is not None else None


def _frame_rate(value: object) -> float | None:
    if not isinstance(value, str) or not value:
        return _number(value)
    numerator, separator, denominator = value.partition("/")
    if separator:
        top = _number(numerator)
        bottom = _number(denominator)
        return top / bottom if top is not None and bottom is not None and bottom != 0 else None
    return _number(value)


def _rotation(stream: dict[str, Any]) -> int | None:
    raw_tags = stream.get("tags")
    tags: dict[str, Any] = raw_tags if isinstance(raw_tags, dict) else {}
    value = _integer(tags.get("rotate"))
    if value is not None:
        return value
    for item in stream.get("side_data_list", []):
        if isinstance(item, dict) and _integer(item.get("rotation")) is not None:
            return _integer(item.get("rotation"))
    return None


class FFmpegMediaBackend:
    """Read local media through subprocess argument arrays; never invokes a shell."""

    def __init__(self, config: MediaSection) -> None:
        self.config = config
        self.ffmpeg = self._resolve(config.ffmpeg_path, "ffmpeg")
        self.ffprobe = self._resolve(config.ffprobe_path, "ffprobe")
        self._version = self._read_version() if self.available else None

    @staticmethod
    def _resolve(configured: str | None, executable: str) -> str | None:
        if configured:
            path = Path(configured).expanduser()
            return str(path.resolve()) if path.is_file() else shutil.which(configured)
        return shutil.which(executable)

    @property
    def available(self) -> bool:
        return self.ffmpeg is not None and self.ffprobe is not None

    @property
    def name(self) -> str:
        return "ffmpeg"

    @property
    def version(self) -> str | None:
        return self._version

    def _read_version(self) -> str | None:
        assert self.ffmpeg is not None
        try:
            result = subprocess.run(
                [self.ffmpeg, "-version"],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=self.config.command_timeout_seconds,
                check=True,
            )
        except (OSError, subprocess.SubprocessError):
            return None
        first = result.stdout.splitlines()[0] if result.stdout else ""
        return first[:200] or None

    def _run(
        self, arguments: list[str], *, binary: bool = False
    ) -> subprocess.CompletedProcess[Any]:
        try:
            return subprocess.run(
                arguments,
                capture_output=True,
                text=not binary,
                encoding=None if binary else "utf-8",
                errors=None if binary else "replace",
                timeout=self.config.command_timeout_seconds,
                check=True,
            )
        except subprocess.CalledProcessError as exc:
            stderr = exc.stderr
            if isinstance(stderr, bytes):
                stderr = stderr.decode("utf-8", errors="replace")
            raise MediaBackendFailure(str(stderr or exc)[:1000]) from exc
        except (OSError, subprocess.SubprocessError) as exc:
            raise MediaBackendFailure(str(exc)[:1000]) from exc

    def probe(self, source: Path, media_hash: str) -> MediaMetadata:
        if not self.available:
            raise MediaBackendFailure("FFmpeg/FFprobe is unavailable")
        assert self.ffprobe is not None
        result = self._run(
            [
                self.ffprobe,
                "-v",
                "error",
                "-show_format",
                "-show_streams",
                "-of",
                "json",
                str(source),
            ]
        )
        try:
            payload = json.loads(result.stdout)
        except (TypeError, json.JSONDecodeError) as exc:
            raise MediaBackendFailure("FFprobe returned invalid JSON") from exc
        streams = payload.get("streams", []) if isinstance(payload, dict) else []
        video = next(
            (
                item
                for item in streams
                if isinstance(item, dict) and item.get("codec_type") == "video"
            ),
            {},
        )
        audio = next(
            (
                item
                for item in streams
                if isinstance(item, dict) and item.get("codec_type") == "audio"
            ),
            {},
        )
        format_value = payload.get("format", {}) if isinstance(payload, dict) else {}
        duration = _number(format_value.get("duration")) or _number(video.get("duration"))
        size = _integer(format_value.get("size"))
        return MediaMetadata(
            media_hash=media_hash,
            container=format_value.get("format_name"),
            duration_ms=round(duration * 1000) if duration is not None else None,
            width=_integer(video.get("width")),
            height=_integer(video.get("height")),
            rotation_degrees=_rotation(video),
            frame_rate=_frame_rate(video.get("avg_frame_rate") or video.get("r_frame_rate")),
            video_codec=video.get("codec_name"),
            audio_codec=audio.get("codec_name"),
            audio_channels=_integer(audio.get("channels")),
            audio_sample_rate=_integer(audio.get("sample_rate")),
            file_size_bytes=size if size is not None else source.stat().st_size,
            backend=self.name,
            backend_version=self.version,
        )

    def detect_scenes(
        self, source: Path, *, duration_ms: int, threshold: float, max_shots: int
    ) -> SceneDetectionResult:
        if not self.available:
            raise MediaBackendFailure("FFmpeg is unavailable")
        assert self.ffmpeg is not None
        result = self._run(
            [
                self.ffmpeg,
                "-hide_banner",
                "-nostdin",
                "-i",
                str(source),
                "-vf",
                f"select='gt(scene,{threshold})',showinfo",
                "-an",
                "-f",
                "null",
                "-",
            ]
        )
        text = str(result.stderr or "")
        cuts = sorted(
            {
                round(float(value) * 1000)
                for value in re.findall(r"pts_time:([0-9]+(?:\.[0-9]+)?)", text)
                if 0 < round(float(value) * 1000) < duration_ms
            }
        )
        warnings: list[str] = []
        if len(cuts) + 1 > max_shots:
            cuts = cuts[: max_shots - 1]
            warnings.append("scene_count_truncated_to_configured_max")
        return SceneDetectionResult([0, *cuts, duration_ms], warnings)

    def extract_frame(self, source: Path, *, timestamp_ms: int, width: int, output: Path) -> None:
        if not self.available:
            raise MediaBackendFailure("FFmpeg is unavailable")
        assert self.ffmpeg is not None
        output.parent.mkdir(parents=True, exist_ok=True)
        self._run(
            [
                self.ffmpeg,
                "-hide_banner",
                "-nostdin",
                "-loglevel",
                "error",
                "-ss",
                f"{timestamp_ms / 1000:.3f}",
                "-i",
                str(source),
                "-frames:v",
                "1",
                "-vf",
                f"scale='min({width},iw)':-2",
                "-q:v",
                "2",
                "-y",
                str(output),
            ]
        )
        if not output.is_file() or output.stat().st_size == 0:
            raise MediaBackendFailure(f"FFmpeg did not create keyframe: {output.name}")

    def decode_audio_pcm(self, source: Path, *, sample_rate: int, max_seconds: int) -> bytes:
        if not self.available:
            raise MediaBackendFailure("FFmpeg is unavailable")
        assert self.ffmpeg is not None
        result = self._run(
            [
                self.ffmpeg,
                "-hide_banner",
                "-nostdin",
                "-loglevel",
                "error",
                "-i",
                str(source),
                "-t",
                str(max_seconds),
                "-vn",
                "-ac",
                "1",
                "-ar",
                str(sample_rate),
                "-f",
                "s16le",
                "-",
            ],
            binary=True,
        )
        return bytes(result.stdout or b"")
