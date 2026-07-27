"""Persistent background-task execution for API endpoints."""

from __future__ import annotations

import asyncio
import json
import os
import sqlite3
import threading
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, TypeAlias

from fastapi.encoders import jsonable_encoder

from video_account_distiller.errors import DistillerError, ErrorCode
from video_account_distiller.utils.ids import new_run_id

TaskData: TypeAlias = dict[str, Any]


def default_task_db_path() -> Path:
    """Return the persistent API task database path."""
    configured = os.environ.get("DISTILLER_TASK_DB")
    if configured:
        return Path(configured).expanduser().resolve()
    return Path.home() / ".video-account-distiller" / "api" / "tasks.sqlite3"


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _json(payload: TaskData) -> str:
    encoded = jsonable_encoder(payload)
    return json.dumps(encoded, ensure_ascii=False, separators=(",", ":"))


class TaskStore:
    """Small SQLite-backed store whose records survive API restarts."""

    def __init__(self, path: Path | str | None = None) -> None:
        self.path = Path(path) if path is not None else default_task_db_path()
        self.path = self.path.expanduser().resolve()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._initialize()
        self.recover_interrupted()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=30)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA busy_timeout = 30000")
        return connection

    @contextmanager
    def _connection(self) -> Iterator[sqlite3.Connection]:
        connection = self._connect()
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    def _initialize(self) -> None:
        with self._lock, self._connection() as connection:
            connection.execute("PRAGMA journal_mode = WAL")
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS api_tasks (
                    task_id TEXT PRIMARY KEY,
                    status TEXT NOT NULL,
                    progress REAL NOT NULL,
                    payload_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            connection.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_api_tasks_updated_at
                ON api_tasks(updated_at DESC)
                """
            )

    def create(self, task_id: str) -> TaskData:
        created_at = _now()
        payload: TaskData = {
            "task_id": task_id,
            "status": "pending",
            "progress": 0.0,
            "created_at": created_at,
            "updated_at": created_at,
        }
        with self._lock, self._connection() as connection:
            connection.execute(
                """
                INSERT INTO api_tasks(
                    task_id, status, progress, payload_json, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (task_id, "pending", 0.0, _json(payload), created_at, created_at),
            )
        return payload

    def update(self, task_id: str, **changes: Any) -> TaskData:
        with self._lock, self._connection() as connection:
            row = connection.execute(
                "SELECT payload_json FROM api_tasks WHERE task_id = ?",
                (task_id,),
            ).fetchone()
            if row is None:
                raise KeyError(task_id)
            payload = json.loads(str(row["payload_json"]))
            if not isinstance(payload, dict):
                raise ValueError(f"Invalid task payload: {task_id}")
            payload.update(changes)
            payload["updated_at"] = _now()
            status = str(payload.get("status", "pending"))
            progress = float(payload.get("progress", 0.0))
            connection.execute(
                """
                UPDATE api_tasks
                SET status = ?, progress = ?, payload_json = ?, updated_at = ?
                WHERE task_id = ?
                """,
                (status, progress, _json(payload), payload["updated_at"], task_id),
            )
        return payload

    def get(self, task_id: str) -> TaskData | None:
        with self._lock, self._connection() as connection:
            row = connection.execute(
                "SELECT payload_json FROM api_tasks WHERE task_id = ?",
                (task_id,),
            ).fetchone()
        if row is None:
            return None
        payload = json.loads(str(row["payload_json"]))
        return payload if isinstance(payload, dict) else None

    def list(self, *, limit: int = 50, status: str | None = None) -> list[TaskData]:
        bounded_limit = min(max(limit, 1), 200)
        with self._lock, self._connection() as connection:
            if status is None:
                rows = connection.execute(
                    """
                    SELECT payload_json FROM api_tasks
                    ORDER BY updated_at DESC LIMIT ?
                    """,
                    (bounded_limit,),
                ).fetchall()
            else:
                rows = connection.execute(
                    """
                    SELECT payload_json FROM api_tasks
                    WHERE status = ? ORDER BY updated_at DESC LIMIT ?
                    """,
                    (status, bounded_limit),
                ).fetchall()
        tasks: list[TaskData] = []
        for row in rows:
            payload = json.loads(str(row["payload_json"]))
            if isinstance(payload, dict):
                tasks.append(payload)
        return tasks

    def recover_interrupted(self) -> int:
        """Mark work abandoned by a previous process as explicitly failed."""
        with self._lock, self._connection() as connection:
            rows = connection.execute(
                """
                SELECT task_id, payload_json FROM api_tasks
                WHERE status IN ('pending', 'running')
                """
            ).fetchall()
            for row in rows:
                payload = json.loads(str(row["payload_json"]))
                if not isinstance(payload, dict):
                    payload = {"task_id": str(row["task_id"])}
                payload.update(
                    status="failed",
                    progress=1.0,
                    error={
                        "code": ErrorCode.TASK_INTERRUPTED.value,
                        "message": "Task was interrupted by an API restart",
                        "details": {"retryable": True},
                    },
                    updated_at=_now(),
                )
                connection.execute(
                    """
                    UPDATE api_tasks
                    SET status = 'failed', progress = 1.0,
                        payload_json = ?, updated_at = ?
                    WHERE task_id = ?
                    """,
                    (_json(payload), payload["updated_at"], str(row["task_id"])),
                )
        return len(rows)


def enqueue_task(
    tasks: TaskStore,
    fn: Callable[..., Any],
    *args: Any,
    **kwargs: Any,
) -> TaskData:
    """Run one blocking service call in a worker thread and expose its status."""
    task_id = new_run_id()
    tasks.create(task_id)

    async def _runner() -> None:
        try:
            tasks.update(task_id, status="running")
            result = await asyncio.to_thread(fn, *args, **kwargs)
            tasks.update(task_id, status="completed", progress=1.0, result=result)
        except DistillerError as exc:
            tasks.update(
                task_id,
                status="failed",
                progress=1.0,
                error=exc.as_dict()["error"],
            )
        except Exception as exc:
            tasks.update(
                task_id,
                status="failed",
                progress=1.0,
                error={"code": "E_INTERNAL", "message": str(exc), "details": {}},
            )

    asyncio.create_task(_runner())
    return {"ok": True, "task_id": task_id, "status": "pending"}
