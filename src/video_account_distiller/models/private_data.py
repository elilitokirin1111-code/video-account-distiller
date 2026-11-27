"""Versioned contracts for authorized private data and report data gaps."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Annotated, Literal

from pydantic import Field, model_validator

from video_account_distiller.models.core import (
    NonNegativeInt,
    StrictModel,
    TraceFields,
)
from video_account_distiller.version import AUDIENCE_PROFILE_SCHEMA_VERSION

Share = Annotated[float, Field(ge=0, le=1)]


class DataSourceTier(StrEnum):
    """Auditable source boundary used by imports and reports."""

    PUBLIC = "public"
    AUTHORIZED_PRIVATE = "authorized_private"
    MODEL_INFERRED = "model_inferred"
    UNKNOWN = "unknown"


class DataAvailability(StrEnum):
    AVAILABLE = "available"
    UNKNOWN = "unknown"


AudienceDimension = Literal[
    "gender",
    "age",
    "region",
    "city_tier",
    "device",
    "interest",
    "active_time",
    "follower_status",
    "other",
]


class AudienceProfileSegment(TraceFields):
    """One normalized segment in a versioned creator-audience snapshot."""

    schema_version: str = AUDIENCE_PROFILE_SCHEMA_VERSION
    profile_segment_id: str
    account_id: str
    snapshot_at: datetime
    dimension: AudienceDimension
    bucket: str = Field(min_length=1)
    share: Share | None = None
    audience_count: NonNegativeInt | None = None
    sample_size: NonNegativeInt | None = None
    source_schema_version: str = Field(min_length=1)

    @model_validator(mode="after")
    def require_observation(self) -> AudienceProfileSegment:
        if self.share is None and self.audience_count is None:
            raise ValueError("audience profile segment requires share or audience_count")
        if (
            self.sample_size is not None
            and self.audience_count is not None
            and self.audience_count > self.sample_size
        ):
            raise ValueError("audience_count cannot exceed sample_size")
        return self


class DataEvidenceRef(StrictModel):
    table: str
    record_id: str
    source_record_id: str
    raw_hash: str
    run_id: str
    source_uri: str | None = None


class DataGapItem(StrictModel):
    field: str
    label: str
    source_tier: DataSourceTier
    availability: DataAvailability
    available_records: NonNegativeInt
    total_records: NonNegativeInt
    observed_source_tiers: list[DataSourceTier] = Field(default_factory=list)
    evidence_refs: list[DataEvidenceRef] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_availability(self) -> DataGapItem:
        if self.available_records > self.total_records:
            raise ValueError("available_records cannot exceed total_records")
        if self.availability == DataAvailability.UNKNOWN and self.available_records != 0:
            raise ValueError("unknown fields cannot have available records")
        if self.availability == DataAvailability.AVAILABLE and self.available_records == 0:
            raise ValueError("available fields require at least one record")
        return self


class AccountDataGapTable(StrictModel):
    schema_version: str = AUDIENCE_PROFILE_SCHEMA_VERSION
    report_id: str
    account_id: str
    generated_at: datetime
    rows: list[DataGapItem]
