"""Typed, synchronous client for the desktop application's embedded REST API."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import quote

import requests


class DesktopApiError(RuntimeError):
    """Human-readable local API error without exposing request secrets."""

    def __init__(
        self,
        message: str,
        *,
        code: str | None = None,
        status_code: int | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.status_code = status_code
        self.details = details or {}


def _project_path(value: Path | str) -> str:
    return quote(str(Path(value).expanduser().resolve()), safe="")


def _account_snapshot_timestamp(value: object) -> float:
    """Return a comparable timestamp while tolerating legacy account rows."""

    if not isinstance(value, str) or not value.strip():
        return float("-inf")
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        return float("-inf")
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    try:
        return parsed.timestamp()
    except (OSError, OverflowError, ValueError):
        return float("-inf")


class DesktopApiClient:
    """Small application boundary used by Qt and headless smoke tests."""

    def __init__(
        self,
        base_url: str,
        *,
        timeout_seconds: float = 20.0,
        session: requests.Session | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds
        self.session = session or requests.Session()

    def close(self) -> None:
        self.session.close()

    def _request(
        self,
        method: str,
        path: str,
        *,
        json: dict[str, Any] | None = None,
        params: dict[str, Any] | None = None,
        timeout_seconds: float | None = None,
    ) -> dict[str, Any]:
        try:
            response = self.session.request(
                method,
                f"{self.base_url}{path}",
                json=json,
                params=params,
                timeout=timeout_seconds or self.timeout_seconds,
            )
        except requests.RequestException as exc:
            raise DesktopApiError(
                "本地蒸馏服务暂时不可用，请检查服务状态后重试。",
                code="LOCAL_SERVICE_UNAVAILABLE",
            ) from exc
        try:
            payload = response.json()
        except ValueError as exc:
            raise DesktopApiError(
                f"本地服务返回了无法解析的响应（HTTP {response.status_code}）。",
                code="INVALID_LOCAL_RESPONSE",
                status_code=response.status_code,
            ) from exc
        if response.ok and isinstance(payload, dict):
            return payload
        error = payload.get("error") if isinstance(payload, dict) else None
        detail = payload.get("detail") if isinstance(payload, dict) else None
        if isinstance(error, dict):
            message = str(error.get("message") or detail or "请求失败")
            code = str(error.get("code")) if error.get("code") else None
            details = error.get("details") if isinstance(error.get("details"), dict) else {}
        else:
            message = str(detail or "请求失败")
            code = None
            details = {}
        raise DesktopApiError(
            message,
            code=code,
            status_code=response.status_code,
            details=details,
        )

    def health(self) -> dict[str, Any]:
        return self._request("GET", "/api/health", timeout_seconds=3)

    def initialize_project(self, path: Path | str, *, name: str | None = None) -> dict[str, Any]:
        return self._request(
            "POST",
            "/api/projects/init",
            json={"path": str(Path(path).expanduser().resolve()), "name": name or None},
        )

    def validate_project(self, path: Path | str) -> dict[str, Any]:
        return self._request("GET", f"/api/projects/{_project_path(path)}/validate")

    def project_status(self, path: Path | str) -> dict[str, Any]:
        return self._request("GET", f"/api/projects/{_project_path(path)}/status")

    def list_project_accounts(
        self,
        project_path: Path | str,
        *,
        page_size: int = 500,
    ) -> list[dict[str, Any]]:
        """List the latest normalized row for every account in a project."""

        bounded_page_size = min(max(page_size, 1), 500)
        offset = 0
        rows: list[dict[str, Any]] = []
        while True:
            payload = self._request(
                "GET",
                f"/api/projects/{_project_path(project_path)}/data",
                params={
                    "table": "accounts",
                    "limit": bounded_page_size,
                    "offset": offset,
                },
                timeout_seconds=10,
            )
            data = payload.get("data")
            if not isinstance(data, dict):
                break
            raw_rows = data.get("rows")
            if not isinstance(raw_rows, list) or not raw_rows:
                break
            rows.extend(item for item in raw_rows if isinstance(item, dict))
            offset += len(raw_rows)
            try:
                total = max(int(data.get("total") or 0), 0)
            except (TypeError, ValueError):
                total = 0
            if (total and offset >= total) or len(raw_rows) < bounded_page_size:
                break

        latest_by_id: dict[str, dict[str, Any]] = {}
        for row in rows:
            account_id = str(row.get("account_id") or "").strip()
            if not account_id:
                continue
            candidate = dict(row)
            candidate["account_id"] = account_id
            current = latest_by_id.get(account_id)
            if current is None or _account_snapshot_timestamp(
                candidate.get("snapshot_at")
            ) >= _account_snapshot_timestamp(current.get("snapshot_at")):
                latest_by_id[account_id] = candidate

        return sorted(
            latest_by_id.values(),
            key=lambda item: (
                _account_snapshot_timestamp(item.get("snapshot_at")),
                str(item.get("account_id") or ""),
            ),
            reverse=True,
        )

    def submit_account_distill(
        self,
        project_path: Path | str,
        payload: dict[str, Any],
        *,
        dry_run: bool = False,
    ) -> dict[str, Any]:
        return self._request(
            "POST",
            f"/api/projects/{_project_path(project_path)}/workflows/account-distill",
            params={"dry_run": str(dry_run).lower()},
            json=payload,
        )

    def distill_existing_account_knowledge(
        self,
        project_path: Path | str,
        account_id: str,
        payload: dict[str, Any],
        *,
        dry_run: bool = False,
    ) -> dict[str, Any]:
        return self._request(
            "POST",
            (
                f"/api/projects/{_project_path(project_path)}/knowledge/local/accounts/"
                f"{quote(account_id, safe='')}/distill-videos"
            ),
            params={"dry_run": str(dry_run).lower()},
            json=payload,
        )

    def list_tasks(self, *, limit: int = 50, status: str | None = None) -> list[dict[str, Any]]:
        params: dict[str, Any] = {"limit": limit}
        if status:
            params["status"] = status
        payload = self._request("GET", "/api/tasks", params=params, timeout_seconds=5)
        tasks = payload.get("tasks")
        return [item for item in tasks if isinstance(item, dict)] if isinstance(tasks, list) else []

    def task_queue_status(self) -> dict[str, Any]:
        return self._request("GET", "/api/task-queue", timeout_seconds=5)

    def get_task(self, task_id: str) -> dict[str, Any]:
        return self._request("GET", f"/api/tasks/{quote(task_id, safe='')}")

    def cancel_task(self, task_id: str) -> dict[str, Any]:
        return self._request("POST", f"/api/tasks/{quote(task_id, safe='')}/cancel")

    def retry_task(
        self,
        task_id: str,
        *,
        overrides: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return self._request(
            "POST",
            f"/api/tasks/{quote(task_id, safe='')}/retry",
            json={"overrides": overrides} if overrides else {},
        )

    def list_weknora_knowledge_bases(
        self,
        project_path: Path | str,
        *,
        base_url: str,
        api_key: str,
    ) -> list[dict[str, Any]]:
        payload = self._request(
            "POST",
            f"/api/projects/{_project_path(project_path)}/knowledge/weknora/knowledge-bases",
            json={"base_url": base_url, "api_key": api_key},
            timeout_seconds=45,
        )
        values = payload.get("knowledge_bases")
        return (
            [item for item in values if isinstance(item, dict)] if isinstance(values, list) else []
        )

    def sync_account_weknora(
        self,
        project_path: Path | str,
        *,
        account_id: str,
        base_url: str,
        api_key: str,
        kb_id: str,
        distillation_mode: str,
    ) -> dict[str, Any]:
        return self._request(
            "POST",
            (
                f"/api/projects/{_project_path(project_path)}/knowledge/weknora/accounts/"
                f"{quote(account_id, safe='')}/sync"
            ),
            json={
                "base_url": base_url,
                "api_key": api_key,
                "kb_id": kb_id,
                "distillation_mode": distillation_mode,
            },
            timeout_seconds=180,
        )

    def save_cloud_credential(self, provider: str, api_key: str) -> dict[str, Any]:
        return self._request(
            "PUT",
            f"/api/cloud-model/credentials/{quote(provider, safe='')}",
            json={"api_key": api_key},
            timeout_seconds=45,
        )

    def delete_cloud_credential(self, provider: str) -> dict[str, Any]:
        return self._request(
            "DELETE",
            f"/api/cloud-model/credentials/{quote(provider, safe='')}",
        )
