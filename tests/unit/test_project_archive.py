from __future__ import annotations

from pathlib import Path

import pytest

from video_account_distiller.errors import DistillerError, ErrorCode
from video_account_distiller.project_archive import (
    backup_manifest_path,
    create_project_backup,
    restore_project_backup,
    run_backup_recovery_drill,
    verify_project_backup,
)
from video_account_distiller.storage.project import ProjectLayout
from video_account_distiller.utils.hashing import sha256_file


def test_project_backup_round_trip_is_verified_and_restored_to_new_directory(
    project: ProjectLayout,
    tmp_path: Path,
) -> None:
    evidence = project.root / "raw" / "manual" / "evidence.txt"
    evidence.parent.mkdir(parents=True)
    evidence.write_text("不可变验收证据", encoding="utf-8")
    archive = tmp_path / "backups" / "project.zip"

    manifest = create_project_backup(project, archive)
    verification = verify_project_backup(archive)
    destination = tmp_path / "restored"
    restored = restore_project_backup(archive, destination)

    assert manifest.file_count >= 3
    assert backup_manifest_path(archive).is_file()
    assert verification.ok is True
    assert verification.archive_sha256 == sha256_file(archive)
    assert restored.ok is True
    assert restored.validation_errors == 0
    assert (destination / "raw" / "manual" / "evidence.txt").read_text(encoding="utf-8") == (
        "不可变验收证据"
    )
    assert (
        ProjectLayout.open(destination).load_state().project_id == project.load_state().project_id
    )


def test_project_backup_refuses_recursive_output_existing_restore_and_tampering(
    project: ProjectLayout,
    tmp_path: Path,
) -> None:
    with pytest.raises(DistillerError) as recursive:
        create_project_backup(project, project.root / "backup.zip")
    assert recursive.value.code == ErrorCode.SCHEMA_INVALID

    archive = tmp_path / "project.zip"
    create_project_backup(project, archive)
    destination = tmp_path / "existing"
    destination.mkdir()
    with pytest.raises(DistillerError) as existing:
        restore_project_backup(archive, destination)
    assert existing.value.code == ErrorCode.PROJECT_EXISTS

    archive.write_bytes(b"tampered")
    with pytest.raises(DistillerError) as tampered:
        verify_project_backup(archive)
    assert tampered.value.code == ErrorCode.RAW_INTEGRITY


def test_backup_recovery_drill_uses_and_removes_an_isolated_workspace(
    project: ProjectLayout,
) -> None:
    result = run_backup_recovery_drill(project)

    assert result.ok is True
    assert result.workspace_scope == "temporary"
    assert result.workspace_removed is True
    assert result.backup_verified is True
    assert result.restored_to_new_directory is True
    assert result.restored_validation_errors == 0
    assert result.steps == [
        "backup_created",
        "backup_verified",
        "restored_to_new_directory",
    ]
