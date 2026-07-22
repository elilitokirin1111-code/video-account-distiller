"""Pydantic data contracts for the offline normalized data kernel."""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from video_account_distiller.version import (
    CORE_SCHEMA_VERSION,
    PACKAGE_VERSION,
    SKILL_VERSION,
)

SCHEMA_VERSION = CORE_SCHEMA_VERSION
NonNegativeInt = Annotated[int, Field(ge=0)]
NonNegativeFloat = Annotated[float, Field(ge=0)]
Rate = Annotated[float, Field(ge=0)]


def utc_now() -> datetime:
    """Return a timezone-aware current timestamp."""

    return datetime.now(UTC)


class StrictModel(BaseModel):
    """Base contract that rejects unknown fields instead of dropping them."""

    model_config = ConfigDict(extra="forbid", validate_assignment=True)


class Platform(StrEnum):
    DOUYIN = "douyin"
    XIAOHONGSHU = "xiaohongshu"
    WECHAT_CHANNELS = "wechat-channels"
    BILIBILI = "bilibili"
    TIKTOK = "tiktok"
    YOUTUBE = "youtube"
    INSTAGRAM = "instagram"


class DataQualityFlag(StrEnum):
    MISSING_VIEWS = "missing_views"
    MISSING_PUBLISH_TIME = "missing_publish_time"
    UNKNOWN_FOLLOWER_AT_PUBLISH = "unknown_follower_at_publish"
    CURRENT_FOLLOWER_USED_AS_PROXY = "current_follower_used_as_proxy"
    SUSPECTED_PAID_TRAFFIC = "suspected_paid_traffic"
    SUSPECTED_REPOST = "suspected_repost"
    DELETED_CONTENT = "deleted_content"
    METRIC_SNAPSHOT_INCONSISTENT = "metric_snapshot_inconsistent"
    TRANSCRIPT_LOW_CONFIDENCE = "transcript_low_confidence"
    COMMENT_SAMPLE_PARTIAL = "comment_sample_partial"
    PLATFORM_METRIC_NOT_COMPARABLE = "platform_metric_not_comparable"
    SMALL_SAMPLE = "small_sample"
    OUTLIER = "outlier"
    MANUAL_OVERRIDE = "manual_override"


class TraceFields(StrictModel):
    schema_version: str = SCHEMA_VERSION
    record_id: str
    source_platform: Platform
    source_type: str
    source_uri: str | None = None
    source_record_id: str
    collected_at: datetime | None = None
    ingested_at: datetime = Field(default_factory=utc_now)
    run_id: str
    raw_hash: str
    data_quality_flags: list[DataQualityFlag] = Field(default_factory=list)


class Account(TraceFields):
    account_id: str
    platform: Platform
    platform_account_id: str
    handle: str | None = None
    display_name: str | None = None
    bio: str | None = None
    profile_url: str | None = None
    verified: bool | None = None
    follower_count_current: NonNegativeInt | None = None
    following_count_current: NonNegativeInt | None = None
    total_likes_current: NonNegativeInt | None = None
    video_count_current: NonNegativeInt | None = None
    category_raw: str | None = None
    country_or_region: str | None = None
    language: str | None = None
    created_at: datetime | None = None
    snapshot_at: datetime


class AccountSnapshot(TraceFields):
    account_snapshot_id: str
    account_id: str
    snapshot_at: datetime
    followers: NonNegativeInt | None = None
    following: NonNegativeInt | None = None
    total_likes: NonNegativeInt | None = None
    video_count: NonNegativeInt | None = None
    profile_views: NonNegativeInt | None = None
    source: str | None = None


class Video(TraceFields):
    video_id: str
    account_id: str
    platform: Platform
    platform_video_id: str
    url: str | None = None
    title: str | None = None
    description: str | None = None
    published_at: datetime | None = None
    duration_seconds: NonNegativeFloat | None = None
    content_type: str | None = None
    language: str | None = None
    is_ad: bool | None = None
    is_pinned: bool | None = None
    is_deleted: bool | None = None
    is_repost: bool | None = None
    music_title: str | None = None
    music_author: str | None = None
    hashtags: list[str] = Field(default_factory=list)
    mentions: list[str] = Field(default_factory=list)
    cover_path: str | None = None
    media_path: str | None = None
    transcript_path: str | None = None
    follower_count_at_publish: NonNegativeInt | None = None


