from __future__ import annotations

import json
from pathlib import Path

import pytest

from video_account_distiller.adapters.collaboration import HttpResponse
from video_account_distiller.collection import AccountCollectionService, TikHubAccountProvider
from video_account_distiller.collection.mediacrawler import (
    MediaCrawlerAccountProvider,
    ProcessResult,
)
from video_account_distiller.collection.providers import resolve_video_id_from_url
from video_account_distiller.errors import DistillerError, ErrorCode
from video_account_distiller.models import CollectionProviderKind
from video_account_distiller.storage.parquet import read_models
from video_account_distiller.storage.project import ProjectLayout
from video_account_distiller.utils.ids import stable_id


class FakeHttpExecutor:
    def __init__(self, responses: list[HttpResponse]) -> None:
        self.responses = responses
        self.requests: list[dict[str, object]] = []

    def send(
        self,
        *,
        method: str,
        url: str,
        headers: dict[str, str],
        body: bytes | None,
        timeout: int,
    ) -> HttpResponse:
        self.requests.append(
            {
                "method": method,
                "url": url,
                "headers": headers,
                "body": body,
                "timeout": timeout,
            }
        )
        return self.responses.pop(0)


class FixtureProcessExecutor:
    def __init__(self, payload: dict[str, object]) -> None:
        self.payload = payload
        self.commands: list[list[str]] = []

    def run(
        self,
        command: list[str],
        *,
        cwd: Path,
        timeout_seconds: int,
    ) -> ProcessResult:
        del cwd, timeout_seconds
        self.commands.append(command)
        output = Path(command[command.index("--output") + 1])
        output.write_text(
            json.dumps(self.payload, ensure_ascii=False),
            encoding="utf-8",
        )
        return ProcessResult(returncode=0)


def _json_response(payload: dict[str, object]) -> HttpResponse:
    return HttpResponse(
        status=200,
        body=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
    )


def _detail_payload() -> dict[str, object]:
    return {
        "code": 0,
        "data": {
            "aweme_id": "7700000000000000001",
            "desc": "一条值得拆解的酒店视频",
            "create_time": 1750000000,
            "duration": 18200,
            "share_url": "https://www.douyin.com/video/7700000000000000001",
            "author": {
                "sec_uid": "MS4wLjABAAAA-single-video-owner",
                "unique_id": "single_owner",
                "nickname": "单视频博主",
                "follower_count": 5200,
                "aweme_count": 3,
            },
            "video": {
                "play_addr": {
                    "url_list": ["https://v11-weba.douyinvod.com/obj/single-video.mp4?sig=fixture"]
                }
            },
            "statistics": {
                "play_count": 88000,
                "digg_count": 1200,
                "comment_count": 45,
                "share_count": 60,
                "collect_count": 90,
            },
        },
    }


def _comments_payload() -> dict[str, object]:
    return {
        "code": 0,
        "data": {
            "comments": [
                {
                    "cid": "comment-1",
                    "text": "这条干货很有用",
                    "user": {"sec_uid": "user-1"},
                    "digg_count": 3,
                }
            ]
        },
    }


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("https://www.douyin.com/video/7300000000000000001", "7300000000000000001"),
        ("https://www.douyin.com/note/7300000000000000002", "7300000000000000002"),
        (
            "https://www.douyin.com/video/7300000000000000003?from_tab_name=main",
            "7300000000000000003",
        ),
        (
            "https://www.douyin.com/?modal_id=7300000000000000004",
            "7300000000000000004",
        ),
        (
            "https://www.douyin.com/discover?modal_id=7300000000000000005",
            "7300000000000000005",
        ),
    ],
)
def test_resolve_video_id_from_url_supports_standard_formats(url: str, expected: str) -> None:
    assert resolve_video_id_from_url(url) == expected


@pytest.mark.parametrize(
    "url",
    [
        "https://v.douyin.com/abc123/",
        "https://www.douyin.com/user/MS4wLjABAAAA-homepage",
        "not-a-url",
    ],
)
def test_resolve_video_id_rejects_short_links_and_homepages(url: str) -> None:
    with pytest.raises(DistillerError) as exc_info:
        resolve_video_id_from_url(url)
    assert exc_info.value.code is ErrorCode.PROFILE_URL_INVALID


