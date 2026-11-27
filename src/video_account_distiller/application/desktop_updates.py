"""Fail-closed GitHub Release updater for the installed Windows desktop app."""

from __future__ import annotations

import hashlib
import hmac
import os
import re
import shutil
import subprocess
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

import requests

from video_account_distiller.application.desktop_settings import default_desktop_data_dir
from video_account_distiller.version import PACKAGE_VERSION

GITHUB_REPOSITORY = "elilitokirin1111-code/video-account-distiller"
GITHUB_LATEST_RELEASE_API = f"https://api.github.com/repos/{GITHUB_REPOSITORY}/releases/latest"
INSTALLER_NAME_TEMPLATE = "VideoAccountDistiller-Setup-{version}-win64.exe"
MAX_INSTALLER_BYTES = 512 * 1024 * 1024
DOWNLOAD_CHUNK_BYTES = 1024 * 1024
DOWNLOAD_FREE_SPACE_OVERHEAD = 64 * 1024 * 1024

_STABLE_VERSION = re.compile(r"(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)")
_SHA256_DIGEST = re.compile(r"sha256:(?P<value>[0-9a-fA-F]{64})")
_DOWNLOAD_PREFIX = f"https://github.com/{GITHUB_REPOSITORY}/releases/download/"
_ALLOWED_DOWNLOAD_HOSTS = {
    "github.com",
    "objects.githubusercontent.com",
    "release-assets.githubusercontent.com",
}

DownloadProgress = Callable[[int, int], None]


