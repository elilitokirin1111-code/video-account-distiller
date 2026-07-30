"""Strict contracts for authorized exports, collaboration adapters, and batch work."""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, Literal

from pydantic import Field, field_validator, model_validator

from video_account_distiller.errors import DistillerError, ErrorCode
from video_account_distiller.models.core import Platform, StrictModel
from video_account_distiller.version import COLLABORATION_SCHEMA_VERSION

EntityName = Literal["accounts", "videos", "metrics", "comments", "audience_profiles"]
AuthorizationScope = Literal["read", "write"]


class ConnectorKind(StrEnum):
    AUTHORIZED_EXPORT = "authorized-export"
    FEISHU_BITABLE = "feishu-bitable"
    GOOGLE_SHEETS = "google-sheets"


class AuthorizationGrant(StrictModel):
    """User-recorded authorization proof; never contains a credential value."""

    grant_id: str = Field(min_length=1)
    connector: ConnectorKind
    confirmed_by: str = Field(min_length=1)
    confirmed_at: datetime
    scopes: list[AuthorizationScope] = Field(min_length=1)
    source_reference: str = Field(min_length=1)
    expires_at: datetime | None = None

    @field_validator("scopes")
    @classmethod
    def unique_scopes(cls, value: list[AuthorizationScope]) -> list[AuthorizationScope]:
        if len(value) != len(set(value)):
            raise ValueError("authorization scopes must be unique")
        return value

    @field_validator("confirmed_at", "expires_at")
    @classmethod
    def require_timezone(cls, value: datetime | None) -> datetime | None:
        if value is not None and value.utcoffset() is None:
            raise ValueError("authorization timestamps must include a timezone")
        return value

    @model_validator(mode="after")
    def validate_expiry(self) -> AuthorizationGrant:
        if self.expires_at is not None and self.expires_at <= self.confirmed_at:
            raise ValueError("authorization expiry must be after confirmation")
        return self

    def require(self, scope: AuthorizationScope, *, now: datetime | None = None) -> None:
        """Require an active explicit grant for one adapter operation."""

        current = now or datetime.now(UTC)
        if self.expires_at is not None and self.expires_at <= current:
            raise DistillerError(
                ErrorCode.ADAPTER_AUTH,
                "Adapter authorization has expired",
                details={"grant_id": self.grant_id},
            )
        if scope not in self.scopes:
            raise DistillerError(
                ErrorCode.ADAPTER_AUTH,
                f"Adapter authorization does not include {scope} access",
                details={"grant_id": self.grant_id, "required_scope": scope},
            )


class AuthorizedExportManifest(StrictModel):
    schema_version: str = COLLABORATION_SCHEMA_VERSION
    entity: EntityName
    platform: Platform
    data_file: str = Field(min_length=1)
    data_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    exported_at: datetime
    authorization: AuthorizationGrant
    data_source_tier: Literal["authorized_private"] = "authorized_private"

    @model_validator(mode="after")
    def validate_connector(self) -> AuthorizedExportManifest:
        if self.authorization.connector != ConnectorKind.AUTHORIZED_EXPORT:
            raise ValueError("authorization connector must be authorized-export")
        return self


class RetryPolicy(StrictModel):
    max_retries: int = Field(default=3, ge=0, le=8)
    base_seconds: float = Field(default=0.5, ge=0, le=30)
    timeout_seconds: int = Field(default=30, ge=1, le=300)


class FeishuBitableConfig(StrictModel):
    connector: Literal[ConnectorKind.FEISHU_BITABLE] = ConnectorKind.FEISHU_BITABLE
    connector_id: str = Field(min_length=1)
    app_token: str = Field(min_length=1)
    table_id: str = Field(min_length=1)
    token_env: str = Field(default="FEISHU_BITABLE_TOKEN", pattern=r"^[A-Z][A-Z0-9_]*$")
    api_base: Literal["https://open.feishu.cn", "https://open.larksuite.com"] = (
        "https://open.feishu.cn"
    )
    page_size: int = Field(default=500, ge=1, le=500)
    authorization: AuthorizationGrant
    retry: RetryPolicy = Field(default_factory=RetryPolicy)

    @model_validator(mode="after")
    def validate_connector_grant(self) -> FeishuBitableConfig:
        if self.authorization.connector != ConnectorKind.FEISHU_BITABLE:
            raise ValueError("authorization connector does not match feishu-bitable")
        expected = f"bitable:{self.app_token}/{self.table_id}"
        if self.authorization.source_reference != expected:
            raise ValueError(f"authorization source_reference must be {expected}")
        return self


class GoogleSheetsConfig(StrictModel):
    connector: Literal[ConnectorKind.GOOGLE_SHEETS] = ConnectorKind.GOOGLE_SHEETS
    connector_id: str = Field(min_length=1)
    spreadsheet_id: str = Field(min_length=1)
    range: str = Field(min_length=1)
    token_env: str = Field(default="GOOGLE_SHEETS_TOKEN", pattern=r"^[A-Z][A-Z0-9_]*$")
    columns: list[str] = Field(default_factory=list)
    authorization: AuthorizationGrant
    retry: RetryPolicy = Field(default_factory=RetryPolicy)

    @field_validator("columns")
    @classmethod
    def validate_columns(cls, value: list[str]) -> list[str]:
        if len(value) != len(set(value)) or any(not item.strip() for item in value):
            raise ValueError("Google Sheets columns must be unique and non-empty")
        return value

    @model_validator(mode="after")
    def validate_connector_grant(self) -> GoogleSheetsConfig:
        if self.authorization.connector != ConnectorKind.GOOGLE_SHEETS:
            raise ValueError("authorization connector does not match google-sheets")
        expected = f"sheets:{self.spreadsheet_id}/{self.range}"
        if self.authorization.source_reference != expected:
            raise ValueError(f"authorization source_reference must be {expected}")
        return self


