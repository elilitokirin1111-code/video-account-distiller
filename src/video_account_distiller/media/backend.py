"""Local FFmpeg/FFprobe adapter behind a small mockable contract."""

from __future__ import annotations

import atexit
import contextlib
import json
import os
import re
import shutil
import subprocess
import sys
import threading
import time
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from video_account_distiller.config import MediaSection
from video_account_distiller.models import MediaMetadata

WINDOWS_STATUS_DLL_INIT_FAILED = 0xC0000142
WINDOWS_ERROR_DLL_INIT_FAILED = 1114
_WINDOWS_LOADER_RETRY_DELAYS_SECONDS = (0.15, 0.4)
_EXTERNAL_PROCESS_START_LOCK = threading.Lock()


def _pyinstaller_bundle_root() -> Path | None:
    raw_root = getattr(sys, "_MEIPASS", None)
    if os.name != "nt" or not isinstance(raw_root, str) or not raw_root:
        return None
    return Path(raw_root).resolve()


def _sanitized_external_process_environment(bundle_root: Path) -> dict[str, str]:
    environment = os.environ.copy()
    raw_path = environment.get("PATH")
    if not raw_path:
        return environment
    filtered: list[str] = []
    for raw_entry in raw_path.split(os.pathsep):
        candidate = raw_entry.strip().strip('"')
        if not candidate:
            continue
        try:
            resolved = Path(os.path.expandvars(candidate)).resolve()
            anchored_in_bundle = resolved == bundle_root or bundle_root in resolved.parents
        except (OSError, RuntimeError):
            anchored_in_bundle = False
        if not anchored_in_bundle:
            filtered.append(raw_entry)
    environment["PATH"] = os.pathsep.join(filtered)
    return environment


def _set_windows_dll_directory(path: str | None) -> bool:
    try:
        import ctypes

        return bool(ctypes.windll.kernel32.SetDllDirectoryW(path))
    except (AttributeError, OSError):
        return False


def _get_windows_dll_directory() -> str | None:
    try:
        import ctypes

        kernel32 = ctypes.windll.kernel32
        buffer = ctypes.create_unicode_buffer(32_768)
        length = int(kernel32.GetDllDirectoryW(len(buffer), buffer))
        return buffer.value if 0 < length < len(buffer) else None
    except (AttributeError, OSError):
        return None


