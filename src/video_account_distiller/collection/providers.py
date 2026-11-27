"""Authorized API providers for account-homepage collection."""

from __future__ import annotations

import os
import re
import time
from collections.abc import Callable, Iterator
from datetime import UTC, datetime
from typing import Any, Protocol
from urllib.parse import urlencode

from pydantic import ValidationError

from video_account_distiller.adapters.collaboration import (
    HttpExecutor,
    HttpResponse,
    UrllibHttpExecutor,
)
from video_account_distiller.common.http_utils import (
    compute_retry_after,
    read_env_credential,
    request_json,
)
from video_account_distiller.errors import DistillerError, ErrorCode
from video_account_distiller.models import (
    HOMEPAGE_PAGE_SAFETY_LIMIT,
    HOMEPAGE_VIDEO_SAFETY_LIMIT,
    AccountCollectionBatch,
    AccountCollectionRequest,
    CollectedAccount,
    CollectedComment,
    CollectedMetricSnapshot,
    CollectedVideo,
    CollectionProviderKind,
    CollectionSort,
    ProviderRawPage,
    RetryPolicy,
)
from video_account_distiller.utils.hashing import hash_text

TIKHUB_BASE_URLS = {"https://api.tikhub.dev", "https://api.tikhub.io"}
RESOLVE_PATH = "/api/v1/douyin/web/get_sec_user_id"
PROFILE_PATH = "/api/v1/douyin/app/v3/handler_user_profile"
VIDEO_DETAIL_PATH = "/api/v1/douyin/web/fetch_one_video"
COMMENTS_PATH = "/api/v1/douyin/web/fetch_video_comments"
POSTS_PATHS = {
    "web": "/api/v1/douyin/web/fetch_user_post_videos",
    "app-v3": "/api/v1/douyin/app/v3/fetch_user_post_videos",
}

_VIDEO_URL_ID_PATTERNS = (
    re.compile(r"(?:video|note)/(\d{5,})"),
    re.compile(r"[?&]modal_id=(\d{5,})"),
    re.compile(r"[?&]aweme_id=(\d{5,})"),
)


def resolve_video_id_from_url(url: str) -> str:
    """Extract a Douyin aweme id from a standard single-video URL.

    Short share links (v.douyin.com) cannot be resolved without a network
    request; the caller is asked to open the link and paste the full address.
    """
    cleaned = url.strip()
    for pattern in _VIDEO_URL_ID_PATTERNS:
        match = pattern.search(cleaned)
        if match is not None:
            return match.group(1)
    raise DistillerError(
        ErrorCode.PROFILE_URL_INVALID,
        "Could not resolve a Douyin video id from the URL",
        details={
            "url": cleaned,
            "next": "打开短链后复制完整视频地址（https://www.douyin.com/video/<id>）再重试",
        },
    )


class AccountCollectionProvider(Protocol):
    """Boundary implemented by a paid or authorized account data provider."""

    def collect(self, request: AccountCollectionRequest) -> AccountCollectionBatch: ...


def _credential() -> str:
    return read_env_credential("TIKHUB_API_KEY")


def _retry_after(response: HttpResponse, attempt: int, policy: RetryPolicy) -> float:
    return compute_retry_after(response, attempt, policy)


def _mapping(value: object) -> dict[str, Any] | None:
    if not isinstance(value, dict):
        return None
    return {str(key): item for key, item in value.items()}


def _provider_data(payload: dict[str, Any]) -> object:
    code = payload.get("code")
    if code in {0, 200, "0", "200", None} and "data" in payload:
        return payload["data"]
    message = str(payload.get("message") or payload.get("msg") or "unknown provider error")
    normalized = message.casefold()
    error_code = (
        ErrorCode.ADAPTER_AUTH
        if any(marker in normalized for marker in ("token", "auth", "permission", "balance"))
        else ErrorCode.RATE_LIMIT
        if any(marker in normalized for marker in ("rate", "limit", "频率", "限流"))
        else ErrorCode.ADAPTER_RESPONSE
    )
    raise DistillerError(
        error_code,
        "Account collection provider rejected the request",
        details={"provider_code": code, "provider_message": message},
    )


