from __future__ import annotations

import json
from pathlib import Path

import pytest

from video_account_distiller.adapters.collaboration import HttpResponse
from video_account_distiller.collection import TikHubAccountProvider
from video_account_distiller.collection import providers as provider_module
from video_account_distiller.errors import DistillerError, ErrorCode
from video_account_distiller.models import (
    AccountCollectionRequest,
    CollectionProviderKind,
    CollectionSort,
    RetryPolicy,
)


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


def _response(path: Path) -> HttpResponse:
    return HttpResponse(status=200, body=path.read_bytes())


def test_tikhub_provider_maps_and_paginates_documented_responses(
    fixtures_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("TIKHUB_API_KEY", "test-token-never-serialize")
    monkeypatch.delenv("TIKHUB_DOUYIN_POSTS_MODE", raising=False)
    phase8 = fixtures_dir / "phase8"
    executor = FakeHttpExecutor(
        [
            _response(phase8 / "resolve.json"),
            _response(phase8 / "profile.json"),
            _response(phase8 / "posts-page-1.json"),
            _response(phase8 / "posts-page-2.json"),
            _response(phase8 / "comments-video-1.json"),
        ]
    )
    request = AccountCollectionRequest(
        profile_url="https://www.douyin.com/user/MS4wLjABAAAAhotel-demo",
        sort=CollectionSort.LATEST,
        provider=CollectionProviderKind.TIKHUB,
        comments_per_video=2,
        comment_video_limit=1,
    )

    result = TikHubAccountProvider(executor=executor, sleep=lambda _: None).collect(request)

    assert result.account.display_name == "示例酒店"
    assert result.account.follower_count_current == 12600
    assert [item.platform_video_id for item in result.videos] == [
        "7300000000000000001",
        "7300000000000000002",
        "7300000000000000003",
    ]
    assert result.videos[0].duration_seconds == 18.2
    assert result.videos[0].hashtags == ["酒店", "旅行"]
    assert result.metrics[0].views == 260000
    assert result.metrics[0].metric_source == "tikhub:douyin-web"
    assert "/api/v1/douyin/web/fetch_user_post_videos" in str(executor.requests[2]["url"])
    assert "filter_type=0" in str(executor.requests[2]["url"])
    assert "max_cursor=10" in str(executor.requests[3]["url"])
    assert "count=20" in str(executor.requests[2]["url"])
    assert len(result.comments) == 2
    assert result.comments[0].video_id == "7300000000000000001"
    assert result.comments[0].author_hash is not None
    assert result.comments[1].is_creator_reply is True
    assert "fetch_video_comments" in str(executor.requests[4]["url"])
    assert "aweme_id=7300000000000000001" in str(executor.requests[4]["url"])
    assert "count=2" in str(executor.requests[4]["url"])
    assert all(
        request_item["headers"]["Authorization"] == "Bearer test-token-never-serialize"  # type: ignore[index]
        for request_item in executor.requests
    )
    assert "test-token-never-serialize" not in json.dumps(
        result.model_dump(mode="json"),
        ensure_ascii=False,
    )
    assert "guest-private-id-1" not in json.dumps(
        [comment.model_dump(mode="json") for comment in result.comments],
        ensure_ascii=False,
    )


def test_tikhub_provider_can_opt_into_paid_app_posts_endpoint(
    fixtures_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("TIKHUB_API_KEY", "test-token")
    monkeypatch.setenv("TIKHUB_DOUYIN_POSTS_MODE", "app-v3")
    phase8 = fixtures_dir / "phase8"
    executor = FakeHttpExecutor(
        [
            _response(phase8 / "resolve.json"),
            _response(phase8 / "profile.json"),
            _response(phase8 / "posts-page-1.json"),
        ]
    )
    request = AccountCollectionRequest(
        profile_url="https://www.douyin.com/user/MS4wLjABAAAAhotel-demo",
        count=1,
        sort=CollectionSort.POPULAR,
        provider=CollectionProviderKind.TIKHUB,
        comments_per_video=0,
    )

    result = TikHubAccountProvider(
        executor=executor,
        sleep=lambda _: None,
    ).collect(request)

    assert result.metrics[0].metric_source == "tikhub:douyin-app-v3"
    assert "/api/v1/douyin/app/v3/fetch_user_post_videos" in str(executor.requests[2]["url"])
    assert "sort_type=1" in str(executor.requests[2]["url"])


def test_tikhub_full_homepage_mode_reports_video_safety_guard(
    fixtures_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("TIKHUB_API_KEY", "test-token")
    monkeypatch.setattr(provider_module, "HOMEPAGE_VIDEO_SAFETY_LIMIT", 2)
    phase8 = fixtures_dir / "phase8"
    executor = FakeHttpExecutor(
        [
            _response(phase8 / "resolve.json"),
            _response(phase8 / "profile.json"),
            _response(phase8 / "posts-page-1.json"),
        ]
    )
    request = AccountCollectionRequest(
        profile_url="https://www.douyin.com/user/MS4wLjABAAAAhotel-demo",
        provider=CollectionProviderKind.TIKHUB,
        comments_per_video=0,
    )

    result = TikHubAccountProvider(executor=executor, sleep=lambda _: None).collect(request)

    assert len(result.videos) == 2
    assert "homepage_video_safety_limit_reached" in result.warnings


def test_tikhub_provider_rejects_unknown_posts_api_mode() -> None:
    with pytest.raises(DistillerError) as captured:
        TikHubAccountProvider(
            executor=FakeHttpExecutor([]),
            posts_api_mode="unknown",
        )

    assert captured.value.code == ErrorCode.SCHEMA_INVALID


def test_tikhub_provider_maps_http_auth_and_rate_limit_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("TIKHUB_API_KEY", "test-token")
    request = AccountCollectionRequest(
        profile_url="https://www.douyin.com/user/demo",
        count=1,
        provider=CollectionProviderKind.TIKHUB,
    )
    auth = TikHubAccountProvider(
        executor=FakeHttpExecutor([HttpResponse(401, b"{}")]),
        sleep=lambda _: None,
    )
    with pytest.raises(DistillerError) as auth_error:
        auth.collect(request)
    assert auth_error.value.code == ErrorCode.ADAPTER_AUTH

    limited = TikHubAccountProvider(
        executor=FakeHttpExecutor([HttpResponse(429, b"{}")]),
        retry=RetryPolicy(max_retries=0),
        sleep=lambda _: None,
    )
    with pytest.raises(DistillerError) as rate_error:
        limited.collect(request)
    assert rate_error.value.code == ErrorCode.RATE_LIMIT


def test_optional_comment_failure_degrades_without_discarding_account_data(
    fixtures_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("TIKHUB_API_KEY", "test-token")
    phase8 = fixtures_dir / "phase8"
    executor = FakeHttpExecutor(
        [
            _response(phase8 / "resolve.json"),
            _response(phase8 / "profile.json"),
            _response(phase8 / "posts-page-1.json"),
            HttpResponse(403, b"{}"),
        ]
    )
    request = AccountCollectionRequest(
        profile_url="https://www.douyin.com/user/MS4wLjABAAAAhotel-demo",
        count=1,
        provider=CollectionProviderKind.TIKHUB,
        comments_per_video=20,
        comment_video_limit=1,
    )

    result = TikHubAccountProvider(executor=executor, sleep=lambda _: None).collect(request)

    assert len(result.videos) == 1
    assert result.comments == []
    assert "comment_collection_degraded:E_ADAPTER_AUTH" in result.warnings
    assert "provider_returned_no_usable_public_comments" in result.warnings


def test_tikhub_provider_requires_credential(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("TIKHUB_API_KEY", raising=False)
    provider = TikHubAccountProvider(executor=FakeHttpExecutor([]))

    with pytest.raises(DistillerError) as captured:
        provider.collect(
            AccountCollectionRequest(
                profile_url="https://www.douyin.com/user/demo",
                count=1,
                provider=CollectionProviderKind.TIKHUB,
            )
        )

    assert captured.value.code == ErrorCode.ADAPTER_AUTH
