from __future__ import annotations

import json

from typer.testing import CliRunner

from video_account_distiller.cli import app
from video_account_distiller.storage.project import ProjectLayout
from video_account_distiller.utils.ids import stable_id

runner = CliRunner()


def test_openkb_export_and_sync_dry_runs_are_offline_json(
    normalized_project: ProjectLayout,
) -> None:
    account_id = stable_id("acc_", "douyin", "hotel-demo")
    exported = runner.invoke(
        app,
        [
            "knowledge",
            "openkb",
            "export",
            "--project",
            str(normalized_project.root),
            "--account",
            account_id,
            "--dry-run",
            "--json",
        ],
    )
    assert exported.exit_code == 0, exported.output
    export_payload = json.loads(exported.stdout)
    assert export_payload["dry_run"] is True

    synced = runner.invoke(
        app,
        [
            "knowledge",
            "openkb",
            "sync",
            "--project",
            str(normalized_project.root),
            "--account",
            account_id,
            "--base-url",
            "https://openkb.example.com",
            "--dry-run",
            "--json",
        ],
    )
    assert synced.exit_code == 0, synced.output
    sync_payload = json.loads(synced.stdout)
    assert sync_payload["dry_run"] is True
    assert sync_payload["would_upload"] is True
    assert sync_payload["target"]["token_configured"] is False


def test_openkb_sync_requires_explicit_model_confirmation(
    normalized_project: ProjectLayout,
) -> None:
    account_id = stable_id("acc_", "douyin", "hotel-demo")
    result = runner.invoke(
        app,
        [
            "knowledge",
            "openkb",
            "sync",
            "--project",
            str(normalized_project.root),
            "--account",
            account_id,
            "--json",
        ],
    )

    assert result.exit_code == 20
    payload = json.loads(result.stdout)
    assert payload["error"]["code"] == "E_PROVIDER_COST_CONFIRMATION_REQUIRED"