ConnectorConfig = FeishuBitableConfig | GoogleSheetsConfig


class AdapterReadResult(StrictModel):
    schema_version: str = COLLABORATION_SCHEMA_VERSION
    connector: ConnectorKind
    connector_id: str
    source_reference: str
    fetched_at: datetime
    records: list[dict[str, Any]]
    raw_pages: list[dict[str, Any]]


class AdapterWriteResult(StrictModel):
    schema_version: str = COLLABORATION_SCHEMA_VERSION
    connector: ConnectorKind
    connector_id: str
    target_reference: str
    written_at: datetime
    requested_rows: int = Field(ge=0)
    accepted_rows: int = Field(ge=0)
    response_ids: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_counts(self) -> AdapterWriteResult:
        if self.accepted_rows > self.requested_rows:
            raise ValueError("accepted_rows cannot exceed requested_rows")
        return self


class SyncReceipt(StrictModel):
    schema_version: str = COLLABORATION_SCHEMA_VERSION
    sync_id: str
    connector: ConnectorKind
    connector_id: str
    direction: Literal["pull", "push"]
    entity: EntityName
    platform: Platform | None = None
    authorization_grant_id: str
    source_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    status: Literal["complete", "partial"] = "complete"
    requested_row_count: int = Field(ge=0)
    row_count: int = Field(ge=0)
    created_at: datetime
    run_id: str | None = None
    artifact_paths: list[str] = Field(default_factory=list)
    dry_run: bool = False

    @model_validator(mode="after")
    def validate_row_counts(self) -> SyncReceipt:
        if self.row_count > self.requested_row_count:
            raise ValueError("row_count cannot exceed requested_row_count")
        if self.status == "complete" and self.row_count != self.requested_row_count:
            raise ValueError("complete syncs require all requested rows")
        return self


class TeamRole(StrEnum):
    OWNER = "owner"
    EDITOR = "editor"
    VIEWER = "viewer"


class TeamMember(StrictModel):
    member_id: str = Field(min_length=1)
    display_name: str | None = None
    role: TeamRole
    connector_ids: list[str] = Field(default_factory=list)


class TeamConnectorPolicy(StrictModel):
    connector_id: str = Field(min_length=1)
    connector: ConnectorKind
    allowed_roles: list[TeamRole] = Field(min_length=1)
    token_env: str = Field(pattern=r"^[A-Z][A-Z0-9_]*$")


class TeamConfig(StrictModel):
    schema_version: str = COLLABORATION_SCHEMA_VERSION
    team_id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    members: list[TeamMember] = Field(min_length=1)
    connectors: list[TeamConnectorPolicy] = Field(default_factory=list)
    created_at: datetime

    @model_validator(mode="after")
    def validate_team(self) -> TeamConfig:
        member_ids = [member.member_id for member in self.members]
        connector_ids = [connector.connector_id for connector in self.connectors]
        if len(member_ids) != len(set(member_ids)):
            raise ValueError("team member IDs must be unique")
        if len(connector_ids) != len(set(connector_ids)):
            raise ValueError("team connector IDs must be unique")
        if not any(member.role == TeamRole.OWNER for member in self.members):
            raise ValueError("team config requires at least one owner")
        known = set(connector_ids)
        for member in self.members:
            unknown = set(member.connector_ids) - known
            if unknown:
                raise ValueError(f"member references unknown connectors: {sorted(unknown)}")
        return self


class ScheduledSnapshotTask(StrictModel):
    schema_version: str = COLLABORATION_SCHEMA_VERSION
    task_id: str
    publication_id: str
    video_id: str
    platform: Platform
    target_age_hours: int = Field(ge=1)
    due_at: datetime
    status: Literal["future", "due", "available"]


class SnapshotScheduleResult(StrictModel):
    schema_version: str = COLLABORATION_SCHEMA_VERSION
    generated_at: datetime
    tasks: list[ScheduledSnapshotTask]
    next_due_at: datetime | None = None


class BatchTask(StrictModel):
    task_id: str = Field(min_length=1)
    operation: Literal["authorized-export", "sync-pull", "sync-push", "snapshot-plan"]
    parameters: dict[str, Any] = Field(default_factory=dict)


class BatchManifest(StrictModel):
    schema_version: str = COLLABORATION_SCHEMA_VERSION
    batch_id: str = Field(min_length=1)
    tasks: list[BatchTask] = Field(min_length=1)
    continue_on_error: bool = True

    @field_validator("tasks")
    @classmethod
    def unique_tasks(cls, value: list[BatchTask]) -> list[BatchTask]:
        task_ids = [task.task_id for task in value]
        if len(task_ids) != len(set(task_ids)):
            raise ValueError("batch task IDs must be unique")
        return value


class BatchTaskResult(StrictModel):
    task_id: str
    operation: str
    status: Literal["success", "failed"]
    output: dict[str, Any] | None = None
    error: dict[str, Any] | None = None


class BatchResult(StrictModel):
    schema_version: str = COLLABORATION_SCHEMA_VERSION
    batch_id: str
    started_at: datetime
    finished_at: datetime
    dry_run: bool
    tasks: list[BatchTaskResult]
    artifact_path: str | None = None
