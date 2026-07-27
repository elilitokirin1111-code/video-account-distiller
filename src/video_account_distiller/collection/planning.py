"""Collection profiles, provider-call budgets, and honest coverage summaries."""

from __future__ import annotations

from enum import StrEnum
from typing import Any

from video_account_distiller.errors import DistillerError, ErrorCode
from video_account_distiller.models import (
    HOMEPAGE_PAGE_SAFETY_LIMIT,
    HOMEPAGE_VIDEO_SAFETY_LIMIT,
    AccountCollectionBatch,
    AccountCollectionRequest,
    CollectionProviderKind,
)


class CollectionProfile(StrEnum):
    """User-facing acquisition depth with explicit data-scope expectations."""

    STANDARD = "standard"
    COMPREHENSIVE = "comprehensive"
    OWNED = "owned"


def resolve_profile_options(
    *,
    profile: CollectionProfile,
    count: int | None,
    all_videos: bool,
    comments_per_video: int | None,
) -> tuple[int | None, int]:
    """Resolve optional HTTP/CLI inputs without changing the legacy domain schema."""
    if all_videos and count is not None:
        raise DistillerError(
            ErrorCode.SCHEMA_INVALID,
            "Pass either an explicit video count or all_videos, not both",
        )
    if all_videos:
        resolved_count = None
    elif count is not None:
        resolved_count = count
    elif profile == CollectionProfile.COMPREHENSIVE:
        resolved_count = None
    else:
        resolved_count = 20

    if comments_per_video is not None:
        resolved_comments = comments_per_video
    elif profile == CollectionProfile.COMPREHENSIVE:
        resolved_comments = 20
    else:
        resolved_comments = 0
    return resolved_count, resolved_comments


def provider_capabilities(
    provider: CollectionProviderKind,
    *,
    profile: CollectionProfile,
) -> dict[str, Any]:
    """Return a stable capability statement; absence is never presented as zero."""
    retained_media = provider == CollectionProviderKind.MEDIACRAWLER
    return {
        "provider": provider.value,
        "profile": profile.value,
        "available": {
            "account_profile_and_current_follower_snapshot": True,
            "homepage_video_metadata_and_public_engagement": True,
            "bounded_top_level_comment_sampling": True,
            "retained_video_media_for_local_enrichment": retained_media,
            "repeat_snapshot_growth_analysis": True,
            "authorized_private_metric_import": "separate_export_or_connector_workflow",
        },
        "not_guaranteed": [
            "complete_comment_universe",
            "comment_reply_tree",
            "deleted_or_hidden_comments",
            "all_fan_profiles_or_fan_demographics",
            "watch_time_completion_conversion_or_revenue_without_owned_data",
        ],
        "profile_note": (
            "Owned mode combines public collection with separately authorized exports/APIs; "
            "this public provider does not expose private creator metrics."
            if profile == CollectionProfile.OWNED
            else "Public-platform evidence only; private creator metrics require owned data."
        ),
    }


def build_collection_plan(
    request: AccountCollectionRequest,
    *,
    profile: CollectionProfile,
    max_provider_calls: int | None,
) -> dict[str, Any]:
    """Calculate the maximum provider work before any network call."""
    page_size = 18 if request.provider == CollectionProviderKind.MEDIACRAWLER else 20
    all_homepage_videos = request.count is None
    if all_homepage_videos:
        collection_count = HOMEPAGE_VIDEO_SAFETY_LIMIT
        page_count = HOMEPAGE_PAGE_SAFETY_LIMIT
    else:
        requested_count = request.count
        assert requested_count is not None
        collection_count = (
            min(
                max(requested_count * 3, requested_count),
                HOMEPAGE_VIDEO_SAFETY_LIMIT,
            )
            if (
                request.provider == CollectionProviderKind.MEDIACRAWLER
                and request.sort.value == "popular"
            )
            else requested_count
        )
        page_count = (collection_count + page_size - 1) // page_size
    comment_calls = (
        (
            request.comment_video_limit
            if request.count is None
            else min(request.count, request.comment_video_limit)
        )
        if request.comments_per_video > 0
        else 0
    )
    detail_calls = (
        collection_count if request.provider == CollectionProviderKind.MEDIACRAWLER else 0
    )
    total_calls = page_count + detail_calls + comment_calls + 2
    chargeable_calls = (
        0
        if request.provider == CollectionProviderKind.MEDIACRAWLER
        else page_count + comment_calls + 2
    )
    would_write = [
        "raw/account-collections/",
        "staging/accounts/",
        "staging/videos/",
        "staging/metrics/",
        "normalized/*.parquet",
        "reports/accounts/",
    ]
    if comment_calls:
        would_write.extend(["staging/comments/", "analyses/comments/"])
    within_budget = max_provider_calls is None or total_calls <= max_provider_calls
    return {
        "collection_profile": profile.value,
        "request": request.model_dump(mode="json"),
        "collection_scope": {
            "mode": ("all_available_homepage_videos" if all_homepage_videos else "limited"),
            "requested_video_limit": request.count,
            "requested_comments_per_sampled_video": request.comments_per_video,
            "comment_video_limit": request.comment_video_limit,
            "termination": (
                "provider_exhausted_or_safety_guard"
                if all_homepage_videos
                else "requested_limit_or_provider_exhausted"
            ),
            "page_safety_limit": HOMEPAGE_PAGE_SAFETY_LIMIT,
            "video_safety_limit": HOMEPAGE_VIDEO_SAFETY_LIMIT,
        },
        "provider_calls": {
            "resolve_profile_url": 1,
            "account_profile": 1,
            "homepage_post_pages_max": page_count,
            "video_detail_calls_max": detail_calls,
            "comment_video_pages_max": comment_calls,
            "total_max": total_calls,
        },
        "budget": {
            "max_provider_calls": max_provider_calls,
            "planned_provider_calls_max": total_calls,
            "within_limit": within_budget,
            "enforced_on_execution": max_provider_calls is not None,
        },
        "billing": {
            "chargeable_calls_max": chargeable_calls,
            "unit_price": (
                "none; local non-commercial research runtime"
                if request.provider == CollectionProviderKind.MEDIACRAWLER
                else "check the provider marketplace for each endpoint"
            ),
            "currency": (
                None
                if request.provider == CollectionProviderKind.MEDIACRAWLER
                else "provider_account_currency"
            ),
        },
        "capabilities": provider_capabilities(request.provider, profile=profile),
        "runtime": (
            {
                "browser": "visible Chrome with a dedicated persistent profile",
                "login": "manual when required",
                "first_run": "uv prepares the pinned MediaCrawler environment",
            }
            if request.provider == CollectionProviderKind.MEDIACRAWLER
            else None
        ),
        "would_write": would_write,
    }