def _request_json(
    executor: HttpExecutor,
    *,
    url: str,
    policy: RetryPolicy,
    sleep: Callable[[float], None],
) -> dict[str, Any]:
    """Fetch a JSON object from the collection provider, with retries.

    Thin wrapper around :func:`request_json` that also validates the
    provider-specific response envelope via ``_provider_data``.
    """
    token = _credential()
    # The provider always uses GET with no request payload.
    mapped = request_json(
        executor,
        method="GET",
        url=url,
        token=token,
        policy=policy,
        sleep=sleep,
    )
    _provider_data(mapped)
    return mapped


def _walk(value: object) -> Iterator[object]:
    yield value
    if isinstance(value, dict):
        for item in value.values():
            yield from _walk(item)
    elif isinstance(value, list):
        for item in value:
            yield from _walk(item)


def _first_scalar(value: object, keys: tuple[str, ...]) -> str | None:
    for item in _walk(value):
        if not isinstance(item, dict):
            continue
        for key in keys:
            candidate = item.get(key)
            if isinstance(candidate, (str, int)) and str(candidate).strip():
                return str(candidate).strip()
    if isinstance(value, (str, int)) and str(value).strip():
        return str(value).strip()
    return None


def _first_mapping(value: object, required_any: tuple[str, ...]) -> dict[str, Any] | None:
    for item in _walk(value):
        mapped = _mapping(item)
        if mapped is not None and any(key in mapped for key in required_any):
            return mapped
    return None


def _first_list(value: object, keys: tuple[str, ...]) -> list[dict[str, Any]]:
    for item in _walk(value):
        if not isinstance(item, dict):
            continue
        for key in keys:
            candidate = item.get(key)
            if isinstance(candidate, list):
                return [mapped for child in candidate if (mapped := _mapping(child)) is not None]
    return []


def _nonnegative_int(value: object) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        parsed = int(float(str(value).replace(",", "")))
    except (TypeError, ValueError):
        return None
    return parsed if parsed >= 0 else None


def _boolean(value: object) -> bool | None:
    if isinstance(value, bool):
        return value
    if value in {0, "0"}:
        return False
    if value in {1, "1"}:
        return True
    return None


def _epoch(value: object) -> datetime | None:
    raw = _nonnegative_int(value)
    if raw is None:
        return None
    try:
        return datetime.fromtimestamp(raw, UTC)
    except (OSError, OverflowError, ValueError):
        return None


def _text(value: object) -> str | None:
    if value is None:
        return None
    normalized = str(value).strip()
    return normalized or None


def _optional_id(value: object) -> str | None:
    normalized = _text(value)
    return None if normalized in {None, "0"} else normalized


def _nested(mapping: dict[str, Any], key: str) -> dict[str, Any]:
    return _mapping(mapping.get(key)) or {}


def _first_present(mapping: dict[str, Any], keys: tuple[str, ...]) -> object:
    for key in keys:
        if key in mapping and mapping[key] is not None:
            return mapping[key]
    return None


def _hashtags(post: dict[str, Any]) -> list[str]:
    values: list[str] = []
    text_extra = post.get("text_extra")
    if isinstance(text_extra, list):
        for item in text_extra:
            mapped = _mapping(item)
            name = _text(mapped.get("hashtag_name")) if mapped else None
            if name and name not in values:
                values.append(name)
    return values


def _mentions(post: dict[str, Any]) -> list[str]:
    values: list[str] = []
    text_extra = post.get("text_extra")
    if isinstance(text_extra, list):
        for item in text_extra:
            mapped = _mapping(item)
            nickname = _text(mapped.get("user_unique_id")) if mapped else None
            if nickname and nickname not in values:
                values.append(nickname)
    return values


def _map_profile(
    data: object,
    *,
    platform_account_id: str,
    profile_url: str,
    fetched_at: datetime,
) -> CollectedAccount:
    profile = _first_mapping(
        data,
        ("nickname", "unique_id", "sec_uid", "follower_count", "aweme_count"),
    )
    if profile is None:
        raise DistillerError(
            ErrorCode.ADAPTER_RESPONSE,
            "Provider profile response did not contain a recognizable Douyin user object",
        )
    verification = _text(
        profile.get("enterprise_verify_reason")
        or profile.get("custom_verify")
        or profile.get("verification_type")
    )
    verified_raw = profile.get("is_verified")
    verified = _boolean(verified_raw)
    if verified is None and verification:
        verified = True
    return CollectedAccount(
        platform_account_id=platform_account_id,
        handle=_text(profile.get("unique_id") or profile.get("short_id")),
        display_name=_text(profile.get("nickname")),
        bio=_text(profile.get("signature")),
        profile_url=profile_url,
        verified=verified,
        follower_count_current=_nonnegative_int(profile.get("follower_count")),
        following_count_current=_nonnegative_int(profile.get("following_count")),
        total_likes_current=_nonnegative_int(
            _first_present(profile, ("total_favorited", "total_liked"))
        ),
        video_count_current=_nonnegative_int(profile.get("aweme_count")),
        category_raw=verification,
        country_or_region=_text(profile.get("country") or profile.get("province")),
        language=_text(profile.get("language")),
        snapshot_at=fetched_at,
    )


