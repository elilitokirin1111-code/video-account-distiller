from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

import video_account_distiller.media.backend as backend_module
from video_account_distiller.config import MediaSection
from video_account_distiller.media.backend import (
    WINDOWS_STATUS_DLL_INIT_FAILED,
    FFmpegMediaBackend,
    MediaBackendFailure,
    _external_process_start_environment,
    _sanitized_external_process_environment,
)


class _Process:
    def __init__(
        self,
        returncode: int = 0,
        *,
        stdout: str | bytes = "ok",
        stderr: str | bytes = "",
        time_out_once: bool = False,
        process_error_once: bool = False,
    ) -> None:
        self.final_returncode = returncode
        self.returncode: int | None = None
        self.stdout = stdout
        self.stderr = stderr
        self.time_out_once = time_out_once
        self.process_error_once = process_error_once
        self.killed = False
        self.communicate_calls = 0

    def communicate(self, timeout: int) -> tuple[str | bytes, str | bytes]:
        self.communicate_calls += 1
        if self.time_out_once and self.communicate_calls == 1:
            raise subprocess.TimeoutExpired("ffmpeg", timeout)
        if self.process_error_once and self.communicate_calls == 1:
            raise OSError("pipe failed")
        self.returncode = self.final_returncode
        return self.stdout, self.stderr

    def poll(self) -> int | None:
        return self.returncode

    def kill(self) -> None:
        self.killed = True

    def wait(self, timeout: int) -> int:
        self.returncode = self.final_returncode
        return self.final_returncode


def _backend() -> FFmpegMediaBackend:
    instance = object.__new__(FFmpegMediaBackend)
    instance.config = MediaSection(command_timeout_seconds=7)
    instance.ffmpeg = "ffmpeg.exe"
    instance.ffprobe = "ffprobe.exe"
    instance._version = None
    instance._active_process = None
    return instance


@pytest.mark.skipif(os.name != "nt", reason="Windows loader status is Windows-specific")
def test_run_retries_transient_windows_dll_initialization_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    processes = [
        _Process(WINDOWS_STATUS_DLL_INIT_FAILED),
        _Process(0, stdout="frame"),
    ]
    calls: list[dict[str, Any]] = []

    def fake_popen(arguments: list[str], **kwargs: Any) -> _Process:
        calls.append({"arguments": arguments, **kwargs})
        return processes[len(calls) - 1]

    monkeypatch.setattr("video_account_distiller.media.backend.subprocess.Popen", fake_popen)
    monkeypatch.setattr("video_account_distiller.media.backend.time.sleep", lambda _seconds: None)

    result = _backend()._run(["ffmpeg.exe", "-version"])

    assert result.returncode == 0
    assert result.stdout == "frame"
    assert len(calls) == 2
    assert calls[0]["stdin"] is subprocess.DEVNULL
    assert calls[0]["creationflags"] == subprocess.CREATE_NO_WINDOW


