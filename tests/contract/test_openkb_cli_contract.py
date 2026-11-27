from __future__ import annotations

import json

from typer.testing import CliRunner

from video_account_distiller.cli import app
from video_account_distiller.storage.project import ProjectLayout
from video_account_distiller.utils.ids import stable_id

runner = CliRunner()


def test_local_knowledge_package_export_is_offline_json(
    normalized_project: ProjectLayout,
) -> None:
    account_id = stable_id("acc_", "douyin", "hotel-demo")
    exported = runner.invoke(
        app,
        [
            "knowledge",
            "package",
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

    assert export_payload["document_path"].startswith("knowledge-outbox/local/")


def test_openkb_cli_group_is_retired() -> None:
    result = runner.invoke(app, ["knowledge", "openkb", "--help"])

    assert result.exit_code != 0