def _map_post(
    post: dict[str, Any],
    *,
    platform_account_id: str,
    fetched_at: datetime,
    metric_source: str,
) -> tuple[CollectedVideo, CollectedMetricSnapshot] | None:
    video_id = _text(post.get("aweme_id") or post.get("item_id") or post.get("id"))
    if video_id is None:
        return None
    description = _text(post.get("desc") or post.get("description"))
    published_at = _epoch(post.get("create_time"))
    duration_ms = _nonnegative_int(post.get("duration"))
    video_object = _nested(post, "video")
    if duration_ms is None:
        duration_ms = _nonnegative_int(video_object.get("duration"))
    statistics = _nested(post, "statistics")
    music = _nested(post, "music")
    views = _nonnegative_int(statistics.get("play_count"))
    likes = _nonnegative_int(statistics.get("digg_count"))
    comments = _nonnegative_int(statistics.get("comment_count"))
    shares = _nonnegative_int(statistics.get("share_count"))
    saves = _nonnegative_int(_first_present(statistics, ("collect_count", "favorite_count")))
    favorites = _nonnegative_int(statistics.get("collect_count"))
    if views == 0 and any(
        value is not None and value > 0 for value in (likes, comments, shares, saves, favorites)
    ):
        # Douyin's public Web payload can expose a zero play_count while
        # simultaneously exposing substantial interactions. That combination
        # means the view count is unavailable, not that the video had no views.
        views = None
    share_url = _text(post.get("share_url"))
    if share_url is None:
        share_url = f"https://www.douyin.com/video/{video_id}"
    video = CollectedVideo(
        platform_video_id=video_id,
        account_id=platform_account_id,
        url=share_url,
        title=description,
        description=description,
        published_at=published_at,
        duration_seconds=duration_ms / 1000.0 if duration_ms is not None else None,
        content_type=_text(post.get("aweme_type") or post.get("content_type")),
        is_ad=_boolean(post.get("is_ads") if "is_ads" in post else post.get("is_ad")),
        is_pinned=_boolean(post.get("is_top") if "is_top" in post else post.get("is_pinned")),
        is_deleted=False,
        is_repost=_boolean(post.get("is_repost")),
        music_title=_text(music.get("title")),
        music_author=_text(music.get("author") or music.get("owner_nickname")),
        hashtags=_hashtags(post),
        mentions=_mentions(post),
        follower_count_at_publish=None,
    )
    metric = CollectedMetricSnapshot(
        video_id=video_id,
        snapshot_at=fetched_at,
        views=views,
        likes=likes,
        comments=comments,
        shares=shares,
        saves=saves,
        favorites=favorites,
        metric_source=metric_source,
    )
    return video, metric


def _map_comment(
    comment: dict[str, Any],
    *,
    video_id: str,
    platform_account_id: str,
) -> CollectedComment | None:
    comment_id = _optional_id(_first_present(comment, ("cid", "comment_id", "id")))
    text = _text(_first_present(comment, ("text", "content", "comment_text")))
    if comment_id is None or text is None:
        return None
    user = _nested(comment, "user")
    author_id = _optional_id(_first_present(user, ("sec_uid", "uid", "unique_id", "short_id")))
    pinned = _boolean(_first_present(comment, ("is_pinned", "is_top", "is_stick")))
    if pinned is None:
        stick_position = _nonnegative_int(comment.get("stick_position"))
        pinned = stick_position > 0 if stick_position is not None else None
    return CollectedComment(
        platform_comment_id=comment_id,
        video_id=video_id,
        parent_comment_id=_optional_id(
            _first_present(
                comment,
                ("parent_comment_id", "reply_id", "reply_to_comment_id"),
            )
        ),
        author_hash=hash_text(author_id) if author_id is not None else None,
        text=text,
        created_at=_epoch(_first_present(comment, ("create_time", "created_at", "create_at"))),
        like_count=_nonnegative_int(_first_present(comment, ("digg_count", "like_count"))),
        is_creator_reply=(author_id == platform_account_id if author_id is not None else None),
        is_pinned=pinned,
        language=_text(comment.get("language")),
    )


