from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import requests

from video_account_distiller.errors import DistillerError, ErrorCode
from video_account_distiller.knowledge.obsidian import HUMAN_DIR_NAME
from video_account_distiller.knowledge.weknora import WeKnoraSyncService, _api_url
from video_account_distiller.storage.project import ProjectLayout


class _Response:
    def __init__(self, status_code: int, payload: dict[str, Any], text: str) -> None:
        self.status_code = status_code
        self._payload = payload
        self.text = text

    @property
    def ok(self) -> bool:
        return 200 <= self.status_code < 400

    def json(self) -> dict[str, Any]:
        return self._payload


class _Export:
    def __init__(self, _: ProjectLayout) -> None:
        pass

    def export_account(
        self,
        *,
        account_id: str,
        vault_path: str,
        max_video_analyses: int,
    ) -> dict[str, str]:
        report_dir = Path(vault_path) / "account" / HUMAN_DIR_NAME
        report_dir.mkdir(parents=True)
        (report_dir / "report.md").write_text("# report", encoding="utf-8")
        return {"account_folder": "account"}


@pytest.mark.parametrize(
    ("base_url", "expected"),
    [
        ("http://localhost", "http://localhost/api/v1"),
        ("http://localhost/", "http://localhost/api/v1"),
        ("http://localhost/api/v1", "http://localhost/api/v1"),
        ("http://localhost/api/v1/", "http://localhost/api/v1"),
    ],
)
def test_weknora_api_url_accepts_root_or_full_api_url(
    base_url: str,
    expected: str,
) -> None:
    assert _api_url(base_url) == expected


def test_weknora_gateway_error_points_to_direct_backend(
    project: ProjectLayout, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        requests,
        "get",
        lambda *args, **kwargs: _Response(502, {}, "Bad Gateway"),
    )

    with pytest.raises(DistillerError) as exc_info:
        WeKnoraSyncService(project).list_knowledge_bases(
            base_url="http://localhost/api/v1",
            api_key="sk-test",
        )

    assert exc_info.value.code is ErrorCode.ADAPTER_RESPONSE
    assert "127.0.0.1:8080" in exc_info.value.message


def test_weknora_scope_rejection_has_actionable_error(
    project: ProjectLayout, monkeypatch: pytest.MonkeyPatch
) -> None:
    post_urls: list[str] = []

    def _reject_upload(url: str, *args: Any, **kwargs: Any) -> _Response:
        post_urls.append(url)
        return _Response(
            403,
            {},
            '{"error":{"code":1002,"message":"scope denied"},"success":false}',
        )

    monkeypatch.setattr("video_account_distiller.knowledge.weknora.ObsidianVaultExporter", _Export)
    monkeypatch.setattr(
        requests,
        "get",
        lambda *args, **kwargs: _Response(
            200,
            {
                "data": [
                    {"id": "kb-old", "name": "target"},
                    {"id": "kb-1", "name": "target"},
                ]
            },
            "",
        ),
    )
    monkeypatch.setattr(requests, "post", _reject_upload)

    result = WeKnoraSyncService(project).sync_account(
        account_id="account-id",
        base_url="http://localhost:8080",
        api_key="sk-test",
        kb_id="kb-1",
    )

    assert result["ok"] is False
    assert result["kb_id"] == "kb-1"
    assert result["error_code"] == "API_KEY_SCOPE_NOT_ALLOWED"
    assert "API Key" in str(result["message"])
    assert post_urls
    assert all("/knowledge-bases/kb-1/" in url for url in post_urls)


def test_weknora_requires_an_existing_visible_knowledge_base(
    project: ProjectLayout, monkeypatch: pytest.MonkeyPatch
) -> None:
    post_calls: list[object] = []
    monkeypatch.setattr(
        requests,
        "get",
        lambda *args, **kwargs: _Response(
            200,
            {"data": [{"id": "kb-other", "name": "other"}]},
            "",
        ),
    )
    monkeypatch.setattr(
        requests,
        "post",
        lambda *args, **kwargs: post_calls.append(args),
    )

    with pytest.raises(DistillerError) as exc_info:
        WeKnoraSyncService(project).sync_account(
            account_id="account-id",
            base_url="http://localhost:8080",
            api_key="sk-test",
            kb_id="kb-missing",
        )

    assert exc_info.value.code is ErrorCode.SCHEMA_INVALID
    assert "not found" in exc_info.value.message
    assert post_calls == []
