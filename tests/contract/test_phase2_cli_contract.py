from __future__ import annotations

import json

from typer.testing import CliRunner

from video_account_distiller.cli import app
from video_account_distiller.storage.project import ProjectLayout
from video_account_distiller.utils.ids import stable_id

runner = CliRunner()


def test_phase2_commands_expose_help() -> None:
    assert runner.invoke(app, ["sample", "--help"]).exit_code == 0
    assert runner.invoke(app, ["report", "--help"]).exit_code == 0


def test_sample_json_uses_stable_insufficient_sample_error(
    normalized_project: ProjectLayout,
) -> None:
    account_id = stable_id("acc_", "douyin", "hotel-demo")
    result = runner.invoke(
        app,
        [
            "sample",
            "--project",
            str(normalized_project.root),
            "--account",
            account_id,
            "--json",
        ],
    )
    payload = json.loads(result.stdout)
    assert result.exit_code == 11
    assert payload["error"]["code"] == "E_INSUFFICIENT_SAMPLE"


def test_sample_and_report_dry_run_emit_machine_json(phase2_project: ProjectLayout) -> None:
    account_id = stable_id("acc_", "douyin", "phase2-hotel")
    sample = runner.invoke(
        app,
        [
            "sample",
            "--project",
            str(phase2_project.root),
            "--account",
            account_id,
            "--size",
            "12",
            "--dry-run",
            "--json",
        ],
    )
    sample_payload = json.loads(sample.stdout)
    assert sample.exit_code == 0
    assert sample_payload["manifest"]["selected_size"] == 12

    report = runner.invoke(
        app,
        [
            "report",
            "--project",
            str(phase2_project.root),
            "--account",
            account_id,
            "--sample-size",
            "12",
            "--dry-run",
            "--json",
        ],
    )
    report_payload = json.loads(report.stdout)
    assert report.exit_code == 0
    assert report_payload["report"]["report_type"] == "account_health"
    assert all(not (phase2_project.root / path).exists() for path in report_payload["outputs"])