class TikHubAccountProvider:
    """Collect public Douyin account metadata through the documented TikHub API."""

    def __init__(
        self,
        *,
        executor: HttpExecutor | None = None,
        base_url: str | None = None,
        posts_api_mode: str | None = None,
        retry: RetryPolicy | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        selected = base_url or os.environ.get("TIKHUB_API_BASE_URL") or "https://api.tikhub.dev"
        selected = selected.rstrip("/")
        if selected not in TIKHUB_BASE_URLS:
            raise DistillerError(
                ErrorCode.SCHEMA_INVALID,
                "TikHub base URL must use an approved API host",
                details={"allowed": sorted(TIKHUB_BASE_URLS)},
            )
        selected_posts_api_mode = (
            posts_api_mode or os.environ.get("TIKHUB_DOUYIN_POSTS_MODE") or "web"
        )
        if selected_posts_api_mode not in POSTS_PATHS:
            raise DistillerError(
                ErrorCode.SCHEMA_INVALID,
                "TikHub Douyin posts API mode must be web or app-v3",
                details={"allowed": sorted(POSTS_PATHS)},
            )
        self.executor = executor or UrllibHttpExecutor()
        self.base_url = selected
        self.posts_api_mode = selected_posts_api_mode
        self.posts_path = POSTS_PATHS[selected_posts_api_mode]
        self.retry = retry or RetryPolicy()
        self.sleep = sleep

    def _get(
        self,
        path: str,
        query: dict[str, str | int],
        *,
        fetched_at: datetime,
    ) -> ProviderRawPage:
        payload = _request_json(
            self.executor,
            url=f"{self.base_url}{path}?{urlencode(query)}",
            policy=self.retry,
            sleep=self.sleep,
        )
        return ProviderRawPage(endpoint=path, fetched_at=fetched_at, payload=payload)

    def collect(self, request: AccountCollectionRequest) -> AccountCollectionBatch:
        """Resolve a homepage URL, paginate posts, and map public fields."""

        if request.provider != CollectionProviderKind.TIKHUB:
            raise DistillerError(
                ErrorCode.PLATFORM_UNSUPPORTED,
                f"TikHub provider cannot handle {request.provider.value}",
            )
        fetched_at = datetime.now(UTC)
        resolve_page = self._get(
            RESOLVE_PATH,
            {"url": request.profile_url},
            fetched_at=fetched_at,
        )
        resolve_data = _provider_data(resolve_page.payload)
        platform_account_id = _first_scalar(resolve_data, ("sec_user_id", "sec_uid"))
        if platform_account_id is None:
            raise DistillerError(
                ErrorCode.ADAPTER_RESPONSE,
                "Provider could not resolve a Douyin sec_user_id from the homepage URL",
            )
        profile_page = self._get(
            PROFILE_PATH,
            {"sec_user_id": platform_account_id},
            fetched_at=fetched_at,
        )
        account = _map_profile(
            _provider_data(profile_page.payload),
            platform_account_id=platform_account_id,
            profile_url=request.profile_url,
            fetched_at=fetched_at,
        )
        pages = [resolve_page, profile_page]
        videos: list[CollectedVideo] = []
        metrics: list[CollectedMetricSnapshot] = []
        seen: set[str] = set()
        cursor = 0
        sort_parameter = "filter_type" if self.posts_api_mode == "web" else "sort_type"
        if request.sort == CollectionSort.LATEST:
            sort_value = 0
        elif self.posts_api_mode == "web":
            sort_value = 3
        else:
            sort_value = 1
        collection_warnings: list[str] = []
        page_count = 0
        seen_cursors = {cursor}
        while request.count is None or len(videos) < request.count:
            if page_count >= HOMEPAGE_PAGE_SAFETY_LIMIT:
                collection_warnings.append("homepage_page_safety_limit_reached")
                break
            page_size = 20 if request.count is None else min(20, request.count - len(videos))
            post_page = self._get(
                self.posts_path,
                {
                    "sec_user_id": platform_account_id,
                    "max_cursor": cursor,
                    "count": page_size,
                    sort_parameter: sort_value,
                },
                fetched_at=fetched_at,
            )
            page_count += 1
            pages.append(post_page)
            data = _provider_data(post_page.payload)
            items = _first_list(data, ("aweme_list", "items", "videos"))
            for item in items:
                mapped = _map_post(
                    item,
                    platform_account_id=platform_account_id,
                    fetched_at=fetched_at,
                    metric_source=f"tikhub:douyin-{self.posts_api_mode}",
                )
                if mapped is None or mapped[0].platform_video_id in seen:
                    continue
                seen.add(mapped[0].platform_video_id)
                videos.append(mapped[0])
                metrics.append(mapped[1])
                if (request.count is not None and len(videos) >= request.count) or len(
                    videos
                ) >= HOMEPAGE_VIDEO_SAFETY_LIMIT:
                    break
            if request.count is None and len(videos) >= HOMEPAGE_VIDEO_SAFETY_LIMIT:
                collection_warnings.append("homepage_video_safety_limit_reached")
                break
            container = _first_mapping(data, ("has_more", "max_cursor", "cursor")) or {}
            has_more = _boolean(container.get("has_more")) is True
            next_cursor = _nonnegative_int(
                container.get("max_cursor")
                if "max_cursor" in container
                else container.get("cursor")
            )
            if not has_more or not items or next_cursor is None or next_cursor in seen_cursors:
                break
            seen_cursors.add(next_cursor)
            cursor = next_cursor
        comments: list[CollectedComment] = []
        sampled_comment_videos = 0
        videos_without_comments = 0
        comment_warnings: list[str] = []
        if request.comments_per_video > 0:
            comment_targets = sorted(
                metrics,
                key=lambda item: (
                    item.comments is None,
                    -(item.comments or 0),
                    item.video_id,
                ),
            )[: request.comment_video_limit]
            comment_seen: set[str] = set()
            for target in comment_targets:
                sampled_comment_videos += 1
                try:
                    comment_page = self._get(
                        COMMENTS_PATH,
                        {
                            "aweme_id": target.video_id,
                            "cursor": 0,
                            "count": request.comments_per_video,
                        },
                        fetched_at=fetched_at,
                    )
                except DistillerError as exc:
                    comment_warnings.append(f"comment_collection_degraded:{exc.code.value}")
                    break
                pages.append(comment_page)
                comment_items = _first_list(
                    _provider_data(comment_page.payload),
                    ("comments", "comment_list", "items"),
                )
                accepted_for_video = 0
                for item in comment_items[: request.comments_per_video]:
                    mapped_comment = _map_comment(
                        item,
                        video_id=target.video_id,
                        platform_account_id=platform_account_id,
                    )
                    if mapped_comment is None or mapped_comment.platform_comment_id in comment_seen:
                        continue
                    comment_seen.add(mapped_comment.platform_comment_id)
                    comments.append(mapped_comment)
                    accepted_for_video += 1
                if accepted_for_video == 0:
                    videos_without_comments += 1
        warnings = collection_warnings + comment_warnings
        if request.count is not None and len(videos) < request.count:
            warnings.append("provider_returned_fewer_videos_than_requested")
        if any(metric.views is None for metric in metrics):
            warnings.append("some_public_view_counts_are_missing")
        if request.comments_per_video > 0 and not comments:
            warnings.append("provider_returned_no_usable_public_comments")
        elif videos_without_comments:
            warnings.append(
                f"sampled_videos_without_usable_comments:{videos_without_comments}/"
                f"{sampled_comment_videos}"
            )
        return AccountCollectionBatch(
            provider=CollectionProviderKind.TIKHUB,
            profile_url=request.profile_url,
            platform_account_id=platform_account_id,
            fetched_at=fetched_at,
            account=account,
            videos=videos,
            metrics=metrics,
            comments=comments,
            raw_pages=pages,
            warnings=warnings,
        )

    def collect_video(
        self,
        url: str,
        *,
        comments_per_video: int = 0,
    ) -> AccountCollectionBatch:
        """Collect one public Douyin video detail and optional top-level comments.

        The returned batch carries exactly one video. The account row is derived
        from the detail's author object when present; otherwise a minimal
        placeholder account is used so the single video can flow through the
        existing import and normalization kernel.
        """
        fetched_at = datetime.now(UTC)
        video_id = resolve_video_id_from_url(url)
        detail_page = self._get(
            VIDEO_DETAIL_PATH,
            {"aweme_id": video_id},
            fetched_at=fetched_at,
        )
        detail_data = _provider_data(detail_page.payload)
        detail = _first_mapping(detail_data, ("aweme_id", "item_id", "statistics", "video"))
        if detail is None:
            raise DistillerError(
                ErrorCode.ADAPTER_RESPONSE,
                "Provider video detail did not contain a recognizable Douyin video object",
            )
        author = _first_mapping(
            detail.get("author"),
            ("sec_uid", "uid", "unique_id", "nickname"),
        ) or _first_mapping(detail, ("sec_uid", "unique_id", "nickname"))
        platform_account_id = (
            _text((author or {}).get("sec_uid") or (author or {}).get("uid"))
            or f"video-owner-{video_id}"
        )
        if author is not None:
            account = _map_profile(
                author,
                platform_account_id=platform_account_id,
                profile_url=url,
                fetched_at=fetched_at,
            )
        else:
            account = CollectedAccount(
                platform_account_id=platform_account_id,
                display_name="单视频采集",
                profile_url=url,
                snapshot_at=fetched_at,
            )
        mapped = _map_post(
            detail,
            platform_account_id=platform_account_id,
            fetched_at=fetched_at,
            metric_source="tikhub:douyin-fetch-one-video",
        )
        if mapped is None:
            raise DistillerError(
                ErrorCode.ADAPTER_RESPONSE,
                "Provider video detail did not map to a public video",
                details={"video_id": video_id},
            )
        video, metric = mapped
        pages = [detail_page]
        comments: list[CollectedComment] = []
        warnings: list[str] = []
        if comments_per_video > 0:
            try:
                comment_page = self._get(
                    COMMENTS_PATH,
                    {
                        "aweme_id": video_id,
                        "cursor": 0,
                        "count": comments_per_video,
                    },
                    fetched_at=fetched_at,
                )
            except DistillerError as exc:
                warnings.append(f"comment_collection_degraded:{exc.code.value}")
            else:
                pages.append(comment_page)
                seen: set[str] = set()
                for item in _first_list(
                    _provider_data(comment_page.payload),
                    ("comments", "comment_list", "items"),
                )[:comments_per_video]:
                    mapped_comment = _map_comment(
                        item,
                        video_id=video_id,
                        platform_account_id=platform_account_id,
                    )
                    if mapped_comment is None or mapped_comment.platform_comment_id in seen:
                        continue
                    seen.add(mapped_comment.platform_comment_id)
                    comments.append(mapped_comment)
                if not comments:
                    warnings.append("provider_returned_no_usable_public_comments")
        if metric.views is None:
            warnings.append("public_view_count_is_missing")
        return AccountCollectionBatch(
            provider=CollectionProviderKind.TIKHUB,
            profile_url=url,
            platform_account_id=platform_account_id,
            fetched_at=fetched_at,
            account=account,
            videos=[video],
            metrics=[metric],
            comments=comments,
            raw_pages=pages,
            warnings=warnings,
        )


def build_account_provider(
    kind: CollectionProviderKind,
    *,
    executor: HttpExecutor | None = None,
) -> AccountCollectionProvider:
    """Build one account provider behind a stable CLI-facing factory."""

    if kind == CollectionProviderKind.MEDIACRAWLER:
        from video_account_distiller.collection.mediacrawler import (
            MediaCrawlerAccountProvider,
        )

        return MediaCrawlerAccountProvider()
    if kind == CollectionProviderKind.TIKHUB:
        return TikHubAccountProvider(executor=executor)
    raise DistillerError(
        ErrorCode.PLATFORM_UNSUPPORTED,
        f"Unsupported account collection provider: {kind.value}",
    )


def build_collection_request(
    *,
    profile_url: str,
    count: int | None = None,
    sort: CollectionSort,
    provider: CollectionProviderKind,
    comments_per_video: int = 0,
    comment_video_limit: int = 3,
) -> AccountCollectionRequest:
    """Convert validation failures into a stable public error contract."""

    try:
        return AccountCollectionRequest(
            profile_url=profile_url,
            count=count,
            sort=sort,
            provider=provider,
            comments_per_video=comments_per_video,
            comment_video_limit=comment_video_limit,
        )
    except ValidationError as exc:
        raise DistillerError(
            ErrorCode.PROFILE_URL_INVALID,
            "Invalid Douyin account homepage request",
            details={"reason": str(exc.errors(include_url=False)[0]["msg"])},
        ) from exc
