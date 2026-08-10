from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import requests

from video_account_distiller.errors import DistillerError, ErrorCode
from video_account_distiller.knowledge.obsidian import HUMAN_DIR_NAME
from video_account_distiller.knowledge.weknora import WeKnoraSyncService
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
