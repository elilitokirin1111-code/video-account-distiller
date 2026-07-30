"""Release-candidate audit and project backup contracts."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import Field, field_validator

from video_account_distiller.models.core import StrictModel


class ProjectBackupFile(StrictModel):
    path: str = Field(min_length=1)
    sha256: str = Field(min_length=64, max_length=64)
    byte_size: int = Field(ge=0)


class ProjectBackupManifest(StrictModel):
    schema_version: str = "1.0"
    backup_id: str = Field(min_length=1)
    package_version: str = Field(min_length=1)
    created_at: datetime
    project_id: str = Field(min_length=1)
    project_name: str = Field(min_length=1)
    project_schema_version: str = Field(min_length=1)
    archive_name: str = Field(min_length=1)
    archive_sha256: str = Field(min_length=64, max_length=64)
    file_count: int = Field(ge=1)
    directory_count: int = Field(ge=0)
    total_bytes: int = Field(ge=0)
    directories: list[str]
    files: list[ProjectBackupFile] = Field(min_length=1)

    @field_validator("created_at")
    @classmethod
    def require_timezone(cls, value: datetime) -> datetime:
        if value.utcoffset() is None:
            raise ValueError("backup timestamp must include a timezone")
        return value


class BackupVerification(StrictModel):
    schema_version: str = "1.0"
    ok: bool
    backup_id: str
    archive_path: str
    manifest_path: str
    archive_sha256: str
    file_count: int = Field(ge=1)
    directory_count: int = Field(ge=0)
    total_bytes: int = Field(ge=0)


class ProjectRestoreResult(StrictModel):
    schema_version: str = "1.0"
    ok: bool
    backup_id: str
    destination: str
    file_count: int = Field(ge=1)
    validation_errors: int = Field(ge=0)
    validation_warnings: int = Field(ge=0)


class BackupRecoveryDrillResult(StrictModel):
    schema_version: str = "1.0"
    ok: bool
    started_at: datetime
    completed_at: datetime
    source_project: str
    workspace_scope: Literal["temporary"]
    workspace_removed: bool
    backup_verified: bool
    restored_to_new_directory: bool
    restored_file_count: int = Field(ge=1)
    restored_validation_errors: int = Field(ge=0)
    restored_validation_warnings: int = Field(ge=0)
    steps: list[str] = Field(min_length=1)

    @field_validator("started_at", "completed_at")
    @classmethod
    def require_timezone(cls, value: datetime) -> datetime:
        if value.utcoffset() is None:
            raise ValueError("backup drill timestamps must include a timezone")
        return value


class ReleaseAuditIssue(StrictModel):
    severity: Literal["error", "warning"]
    code: str = Field(min_length=1)
    message: str = Field(min_length=1)
    path: str | None = None


class ReleaseAuditReport(StrictModel):
    schema_version: str = "1.0"
    ok: bool
    checked_at: datetime
    repository: str
    package_version: str | None = None
    skill_version: str | None = None
    required_files: dict[str, bool]
    artifact_checksums: dict[str, str]
    issues: list[ReleaseAuditIssue]

    @field_validator("checked_at")
    @classmethod
    def require_timezone(cls, value: datetime) -> datetime:
        if value.utcoffset() is None:
            raise ValueError("release audit timestamp must include a timezone")
        return value
