"""Controlled MediaCrawler runner used by the provider subprocess.

This file runs inside MediaCrawler's pinned uv environment. It deliberately does
not invoke MediaCrawler's login, proxy, stealth, or CAPTCHA automation. A visible
dedicated browser profile is opened and authentication, when needed, remains a
manual user action.
"""

from __future__ import annotations

import argparse
import asyncio
import importlib
import json
import sys
import time
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

BRIDGE_SCHEMA_VERSION = "1.0"
DOUYIN_HOME = "https://www.douyin.com/"
DEFAULT_HOMEPAGE_PAGE_SAFETY_LIMIT = 1000
DEFAULT_HOMEPAGE_VIDEO_SAFETY_LIMIT = 20_000


class BridgeFailure(Exception):
    """Expected bridge failure serialized for the parent provider."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def _write_payload(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    temporary.replace(path)


def _write_error(path: Path, code: str, message: str) -> None:
    _write_payload(
        path,
        {
            "schema_version": BRIDGE_SCHEMA_VERSION,
            "ok": False,
            "error_code": code,
            "message": message,
        },
    )


def _mapping(value: object) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    return {str(key): item for key, item in value.items()}


def _list_of_mappings(value: object) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [_mapping(item) for item in value if isinstance(item, dict)]


def _integer(value: object) -> int:
    if isinstance(value, bool):
        return 0
    if not isinstance(value, (int, float, str)):
        return 0
    try:
        return max(int(value), 0)
    except (TypeError, ValueError):
        return 0


def _video_score(item: dict[str, Any]) -> tuple[int, int, int, int]:
    statistics = _mapping(item.get("statistics"))
    return (
        _integer(statistics.get("play_count")),
        _integer(statistics.get("digg_count")),
        _integer(statistics.get("comment_count")),
        _integer(item.get("create_time")),
    )


def _video_id(item: dict[str, Any]) -> str | None:
    value = item.get("aweme_id") or item.get("item_id") or item.get("id")
    if value is None:
        return None
    normalized = str(value).strip()
    return normalized or None


def _load_mediacrawler(media_root: Path) -> dict[str, Any]:
    if str(media_root) not in sys.path:
        sys.path.insert(0, str(media_root))
    try:
        config = importlib.import_module("config")
        utils = importlib.import_module("tools.utils")
        client_module = importlib.import_module("media_platform.douyin.client")
        help_module = importlib.import_module("media_platform.douyin.help")
        playwright_module = importlib.import_module("playwright.async_api")
    except Exception as exc:
        raise BridgeFailure(
            "dependency_error",
            f"MediaCrawler runtime could not be imported: {type(exc).__name__}: {exc}",
        ) from exc
    config_values = vars(config)
    config_values["ENABLE_IP_PROXY"] = False
    config_values["DISABLE_SSL_VERIFY"] = False
    return {
        "utils": utils,
        "client_class": client_module.DouYinClient,
        "parse_creator": help_module.parse_creator_info_from_url,
        "async_playwright": playwright_module.async_playwright,
    }


async def _wait_for_manual_login(
    client: Any,
    browser_context: Any,
    *,
    timeout_seconds: int,
) -> None:
    deadline = time.monotonic() + timeout_seconds
    announced = False
    while time.monotonic() < deadline:
        try:
            authenticated = await client.pong(browser_context=browser_context)
        except Exception:
            # Login and challenge pages may navigate between the local-storage
            # check and Playwright evaluation. Treat that as transient while
            # the manual-authentication window remains open.
            authenticated = False
        if authenticated:
            await client.update_cookies(
                browser_context=browser_context,
                urls=client.cookie_urls,
            )
            return
        if not announced:
            print(
                "MediaCrawler: 请在打开的浏览器窗口中手动登录抖音；如出现验证，请由用户手动完成。",
                file=sys.stderr,
                flush=True,
            )
            announced = True
        await asyncio.sleep(2)
    raise BridgeFailure(
        "login_required",
        "Douyin login was not completed in the visible browser before the timeout.",
    )


async def _collect_post_summaries(
    client: Any,
    *,
    sec_user_id: str,
    target_count: int | None,
    request_interval: float,
    raw_pages: list[dict[str, Any]],
    warnings: list[str],
    max_pages: int = DEFAULT_HOMEPAGE_PAGE_SAFETY_LIMIT,
    max_videos: int = DEFAULT_HOMEPAGE_VIDEO_SAFETY_LIMIT,
) -> list[dict[str, Any]]:
    cursor: str | int = ""
    seen_cursors: set[str] = set()
    seen_videos: set[str] = set()
    summaries: list[dict[str, Any]] = []
    page_count = 0
    while target_count is None or len(summaries) < target_count:
        if page_count >= max_pages:
            warnings.append("homepage_page_safety_limit_reached")
            break
        response = _mapping(await client.get_user_aweme_posts(sec_user_id, cursor))
        page_count += 1
        raw_pages.append(
            {
                "endpoint": "/aweme/v1/web/aweme/post/",
                "payload": response,
            }
        )
        items = _list_of_mappings(response.get("aweme_list"))
        if not items:
            break
        for item in items:
            item_id = _video_id(item)
            if item_id is None or item_id in seen_videos:
                continue
            seen_videos.add(item_id)
            summaries.append(item)
            if (target_count is not None and len(summaries) >= target_count) or len(
                summaries
            ) >= max_videos:
                break
        if len(summaries) >= max_videos:
            if target_count is None or len(summaries) < target_count:
                warnings.append("homepage_video_safety_limit_reached")
            break
        has_more = _integer(response.get("has_more")) == 1
        next_cursor = response.get("max_cursor")
        cursor_key = str(next_cursor)
        if not has_more or next_cursor is None or cursor_key in seen_cursors:
            break
        seen_cursors.add(cursor_key)
        cursor = next_cursor
        await asyncio.sleep(request_interval)
    return summaries


async def _collect_video_details(
    client: Any,
    summaries: Sequence[dict[str, Any]],
    *,
    request_interval: float,
    raw_pages: list[dict[str, Any]],
    warnings: list[str],
) -> list[dict[str, Any]]:
    details: list[dict[str, Any]] = []
    for summary in summaries:
        item_id = _video_id(summary)
        if item_id is None:
            continue
        try:
            detail = _mapping(await client.get_video_by_id(item_id))
        except Exception as exc:
            warnings.append(f"video_detail_degraded:{item_id}:{type(exc).__name__}")
            detail = {}
        if detail:
            raw_pages.append(
                {
                    "endpoint": f"/aweme/v1/web/aweme/detail/?aweme_id={item_id}",
                    "payload": detail,
                }
            )
            details.append(detail)
        else:
            details.append(summary)
        await asyncio.sleep(request_interval)
    return details


async def _collect_comments(
    client: Any,
    videos: Sequence[dict[str, Any]],
    *,
    comments_per_video: int,
    comment_video_limit: int,
    request_interval: float,
    raw_pages: list[dict[str, Any]],
    warnings: list[str],
) -> dict[str, list[dict[str, Any]]]:
    if comments_per_video <= 0:
        return {}
    targets = sorted(
        videos,
        key=lambda item: (
            -_integer(_mapping(item.get("statistics")).get("comment_count")),
            _video_id(item) or "",
        ),
    )[:comment_video_limit]
    result: dict[str, list[dict[str, Any]]] = {}
    for target in targets:
        item_id = _video_id(target)
        if item_id is None:
            continue
        cursor = 0
        seen_cursors: set[int] = set()
        accepted: list[dict[str, Any]] = []
        try:
            while len(accepted) < comments_per_video:
                response = _mapping(await client.get_aweme_comments(item_id, cursor))
                raw_pages.append(
                    {
                        "endpoint": (
                            f"/aweme/v1/web/comment/list/?aweme_id={item_id}&cursor={cursor}"
                        ),
                        "payload": response,
                    }
                )
                items = _list_of_mappings(response.get("comments"))
                if not items:
                    break
                remaining = comments_per_video - len(accepted)
                accepted.extend(items[:remaining])
                has_more = _integer(response.get("has_more")) == 1
                next_cursor = _integer(response.get("cursor"))
                if not has_more or next_cursor in seen_cursors or next_cursor == cursor:
                    break
                seen_cursors.add(next_cursor)
                cursor = next_cursor
                await asyncio.sleep(request_interval)
        except Exception as exc:
            warnings.append(f"comment_collection_degraded:{item_id}:{type(exc).__name__}")
        result[item_id] = accepted
    return result


def _resolve_douyin_short_url(url: str) -> str:
    """Follow v.douyin.com short link redirects and extract the full profile URL."""
    host = (urlparse(url).hostname or "").casefold()
    if host not in ("v.douyin.com", "v.douyin.com."):
        return url
    try:
        req = Request(url, method="HEAD", headers={"User-Agent": "Mozilla/5.0"})
        with urlopen(req, timeout=15) as resp:
            resolved = resp.url
        if resolved and resolved != url:
            # iesdouyin.com/share/user/... contains sec_uid in the path or query
            parsed = urlparse(resolved)
            if "iesdouyin.com" in (parsed.hostname or ""):
                # Extract sec_uid from path: /share/user/{sec_uid}
                path_match = __import__("re").search(r"/share/user/([^/?]+)", resolved)
                if path_match:
                    return f"https://www.douyin.com/user/{path_match.group(1)}"
                # Fallback: extract sec_uid from query params
                qs = __import__("urllib.parse").parse_qs(parsed.query)
                if "sec_uid" in qs:
                    sec_uid = qs["sec_uid"][0]
                    if isinstance(sec_uid, str):
                        return f"https://www.douyin.com/user/{sec_uid}"
                return str(resolved)
            if "douyin.com" in (parsed.hostname or ""):
                return str(resolved)
    except (HTTPError, URLError, TimeoutError, OSError):
        pass
    return url


async def _run(args: argparse.Namespace) -> dict[str, Any]:
    media_root = Path(args.media_root).resolve()
    runtime = _load_mediacrawler(media_root)
    browser_profile = Path(args.browser_profile).expanduser().resolve()
    browser_profile.mkdir(parents=True, exist_ok=True)
    fetched_at = datetime.now(UTC)
    raw_pages: list[dict[str, Any]] = []
    warnings: list[str] = []
    parse_creator = runtime["parse_creator"]
    profile_url = _resolve_douyin_short_url(args.profile_url)
    try:
        sec_user_id = str(parse_creator(profile_url).sec_user_id)
    except Exception as exc:
        raise BridgeFailure("profile_invalid", str(exc)) from exc

    try:
        async with runtime["async_playwright"]() as playwright:
            browser_context = await playwright.chromium.launch_persistent_context(
                user_data_dir=str(browser_profile),
                channel=args.browser_channel,
                headless=False,
                accept_downloads=False,
                locale="zh-CN",
                viewport={"width": 1440, "height": 900},
            )
            try:
                page = browser_context.pages[0] if browser_context.pages else None
                if page is None:
                    page = await browser_context.new_page()
                await page.goto(
                    DOUYIN_HOME,
                    wait_until="domcontentloaded",
                    timeout=60_000,
                )
                cookie_urls = [
                    "https://www.douyin.com",
                    "https://www.toutiao.com",
                ]
                cookie_str, cookie_dict = await runtime["utils"].convert_browser_context_cookies(
                    browser_context,
                    urls=cookie_urls,
                )
                client = runtime["client_class"](
                    proxy=None,
                    headers={
                        "User-Agent": await page.evaluate("() => navigator.userAgent"),
                        "Cookie": cookie_str,
                        "Host": "www.douyin.com",
                        "Origin": "https://www.douyin.com/",
                        "Referer": "https://www.douyin.com/",
                        "Content-Type": "application/json;charset=UTF-8",
                    },
                    playwright_page=page,
                    cookie_dict=cookie_dict,
                    proxy_ip_pool=None,
                )
                await _wait_for_manual_login(
                    client,
                    browser_context,
                    timeout_seconds=args.login_timeout,
                )
                profile = _mapping(await client.get_user_info(sec_user_id))
                if not profile:
                    raise BridgeFailure(
                        "data_fetch_error",
                        "MediaCrawler returned no public account profile.",
                    )
                raw_pages.append(
                    {
                        "endpoint": (
                            f"/aweme/v1/web/user/profile/other/?sec_user_id={sec_user_id}"
                        ),
                        "payload": profile,
                    }
                )
                summary_target = (
                    min(max(args.count * 3, args.count), args.max_videos)
                    if args.count is not None and args.sort == "popular"
                    else args.count
                )
                summaries = await _collect_post_summaries(
                    client,
                    sec_user_id=sec_user_id,
                    target_count=summary_target,
                    request_interval=args.request_interval,
                    raw_pages=raw_pages,
                    warnings=warnings,
                    max_pages=args.max_pages,
                    max_videos=args.max_videos,
                )
                details = await _collect_video_details(
                    client,
                    summaries,
                    request_interval=args.request_interval,
                    raw_pages=raw_pages,
                    warnings=warnings,
                )
                if args.sort == "popular":
                    details.sort(key=_video_score, reverse=True)
                    if args.count is not None:
                        warnings.append("popular_sort_is_within_bounded_recent_pool")
                else:
                    details.sort(
                        key=lambda item: _integer(item.get("create_time")),
                        reverse=True,
                    )
                selected = details if args.count is None else details[: args.count]
                comments = await _collect_comments(
                    client,
                    selected,
                    comments_per_video=args.comments_per_video,
                    comment_video_limit=args.comment_video_limit,
                    request_interval=args.request_interval,
                    raw_pages=raw_pages,
                    warnings=warnings,
                )
            finally:
                await browser_context.close()
    except BridgeFailure:
        raise
    except Exception as exc:
        raise BridgeFailure(
            "browser_or_collection_error",
            f"{type(exc).__name__}: {exc}",
        ) from exc

    if args.count is not None and len(selected) < args.count:
        warnings.append("provider_returned_fewer_videos_than_requested")
    return {
        "schema_version": BRIDGE_SCHEMA_VERSION,
        "ok": True,
        "fetched_at": fetched_at.isoformat(),
        "profile_url": args.profile_url,
        "platform_account_id": sec_user_id,
        "profile": profile,
        "videos": selected,
        "comments": comments,
        "raw_pages": raw_pages,
        "warnings": warnings,
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run a controlled MediaCrawler Douyin collection.")
    parser.add_argument("--media-root", required=True)
    parser.add_argument("--profile-url", required=True)
    parser.add_argument("--count", type=int)
    parser.add_argument("--sort", choices=("latest", "popular"), required=True)
    parser.add_argument(
        "--max-pages",
        type=int,
        default=DEFAULT_HOMEPAGE_PAGE_SAFETY_LIMIT,
    )
    parser.add_argument(
        "--max-videos",
        type=int,
        default=DEFAULT_HOMEPAGE_VIDEO_SAFETY_LIMIT,
    )
    parser.add_argument("--comments-per-video", type=int, required=True)
    parser.add_argument("--comment-video-limit", type=int, required=True)
    parser.add_argument("--browser-profile", required=True)
    parser.add_argument("--browser-channel", default="chrome")
    parser.add_argument("--login-timeout", type=int, default=180)
    parser.add_argument("--request-interval", type=float, default=1.0)
    parser.add_argument("--output", required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    output_path = Path(args.output).resolve()
    try:
        payload = asyncio.run(_run(args))
    except BridgeFailure as exc:
        print(f"MediaCrawler: {exc.message}", file=sys.stderr, flush=True)
        _write_error(output_path, exc.code, exc.message)
        return 2
    except Exception as exc:
        message = f"Unexpected bridge failure: {type(exc).__name__}: {exc}"
        print(f"MediaCrawler: {message}", file=sys.stderr, flush=True)
        _write_error(output_path, "internal_error", message)
        return 3
    _write_payload(output_path, payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
