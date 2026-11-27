from __future__ import annotations

import hashlib
import json
import os
import time
from pathlib import Path
from typing import Any, cast
from unittest.mock import Mock

import pytest
import requests

from video_account_distiller.application.desktop_updates import (
    GITHUB_LATEST_RELEASE_API,
    AvailableDesktopUpdate,
    DesktopReleaseAsset,
    DesktopUpdateError,
    DesktopUpdateService,
    PreparedDesktopUpdate,
    cleanup_stale_updates,
)


class _Session:
    def __init__(self, *responses: requests.Response) -> None:
        self.responses = list(responses)
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.closed = False

    def get(self, url: str, **kwargs: Any) -> requests.Response:
        self.calls.append((url, kwargs))
        return self.responses.pop(0)

    def close(self) -> None:
        self.closed = True


def _response(
    content: bytes,
    *,
    url: str,
    status_code: int = 200,
    content_length: bool = False,
) -> requests.Response:
    response = requests.Response()
    response.status_code = status_code
    response.url = url
    response._content = content
    response._content_consumed = True
    if content_length:
        response.headers["Content-Length"] = str(len(content))
    return response


def _release_payload(
    content: bytes,
    *,
    version: str = "1.1.0",
) -> dict[str, Any]:
    asset_name = f"VideoAccountDistiller-Setup-{version}-win64.exe"
    return {
        "tag_name": f"v{version}",
        "draft": False,
        "prerelease": False,
        "html_url": (
            "https://github.com/elilitokirin1111-code/"
            f"video-account-distiller/releases/tag/v{version}"
        ),
        "body": "Stable desktop update",
        "assets": [
            {
                "name": asset_name,
                "state": "uploaded",
                "size": len(content),
                "digest": f"sha256:{hashlib.sha256(content).hexdigest()}",
                "browser_download_url": (
                    "https://github.com/elilitokirin1111-code/video-account-distiller/"
                    f"releases/download/v{version}/{asset_name}"
                ),
            }
        ],
    }


def _json_response(payload: object) -> requests.Response:
    return _response(
        json.dumps(payload).encode(),
        url=GITHUB_LATEST_RELEASE_API,
    )


def _service(tmp_path: Path, session: _Session) -> DesktopUpdateService:
    return DesktopUpdateService(
        current_version="1.0.0",
        update_root=tmp_path / "updates",
        session=cast(requests.Session, session),
    )


def _update(content: bytes, *, digest: str | None = None) -> AvailableDesktopUpdate:
    version = "1.1.0"
    name = f"VideoAccountDistiller-Setup-{version}-win64.exe"
    return AvailableDesktopUpdate(
        current_version="1.0.0",
        version=version,
        tag_name=f"v{version}",
        release_url=(
            "https://github.com/elilitokirin1111-code/"
            f"video-account-distiller/releases/tag/v{version}"
        ),
        notes="",
        asset=DesktopReleaseAsset(
            name=name,
            download_url=(
                "https://github.com/elilitokirin1111-code/video-account-distiller/"
                f"releases/download/v{version}/{name}"
            ),
            size=len(content),
            sha256=digest or hashlib.sha256(content).hexdigest(),
        ),
    )


def test_check_for_update_requires_exact_stable_asset_and_digest(tmp_path: Path) -> None:
    content = b"MZsigned-installer"
    fake_session = _Session(_json_response(_release_payload(content)))
    service = _service(tmp_path, fake_session)

    update = service.check_for_update()

    assert update is not None
    assert update.version == "1.1.0"
    assert update.asset.size == len(content)
    assert update.asset.sha256 == hashlib.sha256(content).hexdigest()
    assert fake_session.calls[0][0] == GITHUB_LATEST_RELEASE_API
    assert fake_session.calls[0][1]["headers"]["Accept-Encoding"] == "identity"
    assert fake_session.calls[0][1]["headers"]["X-GitHub-Api-Version"] == "2022-11-28"


def test_check_for_update_returns_none_for_current_release(tmp_path: Path) -> None:
    content = b"MZinstaller"
    fake_session = _Session(_json_response(_release_payload(content, version="1.0.0")))

    assert _service(tmp_path, fake_session).check_for_update() is None