class MetricSnapshot(TraceFields):
    metric_snapshot_id: str
    video_id: str
    snapshot_at: datetime
    age_hours: NonNegativeFloat | None = None
    views: NonNegativeInt | None = None
    impressions: NonNegativeInt | None = None
    likes: NonNegativeInt | None = None
    comments: NonNegativeInt | None = None
    shares: NonNegativeInt | None = None
    saves: NonNegativeInt | None = None
    favorites: NonNegativeInt | None = None
    follows_gained: NonNegativeInt | None = None
    profile_visits: NonNegativeInt | None = None
    avg_watch_time_seconds: NonNegativeFloat | None = None
    completion_rate: Rate | None = None
    three_second_view_rate: Rate | None = None
    five_second_view_rate: Rate | None = None
    clicks: NonNegativeInt | None = None
    leads: NonNegativeInt | None = None
    orders: NonNegativeInt | None = None
    revenue: NonNegativeFloat | None = None
    is_promoted: bool | None = None
    promotion_spend: NonNegativeFloat | None = None
    metric_source: str | None = None


class DerivedMetrics(TraceFields):
    video_id: str
    snapshot_at: datetime
    like_rate_by_view: float | None = None
    comment_rate_by_view: float | None = None
    share_rate_by_view: float | None = None
    save_rate_by_view: float | None = None
    engagement_rate_by_view: float | None = None
    engagement_rate_by_follower: float | None = None
    follow_conversion_rate: float | None = None
    profile_conversion_rate: float | None = None
    completion_efficiency: float | None = None
    robust_z_views: float | None = None
    robust_z_like_rate: float | None = None
    robust_z_comment_rate: float | None = None
    robust_z_share_rate: float | None = None
    robust_z_save_rate: float | None = None
    robust_z_follow_conversion: float | None = None
    robust_z_watch_efficiency: float | None = None
    viral_index_account: float | None = None
    viral_index_peer: float | None = None
    performance_score: float | None = None
    performance_band: Literal["S", "A", "B", "C", "D"] | None = None
    outlier_flags: list[str] = Field(default_factory=list)


class Comment(TraceFields):
    comment_id: str
    video_id: str
    platform_comment_id: str
    parent_comment_id: str | None = None
    author_hash: str | None = None
    text: str
    created_at: datetime | None = None
    like_count: NonNegativeInt | None = None
    is_creator_reply: bool | None = None
    is_pinned: bool | None = None
    language: str | None = None


class TranscriptSegment(TraceFields):
    segment_id: str
    video_id: str
    start_ms: NonNegativeInt | None = None
    end_ms: NonNegativeInt | None = None
    text: str = Field(min_length=1)
    speaker: str | None = None
    confidence: float | None = Field(default=None, ge=0, le=1)
    language: str | None = None
    source: str

    @model_validator(mode="after")
    def validate_timing(self) -> TranscriptSegment:
        """Reject reversed subtitle intervals while preserving unknown timing as null."""

        if self.start_ms is not None and self.end_ms is not None and self.end_ms < self.start_ms:
            raise ValueError("end_ms must be greater than or equal to start_ms")
        return self


class DataQualityIssue(StrictModel):
    schema_version: str = SCHEMA_VERSION
    issue_id: str
    run_id: str
    severity: Literal["warning", "error"]
    code: str
    entity: str
    message: str
    row_number: int | None = None
    field: str | None = None
    raw_hash: str | None = None
    details: dict[str, Any] = Field(default_factory=dict)


class FieldMapping(StrictModel):
    schema_version: str = SCHEMA_VERSION
    entity: Literal["accounts", "videos", "metrics", "comments", "transcripts"]
    platform: Platform
    fields: dict[str, str]
    timezone: str = "UTC"
    mapping_version: str = "1"


class ImportReceipt(StrictModel):
    schema_version: str = SCHEMA_VERSION
    entity: Literal["accounts", "videos", "metrics", "comments", "transcripts"]
    platform: Platform
    source_name: str
    target_id: str | None = None
    raw_hash: str
    raw_path: str
    staging_path: str | None = None
    imported_at: datetime = Field(default_factory=utc_now)
    run_id: str
    input_rows: int
    accepted_rows: int
    rejected_rows: int
    duplicate_rows: int
    quality_report_json: str
    quality_report_markdown: str


class RunManifest(StrictModel):
    schema_version: str = SCHEMA_VERSION
    run_id: str
    command: str
    started_at: datetime
    finished_at: datetime | None = None
    status: Literal["running", "success", "failed"] = "running"
    input_hashes: list[str] = Field(default_factory=list)
    config_hash: str | None = None
    code_version: str = PACKAGE_VERSION
    skill_version: str = SKILL_VERSION
    processed_counts: dict[str, int] = Field(default_factory=dict)
    warnings: list[str] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)
    output_files: list[str] = Field(default_factory=list)


class ProjectState(StrictModel):
    schema_version: str = SCHEMA_VERSION
    project_id: str
    project_name: str
    created_at: datetime
    updated_at: datetime
    imports: list[ImportReceipt] = Field(default_factory=list)
    last_run_id: str | None = None
    last_normalized_at: datetime | None = None
    last_metrics_at: datetime | None = None
    last_sample_at: datetime | None = None
    last_report_at: datetime | None = None
    last_transcript_at: datetime | None = None
    last_video_analysis_at: datetime | None = None
