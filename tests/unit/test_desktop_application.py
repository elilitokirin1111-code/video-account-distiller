from __future__ import annotations

import ctypes
import json
import os
import zipfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from video_account_distiller.application.desktop_api import (
    DesktopApiClient,
    DesktopApiError,
)
from video_account_distiller.application.desktop_settings import (
    DESKTOP_KEYRING_SERVICE,
    DesktopSecretStore,
    DesktopSettings,
    DesktopSettingsStore,
)
from video_account_distiller.application.knowledge_packages import KnowledgePackageService
from video_account_distiller.models import (
    AccountVideoKnowledgeDocument,
    AccountVideoKnowledgeManifest,
)
from video_account_distiller.storage import ProjectLayout
from video_account_distiller.utils.io import atomic_write_json, atomic_write_text
from video_account_distiller_desktop.main import _configure_windows_error_mode


class _Response:
    def __init__(self, payload: dict[str, Any], status_code: int = 200) -> None:
        self.payload = payload
        self.status_code = status_code
        self.ok = status_code < 400

    def json(self) -> dict[str, Any]:
        return self.payload


class _Session:
    def __init__(self, response: _Response) -> None:
        self.response = response
        self.calls: list[dict[str, Any]] = []
        self.closed = False

    def request(self, method: str, url: str, **kwargs: Any) -> _Response:
        self.calls.append({"method": method, "url": url, **kwargs})
        return self.response

    def close(self) -> None:
        self.closed = True


class _PagedSession:
    def __init__(self, responses: list[_Response]) -> None:
        self.responses = responses
        self.calls: list[dict[str, Any]] = []

    def request(self, method: str, url: str, **kwargs: Any) -> _Response:
        self.calls.append({"method": method, "url": url, **kwargs})
        return self.responses.pop(0)

    def close(self) -> None:
        return None


@pytest.mark.skipif(os.name != "nt", reason="Windows error mode is Windows-specific")
def test_desktop_error_mode_preserves_existing_flags_and_adds_fail_critical_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _Kernel32:
        def __init__(self) -> None:
            self.modes: list[int] = []

        @staticmethod
        def GetErrorMode() -> int:
            return 0x0040

        def SetErrorMode(self, mode: int) -> int:
            self.modes.append(mode)
            return 0x0040

    kernel32 = _Kernel32()
    monkeypatch.setattr(ctypes.windll, "kernel32", kernel32)

    _configure_windows_error_mode()

    assert kernel32.modes == [0x0041]


def test_desktop_api_client_encodes_project_path_and_surfaces_stable_errors(
    tmp_path: Path,
) -> None:
    session = _Session(_Response({"ok": True, "tasks": []}))
    client = DesktopApiClient("http://127.0.0.1:8123", session=session)  # type: ignore[arg-type]

    assert client.list_tasks() == []
    client.validate_project(tmp_path / "project folder")

    assert session.calls[1]["url"].endswith("/validate")
    assert "%20" in session.calls[1]["url"]
    client.close()
    assert session.closed is True

    failure = _Session(
        _Response(
            {
                "ok": False,
                "error": {
                    "code": "E_TEST",
                    "message": "可重试错误",
                    "details": {"retryable": True},
                },
            },
            409,
        )
    )
    with pytest.raises(DesktopApiError, match="可重试错误") as raised:
        DesktopApiClient("http://local", session=failure).health()  # type: ignore[arg-type]
    assert raised.value.code == "E_TEST"
    assert raised.value.details == {"retryable": True}


def test_desktop_api_client_lists_latest_project_accounts_across_pages(
    tmp_path: Path,
) -> None:
    session = _PagedSession(
        [
            _Response(
                {
                    "ok": True,
                    "data": {
                        "total": 4,
                        "rows": [
                            {
                                "account_id": "acc_repeat",
                                "display_name": "旧名称",
                                "snapshot_at": "2026-08-01T08:00:00+00:00",
                            },
                            {
                                "account_id": "acc_recent",
                                "display_name": "最近账号",
                                "snapshot_at": "2026-09-03T09:00:00+00:00",
                            },
                        ],
                    },
                }
            ),
            _Response(
                {
                    "ok": True,
                    "data": {
                        "total": 4,
                        "rows": [
                            {
                                "account_id": " acc_repeat ",
                                "display_name": "新名称",
                                "snapshot_at": "2026-09-02T08:00:00Z",
                            },
                            {
                                "display_name": "缺少账号 ID",
                                "snapshot_at": "2026-09-03T10:00:00+00:00",
                            },
                        ],
                    },
                }
            ),
        ]
    )
    client = DesktopApiClient("http://127.0.0.1:8123", session=session)  # type: ignore[arg-type]

    accounts = client.list_project_accounts(tmp_path / "project folder", page_size=2)

    assert [item["account_id"] for item in accounts] == ["acc_recent", "acc_repeat"]
    assert accounts[1]["display_name"] == "新名称"
    assert len(session.calls) == 2
    assert session.calls[0]["params"] == {"table": "accounts", "limit": 2, "offset": 0}
    assert session.calls[1]["params"] == {"table": "accounts", "limit": 2, "offset": 2}
    assert "%20" in session.calls[0]["url"]


