"""Centralized platform field mapping resolution."""

from __future__ import annotations

from importlib.resources import files
from pathlib import Path
from typing import Any, Literal, cast

import yaml

from video_account_distiller.errors import DistillerError, ErrorCode
from video_account_distiller.models import FieldMapping, Platform

Entity = Literal["accounts", "videos", "metrics", "comments"]

COMMON_ALIASES: dict[Entity, dict[str, list[str]]] = {
    "accounts": {
        "platform_account_id": ["platform_account_id", "account_id"],
        "account_id": ["account_id"],
        "handle": ["handle", "username"],
        "display_name": ["display_name", "name"],
        "bio": ["bio", "description"],
        "profile_url": ["profile_url", "url"],
        "verified": ["verified", "is_verified"],
        "follower_count_current": ["follower_count_current", "followers"],
        "following_count_current": ["following_count_current", "following"],
        "total_likes_current": ["total_likes_current", "total_likes"],
        "video_count_current": ["video_count_current", "video_count"],
        "category_raw": ["category_raw", "category"],
        "country_or_region": ["country_or_region", "country", "region"],
        "language": ["language", "lang"],
        "created_at": ["created_at"],
        "snapshot_at": ["snapshot_at", "collected_at", "updated_at"],
    },
    "videos": {
        "video_id": ["video_id"],
        "platform_video_id": ["platform_video_id", "video_id"],
        "account_id": ["account_id", "platform_account_id"],
        "url": ["url", "video_url"],
        "title": ["title"],
        "description": ["description", "caption"],
        "published_at": ["published_at", "publish_time"],
        "duration_seconds": ["duration_seconds", "duration"],
        "content_type": ["content_type", "type"],
        "language": ["language", "lang"],
        "is_ad": ["is_ad", "ad"],
        "is_pinned": ["is_pinned", "pinned"],
        "is_deleted": ["is_deleted", "deleted"],
        "is_repost": ["is_repost", "repost"],
        "music_title": ["music_title"],
        "music_author": ["music_author"],
        "hashtags": ["hashtags", "tags"],
        "mentions": ["mentions"],
        "cover_path": ["cover_path"],
        "media_path": ["media_path"],
        "transcript_path": ["transcript_path"],
        "follower_count_at_publish": ["follower_count_at_publish"],
    },
    "metrics": {
        "metric_snapshot_id": ["metric_snapshot_id", "snapshot_id"],
        "video_id": ["video_id", "platform_video_id"],
        "snapshot_at": ["snapshot_at", "collected_at", "updated_at"],
        "age_hours": ["age_hours"],
        "views": ["views", "view_count"],
        "impressions": ["impressions"],
        "likes": ["likes", "like_count"],
        "comments": ["comments", "comment_count"],
        "shares": ["shares", "share_count"],
        "saves": ["saves", "save_count", "favorites"],
        "favorites": ["favorites", "favorite_count"],
        "follows_gained": ["follows_gained", "new_followers"],
        "profile_visits": ["profile_visits"],
        "avg_watch_time_seconds": ["avg_watch_time_seconds", "avg_watch_time"],
        "completion_rate": ["completion_rate"],
        "three_second_view_rate": ["three_second_view_rate"],
        "five_second_view_rate": ["five_second_view_rate"],
        "clicks": ["clicks"],
        "leads": ["leads"],
        "orders": ["orders"],
        "revenue": ["revenue"],
        "is_promoted": ["is_promoted", "promoted"],
        "promotion_spend": ["promotion_spend", "ad_spend"],
        "metric_source": ["metric_source", "source"],
    },
    "comments": {
        "comment_id": ["comment_id"],
        "platform_comment_id": ["platform_comment_id", "comment_id"],
        "video_id": ["video_id", "platform_video_id"],
        "parent_comment_id": ["parent_comment_id", "parent_id"],
        "author_id": ["author_id", "user_id", "author"],
        "author_hash": ["author_hash"],
        "text": ["text", "content"],
        "created_at": ["created_at", "create_time"],
        "like_count": ["like_count", "likes"],
        "is_creator_reply": ["is_creator_reply", "creator_reply"],
        "is_pinned": ["is_pinned", "pinned"],
        "language": ["language", "lang"],
    },
}

REQUIRED_FIELDS: dict[Entity, tuple[str, ...]] = {
    "accounts": ("platform_account_id",),
    "videos": ("platform_video_id", "account_id"),
    "metrics": ("video_id", "snapshot_at"),
    "comments": ("platform_comment_id", "video_id", "text"),
}


def load_mapping_file(path: Path) -> FieldMapping:
    """Load a user-provided JSON or YAML FieldMapping contract."""

    if not path.is_file():
        raise DistillerError(ErrorCode.INPUT_MISSING, f"Mapping file not found: {path}")
    try:
        if path.suffix.lower() == ".json":
            import json

            payload = json.loads(path.read_text(encoding="utf-8"))
        else:
            payload = yaml.safe_load(path.read_text(encoding="utf-8"))
        return FieldMapping.model_validate(payload)
    except Exception as exc:
        raise DistillerError(
            ErrorCode.SCHEMA_INVALID,
            f"Invalid field mapping: {path}",
            details={"reason": str(exc)},
        ) from exc


class MappingResolver:
    """Resolve canonical fields from user mappings and platform templates."""

    def __init__(self) -> None:
        mapping_path = files("video_account_distiller.resources").joinpath("platform_mappings.yaml")
        payload = yaml.safe_load(mapping_path.read_text(encoding="utf-8"))
        self.version = str(payload["version"])
        self.platform_templates: dict[str, Any] = cast(dict[str, Any], payload["platforms"])

    def resolve(
        self,
        *,
        entity: Entity,
        platform: Platform,
        available_fields: set[str],
        explicit: FieldMapping | None = None,
        timezone: str = "UTC",
    ) -> FieldMapping:
        """Return a complete canonical-to-source mapping for available columns."""

        if explicit is not None:
            if explicit.entity != entity or explicit.platform != platform:
                raise DistillerError(
                    ErrorCode.SCHEMA_INVALID,
                    "Mapping entity or platform does not match the import command",
                )
            mapping = dict(explicit.fields)
        else:
            mapping = {}

        platform_entities = self.platform_templates.get(platform.value, {})
        platform_aliases = platform_entities.get(entity, {})
        for canonical, common_aliases in COMMON_ALIASES[entity].items():
            if canonical in mapping:
                continue
            candidates = [canonical, *platform_aliases.get(canonical, []), *common_aliases]
            source = next(
                (candidate for candidate in candidates if candidate in available_fields),
                None,
            )
            if source is not None:
                mapping[canonical] = source

        missing = [field for field in REQUIRED_FIELDS[entity] if field not in mapping]
        if missing:
            raise DistillerError(
                ErrorCode.FIELD_MAPPING_REQUIRED,
                "Required fields could not be mapped",
                details={
                    "entity": entity,
                    "platform": platform.value,
                    "missing": missing,
                    "available": sorted(available_fields),
                },
            )
        return FieldMapping(
            entity=entity,
            platform=platform,
            fields=mapping,
            timezone=explicit.timezone if explicit else timezone,
            mapping_version=explicit.mapping_version if explicit else self.version,
        )

    @staticmethod
    def apply(record: dict[str, Any], mapping: FieldMapping) -> dict[str, Any]:
        """Apply a canonical-to-source mapping without leaking unknown fields."""

        return {canonical: record.get(source) for canonical, source in mapping.fields.items()}