class DesktopUpdateError(RuntimeError):
    """Stable, human-readable failure raised before an untrusted installer can run."""

    def __init__(
        self,
        message: str,
        *,
        code: str,
        status_code: int | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.status_code = status_code


@dataclass(frozen=True, slots=True)
class DesktopReleaseAsset:
    """Validated Windows installer metadata returned by GitHub."""

    name: str
    download_url: str
    size: int
    sha256: str


@dataclass(frozen=True, slots=True)
class AvailableDesktopUpdate:
    """A stable release that is strictly newer than the running package."""

    current_version: str
    version: str
    tag_name: str
    release_url: str
    notes: str
    asset: DesktopReleaseAsset


@dataclass(frozen=True, slots=True)
class PreparedDesktopUpdate:
    """A fully downloaded and verified installer ready to execute."""

    update: AvailableDesktopUpdate
    installer_path: Path
    sha256: str


def _version_tuple(value: str, *, field: str) -> tuple[int, int, int]:
    matched = _STABLE_VERSION.fullmatch(value)
    if matched is None:
        raise DesktopUpdateError(
            f"{field} 必须是稳定的 major.minor.patch 版本号。",
            code="UPDATE_VERSION_INVALID",
        )
    major, minor, patch = matched.groups()
    return int(major), int(minor), int(patch)


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(DOWNLOAD_CHUNK_BYTES), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _inside(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return True


def _resolved_update_root(update_root: Path | None) -> Path:
    return (update_root or (default_desktop_data_dir() / "updates")).expanduser().resolve()


def cleanup_stale_updates(
    *,
    update_root: Path | None = None,
    max_age_days: int = 7,
    now: float | None = None,
) -> list[Path]:
    """Remove only bounded, old semver staging directories under the updater root."""

    if max_age_days < 1:
        raise ValueError("max_age_days must be at least one")
    root = _resolved_update_root(update_root)
    if not root.is_dir():
        return []
    cutoff = (time.time() if now is None else now) - max_age_days * 86_400
    removed: list[Path] = []
    for candidate in root.iterdir():
        if candidate.is_symlink() or not candidate.is_dir():
            continue
        if _STABLE_VERSION.fullmatch(candidate.name) is None or candidate.stat().st_mtime >= cutoff:
            continue
        resolved = candidate.resolve()
        if resolved == root or not _inside(resolved, root):
            continue
        try:
            shutil.rmtree(resolved)
        except OSError:
            continue
        removed.append(resolved)
    return removed


def _validated_download_url(value: object, *, redirected: bool = False) -> str:
    if not isinstance(value, str):
        raise DesktopUpdateError("更新资产缺少 HTTPS 下载地址。", code="UPDATE_URL_INVALID")
    parsed = urlparse(value)
    host = (parsed.hostname or "").casefold()
    if parsed.scheme != "https" or host not in _ALLOWED_DOWNLOAD_HOSTS:
        raise DesktopUpdateError("更新资产跳转到了非 GitHub 地址。", code="UPDATE_URL_INVALID")
    if not redirected and not value.startswith(_DOWNLOAD_PREFIX):
        raise DesktopUpdateError("更新资产不属于受信任的项目 Release。", code="UPDATE_URL_INVALID")
    return value


class DesktopUpdateService:
    """Check, stage, verify, and start an in-place Windows desktop update."""

    def __init__(
        self,
        *,
        current_version: str = PACKAGE_VERSION,
        update_root: Path | None = None,
        session: requests.Session | None = None,
        platform_name: str = os.name,
        check_timeout_seconds: float = 15.0,
        download_timeout_seconds: float = 300.0,
    ) -> None:
        _version_tuple(current_version, field="当前版本")
        self.current_version = current_version
        self.update_root = _resolved_update_root(update_root)
        self.session = session or requests.Session()
        self.platform_name = platform_name
        self.check_timeout_seconds = check_timeout_seconds
        self.download_timeout_seconds = download_timeout_seconds

    @property
    def request_headers(self) -> dict[str, str]:
        return {
            "Accept": "application/vnd.github+json",
            "Accept-Encoding": "identity",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": f"VideoAccountDistiller/{self.current_version}",
        }

    def close(self) -> None:
        self.session.close()

    def check_for_update(self) -> AvailableDesktopUpdate | None:
        """Return the latest stable Windows update, or ``None`` when already current."""

        try:
            response = self.session.get(
                GITHUB_LATEST_RELEASE_API,
                headers=self.request_headers,
                timeout=self.check_timeout_seconds,
            )
        except requests.RequestException as exc:
            raise DesktopUpdateError(
                "暂时无法连接 GitHub 检查更新，请稍后重试。",
                code="UPDATE_CHECK_UNAVAILABLE",
            ) from exc
        if response.status_code != 200:
            response.close()
            raise DesktopUpdateError(
                f"GitHub 更新检查失败（HTTP {response.status_code}）。",
                code="UPDATE_CHECK_FAILED",
                status_code=response.status_code,
            )
        try:
            payload = response.json()
        except ValueError as exc:
            response.close()
            raise DesktopUpdateError(
                "GitHub 返回了无法解析的更新信息。",
                code="UPDATE_RESPONSE_INVALID",
            ) from exc
        response.close()
        if not isinstance(payload, dict):
            raise DesktopUpdateError(
                "GitHub 返回了无效的更新信息。",
                code="UPDATE_RESPONSE_INVALID",
            )
        if payload.get("draft") is not False or payload.get("prerelease") is not False:
            raise DesktopUpdateError(
                "GitHub 最新发布不是稳定正式版。",
                code="UPDATE_RELEASE_UNSTABLE",
            )

        raw_tag = payload.get("tag_name")
        if not isinstance(raw_tag, str) or not raw_tag.startswith("v"):
            raise DesktopUpdateError("Release 标签格式无效。", code="UPDATE_VERSION_INVALID")
        version = raw_tag[1:]
        latest = _version_tuple(version, field="Release 版本")
        current = _version_tuple(self.current_version, field="当前版本")
        if latest <= current:
            return None

        expected_name = INSTALLER_NAME_TEMPLATE.format(version=version)
        raw_assets = payload.get("assets")
        if not isinstance(raw_assets, list):
            raise DesktopUpdateError(
                "Release 缺少 Windows 更新资产列表。",
                code="UPDATE_ASSET_MISSING",
            )
        matches = [
            item
            for item in raw_assets
            if isinstance(item, dict)
            and item.get("name") == expected_name
            and item.get("state") == "uploaded"
        ]
        if len(matches) != 1:
            raise DesktopUpdateError(
                f"Release 必须且只能包含一个 {expected_name}。",
                code="UPDATE_ASSET_MISSING",
            )
        raw_asset = matches[0]
        raw_size = raw_asset.get("size")
        if (
            not isinstance(raw_size, int)
            or isinstance(raw_size, bool)
            or raw_size <= 0
            or raw_size > MAX_INSTALLER_BYTES
        ):
            raise DesktopUpdateError(
                "Windows 更新包大小无效或超过 512 MiB 安全上限。",
                code="UPDATE_SIZE_INVALID",
            )
        raw_digest = raw_asset.get("digest")
        digest_match = _SHA256_DIGEST.fullmatch(raw_digest) if isinstance(raw_digest, str) else None
        if digest_match is None:
            raise DesktopUpdateError(
                "Windows 更新包缺少有效的 GitHub SHA-256 摘要。",
                code="UPDATE_DIGEST_INVALID",
            )
        download_url = _validated_download_url(raw_asset.get("browser_download_url"))
        release_url = payload.get("html_url")
        if not isinstance(release_url, str) or not release_url.startswith(
            f"https://github.com/{GITHUB_REPOSITORY}/releases/"
        ):
            raise DesktopUpdateError("Release 页面地址无效。", code="UPDATE_URL_INVALID")
        notes = payload.get("body")
        return AvailableDesktopUpdate(
            current_version=self.current_version,
            version=version,
            tag_name=raw_tag,
            release_url=release_url,
            notes=str(notes or "")[:16_384],
            asset=DesktopReleaseAsset(
                name=expected_name,
                download_url=download_url,
                size=raw_size,
                sha256=digest_match.group("value").casefold(),
            ),
        )

    def download_update(
        self,
        update: AvailableDesktopUpdate,
        *,
        progress: DownloadProgress | None = None,
    ) -> PreparedDesktopUpdate:
        """Stream a release installer to ``.part``, verify it, then atomically publish it."""

        if update.current_version != self.current_version:
            raise DesktopUpdateError(
                "更新计划与当前程序版本不一致。",
                code="UPDATE_PLAN_INVALID",
            )
        if _version_tuple(update.version, field="更新版本") <= _version_tuple(
            self.current_version,
            field="当前版本",
        ):
            raise DesktopUpdateError(
                "更新版本必须严格高于当前程序版本。",
                code="UPDATE_PLAN_INVALID",
            )
        if update.tag_name != f"v{update.version}":
            raise DesktopUpdateError(
                "更新计划中的 Release 标签不匹配。",
                code="UPDATE_PLAN_INVALID",
            )
        expected_name = INSTALLER_NAME_TEMPLATE.format(version=update.version)
        if update.asset.name != expected_name:
            raise DesktopUpdateError("更新资产文件名不匹配。", code="UPDATE_ASSET_INVALID")
        _validated_download_url(update.asset.download_url)
        if update.asset.size <= 0 or update.asset.size > MAX_INSTALLER_BYTES:
            raise DesktopUpdateError("更新资产大小无效。", code="UPDATE_SIZE_INVALID")
        if re.fullmatch(r"[0-9a-f]{64}", update.asset.sha256) is None:
            raise DesktopUpdateError("更新资产摘要无效。", code="UPDATE_DIGEST_INVALID")

        self.update_root.mkdir(parents=True, exist_ok=True)
        stage = (self.update_root / update.version).resolve()
        if not _inside(stage, self.update_root) or stage == self.update_root:
            raise DesktopUpdateError("更新暂存目录越界。", code="UPDATE_PATH_INVALID")
        stage.mkdir(parents=False, exist_ok=True)
        installer = stage / expected_name
        partial = stage / f"{expected_name}.part"
        if installer.is_file() and installer.stat().st_size == update.asset.size:
            existing_hash = _sha256_file(installer)
            if hmac.compare_digest(existing_hash, update.asset.sha256):
                if progress is not None:
                    progress(update.asset.size, update.asset.size)
                return PreparedDesktopUpdate(update, installer, existing_hash)
            installer.unlink()
        if partial.exists():
            partial.unlink()
        free = shutil.disk_usage(self.update_root).free
        if free < update.asset.size + DOWNLOAD_FREE_SPACE_OVERHEAD:
            raise DesktopUpdateError(
                "更新暂存盘空间不足，请至少释放更新包大小外加 64 MiB。",
                code="UPDATE_DISK_FULL",
            )

        try:
            response = self.session.get(
                update.asset.download_url,
                headers={
                    "Accept-Encoding": "identity",
                    "User-Agent": self.request_headers["User-Agent"],
                },
                timeout=self.download_timeout_seconds,
                stream=True,
                allow_redirects=True,
            )
        except requests.RequestException as exc:
            raise DesktopUpdateError(
                "Windows 更新包下载失败，请稍后重试。",
                code="UPDATE_DOWNLOAD_FAILED",
            ) from exc
        if response.status_code != 200:
            response.close()
            raise DesktopUpdateError(
                f"Windows 更新包下载失败（HTTP {response.status_code}）。",
                code="UPDATE_DOWNLOAD_FAILED",
                status_code=response.status_code,
            )
        final_url = getattr(response, "url", update.asset.download_url)
        try:
            _validated_download_url(final_url, redirected=True)
        except DesktopUpdateError:
            response.close()
            raise
        raw_content_length = response.headers.get("Content-Length")
        if raw_content_length:
            try:
                content_length = int(raw_content_length)
            except ValueError as exc:
                response.close()
                raise DesktopUpdateError(
                    "更新服务器返回了无效的文件大小。",
                    code="UPDATE_SIZE_INVALID",
                ) from exc
            if content_length != update.asset.size:
                response.close()
                raise DesktopUpdateError(
                    "下载文件大小与 GitHub Release 元数据不一致。",
                    code="UPDATE_SIZE_MISMATCH",
                )

        digest = hashlib.sha256()
        downloaded = 0
        try:
            with partial.open("xb") as handle:
                for chunk in response.iter_content(chunk_size=DOWNLOAD_CHUNK_BYTES):
                    if not chunk:
                        continue
                    downloaded += len(chunk)
                    if downloaded > update.asset.size:
                        raise DesktopUpdateError(
                            "下载文件超过 GitHub 声明大小。",
                            code="UPDATE_SIZE_MISMATCH",
                        )
                    handle.write(chunk)
                    digest.update(chunk)
                    if progress is not None:
                        progress(downloaded, update.asset.size)
                handle.flush()
                os.fsync(handle.fileno())
            if downloaded != update.asset.size:
                raise DesktopUpdateError(
                    "Windows 更新包下载不完整。",
                    code="UPDATE_SIZE_MISMATCH",
                )
            actual_hash = digest.hexdigest()
            if not hmac.compare_digest(actual_hash, update.asset.sha256):
                raise DesktopUpdateError(
                    "Windows 更新包 SHA-256 校验失败，文件已拒绝执行。",
                    code="UPDATE_DIGEST_MISMATCH",
                )
            with partial.open("rb") as handle:
                if handle.read(2) != b"MZ":
                    raise DesktopUpdateError(
                        "Windows 更新包不是有效的 PE 安装程序。",
                        code="UPDATE_BINARY_INVALID",
                    )
            os.replace(partial, installer)
        except DesktopUpdateError:
            partial.unlink(missing_ok=True)
            raise
        except (OSError, requests.RequestException) as exc:
            partial.unlink(missing_ok=True)
            raise DesktopUpdateError(
                "更新包无法安全写入暂存目录。",
                code="UPDATE_STAGE_FAILED",
            ) from exc
        finally:
            response.close()
            partial.unlink(missing_ok=True)
        return PreparedDesktopUpdate(update, installer, digest.hexdigest())

    def installer_command(
        self,
        prepared: PreparedDesktopUpdate,
        *,
        executable_path: Path | None = None,
    ) -> list[str]:
        """Build the shell-free Inno Setup command for the current install directory."""

        if self.platform_name != "nt":
            raise DesktopUpdateError(
                "自动原地更新仅支持 Windows 安装版。",
                code="UPDATE_PLATFORM_UNSUPPORTED",
            )
        executable = (executable_path or Path(sys.executable)).expanduser().resolve()
        if executable.name.casefold() != "videoaccountdistiller.exe" or not executable.is_file():
            raise DesktopUpdateError(
                "当前程序不是可识别的 Windows 安装版。",
                code="UPDATE_INSTALLATION_INVALID",
            )
        install_dir = executable.parent
        if not any(install_dir.glob("unins*.exe")):
            raise DesktopUpdateError(
                "当前目录缺少安装记录，便携版不能自动原地更新。",
                code="UPDATE_INSTALLATION_INVALID",
            )
        installer = prepared.installer_path.expanduser().resolve()
        if not installer.is_file() or not _inside(installer, self.update_root):
            raise DesktopUpdateError(
                "已验证的更新安装器不存在或路径越界。",
                code="UPDATE_PATH_INVALID",
            )
        if installer.stat().st_size != prepared.update.asset.size:
            raise DesktopUpdateError("安装器大小已发生变化。", code="UPDATE_SIZE_MISMATCH")
        actual_hash = _sha256_file(installer)
        if not hmac.compare_digest(actual_hash, prepared.update.asset.sha256):
            raise DesktopUpdateError(
                "安装器在执行前校验失败。",
                code="UPDATE_DIGEST_MISMATCH",
            )
        log_path = installer.parent / "install.log"
        return [
            str(installer),
            "/SP-",
            "/VERYSILENT",
            "/SUPPRESSMSGBOXES",
            "/NORESTART",
            "/CLOSEAPPLICATIONS",
            "/NORESTARTAPPLICATIONS",
            f"/DIR={install_dir}",
            f"/LOG={log_path}",
        ]

    def launch_installer(
        self,
        prepared: PreparedDesktopUpdate,
        *,
        executable_path: Path | None = None,
        popen: Callable[..., subprocess.Popen[bytes]] = subprocess.Popen,
    ) -> subprocess.Popen[bytes]:
        """Start the verified installer detached from the Qt event loop; never invoke a shell."""

        command = self.installer_command(prepared, executable_path=executable_path)
        try:
            return popen(
                command,
                cwd=str(prepared.installer_path.parent),
                shell=False,
                close_fds=True,
            )
        except OSError as exc:
            raise DesktopUpdateError(
                "更新安装程序无法启动；当前程序将继续运行。",
                code="UPDATE_LAUNCH_FAILED",
            ) from exc

    def cleanup_stale_updates(
        self,
        *,
        max_age_days: int = 7,
        now: float | None = None,
    ) -> list[Path]:
        return cleanup_stale_updates(
            update_root=self.update_root,
            max_age_days=max_age_days,
            now=now,
        )


__all__ = [
    "AvailableDesktopUpdate",
    "DesktopReleaseAsset",
    "DesktopUpdateError",
    "DesktopUpdateService",
    "PreparedDesktopUpdate",
    "cleanup_stale_updates",
]
