"""Provider-neutral contracts for authorized account-homepage collection."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any, Literal, overload
from urllib.parse import urlparse

from pydantic import Field, field_validator, model_validator

from video_account_distiller.models.core import StrictModel
from video_account_distiller.version import COLLECTION_SCHEMA_VERSION

HOMEPAGE_PAGE_SAFETY_LIMIT = 1000
HOMEPAGE_VIDEO_SAFETY_LIMIT = 20_000


class CollectionProviderKind(StrEnum):
    """Supported authorized account collection providers."""

    MEDIACRAWLER = "mediacrawler"
    TIKHUB = "tikhub"


class CollectionSort(StrEnum):
    """Provider-neutral homepage ordering."""

    LATEST = "latest"
    POPULAR = "popular"


@overload
def _timezone_aware(value: datetime) -> datetime: ...


@overload
def _timezone_aware(value: None) -> None: ...


def _timezone_aware(value: datetime | None) -> datetime | None:
    if value is not None and value.utcoffset() is None:
        raise ValueError("collection timestamps must include a timezone")
    return value


class AccountCollectionRequest(StrictModel):
    """Validated request for one public Douyin account homepage."""

    schema_version: str = COLLECTION_SCHEMA_VERSION
    profile_url: str = Field(min_length=1, max_length=2048)
    count: int | None = Field(
        default=None,
        ge=1,
        le=HOMEPAGE_VIDEO_SAFETY_LIMIT,
        description=(
            "Optional video limit. None collects every homepage video exposed by the provider."
        ),
    )
    sort: CollectionSort = CollectionSort.LATEST
    provider: CollectionProviderKind = CollectionProviderKind.MEDIACRAWLER
    comments_per_video: int = Field(default=10, ge=0, le=20)
    comment_video_limit: int = Field(default=3, ge=1, le=20_000)

    @field_validator("profile_url")
    @classmethod
    def validate_profile_url(cls, value: str) -> str:
        """Allow only HTTPS Douyin hosts, preventing arbitrary URL fetches."""

        normalized = value.strip()
        parsed = urlparse(normalized)
        host = (parsed.hostname or "").casefold().rstrip(".")
        if (
            parsed.scheme != "https"
            or not host
            or (host != "douyin.com" and not host.endswith(".douyin.com"))
        ):
            raise ValueError("profile_url must be an HTTPS URL on douyin.com")
        if parsed.username or parsed.password or parsed.port is not None:
            raise ValueError("profile_url must not contain credentials or a custom port")
        return normalized


class CollectedAccount(StrictModel):
    """Canonical account row compatible with the offline importer."""

    platform_account_id: str = Field(min_length=1)
    handle: str | None = None
    display_name: str | None = None
    bio: str | None = None
    profile_url: str | None = None
    verified: bool | None = None
    follower_count_current: int | None = Field(default=None, ge=0)
    following_count_current: int | None = Field(default=None, ge=0)
    total_likes_current: int | None = Field(default=None, ge=0)
    video_count_current: int | None = Field(default=None, ge=0)
    category_raw: str | None = None
    country_or_region: str | None = None
    language: str | None = None
    snapshot_at: datetime

    @field_validator("snapshot_at")
    @classmethod
    def require_timezone(cls, value: datetime) -> datetime:
        return _timezone_aware(value)


class CollectedVideo(StrictModel):
    """Canonical video row compatible with the offline importer."""

    platform_video_id: str = Field(min_length=1)
    account_id: str = Field(min_length=1)
    url: str | None = None
    title: str | None = None
    description: str | None = None
    published_at: datetime | None = None
    duration_seconds: float | None = Field(default=None, ge=0)
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
    follower_count_at_publish: int | None = Field(default=None, ge=0)

    @field_validator("published_at")
    @classmethod
    def require_timezone(cls, value: datetime | None) -> datetime | None:
        return _timezone_aware(value)


class CollectedMetricSnapshot(StrictModel):
    """Canonical public metric row compatible with the offline importer."""

    video_id: str = Field(min_length=1)
    snapshot_at: datetime
    views: int | None = Field(default=None, ge=0)
    likes: int | None = Field(default=None, ge=0)
    comments: int | None = Field(default=None, ge=0)
    shares: int | None = Field(default=None, ge=0)
    saves: int | None = Field(default=None, ge=0)
    favorites: int | None = Field(default=None, ge=0)
    metric_source: str | None = None

    @field_validator("snapshot_at")
    @classmethod
    def require_timezone(cls, value: datetime) -> datetime:
        return _timezone_aware(value)


class CollectedComment(StrictModel):
    """Privacy-minimized public comment row compatible with the offline importer."""

    platform_comment_id: str = Field(min_length=1)
    video_id: str = Field(min_length=1)
    parent_comment_id: str | None = None
    author_hash: str | None = None
    text: str
    created_at: datetime | None = None
    like_count: int | None = Field(default=None, ge=0)
    is_creator_reply: bool | None = None
    is_pinned: bool | None = None
    language: str | None = None

    @field_validator("created_at")
    @classmethod
    def require_timezone(cls, value: datetime | None) -> datetime | None:
        return _timezone_aware(value)


class ProviderRawPage(StrictModel):
    """One immutable provider response retained for audit and reprocessing."""

    endpoint: str = Field(min_length=1)
    fetched_at: datetime
    payload: dict[str, Any]

    @field_validator("fetched_at")
    @classmethod
    def require_timezone(cls, value: datetime) -> datetime:
        return _timezone_aware(value)


class ProviderDriftSeverity(StrEnum):
    """Severity assigned to one provider response contract observation."""

    WARNING = "warning"
    ERROR = "error"


class ProviderDriftIssue(StrictModel):
    """One stable, secret-free provider response contract observation."""

    endpoint: str = Field(min_length=1)
    severity: ProviderDriftSeverity
    code: str = Field(min_length=1)
    message: str = Field(min_length=1)


class ProviderDriftReport(StrictModel):
    """Versioned response-shape report retained beside an immutable provider batch."""

    schema_version: str = "1.0"
    provider: CollectionProviderKind
    contract_version: str = Field(min_length=1)
    checked_at: datetime
    status: Literal["pass", "warn", "fail"]
    ok: bool
    schema_fingerprint: str = Field(min_length=64, max_length=64)
    endpoints: dict[str, int]
    issues: list[ProviderDriftIssue] = Field(default_factory=list)

    @field_validator("checked_at")
    @classmethod
    def require_timezone(cls, value: datetime) -> datetime:
        return _timezone_aware(value)


class AccountCollectionBatch(StrictModel):
    """Complete provider-neutral batch returned by an account collector."""

    schema_version: str = COLLECTION_SCHEMA_VERSION
    provider: CollectionProviderKind
    profile_url: str
    platform_account_id: str = Field(min_length=1)
    fetched_at: datetime
    account: CollectedAccount
    videos: list[CollectedVideo]
    metrics: list[CollectedMetricSnapshot]
    comments: list[CollectedComment] = Field(default_factory=list)
    raw_pages: list[ProviderRawPage] = Field(min_length=1)
    warnings: list[str] = Field(default_factory=list)

    @field_validator("fetched_at")
    @classmethod
    def require_timezone(cls, value: datetime) -> datetime:
        return _timezone_aware(value)

    @model_validator(mode="after")
    def validate_entity_links(self) -> AccountCollectionBatch:
        if self.account.platform_account_id != self.platform_account_id:
            raise ValueError("collected account ID must match batch account ID")
        video_ids = [video.platform_video_id for video in self.videos]
        if len(video_ids) != len(set(video_ids)):
            raise ValueError("collected video IDs must be unique")
        if any(video.account_id != self.platform_account_id for video in self.videos):
            raise ValueError("every collected video must belong to the batch account")
        metric_ids = [metric.video_id for metric in self.metrics]
        if len(metric_ids) != len(set(metric_ids)):
            raise ValueError("collected metric video IDs must be unique")
        if set(metric_ids) != set(video_ids):
            raise ValueError("collected metrics must match collected videos exactly")
        comment_ids = [comment.platform_comment_id for comment in self.comments]
        if len(comment_ids) != len(set(comment_ids)):
            raise ValueError("collected comment IDs must be unique")
        if any(comment.video_id not in video_ids for comment in self.comments):
            raise ValueError("every collected comment must belong to a collected video")
        return self
