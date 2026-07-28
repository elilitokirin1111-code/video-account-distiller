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
ProgressCallback: TypeAlias = Callable[[float, str, str], None]
CheckpointCallback: TypeAlias = Callable[[str, dict[str, Any]], None]


class TaskCancellationRequested(Exception):
    """Internal cooperative-cancellation signal for background workers."""


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

    def create(
        self,
        task_id: str,
        *,
        initial: TaskData | None = None,
    ) -> TaskData:
        created_at = _now()
        payload: TaskData = {
            "task_id": task_id,
            "status": "pending",
            "progress": 0.0,
            "created_at": created_at,
            "updated_at": created_at,
        }
        if initial:
            payload.update(initial)
        payload.update(
            task_id=task_id,
            status="pending",
            progress=0.0,
            created_at=created_at,
            updated_at=created_at,
        )
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

    def request_cancel(self, task_id: str) -> TaskData:
        """Request cooperative cancellation without terminating worker threads."""
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

            status = str(payload.get("status", "pending"))
            if status in {"completed", "failed", "cancelled"}:
                return payload
            if status == "pending":
                payload.update(
                    status="cancelled",
                    stage="cancelled",
                    message="任务已在启动前取消",
                    cancel_requested=True,
                )
            else:
                payload.update(
                    status="cancelling",
                    message="正在安全取消；当前不可中断步骤结束后生效",
                    cancel_requested=True,
                )
            payload["updated_at"] = _now()
            connection.execute(
                """
                UPDATE api_tasks
                SET status = ?, progress = ?, payload_json = ?, updated_at = ?
                WHERE task_id = ?
                """,
                (
                    str(payload["status"]),
                    float(payload.get("progress", 0.0)),
                    _json(payload),
                    payload["updated_at"],
                    task_id,
                ),
            )
        return payload

    def cancellation_requested(self, task_id: str) -> bool:
        """Return whether a task has received a cancellation request."""
        task = self.get(task_id)
        return bool(
            task
            and (task.get("cancel_requested") or task.get("status") in {"cancelling", "cancelled"})
        )

    def recover_interrupted(self) -> int:
        """Mark work abandoned by a previous process as explicitly failed."""
        with self._lock, self._connection() as connection:
            cancelling_rows = connection.execute(
                """
                SELECT task_id, payload_json FROM api_tasks
                WHERE status = 'cancelling'
                """
            ).fetchall()
            for row in cancelling_rows:
                payload = json.loads(str(row["payload_json"]))
                if not isinstance(payload, dict):
                    payload = {"task_id": str(row["task_id"])}
                payload.update(
                    status="cancelled",
                    stage="cancelled",
                    message="任务已在应用重启时完成取消",
                    cancel_requested=True,
                    updated_at=_now(),
                )
                connection.execute(
                    """
                    UPDATE api_tasks
                    SET status = 'cancelled', payload_json = ?, updated_at = ?
                    WHERE task_id = ?
                    """,
                    (_json(payload), payload["updated_at"], str(row["task_id"])),
                )

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
        return len(rows) + len(cancelling_rows)


def _mark_cancelled(tasks: TaskStore, task_id: str) -> TaskData:
    current = tasks.get(task_id) or {}
    return tasks.update(
        task_id,
        status="cancelled",
        progress=float(current.get("progress", 0.0)),
        stage="cancelled",
        message="任务已安全取消",
        cancel_requested=True,
    )


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
            if tasks.cancellation_requested(task_id):
                _mark_cancelled(tasks, task_id)
                return
            tasks.update(task_id, status="running")
            result = await asyncio.to_thread(fn, *args, **kwargs)
            if tasks.cancellation_requested(task_id):
                _mark_cancelled(tasks, task_id)
                return
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


def enqueue_progress_task(
    tasks: TaskStore,
    fn: Callable[..., Any],
    *args: Any,
    task_type: str = "workflow",
    task_metadata: TaskData | None = None,
    resume_state: dict[str, Any] | None = None,
    retried_from: str | None = None,
    **kwargs: Any,
) -> TaskData:
    """Run a blocking workflow while persisting its current stage and progress."""

    task_id = new_run_id()
    initial: TaskData = {
        "task_type": task_type,
        "stage": "pending",
        "message": "任务已进入本地队列",
        "retryable": task_metadata is not None,
    }
    if task_metadata is not None:
        initial["task_metadata"] = task_metadata
    if resume_state is not None:
        initial["checkpoint"] = resume_state
    if retried_from is not None:
        initial["retried_from"] = retried_from
    tasks.create(task_id, initial=initial)

    def _raise_if_cancelled() -> None:
        if tasks.cancellation_requested(task_id):
            raise TaskCancellationRequested

    def _progress(value: float, stage: str, message: str) -> None:
        _raise_if_cancelled()
        bounded = min(max(float(value), 0.0), 1.0)
        tasks.update(
            task_id,
            status="running",
            progress=bounded,
            stage=stage,
            message=message,
        )

    def _checkpoint(stage: str, state: dict[str, Any]) -> None:
        tasks.update(
            task_id,
            checkpoint_stage=stage,
            checkpoint=state,
        )
        _raise_if_cancelled()

    async def _runner() -> None:
        try:
            _raise_if_cancelled()
            tasks.update(
                task_id,
                status="running",
                task_type=task_type,
                stage="starting",
                message="正在启动工作流",
            )
            _raise_if_cancelled()
            result = await asyncio.to_thread(
                fn,
                *args,
                progress=_progress,
                checkpoint=_checkpoint,
                resume_state=resume_state,
                **kwargs,
            )
            _raise_if_cancelled()
            tasks.update(
                task_id,
                status="completed",
                progress=1.0,
                stage="completed",
                message="工作流已完成",
                result=result,
            )
        except TaskCancellationRequested:
            _mark_cancelled(tasks, task_id)
        except DistillerError as exc:
            if tasks.cancellation_requested(task_id):
                _mark_cancelled(tasks, task_id)
                return
            tasks.update(
                task_id,
                status="failed",
                progress=1.0,
                stage="failed",
                message=exc.message,
                error=exc.as_dict()["error"],
            )
        except Exception as exc:
            if tasks.cancellation_requested(task_id):
                _mark_cancelled(tasks, task_id)
                return
            tasks.update(
                task_id,
                status="failed",
                progress=1.0,
                stage="failed",
                message=str(exc),
                error={"code": "E_INTERNAL", "message": str(exc), "details": {}},
            )

    asyncio.create_task(_runner())
    submission: TaskData = {
        "ok": True,
        "task_id": task_id,
        "task_type": task_type,
        "status": "pending",
    }
    if retried_from is not None:
        submission["retried_from"] = retried_from
    return submission
