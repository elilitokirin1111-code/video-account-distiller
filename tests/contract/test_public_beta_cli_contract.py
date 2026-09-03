from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from video_account_distiller.cli import app
from video_account_distiller.errors import EXIT_CODES, ErrorCode
from video_account_distiller.storage.project import ProjectLayout

runner = CliRunner()


def test_release_migration_and_beta_command_groups_expose_help() -> None:
    assert runner.invoke(app, ["release", "migrate", "--help"]).exit_code == 0
    beta_help = runner.invoke(app, ["release", "beta", "--help"])
    assert beta_help.exit_code == 0
    assert "verify" in beta_help.output
    assert "bundle" in beta_help.output


def test_release_migration_preview_and_public_beta_status_are_machine_readable(
    project: ProjectLayout,
    tmp_path: Path,
) -> None:
    preview = runner.invoke(
        app,
        [
            "release",
            "migrate",
            "preview",
            "--project",
            str(project.root),
            "--json",
        ],
    )
    assert preview.exit_code == 0, preview.output
    migration = json.loads(preview.stdout)
    assert migration["migration_required"] is False
    assert migration["supported"] is True

    evidence = tmp_path / "beta-evidence"
    initialized = runner.invoke(
        app,
        [
            "release",
            "beta",
            "init",
            "--evidence",
            str(evidence),
            "--campaign",
            "cli-pilot",
            "--json",
        ],
    )
    assert initialized.exit_code == 0, initialized.output
    assert json.loads(initialized.stdout)["already_initialized"] is False

    status = runner.invoke(
        app,
        [
            "release",
            "beta",
            "status",
            "--evidence",
            str(evidence),
            "--campaign",
            "cli-pilot",
            "--json",
        ],
    )
    assert status.exit_code == 0, status.output
    payload = json.loads(status.stdout)
    assert payload["eligible_for_freeze"] is False
    assert "pilot_duration_incomplete" in payload["blockers"]

    freeze = runner.invoke(
        app,
        [
            "release",
            "beta",
            "freeze",
            "--evidence",
            str(evidence),
            "--campaign",
            "cli-pilot",
            "--confirm-freeze",
            "--json",
        ],
    )
    assert freeze.exit_code == EXIT_CODES[ErrorCode.PUBLIC_BETA_GATE_FAILED]
    assert json.loads(freeze.stdout)["error"]["code"] == "E_PUBLIC_BETA_GATE_FAILED"

    verify = runner.invoke(
        app,
        [
            "release",
            "beta",
            "verify",
            "--evidence",
            str(evidence),
            "--campaign",
            "cli-pilot",
            "--json",
        ],
    )
    assert verify.exit_code == 4
    verification = json.loads(verify.stdout)
    assert verification["ok"] is False
    assert verification["issues"][0]["code"] == "public_beta_required_evidence_missing"
