from __future__ import annotations

import json
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

import pytest
from pydantic import ValidationError

from video_account_distiller.media.enrichment import (
    FasterWhisperTranscriber,
    WhisperCliTranscriber,
    _media_candidates,
    _probe_faster_whisper_runtime,
    _retained_video_payloads,
    _validated_media_url,
)
from video_account_distiller.models import AccountMediaEnrichment


@pytest.mark.parametrize(
    "url",
    [
        "https://v11-weba.douyinvod.com/video.mp4?token=opaque",
        "https://www.douyin.com/aweme/v1/play/?video_id=opaque",
    ],
)
def test_media_source_accepts_only_approved_https_douyin_hosts(url: str) -> None:
    _, host = _validated_media_url(url)
    assert host.endswith((".douyinvod.com", ".douyin.com"))


@pytest.mark.parametrize(
    "url",
    [
        "http://v11-weba.douyinvod.com/video.mp4",
        "https://example.com/video.mp4",
        "https://user:pass@www.douyin.com/video.mp4",
        "https://www.douyin.com:8443/video.mp4",
    ],
)
def test_media_source_rejects_unapproved_or_credentialed_urls(url: str) -> None:
    with pytest.raises(ValueError):
        _validated_media_url(url)


def test_retained_video_payloads_reads_detail_wrappers_and_account_lists() -> None:
    detail = {"aweme_id": "detail", "video": {"play_addr": {"url_list": ["detail"]}}}
    listed = {"aweme_id": "listed", "video": {"play_addr": {"url_list": ["listed"]}}}

    values = _retained_video_payloads(
        {
            "aweme_detail": detail,
            "aweme_list": [listed, {"aweme_id": "metadata-only"}, "invalid"],
        }
    )

    assert [item["aweme_id"] for item in values] == ["detail", "listed"]


def test_media_candidates_ignore_image_post_background_audio() -> None:
    audio_url = "https://sf6-cdn-tos.douyinstatic.com/obj/background-audio"
    assert (
        _media_candidates(
            {
                "aweme_id": "image-post",
                "aweme_type": 68,
                "images": [{"url_list": ["https://example.invalid/image.jpeg"]}],
                "video": {
                    "duration": 0,
                    "play_addr": {"url_list": [audio_url]},
                },
            }
        )
        == ()
    )

    video_url = "https://v11-weba.douyinvod.com/video.mp4"
    assert _media_candidates(
        {
            "aweme_id": "video-post",
            "video": {
                "duration": 10_000,
                "play_addr": {"url_list": [video_url]},
            },
        }
    ) == (video_url,)


def test_account_media_enrichment_accepts_full_collection_scope() -> None:
    values = {
        "enrichment_id": "ame_demo",
        "account_id": "acc_demo",
        "generated_at": datetime(2026, 7, 28, tzinfo=UTC),
        "run_id": "run_demo",
        "adapter_version": "test",
        "upstream_commit": "test",
        "source_provider": "mediacrawler",
        "source_batch_hash": "a" * 64,
        "source_batch_path": "raw/provider-batch.json",
        "selection_policy": "provider_order_unanalyzed_first",
        "requested_limit": 20_000,
        "selected_count": 0,
        "completed_count": 0,
        "degraded_count": 0,
        "failed_count": 0,
        "videos": [],
    }

    enrichment = AccountMediaEnrichment.model_validate(values)
    assert enrichment.requested_limit == 20_000

    with pytest.raises(ValidationError):
        AccountMediaEnrichment.model_validate({**values, "requested_limit": 20_001})


