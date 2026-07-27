from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from video_account_distiller.collection import build_collection_request
from video_account_distiller.collection.providers import _map_post
from video_account_distiller.errors import DistillerError, ErrorCode
from video_account_distiller.models import AccountCollectionRequest


@pytest.mark.parametrize(
    "url",
    [
        "https://www.douyin.com/user/MS4wLjAB",
        "https://v.douyin.com/ABC123/",
        "https://douyin.com/user/demo",
    ],
)
def test_collection_request_accepts_only_douyin_https_hosts(url: str) -> None:
    request = AccountCollectionRequest(profile_url=url)

    assert request.profile_url == url
    assert request.count is None


def test_collection_request_uses_optional_count_only_as_a_limit() -> None:
    request = AccountCollectionRequest(
        profile_url="https://www.douyin.com/user/demo",
        count=20_000,
    )

    assert request.count == 20_000
    with pytest.raises(ValidationError):
        AccountCollectionRequest(
            profile_url="https://www.douyin.com/user/demo",
            count=0,
        )
    with pytest.raises(ValidationError):
        AccountCollectionRequest(
            profile_url="https://www.douyin.com/user/demo",
            count=20_001,
        )


@pytest.mark.parametrize(
    "url",
    [
        "http://www.douyin.com/user/demo",
        "https://douyin.com.evil.example/user/demo",
        "https://example.com/user/demo",
        "file:///etc/passwd",
        "https://user:pass@douyin.com/user/demo",
        "https://douyin.com:8443/user/demo",
    ],
)
def test_collection_request_rejects_non_douyin_or_unsafe_urls(url: str) -> None:
    with pytest.raises(ValidationError):
        AccountCollectionRequest(profile_url=url)


def test_collection_request_builder_exposes_stable_error() -> None:
    with pytest.raises(DistillerError) as captured:
        build_collection_request(
            profile_url="https://example.com/not-douyin",
            count=10,
            sort="latest",  # type: ignore[arg-type]
            provider="tikhub",  # type: ignore[arg-type]
        )

    assert captured.value.code == ErrorCode.PROFILE_URL_INVALID


def test_collection_request_bounds_optional_comment_sampling() -> None:
    request = AccountCollectionRequest(
        profile_url="https://www.douyin.com/user/demo",
        comments_per_video=20,
        comment_video_limit=10,
    )

    assert request.comments_per_video == 20
    assert request.comment_video_limit == 10
    with pytest.raises(ValidationError):
        AccountCollectionRequest(
            profile_url="https://www.douyin.com/user/demo",
            comments_per_video=21,
        )
    with pytest.raises(ValidationError):
        AccountCollectionRequest(
            profile_url="https://www.douyin.com/user/demo",
            comment_video_limit=11,
        )


def test_public_zero_views_with_positive_interactions_are_treated_as_missing() -> None:
    mapped = _map_post(
        {
            "aweme_id": "video-with-hidden-views",
            "statistics": {
                "play_count": 0,
                "digg_count": 100,
                "comment_count": 5,
                "share_count": 2,
                "collect_count": 3,
            },
        },
        platform_account_id="account",
        fetched_at=datetime(2026, 7, 23, tzinfo=UTC),
        metric_source="fixture",
    )

    assert mapped is not None
    assert mapped[1].views is None
    assert mapped[1].likes == 100