@pytest.mark.parametrize(
    ("mutation", "expected_code"),
    [
        (lambda payload: payload.update({"prerelease": True}), "UPDATE_RELEASE_UNSTABLE"),
        (lambda payload: payload.update({"tag_name": "v1.1"}), "UPDATE_VERSION_INVALID"),
        (
            lambda payload: payload["assets"][0].pop("digest"),
            "UPDATE_DIGEST_INVALID",
        ),
        (
            lambda payload: payload["assets"].append(dict(payload["assets"][0])),
            "UPDATE_ASSET_MISSING",
        ),
    ],
)
def test_check_for_update_rejects_ambiguous_or_unverifiable_release(
    tmp_path: Path,
    mutation: Any,
    expected_code: str,
) -> None:
    payload = _release_payload(b"MZinstaller")
    mutation(payload)
    service = _service(tmp_path, _Session(_json_response(payload)))

    with pytest.raises(DesktopUpdateError) as caught:
        service.check_for_update()

    assert caught.value.code == expected_code


def test_download_streams_to_part_then_atomically_publishes(tmp_path: Path) -> None:
    content = b"MZ" + b"installer-data" * 64
    update = _update(content)
    response = _response(
        content,
        url="https://release-assets.githubusercontent.com/github-production-release-asset/file",
        content_length=True,
    )
    service = _service(tmp_path, _Session(response))
    progress: list[tuple[int, int]] = []

    prepared = service.download_update(
        update, progress=lambda done, total: progress.append((done, total))
    )

    assert prepared.installer_path.read_bytes() == content
    assert prepared.sha256 == hashlib.sha256(content).hexdigest()
    assert not prepared.installer_path.with_suffix(".exe.part").exists()
    assert progress[-1] == (len(content), len(content))


def test_download_removes_partial_file_when_digest_does_not_match(tmp_path: Path) -> None:
    content = b"MZuntrusted"
    update = _update(content, digest="0" * 64)
    response = _response(
        content,
        url="https://objects.githubusercontent.com/release/file",
        content_length=True,
    )
    service = _service(tmp_path, _Session(response))

    with pytest.raises(DesktopUpdateError) as caught:
        service.download_update(update)

    assert caught.value.code == "UPDATE_DIGEST_MISMATCH"
    stage = tmp_path / "updates" / "1.1.0"
    assert list(stage.iterdir()) == []


def test_installer_command_pins_current_install_dir_and_never_uses_shell(
    tmp_path: Path,
) -> None:
    content = b"MZverified"
    update = _update(content)
    update_root = tmp_path / "updates"
    installer = update_root / update.version / update.asset.name
    installer.parent.mkdir(parents=True)
    installer.write_bytes(content)
    prepared = PreparedDesktopUpdate(update, installer, hashlib.sha256(content).hexdigest())
    install_dir = tmp_path / "Installed App"
    install_dir.mkdir()
    executable = install_dir / "VideoAccountDistiller.exe"
    executable.write_bytes(b"MZapp")
    (install_dir / "unins000.exe").write_bytes(b"MZuninstall")
    service = DesktopUpdateService(
        current_version="1.0.0",
        update_root=update_root,
        session=cast(requests.Session, _Session()),
        platform_name="nt",
    )
    fake_popen = Mock(return_value=object())

    command = service.installer_command(prepared, executable_path=executable)
    result = service.launch_installer(
        prepared,
        executable_path=executable,
        popen=fake_popen,
    )

    assert f"/DIR={install_dir.resolve()}" in command
    assert "/VERYSILENT" in command
    assert "/CLOSEAPPLICATIONS" in command
    assert result is fake_popen.return_value
    fake_popen.assert_called_once_with(
        command,
        cwd=str(installer.parent),
        shell=False,
        close_fds=True,
    )


def test_cleanup_stale_updates_only_removes_old_semver_directories(tmp_path: Path) -> None:
    update_root = tmp_path / "updates"
    old = update_root / "1.0.1"
    recent = update_root / "1.1.0"
    unrelated = update_root / "manual-backup"
    for directory in (old, recent, unrelated):
        directory.mkdir(parents=True)
        (directory / "keep.txt").write_text("test", encoding="utf-8")
    now = time.time()
    old_timestamp = now - 10 * 86_400
    os.utime(old, (old_timestamp, old_timestamp))
    removed = cleanup_stale_updates(
        update_root=update_root,
        max_age_days=7,
        now=now,
    )

    assert removed == [old.resolve()]
    assert not old.exists()
    assert recent.is_dir()
    assert unrelated.is_dir()
