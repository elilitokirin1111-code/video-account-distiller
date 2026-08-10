"""One-way Distiller-to-WeKnora knowledge base synchronization."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path
from typing import Any

import requests

from video_account_distiller.errors import DistillerError, ErrorCode
from video_account_distiller.knowledge.obsidian import (
    HUMAN_DIR_NAME,
    ObsidianVaultExporter,
)
from video_account_distiller.storage.project import ProjectLayout

DEFAULT_WEKNORA_BASE_URL = "http://127.0.0.1:8080"
DEFAULT_WEKNORA_KB_NAME = "视频账号蒸馏"


def _api_url(base_url: str) -> str:
    return base_url.rstrip("/") + "/api/v1"


class WeKnoraSyncService:
    """Export the human-readable analysis reports and upload them to WeKnora."""

    def __init__(self, project: ProjectLayout) -> None:
        self.project = project

    def _find_kb(self, api: str, headers: dict[str, str], kb_name: str) -> str | None:
        response = requests.get(
            f"{api}/knowledge-bases",
            headers=headers,
            timeout=30,
        )
        if response.status_code == 401:
            raise DistillerError(
                ErrorCode.ADAPTER_AUTH,
                "WeKnora API Key rejected (401)",
            )
        if not response.ok:
            raise DistillerError(
                ErrorCode.ADAPTER_RESPONSE,
                f"WeKnora knowledge-base list failed: HTTP {response.status_code}",
            )
        payload = response.json()
        items = payload.get("data") if isinstance(payload, dict) else None
        if not isinstance(items, list):
            return None
        for item in items:
            if isinstance(item, dict) and item.get("name") == kb_name:
                return str(item.get("id") or "")
        return None

    def sync_account(
        self,
        *,
        account_id: str,
        base_url: str = DEFAULT_WEKNORA_BASE_URL,
        api_key: str,
        kb_name: str = DEFAULT_WEKNORA_KB_NAME,
        max_video_analyses: int = 10,
    ) -> dict[str, Any]:
        if not base_url.strip():
            raise DistillerError(ErrorCode.SCHEMA_INVALID, "WeKnora base URL is required")
        if not api_key.strip():
            raise DistillerError(
                ErrorCode.ADAPTER_AUTH,
                "WeKnora API Key is required",
                details={"next": "在 WeKnora 账户页面获取 API Key"},
            )
        if not kb_name.strip():
            kb_name = DEFAULT_WEKNORA_KB_NAME
        headers = {"X-API-Key": api_key.strip()}
        api = _api_url(base_url)
        kb_id = self._find_kb(api, headers, kb_name)
        if not kb_id:
            raise DistillerError(
                ErrorCode.SCHEMA_INVALID,
                "WeKnora target knowledge base was not found or is not visible to this API Key",
                details={
                    "kb_name": kb_name,
                    "next": (
                        "先在 WeKnora 创建目标知识库，并为当前 API Key 授予该知识库的"
                        "文档上传/编辑权限，再返回此处导入。"
                    ),
                },
            )

        with tempfile.TemporaryDirectory(prefix="distiller-weknora-") as temporary:
            vault = Path(temporary)
            export = ObsidianVaultExporter(self.project).export_account(
                account_id=account_id,
                vault_path=str(vault),
                max_video_analyses=max_video_analyses,
            )
            human_dir = vault / export["account_folder"] / HUMAN_DIR_NAME
            uploaded: list[str] = []
            errors: list[str] = []
            for path in sorted(human_dir.glob("*.md")):
                relative_name = (
                    f"{export['account_folder']}/{HUMAN_DIR_NAME}/{path.name}"
                ).replace("\\", "/")
                try:
                    with path.open("rb") as handle:
                        response = requests.post(
                            f"{api}/knowledge-bases/{kb_id}/knowledge/file",
                            headers=headers,
                            files={"file": (path.name, handle, "text/markdown")},
                            data={
                                "fileName": relative_name,
                                "metadata": json.dumps(
                                    {
                                        "source": "video-account-distiller",
                                        "account_id": account_id,
                                    },
                                    ensure_ascii=False,
                                ),
                                "channel": "distiller",
                            },
                            timeout=180,
                        )
                    if response.status_code in {200, 409}:
                        uploaded.append(relative_name)
                    else:
                        errors.append(
                            f"{path.name}: HTTP {response.status_code} {response.text[:200]}"
                        )
                except requests.RequestException as exc:
                    errors.append(f"{path.name}: {exc}")

        error_code: str | None = None
        message: str | None = None
        scope_rejected = any(": HTTP 403" in error and '"code":1002' in error for error in errors)
        if scope_rejected:
            error_code = "API_KEY_SCOPE_NOT_ALLOWED"
            message = (
                "WeKnora API Key 无权向此知识库上传文件。请在 WeKnora 的 API Key 设置中，"
                "为目标知识库授予文档上传/编辑权限后重试。"
            )
        elif errors:
            message = "WeKnora 未能完成全部文件上传。"

        return {
            "ok": not errors,
            "kb_id": kb_id,
            "kb_name": kb_name,
            "uploaded": uploaded,
            "errors": errors,
            "error_code": error_code,
            "message": message,
        }