def test_desktop_api_client_bounds_account_page_size(tmp_path: Path) -> None:
    session = _PagedSession([_Response({"ok": True, "data": {"total": 0, "rows": []}})])
    client = DesktopApiClient("http://127.0.0.1:8123", session=session)  # type: ignore[arg-type]

    assert client.list_project_accounts(tmp_path, page_size=10_000) == []

    assert session.calls[0]["params"] == {"table": "accounts", "limit": 500, "offset": 0}


def test_desktop_settings_store_serializes_no_secret_fields(tmp_path: Path) -> None:
    path = tmp_path / "settings.json"
    store = DesktopSettingsStore(path)
    settings = DesktopSettings(project_path=str(tmp_path), weknora_kb_id="kb-demo")

    store.save(settings)

    serialized = path.read_text(encoding="utf-8")
    assert "api_key" not in serialized
    assert "secret" not in serialized
    assert store.load() == settings


def test_desktop_secret_store_uses_desktop_scoped_keyring_name(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    values: dict[tuple[str, str], str] = {}
    monkeypatch.setattr(
        "keyring.get_password",
        lambda service, username: values.get((service, username)),
    )
    monkeypatch.setattr(
        "keyring.set_password",
        lambda service, username, value: values.__setitem__((service, username), value),
    )
    monkeypatch.setattr(
        "keyring.delete_password",
        lambda service, username: values.pop((service, username)),
    )
    store = DesktopSecretStore()

    store.set("weknora-api-key", "  wk-secret  ")

    assert store.get("weknora-api-key") == "wk-secret"
    assert values[(DESKTOP_KEYRING_SERVICE, "desktop:weknora-api-key")] == "wk-secret"
    assert store.delete("weknora-api-key") is True


def _knowledge_bundle(project: ProjectLayout) -> Path:
    account_id = "acc_desktop"
    manifest_id = "avk_desktop"
    root = project.root / "knowledge" / "accounts" / account_id / "video-knowledge" / manifest_id
    document = root / "documents" / "酒店AI前台完整指南.md"
    atomic_write_text(document, "# 酒店AI前台完整指南\n")
    atomic_write_text(root / "README.md", "# 索引\n")
    manifest = AccountVideoKnowledgeManifest(
        manifest_id=manifest_id,
        manifest_version="1.0.0",
        account_id=account_id,
        generated_at=datetime.now(UTC),
        run_id="run_desktop",
        status="complete",
        requested_count=1,
        eligible_count=1,
        completed_count=1,
        degraded_count=0,
        skipped_count=0,
        documents=[
            AccountVideoKnowledgeDocument(
                video_id="vid_desktop",
                title="酒店AI前台完整指南",
                knowledge_id="svk_desktop",
                status="complete",
                source_path="analyses/videos/vid_desktop/knowledge/svk_desktop/knowledge.md",
                document_path=project.relative(document),
            )
        ],
    )
    path = root / "manifest.json"
    atomic_write_json(path, manifest.model_dump(mode="json"))
    return path


def test_knowledge_package_service_discovers_and_exports_title_documents(
    project: ProjectLayout,
    tmp_path: Path,
) -> None:
    manifest_path = _knowledge_bundle(project)
    service = KnowledgePackageService(project)

    bundles = service.list_bundles()
    output = service.export_zip(manifest_path, destination_dir=tmp_path / "exports")

    assert len(bundles) == 1
    assert bundles[0].document_count == 1
    assert bundles[0].missing_count == 0
    with zipfile.ZipFile(output) as archive:
        assert archive.namelist() == [
            "manifest.json",
            "README.md",
            "documents/酒店AI前台完整指南.md",
        ]
        payload = json.loads(archive.read("manifest.json"))
        assert payload["manifest_id"] == "avk_desktop"