@contextlib.contextmanager
def _external_process_start_environment() -> Iterator[dict[str, str] | None]:
    """Undo PyInstaller's DLL overrides only while creating a system process."""
    bundle_root = _pyinstaller_bundle_root()
    if bundle_root is None:
        yield None
        return
    child_environment = _sanitized_external_process_environment(bundle_root)
    with _EXTERNAL_PROCESS_START_LOCK:
        previous_dll_directory = _get_windows_dll_directory()
        dll_directory_was_reset = _set_windows_dll_directory(None)
        try:
            yield child_environment
        finally:
            if dll_directory_was_reset:
                _set_windows_dll_directory(previous_dll_directory)


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
    """Read local media through subprocess argument arrays; never invokes a shell.

    Tracks the active child process so that :func:`atexit` can terminate it
    when the Python process is shutting down normally, reducing the chance of
    orphan FFmpeg / FFprobe instances.
    """

    def __init__(self, config: MediaSection) -> None:
        self.config = config
        self.ffmpeg = self._resolve(config.ffmpeg_path, "ffmpeg")
        self.ffprobe = self._resolve(config.ffprobe_path, "ffprobe")
        self._active_process: subprocess.Popen[Any] | None = None
        atexit.register(self._cleanup)
        self._version = self._read_version() if self.available else None

    def _cleanup(self) -> None:
        """Terminate the active child process on normal interpreter shutdown."""
        proc = self._active_process
        if proc is not None and proc.poll() is None:
            try:
                proc.kill()
                proc.wait(timeout=5)
            except (OSError, subprocess.TimeoutExpired):
                pass

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
            result = self._run([self.ffmpeg, "-version"])
        except MediaBackendFailure:
            return None
        first = result.stdout.splitlines()[0] if result.stdout else ""
        return first[:200] or None

    @staticmethod
    def _windows_loader_status(returncode: int | None) -> bool:
        return (
            os.name == "nt"
            and returncode is not None
            and returncode & 0xFFFFFFFF == WINDOWS_STATUS_DLL_INIT_FAILED
        )

    @staticmethod
    def _windows_loader_os_error(exc: OSError) -> bool:
        return os.name == "nt" and getattr(exc, "winerror", None) == WINDOWS_ERROR_DLL_INIT_FAILED

    @staticmethod
    def _process_start_options() -> dict[str, Any]:
        if os.name != "nt":
            return {}
        startup_info = subprocess.STARTUPINFO()
        startup_info.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        startup_info.wShowWindow = subprocess.SW_HIDE
        return {
            "creationflags": subprocess.CREATE_NO_WINDOW,
            "startupinfo": startup_info,
        }

    @staticmethod
    def _drain_terminated_process(proc: subprocess.Popen[Any]) -> None:
        try:
            proc.kill()
        except OSError:
            pass
        try:
            proc.communicate(timeout=5)
        except (OSError, subprocess.TimeoutExpired):
            try:
                proc.wait(timeout=5)
            except (OSError, subprocess.TimeoutExpired):
                pass

    @staticmethod
    def _failure_message(
        arguments: list[str], returncode: int, stderr: str | bytes | None, attempts: int
    ) -> str:
        executable = Path(arguments[0]).name or "FFmpeg"
        unsigned_status = returncode & 0xFFFFFFFF
        if unsigned_status == WINDOWS_STATUS_DLL_INIT_FAILED:
            summary = (
                f"{executable} failed with Windows status 0x{unsigned_status:08X} "
                f"after {attempts} attempts (DLL initialization failed)"
            )
        else:
            summary = f"{executable} failed with exit status {returncode}"
        detail = stderr.decode("utf-8", errors="replace") if isinstance(stderr, bytes) else stderr
        detail = (detail or "").strip()
        return f"{summary}: {detail[-700:]}"[:1000] if detail else summary

    def _run(
        self, arguments: list[str], *, binary: bool = False
    ) -> subprocess.CompletedProcess[Any]:
        maximum_attempts = len(_WINDOWS_LOADER_RETRY_DELAYS_SECONDS) + 1
        for attempt in range(1, maximum_attempts + 1):
            proc: subprocess.Popen[Any] | None = None
            try:
                with _external_process_start_environment() as child_environment:
                    proc = subprocess.Popen(
                        arguments,
                        stdin=subprocess.DEVNULL,
                        stdout=subprocess.PIPE,
                        stderr=subprocess.PIPE,
                        text=not binary,
                        encoding=None if binary else "utf-8",
                        errors=None if binary else "replace",
                        env=child_environment,
                        **self._process_start_options(),
                    )
                self._active_process = proc
                try:
                    stdout, stderr = proc.communicate(timeout=self.config.command_timeout_seconds)
                except subprocess.TimeoutExpired as exc:
                    self._drain_terminated_process(proc)
                    executable = Path(arguments[0]).name or "FFmpeg"
                    raise MediaBackendFailure(
                        f"{executable} timed out after "
                        f"{self.config.command_timeout_seconds} seconds"
                    ) from exc
                returncode = proc.returncode if proc.returncode is not None else 0
                if returncode == 0:
                    return subprocess.CompletedProcess(
                        arguments, returncode, stdout=stdout, stderr=stderr
                    )
                if self._windows_loader_status(returncode) and attempt < maximum_attempts:
                    time.sleep(_WINDOWS_LOADER_RETRY_DELAYS_SECONDS[attempt - 1])
                    continue
                raise MediaBackendFailure(
                    self._failure_message(arguments, returncode, stderr, attempt)
                )
            except MediaBackendFailure:
                raise
            except OSError as exc:
                executable = Path(arguments[0]).name or "FFmpeg"
                if self._windows_loader_os_error(exc):
                    if attempt < maximum_attempts:
                        time.sleep(_WINDOWS_LOADER_RETRY_DELAYS_SECONDS[attempt - 1])
                        continue
                    raise MediaBackendFailure(
                        f"{executable} failed to start after {attempt} attempts "
                        f"(Windows error {WINDOWS_ERROR_DLL_INIT_FAILED}: "
                        "DLL initialization failed)"
                    ) from exc
                raise MediaBackendFailure(f"{executable} could not start: {exc}") from exc
            except subprocess.SubprocessError as exc:
                executable = Path(arguments[0]).name or "FFmpeg"
                raise MediaBackendFailure(f"{executable} process failed: {exc}") from exc
            finally:
                if proc is not None:
                    try:
                        still_running = proc.poll() is None
                    except OSError:
                        still_running = False
                    if still_running:
                        self._drain_terminated_process(proc)
                if self._active_process is proc:
                    self._active_process = None
        raise AssertionError("unreachable")

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
