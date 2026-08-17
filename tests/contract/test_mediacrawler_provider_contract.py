from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from video_account_distiller.collection.mediacrawler import (
    MediaCrawlerAccountProvider,
    ProcessResult,
    SubprocessExecutor,
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


class TransientWindowsFailureExecutor:
    def __init__(self, fixture: Path | None = None) -> None:
        self.fixture = fixture
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
        if len(self.commands) == 1 or self.fixture is None:
            return ProcessResult(
                returncode=0xC0000142,
                stderr="python.exe: DLL initialization failed\n",
            )
        output = Path(command[command.index("--output") + 1])
        shutil.copyfile(self.fixture, output)
        return ProcessResult(returncode=0)


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


def test_subprocess_executor_does_not_depend_on_console_handles(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    captured: dict[str, object] = {}

    def fake_run(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        captured.update(kwargs)
        return subprocess.CompletedProcess(
            command,
            returncode=0,
            stdout=None,
            stderr="bridge diagnostic\n",
        )

    monkeypatch.setattr(subprocess, "run", fake_run)

    result = SubprocessExecutor().run(
        ["python", "bridge.py"],
        cwd=tmp_path,
        timeout_seconds=30,
    )

    assert captured["stdin"] is subprocess.DEVNULL
    assert captured["stdout"] is subprocess.DEVNULL
    assert captured["stderr"] is subprocess.PIPE
    assert result == ProcessResult(returncode=0, stderr="bridge diagnostic\n")


def test_mediacrawler_provider_maps_complete_bridge_payload(
    fixtures_dir: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("MEDIACRAWLER_BROWSER_CHANNEL", "msedge")
    home, bridge = _runtime(tmp_path)
    executor = FixtureProcessExecutor(fixtures_dir / "mediacrawler" / "bridge-success.json")
    provider = MediaCrawlerAccountProvider(
        home=home,
        bridge_script=bridge,
        uv_executable="uv-fixture",
        executor=executor,
    )
    request = AccountCollectionRequest(
        profile_url=("https://www.douyin.com/user/MS4wLjABAAAAmediacrawler-hotel"),
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


def test_mediacrawler_provider_omits_count_for_full_homepage_collection(
    tmp_path: Path,
) -> None:
    home, bridge = _runtime(tmp_path)
    provider = MediaCrawlerAccountProvider(
        home=home,
        bridge_script=bridge,
        uv_executable="uv-fixture",
        executor=FixtureProcessExecutor(tmp_path / "unused.json"),
    )
    request = AccountCollectionRequest(
        profile_url="https://www.douyin.com/user/demo",
        provider=CollectionProviderKind.MEDIACRAWLER,
    )

    command = provider._command(request, tmp_path / "result.json")

    assert "--count" not in command
    assert command[command.index("--max-pages") + 1] == "1000"
    assert command[command.index("--max-videos") + 1] == "20000"


def test_mediacrawler_provider_retries_windows_dll_initialization_failure(
    fixtures_dir: Path,
    tmp_path: Path,
) -> None:
    home, bridge = _runtime(tmp_path)
    executor = TransientWindowsFailureExecutor(
        fixtures_dir / "mediacrawler" / "bridge-success.json"
    )
    provider = MediaCrawlerAccountProvider(
        home=home,
        bridge_script=bridge,
        uv_executable="uv-fixture",
        executor=executor,
    )

    result = provider.collect(
        AccountCollectionRequest(
            profile_url="https://www.douyin.com/user/demo",
            count=2,
            provider=CollectionProviderKind.MEDIACRAWLER,
        )
    )

    assert len(executor.commands) == 2
    assert len(result.videos) == 2


def test_mediacrawler_provider_exposes_bounded_process_diagnostic_after_retry(
    tmp_path: Path,
) -> None:
    home, bridge = _runtime(tmp_path)
    executor = TransientWindowsFailureExecutor()
    provider = MediaCrawlerAccountProvider(
        home=home,
        bridge_script=bridge,
        uv_executable="uv-fixture",
        executor=executor,
    )

    with pytest.raises(DistillerError) as captured:
        provider.collect(
            AccountCollectionRequest(
                profile_url="https://www.douyin.com/user/demo",
                provider=CollectionProviderKind.MEDIACRAWLER,
            )
        )

    assert len(executor.commands) == 2
    assert captured.value.code == ErrorCode.MEDIACRAWLER_UNAVAILABLE
    assert captured.value.details["returncode_hex"] == "0xC0000142"
    assert captured.value.details["attempts"] == 2
    assert "DLL initialization failed" in captured.value.details["stderr"]
    assert "required DLL" in captured.value.details["reason"]


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
