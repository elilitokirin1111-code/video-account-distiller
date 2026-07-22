from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from video_account_distiller.cli import app
from video_account_distiller.errors import EXIT_CODES, ErrorCode

runner = CliRunner()


def test_every_phase_one_command_has_help() -> None:
    commands = [
        ["init", "--help"],
        ["import", "accounts", "--help"],
        ["import", "videos", "--help"],
        ["import", "metrics", "--help"],
        ["import", "comments", "--help"],
        ["validate", "--help"],
        ["normalize", "--help"],
        ["metrics", "--help"],
        ["status", "--help"],
    ]
    for arguments in commands:
        result = runner.invoke(app, arguments)
        assert result.exit_code == 0, arguments
        assert "Usage:" in result.stdout


def test_json_error_envelope_and_stable_exit_code(tmp_path: Path) -> None:
    result = runner.invoke(
        app,
        ["status", "--project", str(tmp_path / "missing"), "--json"],
    )
    assert result.exit_code == EXIT_CODES[ErrorCode.PROJECT_NOT_INITIALIZED]
    payload = json.loads(result.stdout)
    assert payload["ok"] is False
    assert payload["error"]["code"] == "E_PROJECT_NOT_INITIALIZED"


def test_init_dry_run_does_not_create_project(tmp_path: Path) -> None:
    target = tmp_path / "dry"
    result = runner.invoke(app, ["init", str(target), "--dry-run", "--json"])
    assert result.exit_code == 0
    assert json.loads(result.stdout)["dry_run"] is True
    assert not target.exists()
