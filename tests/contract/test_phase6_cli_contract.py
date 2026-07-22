from __future__ import annotations

import json
from pathlib import Path

import yaml
from typer.testing import CliRunner

from video_account_distiller.cli import app
from video_account_distiller.storage.project import ProjectLayout

runner = CliRunner()


def test_phase6_command_exposes_help() -> None:
    result = runner.invoke(app, ["analyze", "media", "--help"])
    assert result.exit_code == 0
    assert "--strict-media" in result.stdout
    assert "--vision-output" in result.stdout


def test_media_dry_run_is_json_and_does_not_write_analysis(
    phase3_project: ProjectLayout, tmp_path: Path
) -> None:
    media = tmp_path / "fixture.mp4"
    media.write_bytes(b"offline fixture")
    result = runner.invoke(
        app,
        [
            "analyze",
            "media",
            "--project",
            str(phase3_project.root),
            "--video",
            "p2-01",
            "--file",
            str(media),
            "--dry-run",
            "--json",
        ],
    )
    payload = json.loads(result.stdout)
    assert result.exit_code == 0
    assert payload["dry_run"] is True
    assert len(payload["media_hash"]) == 64
    assert not list((phase3_project.root / "analyses" / "media").glob("*/*"))


def test_strict_media_uses_stable_decode_error(
    phase3_project: ProjectLayout, tmp_path: Path
) -> None:
    config = yaml.safe_load(phase3_project.config_path.read_text(encoding="utf-8"))
    config["media"] = {
        "ffmpeg_path": "definitely-not-installed-ffmpeg",
        "ffprobe_path": "definitely-not-installed-ffprobe",
    }
    phase3_project.config_path.write_text(
        yaml.safe_dump(config, allow_unicode=True, sort_keys=False), encoding="utf-8"
    )
    media = tmp_path / "fixture.mp4"
    media.write_bytes(b"offline fixture")
    result = runner.invoke(
        app,
        [
            "analyze",
            "media",
            "--project",
            str(phase3_project.root),
            "--video",
            "p2-01",
            "--file",
            str(media),
            "--strict-media",
            "--json",
        ],
    )
    assert result.exit_code == 15
    assert json.loads(result.stdout)["error"]["code"] == "E_MEDIA_DECODE"
