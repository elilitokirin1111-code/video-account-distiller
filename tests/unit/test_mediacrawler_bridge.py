from __future__ import annotations

import asyncio
import importlib
import json
import time
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from video_account_distiller.collection import _mediacrawler_bridge as bridge


def _run_immediate(coroutine: Any) -> Any:
    try:
        coroutine.send(None)
    except StopIteration as completed:
        return completed.value
    raise AssertionError("fixture coroutine unexpectedly yielded")


class FakeDouyinClient:
    def __init__(self) -> None:
        self.post_calls: list[str | int] = []
        self.comment_calls: list[tuple[str, int]] = []

    async def get_user_aweme_posts(
        self,
        sec_user_id: str,
        cursor: str | int,
    ) -> dict[str, Any]:
        assert sec_user_id == "approved-account"
        self.post_calls.append(cursor)
        if cursor == "":
            return {
                "aweme_list": [
                    {
                        "aweme_id": "video-a",
                        "create_time": 3,
                        "statistics": {"comment_count": 5},
                    },
                    {
                        "aweme_id": "video-b",
                        "create_time": 2,
                        "statistics": {"comment_count": 20},
                    },
                ],
                "has_more": 1,
                "max_cursor": 18,
            }
        return {
            "aweme_list": [
                {"aweme_id": "video-a"},
                {
                    "aweme_id": "video-c",
                    "create_time": 1,
                    "statistics": {"comment_count": 1},
                },
            ],
            "has_more": 0,
            "max_cursor": 36,
        }

    async def get_video_by_id(self, item_id: str) -> dict[str, Any]:
        if item_id == "video-b":
            raise RuntimeError("detail unavailable")
        return {
            "aweme_id": item_id,
            "create_time": 3 if item_id == "video-a" else 1,
            "statistics": {"comment_count": 5 if item_id == "video-a" else 1},
        }

    async def get_aweme_comments(self, item_id: str, cursor: int) -> dict[str, Any]:
        self.comment_calls.append((item_id, cursor))
        if cursor == 0:
            return {
                "comments": [{"cid": "comment-1"}, {"cid": "comment-2"}],
                "has_more": 1,
                "cursor": 20,
            }
        return {
            "comments": [{"cid": "comment-3"}],
            "has_more": 0,
            "cursor": 40,
        }


class NavigatingLoginClient:
    cookie_urls = ["https://www.douyin.com"]

    def __init__(self) -> None:
        self.checks = 0
        self.updated = False

    async def pong(self, *, browser_context: object) -> bool:
        del browser_context
        self.checks += 1
        if self.checks == 1:
            raise RuntimeError("Execution context was destroyed because of navigation")
        return True

    async def update_cookies(
        self,
        *,
        browser_context: object,
        urls: list[str],
    ) -> None:
        del browser_context
        assert urls == self.cookie_urls
        self.updated = True


def test_manual_login_wait_tolerates_page_navigation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def no_sleep(_: float) -> None:
        return None

    monotonic_values = iter((0.0, 0.1, 0.2))
    monkeypatch.setattr(asyncio, "sleep", no_sleep)
    monkeypatch.setattr(time, "monotonic", lambda: next(monotonic_values))
    client = NavigatingLoginClient()

    _run_immediate(
        bridge._wait_for_manual_login(
            client,
            object(),
            timeout_seconds=30,
        )
    )

    assert client.checks == 2
    assert client.updated is True


def test_bridge_collectors_bound_pages_details_and_top_level_comments(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def no_sleep(_: float) -> None:
        return None

    monkeypatch.setattr(asyncio, "sleep", no_sleep)
    client = FakeDouyinClient()
    raw_pages: list[dict[str, Any]] = []
    warnings: list[str] = []

    summaries = _run_immediate(
        bridge._collect_post_summaries(
            client,
            sec_user_id="approved-account",
            target_count=3,
            request_interval=0,
            raw_pages=raw_pages,
        )
    )
    details = _run_immediate(
        bridge._collect_video_details(
            client,
            summaries,
            request_interval=0,
            raw_pages=raw_pages,
            warnings=warnings,
        )
    )
    comments = _run_immediate(
        bridge._collect_comments(
            client,
            details,
            comments_per_video=3,
            comment_video_limit=1,
            request_interval=0,
            raw_pages=raw_pages,
            warnings=warnings,
        )
    )

    assert [item["aweme_id"] for item in summaries] == [
        "video-a",
        "video-b",
        "video-c",
    ]
    assert client.post_calls == ["", 18]
    assert "video_detail_degraded:video-b:RuntimeError" in warnings
    assert list(comments) == ["video-b"]
    assert [item["cid"] for item in comments["video-b"]] == [
        "comment-1",
        "comment-2",
        "comment-3",
    ]
    assert client.comment_calls == [("video-b", 0), ("video-b", 20)]
    assert all("reply" not in str(page["endpoint"]) for page in raw_pages)


def test_bridge_loader_forces_proxy_and_ssl_bypass_flags_off(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = SimpleNamespace(ENABLE_IP_PROXY=True, DISABLE_SSL_VERIFY=True)
    utils = SimpleNamespace()
    client_module = SimpleNamespace(DouYinClient=object)
    help_module = SimpleNamespace(parse_creator_info_from_url=lambda value: value)
    playwright_module = SimpleNamespace(async_playwright=object)
    modules = {
        "config": config,
        "tools.utils": utils,
        "media_platform.douyin.client": client_module,
        "media_platform.douyin.help": help_module,
        "playwright.async_api": playwright_module,
    }
    monkeypatch.setattr(
        importlib,
        "import_module",
        lambda name: modules[name],
    )

    runtime = bridge._load_mediacrawler(tmp_path)

    assert config.ENABLE_IP_PROXY is False
    assert config.DISABLE_SSL_VERIFY is False
    assert runtime["utils"] is utils
    assert runtime["client_class"] is object


def test_bridge_main_writes_stable_error_envelope(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fail(_: object) -> dict[str, Any]:
        raise bridge.BridgeFailure("login_required", "manual login timed out")

    monkeypatch.setattr(bridge, "_run", fail)
    monkeypatch.setattr(asyncio, "run", _run_immediate)
    output = tmp_path / "bridge-error.json"

    exit_code = bridge.main(
        [
            "--media-root",
            str(tmp_path),
            "--profile-url",
            "https://www.douyin.com/user/demo",
            "--count",
            "10",
            "--sort",
            "latest",
            "--comments-per-video",
            "10",
            "--comment-video-limit",
            "3",
            "--browser-profile",
            str(tmp_path / "profile"),
            "--output",
            str(output),
        ]
    )

    payload = json.loads(output.read_text(encoding="utf-8"))
    assert exit_code == 2
    assert payload == {
        "schema_version": "1.0",
        "ok": False,
        "error_code": "login_required",
        "message": "manual login timed out",
    }