def test_whisper_cli_forces_utf8_child_output(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "sample.mp4"
    source.write_bytes(b"fixture")
    destination = tmp_path / "transcript.json"

    def fake_run(
        command: list[str],
        **kwargs: object,
    ) -> subprocess.CompletedProcess[str]:
        env = kwargs["env"]
        assert isinstance(env, dict)
        assert env["PYTHONIOENCODING"] == "utf-8"
        assert command[command.index("--verbose") + 1] == "False"
        output_dir = Path(command[command.index("--output_dir") + 1])
        (output_dir / "sample.json").write_text(
            json.dumps(
                {
                    "segments": [
                        {"id": 1, "start": 0.0, "end": 1.0, "text": "异常字符\ufffd也可写出"}
                    ]
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        return subprocess.CompletedProcess(command, 0, "", "")

    monkeypatch.setattr(subprocess, "run", fake_run)
    transcriber = WhisperCliTranscriber(command=sys.executable)

    result = transcriber.transcribe(source, destination, language="zh")

    assert result.segment_count == 1
    assert "异常字符" in destination.read_text(encoding="utf-8")


def test_whisper_cli_returns_valid_empty_transcript_when_no_speech_is_detected(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "music-only.mp4"
    source.write_bytes(b"fixture")
    destination = tmp_path / "transcript.json"

    def fake_run(
        command: list[str],
        **kwargs: object,
    ) -> subprocess.CompletedProcess[str]:
        del kwargs
        output_dir = Path(command[command.index("--output_dir") + 1])
        (output_dir / "music-only.json").write_text(
            json.dumps({"segments": []}),
            encoding="utf-8",
        )
        return subprocess.CompletedProcess(command, 0, "", "")

    monkeypatch.setattr(subprocess, "run", fake_run)
    transcriber = WhisperCliTranscriber(command=sys.executable)

    result = transcriber.transcribe(source, destination, language="zh")
    payload = json.loads(destination.read_text(encoding="utf-8"))

    assert result.segment_count == 0
    assert payload["segments"] == []
    assert payload["warnings"] == ["no_speech_detected"]


def test_faster_whisper_uses_detected_cuda_batch_and_vad(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "sample.mp4"
    source.write_bytes(b"fixture")
    destination = tmp_path / "transcript.json"
    commands: list[list[str]] = []

    def fake_run(
        command: list[str],
        **kwargs: object,
    ) -> subprocess.CompletedProcess[str]:
        del kwargs
        commands.append(command)
        if "--probe" in command:
            return subprocess.CompletedProcess(
                command,
                0,
                json.dumps(
                    {
                        "available": True,
                        "device": "cuda",
                        "compute_type": "int8_float16",
                        "cuda_devices": 1,
                        "faster_whisper_version": "test",
                        "ctranslate2_version": "test",
                    }
                ),
                "",
            )
        output = Path(command[command.index("--output") + 1])
        output.write_text(
            json.dumps(
                {"segments": [{"id": 1, "start": 0.0, "end": 1.0, "text": "GPU 转写成功"}]},
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        return subprocess.CompletedProcess(command, 0, "", "")

    _probe_faster_whisper_runtime.cache_clear()
    monkeypatch.setattr(subprocess, "run", fake_run)
    transcriber = FasterWhisperTranscriber(
        python_executable=sys.executable,
        model="small",
        batch_size=8,
    )

    result = transcriber.transcribe(source, destination, language="zh")

    transcription_command = commands[-1]
    assert transcription_command[transcription_command.index("--device") + 1] == "cuda"
    assert (
        transcription_command[transcription_command.index("--compute-type") + 1] == "int8_float16"
    )
    assert transcription_command[transcription_command.index("--batch-size") + 1] == "8"
    assert "--vad-filter" in transcription_command
    assert result.segment_count == 1
    assert "GPU 转写成功" in destination.read_text(encoding="utf-8")
    _probe_faster_whisper_runtime.cache_clear()


def test_faster_whisper_auto_falls_back_to_cpu_after_cuda_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "sample.mp4"
    source.write_bytes(b"fixture")
    destination = tmp_path / "transcript.json"
    devices: list[str] = []

    def fake_run(
        command: list[str],
        **kwargs: object,
    ) -> subprocess.CompletedProcess[str]:
        del kwargs
        if "--probe" in command:
            return subprocess.CompletedProcess(
                command,
                0,
                json.dumps({"available": True, "device": "cuda", "cuda_devices": 1}),
                "",
            )
        device = command[command.index("--device") + 1]
        devices.append(device)
        if device == "cuda":
            return subprocess.CompletedProcess(command, 1, "", "CUDA out of memory")
        output = Path(command[command.index("--output") + 1])
        output.write_text(
            json.dumps(
                {"segments": [{"id": 1, "start": 0.0, "end": 1.0, "text": "CPU 回退"}]},
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        return subprocess.CompletedProcess(command, 0, "", "")

    _probe_faster_whisper_runtime.cache_clear()
    monkeypatch.setattr(subprocess, "run", fake_run)
    transcriber = FasterWhisperTranscriber(python_executable=sys.executable)

    result = transcriber.transcribe(source, destination, language="zh")

    assert devices == ["cuda", "cpu"]
    assert transcriber.device_name == "cpu"
    assert transcriber.compute_type == "int8"
    assert result.segment_count == 1
    _probe_faster_whisper_runtime.cache_clear()


def test_faster_whisper_treats_no_speech_as_success_without_cpu_retry(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "music-only.mp4"
    source.write_bytes(b"fixture")
    destination = tmp_path / "transcript.json"
    devices: list[str] = []

    def fake_run(
        command: list[str],
        **kwargs: object,
    ) -> subprocess.CompletedProcess[str]:
        del kwargs
        if "--probe" in command:
            return subprocess.CompletedProcess(
                command,
                0,
                json.dumps({"available": True, "device": "cuda", "cuda_devices": 1}),
                "",
            )
        devices.append(command[command.index("--device") + 1])
        output = Path(command[command.index("--output") + 1])
        output.write_text(json.dumps({"segments": []}), encoding="utf-8")
        return subprocess.CompletedProcess(command, 0, "", "")

    _probe_faster_whisper_runtime.cache_clear()
    monkeypatch.setattr(subprocess, "run", fake_run)
    transcriber = FasterWhisperTranscriber(python_executable=sys.executable)

    result = transcriber.transcribe(source, destination, language="zh")
    payload = json.loads(destination.read_text(encoding="utf-8"))

    assert devices == ["cuda"]
    assert result.segment_count == 0
    assert payload["segments"] == []
    assert payload["warnings"] == ["no_speech_detected"]
    _probe_faster_whisper_runtime.cache_clear()
