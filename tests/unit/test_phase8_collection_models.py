from __future__ import annotations

import pytest
from pydantic import ValidationError

from video_account_distiller.collection import build_collection_request
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
