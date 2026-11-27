"""Audited, backup-first migrations for durable project state."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from video_account_distiller.errors import DistillerError, ErrorCode
from video_account_distiller.models.core import ProjectState
from video_account_distiller.models.release import (
    ProjectMigrationPlan,
    ProjectMigrationResult,
)
from video_account_distiller.project_archive import (
    backup_manifest_path,
    create_project_backup,
)
from video_account_distiller.storage.project import ProjectLayout
from video_account_distiller.utils.hashing import sha256_file
from video_account_distiller.utils.ids import stable_id
from video_account_distiller.utils.io import atomic_write_json, atomic_write_text, read_json
from video_account_distiller.validation import validate_project
from video_account_distiller.version import CORE_SCHEMA_VERSION

LEGACY_PROJECT_SCHEMA_VERSION = "0.0.0"
SUPPORTED_PROJECT_MIGRATIONS = {
    LEGACY_PROJECT_SCHEMA_VERSION: CORE_SCHEMA_VERSION,
}


def _state_payload(project: ProjectLayout) -> dict[str, Any]:
    payload: Any = read_json(project.state_path)
    if not isinstance(payload, dict):
        raise DistillerError(
            ErrorCode.SCHEMA_INVALID,
            "Project state must be a JSON object",
            details={"path": str(project.state_path)},
        )
    return payload


def plan_project_migration(project: ProjectLayout) -> ProjectMigrationPlan:
    """Inspect the project state and return a write-free migration plan."""

    payload = _state_payload(project)
    source_value = payload.get("schema_version", LEGACY_PROJECT_SCHEMA_VERSION)
    source_version = str(source_value)
    project_id = str(payload.get("project_id") or "unknown")
    migration_required = source_version != CORE_SCHEMA_VERSION
    supported = not migration_required or (
        SUPPORTED_PROJECT_MIGRATIONS.get(source_version) == CORE_SCHEMA_VERSION
    )
    steps = (
        [
            "create_verified_backup",
            "normalize_project_state_contract",
            f"set_schema_version:{CORE_SCHEMA_VERSION}",
            "validate_migrated_project",
            "write_migration_receipt",
        ]
        if migration_required and supported
        else []
    )
    return ProjectMigrationPlan(
        project_root=str(project.root),
        project_id=project_id,
        source_schema_version=source_version,
        target_schema_version=CORE_SCHEMA_VERSION,
        migration_required=migration_required,
        supported=supported,
        steps=steps,
        state_sha256=sha256_file(project.state_path),
    )


def apply_project_migration(
    project: ProjectLayout,
    *,
    backup_path: Path,
    confirm: bool,
) -> ProjectMigrationResult:
    """Apply one supported state migration after creating a verified project backup."""

    plan = plan_project_migration(project)
    migration_id = stable_id(
        "mig_",
        plan.project_id,
        plan.source_schema_version,
        plan.target_schema_version,
        plan.state_sha256,
    )
    if not plan.supported:
        raise DistillerError(
            ErrorCode.PROJECT_MIGRATION_UNSUPPORTED,
            "Project schema cannot be migrated by this release",
            details={
                "source_schema_version": plan.source_schema_version,
                "target_schema_version": plan.target_schema_version,
                "next": "install a release that contains an explicit migration path",
            },
        )
    if not plan.migration_required:
        return ProjectMigrationResult(
            ok=True,
            applied=False,
            migration_id=migration_id,
            completed_at=datetime.now(UTC),
            source_schema_version=plan.source_schema_version,
            target_schema_version=plan.target_schema_version,
            state_sha256_before=plan.state_sha256,
            state_sha256_after=plan.state_sha256,
            rollback_performed=False,
            validation_errors=0,
            validation_warnings=0,
        )
    if not confirm:
        raise DistillerError(
            ErrorCode.PROJECT_MIGRATION_CONFIRMATION_REQUIRED,
            "Project migration requires explicit backup and write confirmation",
            details={
                "required": "confirm=true",
                "backup_path": str(backup_path.expanduser().resolve()),
                "steps": plan.steps,
            },
        )

    original_text = project.state_path.read_text(encoding="utf-8")
    payload = _state_payload(project)
    backup = create_project_backup(project, backup_path)
    state_written = False
    rollback_performed = False
    try:
        payload["schema_version"] = CORE_SCHEMA_VERSION
        normalized = ProjectState.model_validate(payload)
        atomic_write_json(project.state_path, normalized.model_dump(mode="json"))
        state_written = True
        validation = validate_project(project, persist=False)
        if validation.error_count:
            raise DistillerError(
                ErrorCode.RAW_INTEGRITY,
                "Migrated project failed validation",
                details={
                    "validation_errors": validation.error_count,
                    "backup_path": str(backup_path.expanduser().resolve()),
                },
            )
        state_sha256_after = sha256_file(project.state_path)
        receipt_path = project.root / "migrations" / f"{migration_id}.json"
        result = ProjectMigrationResult(
            ok=True,
            applied=True,
            migration_id=migration_id,
            completed_at=datetime.now(UTC),
            source_schema_version=plan.source_schema_version,
            target_schema_version=plan.target_schema_version,
            state_sha256_before=plan.state_sha256,
            state_sha256_after=state_sha256_after,
            backup_archive=str(backup_path.expanduser().resolve()),
            backup_manifest=str(backup_manifest_path(backup_path).resolve()),
            receipt_path=project.relative(receipt_path),
            rollback_performed=False,
            validation_errors=validation.error_count,
            validation_warnings=validation.stats.get(
                "warnings",
                len(validation.warnings),
            ),
        )
        atomic_write_json(
            receipt_path,
            {
                **result.model_dump(mode="json"),
                "backup_id": backup.backup_id,
                "backup_archive_sha256": backup.archive_sha256,
                "steps": plan.steps,
            },
        )
        return result
    except Exception as exc:
        if state_written:
            atomic_write_text(project.state_path, original_text)
            rollback_performed = True
        if rollback_performed and sha256_file(project.state_path) != plan.state_sha256:
            raise DistillerError(
                ErrorCode.RAW_INTEGRITY,
                "Project migration rollback could not restore the original state hash",
                details={"backup_path": str(backup_path.expanduser().resolve())},
            ) from exc
        raise
