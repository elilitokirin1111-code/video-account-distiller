from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from video_account_distiller.media.enrichment import (
    WhisperCliTranscriber,
    _validated_media_url,
)


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