def enforce_collection_budget(plan: dict[str, Any]) -> None:
    """Stop before provider execution when the explicit call ceiling is exceeded."""
    budget = plan["budget"]
    if budget["within_limit"]:
        return
    raise DistillerError(
        ErrorCode.COLLECTION_BUDGET_EXCEEDED,
        "Planned provider calls exceed the configured collection budget",
        details={
            "max_provider_calls": budget["max_provider_calls"],
            "planned_provider_calls_max": budget["planned_provider_calls_max"],
            "next": "reduce scope or raise max_provider_calls after reviewing the dry-run",
        },
    )


def collection_coverage(
    request: AccountCollectionRequest,
    batch: AccountCollectionBatch,
    *,
    profile: CollectionProfile,
) -> dict[str, Any]:
    """Describe what was actually captured without claiming inaccessible completeness."""
    safety_warnings = [
        item
        for item in batch.warnings
        if item in {"homepage_page_safety_limit_reached", "homepage_video_safety_limit_reached"}
    ]
    degraded_warnings = [
        item
        for item in batch.warnings
        if item.startswith("comment_collection_degraded")
        or item.startswith("video_detail_degraded")
    ]
    if safety_warnings:
        video_status = "partial_safety_limit"
        stop_reason = safety_warnings[0]
    elif request.count is None:
        video_status = "complete_available_homepage"
        stop_reason = "provider_exhausted"
    elif len(batch.videos) >= request.count:
        video_status = "requested_limit_reached"
        stop_reason = "requested_limit"
    else:
        video_status = "partial_provider_exhausted"
        stop_reason = "provider_returned_fewer_videos_than_requested"

    if request.comments_per_video <= 0:
        comment_status = "not_requested"
    elif degraded_warnings:
        comment_status = "partial_degraded"
    elif batch.comments:
        comment_status = "bounded_sample_collected"
    else:
        comment_status = "no_usable_public_comments"

    partial = video_status.startswith("partial") or comment_status in {
        "partial_degraded",
        "no_usable_public_comments",
    }
    return {
        "collection_profile": profile.value,
        "status": (
            "partial"
            if partial
            else ("complete_with_warnings" if batch.warnings else "complete_for_declared_scope")
        ),
        "videos": {
            "requested": request.count if request.count is not None else "all_available",
            "collected": len(batch.videos),
            "status": video_status,
            "stop_reason": stop_reason,
        },
        "comments": {
            "scope": "bounded_top_level_sample_not_full_comment_universe",
            "requested_per_video": request.comments_per_video,
            "requested_video_limit": request.comment_video_limit,
            "sampled_videos": len({item.video_id for item in batch.comments}),
            "collected": len(batch.comments),
            "status": comment_status,
        },
        "account_snapshot": {
            "captured": True,
            "followers": batch.account.follower_count_current is not None,
            "following": batch.account.following_count_current is not None,
            "total_likes": batch.account.total_likes_current is not None,
            "video_count": batch.account.video_count_current is not None,
        },
        "warnings": batch.warnings,
    }
