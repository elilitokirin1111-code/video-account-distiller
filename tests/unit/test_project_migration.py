from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

import video_account_distiller.project_migration as migration_module
from video_account_distiller.errors import DistillerError, ErrorCode
from video_account_distiller.project_archive import restore_project_backup
from video_account_distiller.project_migration import (
    apply_project_migration,
    plan_project_migration,
)
from video_account_distiller.storage.project import ProjectLayout
from video_account_distiller.utils.io import atomic_write_json, read_json
from video_account_distiller.version import CORE_SCHEMA_VERSION


def _set_schema(project: ProjectLayout, version: str) -> None:
    payload: Any = read_json(project.state_path)
    assert isinstance(payload, dict)
    payload["schema_version"] = version
    atomic_write_json(project.state_path, payload)


def test_current_project_migration_is_a_write_free_noop(
    project: ProjectLayout,
    tmp_path: Path,
) -> None:
    before = project.state_path.read_bytes()
    plan = plan_project_migration(project)
    result = apply_project_migration(
        project,
        backup_path=tmp_path / "unused.zip",
        confirm=False,
    )

    assert plan.migration_required is False
    assert plan.supported is True
    assert result.ok is True
    assert result.applied is False
    assert result.backup_archive is None
    assert project.state_path.read_bytes() == before
    assert not (tmp_path / "unused.zip").exists()


def test_legacy_project_migration_requires_confirmation_and_preserves_rollback(
    project: ProjectLayout,
    tmp_path: Path,
) -> None:
    _set_schema(project, "0.0.0")
    backup = tmp_path / "pre-migration.zip"
    plan = plan_project_migration(project)

    assert plan.migration_required is True
    assert plan.supported is True
    assert plan.steps[0] == "create_verified_backup"
    with pytest.raises(DistillerError) as confirmation:
        apply_project_migration(project, backup_path=backup, confirm=False)
    assert confirmation.value.code is ErrorCode.PROJECT_MIGRATION_CONFIRMATION_REQUIRED
    assert not backup.exists()

    result = apply_project_migration(project, backup_path=backup, confirm=True)

    assert result.ok is True
    assert result.applied is True
    assert result.source_schema_version == "0.0.0"
    assert result.target_schema_version == CORE_SCHEMA_VERSION
    assert project.load_state().schema_version == CORE_SCHEMA_VERSION
    assert backup.is_file()
    assert result.receipt_path is not None
    assert (project.root / result.receipt_path).is_file()

    rollback = tmp_path / "rollback"
    restored = restore_project_backup(backup, rollback)
    restored_payload: Any = read_json(rollback / ".distiller-state.json")
    assert restored.ok is True
    assert isinstance(restored_payload, dict)
    assert restored_payload["schema_version"] == "0.0.0"


def test_unknown_future_project_schema_is_rejected_before_backup(
    project: ProjectLayout,
    tmp_path: Path,
) -> None:
    _set_schema(project, "9.9.9")
    backup = tmp_path / "future.zip"
    plan = plan_project_migration(project)

    assert plan.migration_required is True
    assert plan.supported is False
    with pytest.raises(DistillerError) as unsupported:
        apply_project_migration(project, backup_path=backup, confirm=True)
    assert unsupported.value.code is ErrorCode.PROJECT_MIGRATION_UNSUPPORTED
    assert not backup.exists()


def test_migration_failure_restores_original_state_after_write(
    project: ProjectLayout,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _set_schema(project, "0.0.0")
    before = project.state_path.read_bytes()
    backup = tmp_path / "failure-backup.zip"

    def fail_validation(*args: object, **kwargs: object) -> object:
        raise DistillerError(ErrorCode.RAW_INTEGRITY, "injected migration validation failure")

    monkeypatch.setattr(migration_module, "validate_project", fail_validation)

    with pytest.raises(DistillerError) as failure:
        apply_project_migration(project, backup_path=backup, confirm=True)

    assert failure.value.code is ErrorCode.RAW_INTEGRITY
    assert backup.is_file()
    assert project.state_path.read_bytes() == before
    assert not (project.root / "migrations").exists()
