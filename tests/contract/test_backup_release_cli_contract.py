from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from video_account_distiller.cli import app
from video_account_distiller.storage.project import ProjectLayout

runner = CliRunner()
REPOSITORY_ROOT = Path(__file__).resolve().parents[2]


def test_backup_and_release_command_groups_expose_help() -> None:
    assert runner.invoke(app, ["backup", "--help"]).exit_code == 0
    assert runner.invoke(app, ["release", "--help"]).exit_code == 0


def test_backup_cli_creates_verifies_and_restores_project(
    project: ProjectLayout,
    tmp_path: Path,
) -> None:
    project_root = project.root
    archive = tmp_path / "project.zip"
    created = runner.invoke(
        app,
        [
            "backup",
            "create",
            "--project",
            str(project_root),
            "--output",
            str(archive),
            "--json",
        ],
    )
    assert created.exit_code == 0, created.output
    created_payload = json.loads(created.stdout)
    assert created_payload["file_count"] >= 2

    verified = runner.invoke(
        app,
        ["backup", "verify", "--archive", str(archive), "--json"],
    )
    assert verified.exit_code == 0, verified.output
    assert json.loads(verified.stdout)["ok"] is True

    destination = tmp_path / "restored"
    restored = runner.invoke(
        app,
        [
            "backup",
            "restore",
            "--archive",
            str(archive),
            "--destination",
            str(destination),
            "--json",
        ],
    )
    assert restored.exit_code == 0, restored.output
    assert json.loads(restored.stdout)["validation_errors"] == 0
    assert (destination / "distiller.yaml").is_file()


def test_release_audit_cli_is_machine_readable() -> None:
    result = runner.invoke(
        app,
        ["release", "audit", "--repository", str(REPOSITORY_ROOT), "--json"],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert payload["ok"] is True
    assert payload["package_version"] == "1.1.1"


def test_release_audit_cli_can_require_public_beta_evidence() -> None:
    result = runner.invoke(
        app,
        [
            "release",
            "audit",
            "--repository",
            str(REPOSITORY_ROOT),
            "--require-public-beta-freeze",
            "--json",
        ],
    )

    assert result.exit_code == 4
    payload = json.loads(result.stdout)
    assert payload["ok"] is False
    assert payload["public_beta_required"] is True
    assert any(issue["code"] == "public_beta_evidence_required" for issue in payload["issues"])