@pytest.mark.skipif(os.name != "nt", reason="Windows loader status is Windows-specific")
def test_run_reports_loader_status_before_truncated_command_details(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    processes = [_Process(WINDOWS_STATUS_DLL_INIT_FAILED) for _ in range(3)]
    call_count = 0

    def fake_popen(_arguments: list[str], **_kwargs: Any) -> _Process:
        nonlocal call_count
        process = processes[call_count]
        call_count += 1
        return process

    monkeypatch.setattr("video_account_distiller.media.backend.subprocess.Popen", fake_popen)
    monkeypatch.setattr("video_account_distiller.media.backend.time.sleep", lambda _seconds: None)

    with pytest.raises(MediaBackendFailure) as raised:
        _backend()._run(["ffmpeg.exe", "-i", "source.mp4"])

    assert str(raised.value).startswith(
        "ffmpeg.exe failed with Windows status 0xC0000142 after 3 attempts"
    )
    assert call_count == 3


@pytest.mark.skipif(os.name != "nt", reason="Windows loader error is Windows-specific")
def test_run_retries_winerror_1114_raised_while_creating_process(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    call_count = 0

    def fake_popen(_arguments: list[str], **_kwargs: Any) -> _Process:
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            error = OSError("DLL initialization failed")
            error.winerror = 1114
            raise error
        return _Process(0, stdout="recovered")

    monkeypatch.setattr("video_account_distiller.media.backend.subprocess.Popen", fake_popen)
    monkeypatch.setattr("video_account_distiller.media.backend.time.sleep", lambda _seconds: None)

    result = _backend()._run(["ffmpeg.exe", "-version"])

    assert result.stdout == "recovered"
    assert call_count == 2


@pytest.mark.skipif(os.name != "nt", reason="Windows loader error is Windows-specific")
def test_run_reports_exhausted_winerror_1114_retries(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    call_count = 0

    def fake_popen(_arguments: list[str], **_kwargs: Any) -> _Process:
        nonlocal call_count
        call_count += 1
        error = OSError("localized operating-system text")
        error.winerror = 1114
        raise error

    monkeypatch.setattr("video_account_distiller.media.backend.subprocess.Popen", fake_popen)
    monkeypatch.setattr("video_account_distiller.media.backend.time.sleep", lambda _seconds: None)

    with pytest.raises(
        MediaBackendFailure,
        match="failed to start after 3 attempts .*Windows error 1114.*DLL initialization failed",
    ):
        _backend()._run(["ffmpeg.exe", "-version"])

    assert call_count == 3


def test_sanitized_environment_removes_only_bundle_anchored_path_entries(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    bundle_root = (tmp_path / "_internal").resolve()
    system_bin = (tmp_path / "ffmpeg-bin").resolve()
    monkeypatch.setenv(
        "PATH",
        os.pathsep.join([str(bundle_root / "PySide6"), str(bundle_root), str(system_bin)]),
    )

    environment = _sanitized_external_process_environment(bundle_root)

    assert environment["PATH"] == str(system_bin)


@pytest.mark.skipif(os.name != "nt", reason="PyInstaller DLL override is Windows-specific")
def test_external_process_context_resets_and_restores_pyinstaller_dll_directory(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    bundle_root = (tmp_path / "_internal").resolve()
    system_bin = (tmp_path / "ffmpeg-bin").resolve()
    monkeypatch.setattr(sys, "_MEIPASS", str(bundle_root), raising=False)
    monkeypatch.setenv("PATH", os.pathsep.join([str(bundle_root / "PySide6"), str(system_bin)]))
    calls: list[str | None] = []
    previous_dll_directory = str(tmp_path / "custom-dll-directory")
    monkeypatch.setattr(
        backend_module,
        "_get_windows_dll_directory",
        lambda: previous_dll_directory,
    )

    def record_dll_directory(path: str | None) -> bool:
        calls.append(path)
        return True

    monkeypatch.setattr(backend_module, "_set_windows_dll_directory", record_dll_directory)

    with pytest.raises(RuntimeError, match="spawn failed"):
        with _external_process_start_environment() as environment:
            assert environment is not None
            assert environment["PATH"] == str(system_bin)
            raise RuntimeError("spawn failed")

    assert calls == [None, previous_dll_directory]


def test_run_kills_and_drains_timed_out_process(monkeypatch: pytest.MonkeyPatch) -> None:
    process = _Process(time_out_once=True)
    monkeypatch.setattr(
        "video_account_distiller.media.backend.subprocess.Popen",
        lambda _arguments, **_kwargs: process,
    )

    instance = _backend()
    with pytest.raises(MediaBackendFailure, match="timed out after 7 seconds"):
        instance._run(["ffmpeg.exe", "-i", "source.mp4"])

    assert process.killed is True
    assert process.communicate_calls == 2
    assert instance._active_process is None


def test_run_kills_and_drains_process_after_pipe_error(monkeypatch: pytest.MonkeyPatch) -> None:
    process = _Process(process_error_once=True)
    monkeypatch.setattr(
        "video_account_distiller.media.backend.subprocess.Popen",
        lambda _arguments, **_kwargs: process,
    )

    instance = _backend()
    with pytest.raises(MediaBackendFailure, match="pipe failed"):
        instance._run(["ffmpeg.exe", "-i", "source.mp4"])

    assert process.killed is True
    assert process.communicate_calls == 2
    assert instance._active_process is None


def test_failure_message_keeps_tail_of_ffmpeg_stderr() -> None:
    message = FFmpegMediaBackend._failure_message(
        [str(Path("ffmpeg.exe"))],
        1,
        "prefix\n" + "x" * 900 + "useful-tail",
        1,
    )

    assert message.startswith("ffmpeg.exe failed with exit status 1")
    assert message.endswith("useful-tail")
    assert len(message) <= 1000
