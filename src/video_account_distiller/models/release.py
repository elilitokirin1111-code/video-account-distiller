"""Release-candidate audit and project backup contracts."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Literal

from pydantic import Field, field_validator, model_validator

from video_account_distiller.models.core import StrictModel
from video_account_distiller.models.system import TaskRecoveryDrillResult


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
    public_beta_required: bool = False
    public_beta_verified: bool | None = None
    public_beta_evidence_path: str | None = None
    public_beta_evidence_sha256: str | None = None
    issues: list[ReleaseAuditIssue]

    @field_validator("checked_at")
    @classmethod
    def require_timezone(cls, value: datetime) -> datetime:
        if value.utcoffset() is None:
            raise ValueError("release audit timestamp must include a timezone")
        return value


class ProjectMigrationPlan(StrictModel):
    schema_version: str = "1.0"
    project_root: str
    project_id: str
    source_schema_version: str
    target_schema_version: str
    migration_required: bool
    supported: bool
    steps: list[str]
    state_sha256: str = Field(min_length=64, max_length=64)


class ProjectMigrationResult(StrictModel):
    schema_version: str = "1.0"
    ok: bool
    applied: bool
    migration_id: str
    completed_at: datetime
    source_schema_version: str
    target_schema_version: str
    state_sha256_before: str = Field(min_length=64, max_length=64)
    state_sha256_after: str = Field(min_length=64, max_length=64)
    backup_archive: str | None = None
    backup_manifest: str | None = None
    receipt_path: str | None = None
    rollback_performed: bool
    validation_errors: int = Field(ge=0)
    validation_warnings: int = Field(ge=0)

    @field_validator("completed_at")
    @classmethod
    def require_timezone(cls, value: datetime) -> datetime:
        if value.utcoffset() is None:
            raise ValueError("migration timestamp must include a timezone")
        return value


class QueueResilienceDrillResult(StrictModel):
    schema_version: str = "1.0"
    ok: bool
    started_at: datetime
    completed_at: datetime
    task_count: int = Field(ge=2)
    concurrency_limit: int = Field(ge=2)
    max_observed_concurrent: int = Field(ge=1)
    completed_count: int = Field(ge=0)
    injected_failure_count: int = Field(ge=0)
    retry_completed: bool
    failure_isolated: bool
    database_scope: Literal["temporary"]
    database_removed: bool
    steps: list[str] = Field(min_length=1)

    @field_validator("started_at", "completed_at")
    @classmethod
    def require_timezone(cls, value: datetime) -> datetime:
        if value.utcoffset() is None:
            raise ValueError("queue drill timestamps must include a timezone")
        return value


class ProjectMigrationDrillResult(StrictModel):
    schema_version: str = "1.0"
    ok: bool
    started_at: datetime
    completed_at: datetime
    source_schema_version: str
    target_schema_version: str
    backup_verified: bool
    migration_applied: bool
    migrated_schema_verified: bool
    rollback_verified: bool
    validation_errors: int = Field(ge=0)
    workspace_scope: Literal["temporary"]
    workspace_removed: bool
    steps: list[str] = Field(min_length=1)

    @field_validator("started_at", "completed_at")
    @classmethod
    def require_timezone(cls, value: datetime) -> datetime:
        if value.utcoffset() is None:
            raise ValueError("migration drill timestamps must include a timezone")
        return value


class CompatibilitySnapshot(StrictModel):
    schema_version: str = "1.0"
    observed_at: datetime
    machine_profile_id: str = Field(min_length=1)
    machine_label_hash: str = Field(min_length=1)
    operating_system: str
    architecture: str
    python_version: str
    python_implementation: str
    package_version: str
    core_schema_version: str
    doctor_ok: bool
    project_validation_ok: bool
    capabilities: dict[str, bool]

    @field_validator("observed_at")
    @classmethod
    def require_timezone(cls, value: datetime) -> datetime:
        if value.utcoffset() is None:
            raise ValueError("compatibility timestamp must include a timezone")
        return value


class PublicBetaCampaign(StrictModel):
    schema_version: Literal["public-beta-campaign-v1"] = "public-beta-campaign-v1"
    campaign_id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{0,47}$")
    target_version: str = Field(min_length=1, max_length=64)
    created_at: datetime
    min_calendar_days: int = Field(default=7, ge=7, le=14)
    min_distinct_observation_days: int = Field(default=7, ge=7, le=14)
    min_machine_profiles: int = Field(default=2, ge=2, le=20)
    min_account_labels: int = Field(default=3, ge=2, le=100)

    @model_validator(mode="after")
    def validate_day_gates(self) -> PublicBetaCampaign:
        if self.min_distinct_observation_days > self.min_calendar_days:
            raise ValueError("distinct observation days cannot exceed calendar days")
        return self

    @field_validator("created_at")
    @classmethod
    def require_timezone(cls, value: datetime) -> datetime:
        if value.utcoffset() is None:
            raise ValueError("campaign timestamp must include a timezone")
        return value


class PublicBetaObservation(StrictModel):
    schema_version: Literal["public-beta-observation-v1"] = "public-beta-observation-v1"
    observation_id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{0,95}$")
    campaign_id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{0,47}$")
    observed_at: datetime
    account_label_hashes: list[str] = Field(min_length=2, max_length=100)
    compatibility: CompatibilitySnapshot
    queue_resilience: QueueResilienceDrillResult | None = None
    task_recovery: TaskRecoveryDrillResult | None = None
    backup_recovery: BackupRecoveryDrillResult | None = None
    migration_recovery: ProjectMigrationDrillResult | None = None
    ok: bool
    errors: list[str] = Field(default_factory=list)
    notes: str = Field(default="", max_length=1_000)

    @field_validator("observed_at")
    @classmethod
    def require_timezone(cls, value: datetime) -> datetime:
        if value.utcoffset() is None:
            raise ValueError("observation timestamp must include a timezone")
        return value


class PublicBetaIncidentSeverity(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class PublicBetaIncident(StrictModel):
    schema_version: Literal["public-beta-incident-v1"] = "public-beta-incident-v1"
    incident_id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{0,95}$")
    campaign_id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{0,47}$")
    occurred_at: datetime
    severity: PublicBetaIncidentSeverity
    summary: str = Field(min_length=1, max_length=500)

    @field_validator("occurred_at")
    @classmethod
    def require_timezone(cls, value: datetime) -> datetime:
        if value.utcoffset() is None:
            raise ValueError("incident timestamp must include a timezone")
        return value


class PublicBetaStatus(StrictModel):
    schema_version: Literal["public-beta-status-v1"] = "public-beta-status-v1"
    campaign_id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{0,47}$")
    target_version: str
    evaluated_at: datetime
    eligible_for_freeze: bool
    blockers: list[str]
    observation_count: int = Field(ge=0)
    successful_observations: int = Field(ge=0)
    distinct_observation_days: int = Field(ge=0)
    elapsed_calendar_days: int = Field(ge=0)
    machine_profiles: int = Field(ge=0)
    account_labels: int = Field(ge=0)
    high_or_critical_incidents: int = Field(ge=0)
    min_calendar_days: int = Field(ge=7, le=14)
    min_distinct_observation_days: int = Field(ge=7, le=14)
    min_machine_profiles: int = Field(ge=2)
    min_account_labels: int = Field(ge=2)

    @field_validator("evaluated_at")
    @classmethod
    def require_timezone(cls, value: datetime) -> datetime:
        if value.utcoffset() is None:
            raise ValueError("status timestamp must include a timezone")
        return value


class PublicBetaFreezeRecord(StrictModel):
    schema_version: Literal["public-beta-freeze-v1"] = "public-beta-freeze-v1"
    campaign_id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{0,47}$")
    target_version: str
    frozen_at: datetime
    evidence_sha256: str = Field(min_length=64, max_length=64)
    status: PublicBetaStatus
    confirmed: bool

    @field_validator("frozen_at")
    @classmethod
    def require_timezone(cls, value: datetime) -> datetime:
        if value.utcoffset() is None:
            raise ValueError("freeze timestamp must include a timezone")
        return value


class PublicBetaEvidenceBundleManifest(StrictModel):
    schema_version: Literal["public-beta-evidence-bundle-v1"] = "public-beta-evidence-bundle-v1"
    campaign_id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{0,47}$")
    target_version: str = Field(min_length=1, max_length=64)
    frozen_at: datetime
    evidence_sha256: str = Field(min_length=64, max_length=64)
    observation_count: int = Field(ge=1)
    incident_count: int = Field(ge=0)
    files: dict[str, str] = Field(min_length=3)

    @field_validator("frozen_at")
    @classmethod
    def require_timezone(cls, value: datetime) -> datetime:
        if value.utcoffset() is None:
            raise ValueError("evidence bundle timestamp must include a timezone")
        return value


class PublicBetaFreezeVerification(StrictModel):
    schema_version: Literal["public-beta-freeze-verification-v1"] = (
        "public-beta-freeze-verification-v1"
    )
    ok: bool
    checked_at: datetime
    source_path: str
    source_kind: Literal["directory", "bundle"]
    campaign_id: str | None = None
    target_version: str | None = None
    frozen_at: datetime | None = None
    declared_evidence_sha256: str | None = None
    computed_evidence_sha256: str | None = None
    source_sha256: str | None = None
    observation_count: int = Field(ge=0)
    incident_count: int = Field(ge=0)
    issues: list[ReleaseAuditIssue]

    @field_validator("checked_at")
    @classmethod
    def require_timezone(cls, value: datetime) -> datetime:
        if value.utcoffset() is None:
            raise ValueError("freeze verification timestamp must include a timezone")
        return value

    @field_validator("frozen_at")
    @classmethod
    def require_optional_timezone(cls, value: datetime | None) -> datetime | None:
        if value is not None and value.utcoffset() is None:
            raise ValueError("verified freeze timestamp must include a timezone")
        return value
