from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from video_account_distiller.cli import app
from video_account_distiller.errors import EXIT_CODES, ErrorCode
from video_account_distiller.storage.project import ProjectLayout
from video_account_distiller.utils.ids import stable_id

runner = CliRunner()


def _suite_file(tmp_path: Path, account_id: str) -> Path:
    path = tmp_path / "gpt-suite.json"
    path.write_text(
        json.dumps(
            {
                "version": "gpt-evaluation-suite-v1",
                "suite_id": "cli-regression",
                "description": "CLI contract suite",
                "max_total_cost_usd": 1.0,
                "stability_threshold": 0.6,
                "cases": [
                    {
                        "case_id": "health",
                        "account_id": account_id,
                        "model": "gpt-5.6-terra",
                        "template": "account_health",
                        "reasoning_effort": "low",
                        "max_video_analyses": 5,
                        "runs_per_case": 2,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    return path


def test_gpt_evaluation_cli_preview_and_confirmation_gate(
    normalized_project: ProjectLayout,
    tmp_path: Path,
) -> None:
    account_id = stable_id("acc_", "douyin", "hotel-demo")
    suite_file = _suite_file(tmp_path, account_id)

    help_result = runner.invoke(app, ["gpt-eval", "--help"])
    assert help_result.exit_code == 0

    preview = runner.invoke(
        app,
        [
            "gpt-eval",
            "preview",
            str(normalized_project.root),
            "--suite",
            str(suite_file),
            "--campaign",
            "cli-acceptance",
            "--json",
        ],
    )
    assert preview.exit_code == 0, preview.output
    payload = json.loads(preview.stdout)
    assert payload["remote_call_performed"] is False
    assert payload["planned_independent_runs"] == 2
    assert payload["budget"]["within_limit"] is True

    blocked = runner.invoke(
        app,
        [
            "gpt-eval",
            "run",
            str(normalized_project.root),
            "--suite",
            str(suite_file),
            "--campaign",
            "cli-acceptance",
            "--confirmed-preview-hash",
            payload["preview_hash"],
            "--json",
        ],
    )
    assert blocked.exit_code == EXIT_CODES[ErrorCode.PROVIDER_COST_CONFIRMATION_REQUIRED]
    blocked_payload = json.loads(blocked.stdout)
    assert blocked_payload["error"]["code"] == "E_PROVIDER_COST_CONFIRMATION_REQUIRED"
    assert "confirm_independent_paid_runs=true" in blocked_payload["error"]["details"]["required"]