def test_tikhub_collect_video_maps_single_detail_and_comments(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("TIKHUB_API_KEY", "test-token-never-serialize")
    executor = FakeHttpExecutor(
        [
            _json_response(_detail_payload()),
            _json_response(_comments_payload()),
        ]
    )
    provider = TikHubAccountProvider(executor=executor, sleep=lambda _: None)

    batch = provider.collect_video(
        "https://www.douyin.com/video/7700000000000000001",
        comments_per_video=10,
    )

    assert len(batch.videos) == 1
    video = batch.videos[0]
    assert video.platform_video_id == "7700000000000000001"
    assert video.title == "一条值得拆解的酒店视频"
    assert video.duration_seconds == 18.2
    assert batch.metrics[0].views == 88000
    assert batch.metrics[0].metric_source == "tikhub:douyin-fetch-one-video"
    assert batch.account.platform_account_id == "MS4wLjABAAAA-single-video-owner"
    assert batch.account.display_name == "单视频博主"
    assert len(batch.comments) == 1
    assert batch.comments[0].video_id == "7700000000000000001"
    assert "fetch_one_video" in str(executor.requests[0]["url"])
    assert "aweme_id=7700000000000000001" in str(executor.requests[0]["url"])
    assert "fetch_video_comments" in str(executor.requests[1]["url"])


def test_tikhub_collect_video_uses_placeholder_account_without_author(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("TIKHUB_API_KEY", "test-token")
    payload = _detail_payload()
    payload["data"].pop("author")  # type: ignore[attr-defined]
    executor = FakeHttpExecutor([_json_response(payload)])
    provider = TikHubAccountProvider(executor=executor, sleep=lambda _: None)

    batch = provider.collect_video("https://www.douyin.com/video/7700000000000000001")

    assert batch.platform_account_id == "video-owner-7700000000000000001"
    assert batch.account.display_name == "单视频采集"
    assert len(batch.videos) == 1


def test_analyze_video_url_imports_single_video_into_kernel(
    project: ProjectLayout,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("TIKHUB_API_KEY", "test-token")
    executor = FakeHttpExecutor([_json_response(_detail_payload())])
    provider = TikHubAccountProvider(executor=executor, sleep=lambda _: None)
    service = AccountCollectionService(project, provider)

    result = service.analyze_video_url(
        url="https://www.douyin.com/video/7700000000000000001",
        confirm_provider_cost=True,
    )

    assert result["ok"] is True
    assert result["platform_video_id"] == "7700000000000000001"
    expected_account = stable_id("acc_", "douyin", "MS4wLjABAAAA-single-video-owner")
    assert result["account_id"] == expected_account
    assert result["video_id"] == stable_id("vid_", "douyin", "7700000000000000001")
    assert result["collection"]["videos"] == 1
    assert "provider-batch.json" in result["collection"]["raw_artifact"]
    assert result["imports"]["accounts"]["already_imported"] is False

    from video_account_distiller.models import Video

    videos = read_models(project.normalized_dir / "videos.parquet", Video)
    assert [item.platform_video_id for item in videos] == ["7700000000000000001"]
    assert videos[0].title == "一条值得拆解的酒店视频"


def test_analyze_video_url_requires_cost_confirmation(project: ProjectLayout) -> None:
    service = AccountCollectionService(project, TikHubAccountProvider(sleep=lambda _: None))
    with pytest.raises(DistillerError) as exc_info:
        service.analyze_video_url(
            url="https://www.douyin.com/video/7700000000000000001",
            confirm_provider_cost=False,
        )
    assert exc_info.value.code is ErrorCode.PROVIDER_COST_CONFIRMATION_REQUIRED


def test_analyze_video_url_dry_run_returns_plan_without_network(project: ProjectLayout) -> None:
    service = AccountCollectionService(project, TikHubAccountProvider(sleep=lambda _: None))
    result = service.analyze_video_url(
        url="https://www.douyin.com/video/7700000000000000001",
        confirm_provider_cost=True,
        dry_run=True,
    )
    assert result["dry_run"] is True
    assert result["url"].endswith("7700000000000000001")


def _mediacrawler_runtime(tmp_path: Path) -> tuple[Path, Path]:
    home = tmp_path / "MediaCrawler"
    for relative in (
        "pyproject.toml",
        "uv.lock",
        "LICENSE",
        "cache/__init__.py",
        "cache/cache_factory.py",
        "media_platform/douyin/client.py",
    ):
        path = home / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("fixture", encoding="utf-8")
    bridge = tmp_path / "bridge.py"
    bridge.write_text("# fixture bridge", encoding="utf-8")
    return home, bridge


def _mediacrawler_video_payload() -> dict[str, object]:
    return {
        "schema_version": "1.0",
        "ok": True,
        "fetched_at": "2026-01-01T00:00:00Z",
        "profile_url": "https://www.douyin.com/video/7700000000000000001",
        "platform_account_id": "MS4wLjABAAAA-video-owner",
        "profile": {
            "sec_uid": "MS4wLjABAAAA-video-owner",
            "unique_id": "video_owner",
            "nickname": "单视频博主",
            "follower_count": 100,
            "aweme_count": 2,
        },
        "videos": [
            {
                "aweme_id": "7700000000000000001",
                "desc": "一条值得拆解的酒店视频",
                "create_time": 1750000000,
                "duration": 18200,
                "share_url": "https://www.douyin.com/video/7700000000000000001",
                "statistics": {
                    "play_count": 88000,
                    "digg_count": 1200,
                    "comment_count": 45,
                    "share_count": 60,
                    "collect_count": 90,
                },
            }
        ],
        "comments": {},
        "raw_pages": [
            {
                "endpoint": "/aweme/v1/web/aweme/detail/?aweme_id=7700000000000000001",
                "payload": {"aweme_id": "7700000000000000001"},
            }
        ],
        "warnings": [],
    }


def test_mediacrawler_collect_video_maps_single_detail(tmp_path: Path) -> None:
    home, bridge = _mediacrawler_runtime(tmp_path)
    executor = FixtureProcessExecutor(_mediacrawler_video_payload())
    provider = MediaCrawlerAccountProvider(
        home=home,
        bridge_script=bridge,
        uv_executable="uv",
        executor=executor,
    )

    batch = provider.collect_video(
        "https://www.douyin.com/video/7700000000000000001",
        comments_per_video=0,
    )

    assert batch.provider == CollectionProviderKind.MEDIACRAWLER
    assert len(batch.videos) == 1
    assert batch.videos[0].platform_video_id == "7700000000000000001"
    assert batch.videos[0].title == "一条值得拆解的酒店视频"
    assert batch.metrics[0].views == 88000
    assert batch.account.platform_account_id == "MS4wLjABAAAA-video-owner"
    assert batch.account.display_name == "单视频博主"
    assert "--video-url" in executor.commands[0]
    assert "7700000000000000001" in str(executor.commands[0])
    assert "--max-videos" in executor.commands[0]
    assert "--profile-url" not in executor.commands[0]


def test_analyze_video_url_works_with_mediacrawler_provider(
    project: ProjectLayout,
    tmp_path: Path,
) -> None:
    home, bridge = _mediacrawler_runtime(tmp_path)
    provider = MediaCrawlerAccountProvider(
        home=home,
        bridge_script=bridge,
        uv_executable="uv",
        executor=FixtureProcessExecutor(_mediacrawler_video_payload()),
    )
    service = AccountCollectionService(project, provider)

    result = service.analyze_video_url(
        url="https://www.douyin.com/video/7700000000000000001",
        provider=CollectionProviderKind.MEDIACRAWLER,
        confirm_provider_cost=True,
    )

    assert result["ok"] is True
    assert result["provider"] == "mediacrawler"
    expected_account = stable_id("acc_", "douyin", "MS4wLjABAAAA-video-owner")
    assert result["account_id"] == expected_account
    assert result["video_id"] == stable_id("vid_", "douyin", "7700000000000000001")

    from video_account_distiller.models import Video

    videos = read_models(project.normalized_dir / "videos.parquet", Video)
    assert [item.platform_video_id for item in videos] == ["7700000000000000001"]
