from __future__ import annotations

import pytest

from video_account_distiller.media.enrichment import _validated_media_url


@pytest.mark.parametrize(
    "url",
    [
        "https://v11-weba.douyinvod.com/video.mp4?token=opaque",
        "https://www.douyin.com/aweme/v1/play/?video_id=opaque",
    ],
)
def test_media_source_accepts_only_approved_https_douyin_hosts(url: str) -> None:
    _, host = _validated_media_url(url)
    assert host.endswith((".douyinvod.com", ".douyin.com"))


@pytest.mark.parametrize(
    "url",
    [
        "http://v11-weba.douyinvod.com/video.mp4",
        "https://example.com/video.mp4",
        "https://user:pass@www.douyin.com/video.mp4",
        "https://www.douyin.com:8443/video.mp4",
    ],
)
def test_media_source_rejects_unapproved_or_credentialed_urls(url: str) -> None:
    with pytest.raises(ValueError):
        _validated_media_url(url)
