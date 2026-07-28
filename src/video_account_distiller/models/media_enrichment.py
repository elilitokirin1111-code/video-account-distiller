"""Account-level media acquisition and transcription contracts."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import Field

from video_account_distiller.models.core import StrictModel
from video_account_distiller.version import MEDIA_SCHEMA_VERSION


class TranscriptionSummary(StrictModel):
    """Traceable local transcription outcome without exposing source URLs."""

    schema_version: str = MEDIA_SCHEMA_VERSION
    status: Literal["complete", "reused", "skipped", "failed"]
    provider: str
    model: str | None = None
    language: str | None = None
    segment_count: int = Field(default=0, ge=0)
    raw_hash: str | None = None
    raw_path: str | None = None
    warnings: list[str] = Field(default_factory=list)


class VideoMediaEnrichment(StrictModel):
    """One video's bounded acquisition, media analysis, and text-analysis result."""

    schema_version: str = MEDIA_SCHEMA_VERSION
    video_id: str
    platform_video_id: str
    status: Literal["complete", "degraded", "failed"]
    source_host: str | None = None
    media_hash: str | None = None
    media_analysis_id: str | None = None
    media_analysis_path: str | None = None
    transcription: TranscriptionSummary
    text_analysis_id: str | None = None
    text_analysis_path: str | None = None
    text_analysis_status: Literal["complete", "degraded"] | None = None
    warnings: list[str] = Field(default_factory=list)


class AccountMediaEnrichment(StrictModel):
    """Content-addressed account media-enrichment artifact."""

    schema_version: str = MEDIA_SCHEMA_VERSION
    enrichment_id: str
    account_id: str
    generated_at: datetime
    run_id: str
    adapter_version: str
    upstream_commit: str
    source_provider: str
    source_batch_hash: str
    source_batch_path: str
    selection_policy: str
    requested_limit: int = Field(ge=1, le=20)
    selected_count: int = Field(ge=0)
    completed_count: int = Field(ge=0)
    degraded_count: int = Field(ge=0)
    failed_count: int = Field(ge=0)
    videos: list[VideoMediaEnrichment] = Field(default_factory=list)
    distillation_id: str | None = None
    distillation_path: str | None = None
    warnings: list[str] = Field(default_factory=list)
