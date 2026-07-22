from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from video_account_distiller.cli import app
from video_account_distiller.errors import EXIT_CODES, ErrorCode

runner = CliRunner()


def test_partial_invalid_import_keeps_valid_rows_and_reports_errors(
    project: Path, fixtures_dir: Path
) -> None:
    invalid = fixtures_dir / "missing-invalid" / "metrics.csv"
    result = runner.invoke(
        app,
        [
            "import",
            "metrics",
            "--project",
            str(project.root),
            "--file",
            str(invalid),
            "--platform",
            "douyin",
            "--json",
        ],
    )
    payload = json.loads(result.stdout)
    assert result.exit_code == 0
    assert payload["quality"]["stats"]["accepted_rows"] == 1
    assert payload["quality"]["stats"]["rejected_rows"] == 2


def test_all_invalid_import_returns_schema_exit(project: Path, tmp_path: Path) -> None:
    invalid = tmp_path / "invalid.csv"
    invalid.write_text(
        "video_id,snapshot_at,views\nv1,not-a-time,-1\n",
        encoding="utf-8",
    )
    result = runner.invoke(
        app,
        [
            "import",
            "metrics",
            "--project",
            str(project.root),
            "--file",
            str(invalid),
            "--platform",
            "douyin",
            "--json",
        ],
    )
    assert result.exit_code == EXIT_CODES[ErrorCode.SCHEMA_INVALID]
    assert json.loads(result.stdout)["ok"] is False


def test_custom_field_mapping_and_cross_platform_warning(project: Path, fixtures_dir: Path) -> None:
    cross = fixtures_dir / "cross-platform"
    custom = runner.invoke(
        app,
        [
            "import",
            "accounts",
            "--project",
            str(project.root),
            "--file",
            str(cross / "custom-accounts.csv"),
            "--platform",
            "douyin",
            "--mapping",
            str(cross / "custom-mapping.yaml"),
            "--json",
        ],
    )
    assert custom.exit_code == 0
    youtube = runner.invoke(
        app,
        [
            "import",
            "accounts",
            "--project",
            str(project.root),
            "--file",
            str(cross / "youtube-accounts.json"),
            "--platform",
            "youtube",
            "--json",
        ],
    )
    assert youtube.exit_code == 0
    validated = runner.invoke(
        app,
        ["validate", "--project", str(project.root), "--json"],
    )
    payload = json.loads(validated.stdout)
    assert validated.exit_code == 0
    assert "not directly comparable" in payload["quality"]["warnings"][0]
