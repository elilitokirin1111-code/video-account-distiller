from __future__ import annotations

import json

from typer.testing import CliRunner

from video_account_distiller.cli import app
from video_account_distiller.errors import EXIT_CODES, ErrorCode
from video_account_distiller.storage.project import ProjectLayout

runner = CliRunner()


def test_account_analyze_help_is_available() -> None:
    result = runner.invoke(app, ["account", "analyze", "--help"])

    assert result.exit_code == 0
    assert "Usage:" in result.stdout
    assert "--dry-run" in result.stdout


def test_account_analyze_dry_run_requires_no_token_and_does_not_write(
    project: ProjectLayout,
) -> None:
    result = runner.invoke(
        app,
        [
            "account",
            "analyze",
            "--project",
            str(project.root),
            "--url",
            "https://www.douyin.com/user/demo",
            "--count",
            "25",
            "--dry-run",
            "--json",
        ],
    )

    payload = json.loads(result.stdout)
    assert result.exit_code == 0
    assert payload["dry_run"] is True
    assert payload["provider_calls"]["total_max"] == 4
    assert not list((project.root / "raw" / "account-collections").rglob("*.json"))


def test_account_analyze_requires_cost_confirmation_before_provider_call(
    project: ProjectLayout,
) -> None:
    result = runner.invoke(
        app,
        [
            "account",
            "analyze",
            "--project",
            str(project.root),
            "--url",
            "https://www.douyin.com/user/demo",
            "--json",
        ],
    )

    payload = json.loads(result.stdout)
    assert result.exit_code == EXIT_CODES[ErrorCode.PROVIDER_COST_CONFIRMATION_REQUIRED]
    assert payload["error"]["code"] == "E_PROVIDER_COST_CONFIRMATION_REQUIRED"


def test_account_analyze_rejects_non_douyin_url_with_stable_code(
    project: ProjectLayout,
) -> None:
    result = runner.invoke(
        app,
        [
            "account",
            "analyze",
            "--project",
            str(project.root),
            "--url",
            "https://example.com/user/demo",
            "--dry-run",
            "--json",
        ],
    )

    payload = json.loads(result.stdout)
    assert result.exit_code == EXIT_CODES[ErrorCode.PROFILE_URL_INVALID]
    assert payload["error"]["code"] == "E_PROFILE_URL_INVALID"
