from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
from typer.testing import CliRunner

from video_account_distiller.cli import app
from video_account_distiller.models import (
    AuthorizationGrant,
    AuthorizedExportManifest,
    ConnectorKind,
    FeishuBitableConfig,
    Platform,
)
from video_account_distiller.storage.project import ProjectLayout
from video_account_distiller.utils.hashing import sha256_file
from video_account_distiller.utils.io import atomic_write_json

runner = CliRunner()


def test_phase7_command_groups_expose_help() -> None:
    for command in ("sync", "batch", "snapshot", "team"):
        result = runner.invoke(app, [command, "--help"], color=False)
        assert result.exit_code == 0


def test_team_and_snapshot_commands_emit_stable_json(project: ProjectLayout) -> None:
    team = runner.invoke(
        app,
        ["team", "init", "--project", str(project.root), "--owner", "owner-1", "--json"],
    )
    snapshot = runner.invoke(
        app,
        ["snapshot", "plan", "--project", str(project.root), "--dry-run", "--json"],
    )

    assert team.exit_code == 0
    assert json.loads(team.stdout)["team"]["members"][0]["role"] == "owner"
    assert snapshot.exit_code == 0
    assert json.loads(snapshot.stdout)["tasks"] == []


def test_authorized_export_cli_dry_run_preserves_project(
    project: ProjectLayout, fixtures_dir: Path, tmp_path: Path
) -> None:
    source = fixtures_dir / "normal" / "accounts.csv"
    grant = AuthorizationGrant(
        grant_id="grant-export",
        connector=ConnectorKind.AUTHORIZED_EXPORT,
        confirmed_by="owner",
        confirmed_at=datetime(2026, 7, 20, tzinfo=UTC),
        scopes=["read"],
        source_reference="contract export",
    )
    manifest = AuthorizedExportManifest(
        entity="accounts",
        platform=Platform.DOUYIN,
        data_file=str(source),
        data_sha256=sha256_file(source),
        exported_at=datetime(2026, 7, 20, tzinfo=UTC),
        authorization=grant,
    )
    path = tmp_path / "manifest.json"
    atomic_write_json(path, manifest.model_dump(mode="json"))

    result = runner.invoke(
        app,
        [
            "import",
            "authorized-export",
            "--project",
            str(project.root),
            "--manifest",
            str(path),
            "--dry-run",
            "--json",
        ],
    )

    assert result.exit_code == 0
    assert json.loads(result.stdout)["quality"]["stats"]["accepted_rows"] == 1
    assert not list((project.root / "raw" / "authorized-manifests").glob("*.json"))


def test_sync_cli_missing_credential_uses_stable_error(
    project: ProjectLayout, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("PHASE7_MISSING_TOKEN", raising=False)
    config = FeishuBitableConfig(
        connector_id="contract-feishu",
        app_token="app",
        table_id="table",
        token_env="PHASE7_MISSING_TOKEN",
        authorization=AuthorizationGrant(
            grant_id="grant-feishu",
            connector=ConnectorKind.FEISHU_BITABLE,
            confirmed_by="owner",
            confirmed_at=datetime(2026, 7, 20, tzinfo=UTC),
            scopes=["read"],
            source_reference="bitable:app/table",
        ),
    )
    path = tmp_path / "feishu.json"
    atomic_write_json(path, config.model_dump(mode="json"))

    result = runner.invoke(
        app,
        [
            "sync",
            "pull",
            "--project",
            str(project.root),
            "--connector-config",
            str(path),
            "--entity",
            "accounts",
            "--platform",
            "douyin",
            "--json",
        ],
    )

    assert result.exit_code == 16
    assert json.loads(result.stdout)["error"]["code"] == "E_ADAPTER_AUTH"
