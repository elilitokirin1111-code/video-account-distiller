"""Runtime diagnostics contracts used for production installation checks."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import Field, field_validator

from video_account_distiller.models.core import StrictModel


class RuntimeDependency(StrictModel):
    name: str = Field(min_length=1)
    version: str | None = None


class RuntimeExecutable(StrictModel):
    name: str = Field(min_length=1)
    available: bool
    path: str | None = None


class ProjectDiagnostic(StrictModel):
    root: str
    exists: bool
    initialized: bool
    readable: bool
    writable: bool
    validation_ok: bool | None = None
    validation_errors: int | None = Field(default=None, ge=0)
    validation_warnings: int | None = Field(default=None, ge=0)


class CapabilityDiagnostic(StrictModel):
    core: bool
    local_media: bool
    video_transcription: bool
    local_vision: bool
    account_media_enrichment: bool
    mediacrawler_douyin: bool
    tikhub_douyin: bool
    feishu_bitable: bool
    google_sheets: bool


class MediaCrawlerDiagnostic(StrictModel):
    """Read-only compatibility and login-readiness matrix for the pinned sidecar."""

    home: str
    expected_commit: str
    actual_commit: str | None = None
    commit_matches: bool
    runtime_files_present: bool
    missing_files: list[str]
    uv_executable: str | None = None
    bridge_script: str
    bridge_present: bool
    browser_channel: str
    browser_executable: str | None = None
    browser_profile: str
    browser_profile_exists: bool
    login_status: Literal["profile_missing", "profile_present_unverified"]
    project_requires_python: str | None = None
    lock_present: bool
    license_present: bool
    runtime_ready: bool
    ready: bool
    warnings: list[str] = Field(default_factory=list)


class TaskRecoveryDrillResult(StrictModel):
    """Auditable result of an isolated queue interruption and checkpoint retry drill."""

    schema_version: str = "1.0"
    ok: bool
    started_at: datetime
    completed_at: datetime
    database_scope: Literal["temporary"]
    database_removed: bool
    original_task_id: str = Field(min_length=1)
    retry_task_id: str = Field(min_length=1)
    interruption_detected: bool
    retryable: bool
    checkpoint_preserved: bool
    retried_from_preserved: bool
    retry_completed: bool
    steps: list[str] = Field(min_length=1)

    @field_validator("started_at", "completed_at")
    @classmethod
    def require_timezone(cls, value: datetime) -> datetime:
        if value.utcoffset() is None:
            raise ValueError("recovery drill timestamps must include a timezone")
        return value


class DoctorReport(StrictModel):
    ok: bool
    package_version: str
    python_version: str
    python_supported: bool
    operating_system: str
    executable: str
    dependencies: list[RuntimeDependency]
    executables: list[RuntimeExecutable]
    capabilities: CapabilityDiagnostic
    mediacrawler: MediaCrawlerDiagnostic
    project: ProjectDiagnostic | None = None
