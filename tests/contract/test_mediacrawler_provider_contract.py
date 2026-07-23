from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from video_account_distiller.collection.mediacrawler import (
    MediaCrawlerAccountProvider,
    ProcessResult,
)
from video_account_distiller.errors import DistillerError, ErrorCode
from video_account_distiller.models import (
    AccountCollectionRequest,
    CollectionProviderKind,
    CollectionSort,
)


class FixtureProcessExecutor:
    def __init__(self, fixture: Path, *, returncode: int = 0) -> None:
        self.fixture = fixture
        self.returncode = returncode
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
        shutil.copyfile(self.fixture, output)
        return ProcessResult(returncode=self.returncode)


def _runtime(tmp_path: Path) -> tuple[Path, Path]:
    home = tmp_path / "MediaCrawler"
    for relative in (
        "pyproject.toml",
        "uv.lock",
        "LICENSE",
        "media_platform/douyin/client.py",
    ):
        path = home / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("fixture", encoding="utf-8")
    bridge = tmp_path / "bridge.py"
    bridge.write_text("# fixture bridge", encoding="utf-8")
    return home, bridge


def test_mediacrawler_provider_maps_complete_bridge_payload(
    fixtures_dir: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("MEDIACRAWLER_BROWSER_CHANNEL", "msedge")
    home, bridge = _runtime(tmp_path)
    executor = FixtureProcessExecutor(
        fixtures_dir / "mediacrawler" / "bridge-success.json"
    )
    provider = MediaCrawlerAccountProvider(
        home=home,
        bridge_script=bridge,
        uv_executable="uv-fixture",
        executor=executor,
    )
    request = AccountCollectionRequest(
        profile_url=(
            "https://www.douyin.com/user/"
            "MS4wLjABAAAAmediacrawler-hotel"
        ),
        count=2,
        sort=CollectionSort.LATEST,
        provider=CollectionProviderKind.MEDIACRAWLER,
        comments_per_video=1,
        comment_video_limit=1,
    )

    result = provider.collect(request)

    assert result.provider == CollectionProviderKind.MEDIACRAWLER
    assert result.account.display_name == "酒店研究样本"
    assert result.account.follower_count_current == 16800
    assert [video.platform_video_id for video in result.videos] == [
        "7600000000000000001",
        "7600000000000000002",
    ]
    assert result.videos[0].duration_seconds == 21.8
    assert result.videos[0].hashtags == ["酒店", "旅行"]
    assert result.metrics[0].views == 280000
    assert result.metrics[0].saves == 3100
    assert result.metrics[0].metric_source is not None
    assert result.metrics[0].metric_source.startswith("mediacrawler:")
    assert len(result.comments) == 1
    assert result.comments[0].text == "亲子入住有没有儿童用品？"
    assert result.comments[0].author_hash is not None
    assert len(result.raw_pages) == 2
    assert "--frozen" in executor.commands[0]
    assert "--comments-per-video" in executor.commands[0]
    channel_index = executor.commands[0].index("--browser-channel")
    assert executor.commands[0][channel_index + 1] == "msedge"


def test_mediacrawler_provider_maps_manual_login_timeout_to_stable_error(
    fixtures_dir: Path,
    tmp_path: Path,
) -> None:
    home, bridge = _runtime(tmp_path)
    provider = MediaCrawlerAccountProvider(
        home=home,
        bridge_script=bridge,
        uv_executable="uv-fixture",
        executor=FixtureProcessExecutor(
            fixtures_dir / "mediacrawler" / "bridge-login-required.json",
            returncode=2,
        ),
    )

    with pytest.raises(DistillerError) as captured:
        provider.collect(
            AccountCollectionRequest(
                profile_url="https://www.douyin.com/user/demo",
                provider=CollectionProviderKind.MEDIACRAWLER,
            )
        )

    assert captured.value.code == ErrorCode.BROWSER_LOGIN_REQUIRED
    assert "visible browser" in captured.value.details["next"]


def test_mediacrawler_provider_requires_bundled_runtime(tmp_path: Path) -> None:
    provider = MediaCrawlerAccountProvider(
        home=tmp_path / "missing",
        bridge_script=tmp_path / "missing-bridge.py",
        uv_executable="uv-fixture",
        executor=FixtureProcessExecutor(tmp_path / "unused.json"),
    )

    with pytest.raises(DistillerError) as captured:
        provider.collect(
            AccountCollectionRequest(
                profile_url="https://www.douyin.com/user/demo",
                provider=CollectionProviderKind.MEDIACRAWLER,
            )
        )

    assert captured.value.code == ErrorCode.MEDIACRAWLER_UNAVAILABLE
    assert captured.value.details["missing"]


def test_mediacrawler_provider_rejects_invalid_login_timeout(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("MEDIACRAWLER_LOGIN_TIMEOUT_SECONDS", "not-an-integer")

    with pytest.raises(DistillerError) as captured:
        MediaCrawlerAccountProvider(
            home=tmp_path / "unused",
            bridge_script=tmp_path / "unused.py",
            uv_executable="uv-fixture",
        )

    assert captured.value.code == ErrorCode.SCHEMA_INVALID
