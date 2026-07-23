"""Pinned MediaCrawler sidecar provider for bounded Douyin account research."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Literal, Protocol

from pydantic import Field, ValidationError, field_validator

from video_account_distiller.collection.providers import (
    _map_comment,
    _map_post,
    _map_profile,
)
from video_account_distiller.errors import DistillerError, ErrorCode
from video_account_distiller.models import (
    AccountCollectionBatch,
    AccountCollectionRequest,
    CollectedComment,
    CollectedMetricSnapshot,
    CollectedVideo,
    CollectionProviderKind,
    ProviderRawPage,
)
from video_account_distiller.models.core import StrictModel

MEDIACRAWLER_PINNED_COMMIT = "0625e01a6bc717a3fc9c96d3dac7fb8957043838"
MEDIACRAWLER_BRIDGE_SCHEMA_VERSION = "1.0"


@dataclass(frozen=True)
class ProcessResult:
    """Minimal subprocess result used by the injectable sidecar runner."""

    returncode: int


class ProcessExecutor(Protocol):
    """Run a bounded process without exposing environment values in the result."""

    def run(
        self,
        command: list[str],
        *,
        cwd: Path,
        timeout_seconds: int,
    ) -> ProcessResult: ...


class SubprocessExecutor:
    """Production process executor that keeps bridge progress on stderr."""

    def run(
        self,
        command: list[str],
        *,
        cwd: Path,
        timeout_seconds: int,
    ) -> ProcessResult:
        completed = subprocess.run(
            command,
            cwd=cwd,
            check=False,
            stdin=None,
            stdout=subprocess.DEVNULL,
            stderr=None,
            timeout=timeout_seconds,
        )
        return ProcessResult(returncode=completed.returncode)


class MediaCrawlerBridgeRawPage(StrictModel):
    """Raw page emitted by the controlled bridge."""

    endpoint: str = Field(min_length=1)
    payload: dict[str, Any]


class MediaCrawlerBridgePayload(StrictModel):
    """Validated success envelope produced by the sidecar bridge."""

    schema_version: Literal["1.0"]
    ok: Literal[True]
    fetched_at: datetime
    profile_url: str
    platform_account_id: str = Field(min_length=1)
    profile: dict[str, Any]
    videos: list[dict[str, Any]]
    comments: dict[str, list[dict[str, Any]]] = Field(default_factory=dict)
    raw_pages: list[MediaCrawlerBridgeRawPage] = Field(min_length=1)
    warnings: list[str] = Field(default_factory=list)

    @field_validator("fetched_at")
    @classmethod
    def require_timezone(cls, value: datetime) -> datetime:
        if value.utcoffset() is None:
            raise ValueError("MediaCrawler fetched_at must include a timezone")
        return value


def _repository_root() -> Path:
    return Path(__file__).resolve().parents[3]


def default_mediacrawler_home() -> Path:
    """Return the bundled submodule path, allowing an explicit development override."""

    configured = os.environ.get("MEDIACRAWLER_HOME")
    if configured:
        return Path(configured).expanduser().resolve()
    return (_repository_root() / "third_party" / "MediaCrawler").resolve()


def default_browser_profile(browser_channel: str = "chrome") -> Path:
    """Keep the dedicated login profile outside projects and the Git worktree."""

    configured = os.environ.get("MEDIACRAWLER_BROWSER_PROFILE")
    if configured:
        return Path(configured).expanduser().resolve()
    profile_name = (
        "mediacrawler-douyin-edge" if browser_channel == "msedge" else "mediacrawler-douyin"
    )
    return (Path.home() / ".video-account-distiller" / "browser-profiles" / profile_name).resolve()


def chrome_executable() -> str | None:
    """Locate the Chrome channel used by the controlled Playwright context."""

    for name in ("google-chrome", "google-chrome-stable", "chrome"):
        discovered = shutil.which(name)
        if discovered:
            return discovered
    candidates = [Path("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome")]
    for variable in ("LOCALAPPDATA", "PROGRAMFILES", "PROGRAMFILES(X86)"):
        root = os.environ.get(variable)
        if root:
            candidates.append(Path(root) / "Google" / "Chrome" / "Application" / "chrome.exe")
    for candidate in candidates:
        if candidate.is_file():
            return str(candidate.resolve())
    return None


def mediacrawler_runtime_available() -> bool:
    """Check whether the pinned source and uv runtime are locally available."""

    home = default_mediacrawler_home()
    return (
        shutil.which(os.environ.get("MEDIACRAWLER_UV", "uv")) is not None
        and (home / "pyproject.toml").is_file()
        and (home / "uv.lock").is_file()
        and (home / "LICENSE").is_file()
        and (home / "media_platform" / "douyin" / "client.py").is_file()
    )


def _read_bridge_payload(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise DistillerError(
            ErrorCode.ADAPTER_RESPONSE,
            "MediaCrawler bridge did not produce valid JSON",
        ) from exc
    if not isinstance(value, dict):
        raise DistillerError(
            ErrorCode.ADAPTER_RESPONSE,
            "MediaCrawler bridge payload must be a JSON object",
        )
    return {str(key): item for key, item in value.items()}


def _bridge_error(payload: dict[str, Any], returncode: int) -> DistillerError:
    bridge_code = str(payload.get("error_code") or "unknown")
    message = str(payload.get("message") or "MediaCrawler collection failed")
    if bridge_code == "login_required":
        return DistillerError(
            ErrorCode.BROWSER_LOGIN_REQUIRED,
            message,
            details={
                "next": (
                    "Run the command again and complete Douyin login manually in the visible "
                    "browser window."
                )
            },
        )
    if bridge_code in {"dependency_error", "browser_or_collection_error"}:
        return DistillerError(
            ErrorCode.MEDIACRAWLER_UNAVAILABLE,
            message,
            details={"bridge_code": bridge_code, "returncode": returncode},
        )
    if bridge_code == "profile_invalid":
        return DistillerError(ErrorCode.PROFILE_URL_INVALID, message)
    return DistillerError(
        ErrorCode.ADAPTER_RESPONSE,
        message,
        details={"bridge_code": bridge_code, "returncode": returncode},
    )


class MediaCrawlerAccountProvider:
    """Run the pinned MediaCrawler client and map it into the canonical batch."""

    def __init__(
        self,
        *,
        home: Path | None = None,
        browser_profile: Path | None = None,
        browser_channel: str = "chrome",
        uv_executable: str | None = None,
        login_timeout_seconds: int = 180,
        request_interval_seconds: float = 1.0,
        process_timeout_seconds: int = 900,
        executor: ProcessExecutor | None = None,
        bridge_script: Path | None = None,
    ) -> None:
        self.home = (home or default_mediacrawler_home()).expanduser().resolve()
        self.browser_channel = os.environ.get(
            "MEDIACRAWLER_BROWSER_CHANNEL",
            browser_channel,
        ).strip()
        if self.browser_channel not in {"chrome", "msedge"}:
            raise DistillerError(
                ErrorCode.SCHEMA_INVALID,
                "MediaCrawler browser channel must be chrome or msedge",
                details={"allowed": ["chrome", "msedge"]},
            )
        self.browser_profile = (
            (browser_profile or default_browser_profile(self.browser_channel))
            .expanduser()
            .resolve()
        )
        self.uv_executable = uv_executable or shutil.which(os.environ.get("MEDIACRAWLER_UV", "uv"))
        configured_login_timeout = os.environ.get("MEDIACRAWLER_LOGIN_TIMEOUT_SECONDS")
        if configured_login_timeout:
            try:
                login_timeout_seconds = int(configured_login_timeout)
            except ValueError as exc:
                raise DistillerError(
                    ErrorCode.SCHEMA_INVALID,
                    "MEDIACRAWLER_LOGIN_TIMEOUT_SECONDS must be an integer",
                ) from exc
        self.login_timeout_seconds = login_timeout_seconds
        self.request_interval_seconds = request_interval_seconds
        self.process_timeout_seconds = process_timeout_seconds
        self.executor = executor or SubprocessExecutor()
        self.bridge_script = (
            bridge_script or Path(__file__).with_name("_mediacrawler_bridge.py")
        ).resolve()
        if not 30 <= self.login_timeout_seconds <= 900:
            raise DistillerError(
                ErrorCode.SCHEMA_INVALID,
                "MediaCrawler login timeout must be between 30 and 900 seconds",
            )
        if not 0.5 <= self.request_interval_seconds <= 10.0:
            raise DistillerError(
                ErrorCode.SCHEMA_INVALID,
                "MediaCrawler request interval must be between 0.5 and 10 seconds",
            )
        if not 60 <= self.process_timeout_seconds <= 3600:
            raise DistillerError(
                ErrorCode.SCHEMA_INVALID,
                "MediaCrawler process timeout must be between 60 and 3600 seconds",
            )

    def _validate_runtime(self) -> None:
        required = [
            self.home / "pyproject.toml",
            self.home / "uv.lock",
            self.home / "LICENSE",
            self.home / "media_platform" / "douyin" / "client.py",
            self.bridge_script,
        ]
        missing = [str(path) for path in required if not path.is_file()]
        if self.uv_executable is None or missing:
            raise DistillerError(
                ErrorCode.MEDIACRAWLER_UNAVAILABLE,
                "Bundled MediaCrawler runtime is not ready",
                details={
                    "missing": missing,
                    "uv_available": self.uv_executable is not None,
                    "next": "Run git submodule update --init --recursive and install uv.",
                },
            )

    def _command(self, request: AccountCollectionRequest, output_path: Path) -> list[str]:
        assert self.uv_executable is not None
        return [
            self.uv_executable,
            "run",
            "--project",
            str(self.home),
            "--frozen",
            "python",
            str(self.bridge_script),
            "--media-root",
            str(self.home),
            "--profile-url",
            request.profile_url,
            "--count",
            str(request.count),
            "--sort",
            request.sort.value,
            "--comments-per-video",
            str(request.comments_per_video),
            "--comment-video-limit",
            str(request.comment_video_limit),
            "--browser-profile",
            str(self.browser_profile),
            "--browser-channel",
            self.browser_channel,
            "--login-timeout",
            str(self.login_timeout_seconds),
            "--request-interval",
            str(self.request_interval_seconds),
            "--output",
            str(output_path),
        ]

    def _run_bridge(self, request: AccountCollectionRequest) -> MediaCrawlerBridgePayload:
        self._validate_runtime()
        with tempfile.TemporaryDirectory(prefix="distiller-mediacrawler-") as temporary:
            output_path = Path(temporary) / "bridge-result.json"
            try:
                result = self.executor.run(
                    self._command(request, output_path),
                    cwd=self.home,
                    timeout_seconds=self.process_timeout_seconds,
                )
            except subprocess.TimeoutExpired as exc:
                raise DistillerError(
                    ErrorCode.COLLECTION_TIMEOUT,
                    "MediaCrawler collection exceeded the configured timeout",
                    details={"timeout_seconds": self.process_timeout_seconds},
                ) from exc
            if not output_path.is_file():
                raise DistillerError(
                    ErrorCode.MEDIACRAWLER_UNAVAILABLE,
                    "MediaCrawler process ended without a bridge result",
                    details={"returncode": result.returncode},
                )
            payload = _read_bridge_payload(output_path)
            if payload.get("ok") is not True or result.returncode != 0:
                raise _bridge_error(payload, result.returncode)
            try:
                return MediaCrawlerBridgePayload.model_validate(payload)
            except ValidationError as exc:
                raise DistillerError(
                    ErrorCode.ADAPTER_RESPONSE,
                    "MediaCrawler bridge result failed schema validation",
                    details={"reason": str(exc.errors(include_url=False)[0]["msg"])},
                ) from exc

    def collect(self, request: AccountCollectionRequest) -> AccountCollectionBatch:
        """Collect one public account and return the complete canonical batch."""

        if request.provider != CollectionProviderKind.MEDIACRAWLER:
            raise DistillerError(
                ErrorCode.PLATFORM_UNSUPPORTED,
                f"MediaCrawler provider cannot handle {request.provider.value}",
            )
        bridge = self._run_bridge(request)
        account = _map_profile(
            bridge.profile,
            platform_account_id=bridge.platform_account_id,
            profile_url=request.profile_url,
            fetched_at=bridge.fetched_at,
        )
        videos: list[CollectedVideo] = []
        metrics: list[CollectedMetricSnapshot] = []
        seen_videos: set[str] = set()
        for item in bridge.videos:
            mapped = _map_post(
                item,
                platform_account_id=bridge.platform_account_id,
                fetched_at=bridge.fetched_at,
                metric_source=f"mediacrawler:{MEDIACRAWLER_PINNED_COMMIT[:12]}",
            )
            if mapped is None or mapped[0].platform_video_id in seen_videos:
                continue
            seen_videos.add(mapped[0].platform_video_id)
            videos.append(mapped[0])
            metrics.append(mapped[1])
        comments: list[CollectedComment] = []
        seen_comments: set[str] = set()
        for video_id, items in bridge.comments.items():
            if video_id not in seen_videos:
                continue
            for item in items:
                mapped_comment = _map_comment(
                    item,
                    video_id=video_id,
                    platform_account_id=bridge.platform_account_id,
                )
                if mapped_comment is None or mapped_comment.platform_comment_id in seen_comments:
                    continue
                seen_comments.add(mapped_comment.platform_comment_id)
                comments.append(mapped_comment)
        warnings = list(bridge.warnings)
        if any(metric.views is None for metric in metrics):
            warnings.append("some_public_view_counts_are_missing")
        if request.comments_per_video > 0 and not comments:
            warnings.append("provider_returned_no_usable_public_comments")
        return AccountCollectionBatch(
            provider=CollectionProviderKind.MEDIACRAWLER,
            profile_url=request.profile_url,
            platform_account_id=bridge.platform_account_id,
            fetched_at=bridge.fetched_at,
            account=account,
            videos=videos,
            metrics=metrics,
            comments=comments,
            raw_pages=[
                ProviderRawPage(
                    endpoint=page.endpoint,
                    fetched_at=bridge.fetched_at,
                    payload=page.payload,
                )
                for page in bridge.raw_pages
            ],
            warnings=warnings,
        )


__all__ = [
    "MEDIACRAWLER_PINNED_COMMIT",
    "MediaCrawlerAccountProvider",
    "ProcessExecutor",
    "ProcessResult",
    "chrome_executable",
    "default_browser_profile",
    "default_mediacrawler_home",
    "mediacrawler_runtime_available",
]
