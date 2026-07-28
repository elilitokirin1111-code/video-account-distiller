"""Persistent background-task execution for API endpoints."""

from __future__ import annotations

import asyncio
import json
import os
import sqlite3
import threading
from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, TypeAlias

from fastapi.encoders import jsonable_encoder
from pydantic import BaseModel, Field, model_validator

from video_account_distiller.errors import DistillerError, ErrorCode
from video_account_distiller.utils.ids import new_run_id

TaskData: TypeAlias = dict[str, Any]
ProgressCallback: TypeAlias = Callable[[float, str, str], None]
CheckpointCallback: TypeAlias = Callable[[str, dict[str, Any]], None]


class TaskCancellationRequested(Exception):
    """Internal cooperative-cancellation signal for background workers."""


class TaskLeaseLost(Exception):
    """Internal signal raised when another process owns or recovered a task."""


class TaskQueueSettings(BaseModel):
    """Bounded settings shared by every worker using one task database."""

    max_concurrent: int = Field(default=2, ge=1, le=32)
    max_pending: int = Field(default=100, ge=1, le=10_000)
    workflow_concurrency: int = Field(default=1, ge=1, le=32)
    lease_seconds: int = Field(default=120, ge=15, le=3_600)
    poll_interval_seconds: float = Field(default=0.05, ge=0.01, le=5.0)

    @model_validator(mode="after")
    def _validate_resource_limits(self) -> TaskQueueSettings:
        if self.workflow_concurrency > self.max_concurrent:
            raise ValueError("workflow_concurrency cannot exceed max_concurrent")
        return self

    @classmethod
    def from_env(cls) -> TaskQueueSettings:
        """Read bounded queue settings without persisting secrets."""
        values: dict[str, str] = {}
        names = {
            "max_concurrent": "DISTILLER_TASK_MAX_CONCURRENT",
            "max_pending": "DISTILLER_TASK_MAX_PENDING",
            "workflow_concurrency": "DISTILLER_TASK_WORKFLOW_CONCURRENCY",
            "lease_seconds": "DISTILLER_TASK_LEASE_SECONDS",
            "poll_interval_seconds": "DISTILLER_TASK_POLL_INTERVAL_SECONDS",
        }
        for field_name, environment_name in names.items():
            value = os.environ.get(environment_name)
            if value is not None:
                values[field_name] = value
        try:
            return cls.model_validate(values)
        except ValueError as exc:
            raise DistillerError(
                ErrorCode.SCHEMA_INVALID,
                "Invalid API task queue settings",
                details={"reason": str(exc)},
            ) from exc

    def resource_limit(self, resource_class: str) -> int:
        if resource_class == "workflow":
            return self.workflow_concurrency
        return self.max_concurrent


def default_task_db_path() -> Path:
    """Return the persistent API task database path."""
    configured = os.environ.get("DISTILLER_TASK_DB")
    if configured:
        return Path(configured).expanduser().resolve()
    return Path.home() / ".video-account-distiller" / "api" / "tasks.sqlite3"


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _lease_deadline(seconds: int) -> str:
    return (datetime.now(UTC) + timedelta(seconds=seconds)).isoformat()


def _json(payload: TaskData) -> str:
    encoded = jsonable_encoder(payload)
    return json.dumps(encoded, ensure_ascii=False, separators=(",", ":"))


class TaskStore:
    """Small SQLite-backed store whose records survive API restarts."""

    def __init__(
        self,
        path: Path | str | None = None,
        *,
        queue_settings: TaskQueueSettings | None = None,
    ) -> None:
        self.path = Path(path) if path is not None else default_task_db_path()
        self.path = self.path.expanduser().resolve()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.queue_settings = queue_settings or TaskQueueSettings.from_env()
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
                    updated_at TEXT NOT NULL,
                    task_type TEXT NOT NULL DEFAULT 'task',
                    resource_class TEXT NOT NULL DEFAULT 'default',
                    durable INTEGER NOT NULL DEFAULT 0,
                    worker_id TEXT,
                    lease_expires_at TEXT
                )
                """
            )
            columns = {
                str(row["name"])
                for row in connection.execute("PRAGMA table_info(api_tasks)").fetchall()
            }
            migrations = {
                "task_type": "TEXT NOT NULL DEFAULT 'task'",
                "resource_class": "TEXT NOT NULL DEFAULT 'default'",
                "durable": "INTEGER NOT NULL DEFAULT 0",
                "worker_id": "TEXT",
                "lease_expires_at": "TEXT",
            }
            for column, declaration in migrations.items():
                if column not in columns:
                    connection.execute(f"ALTER TABLE api_tasks ADD COLUMN {column} {declaration}")
            connection.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_api_tasks_updated_at
                ON api_tasks(updated_at DESC)
                """
            )
            connection.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_api_tasks_queue
                ON api_tasks(durable, status, created_at)
                """
            )
            connection.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_api_tasks_leases
                ON api_tasks(status, lease_expires_at)
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
        task_type = str(payload.get("task_type") or "task")
        resource_class = str(payload.get("resource_class") or "default")
        durable = bool(payload.get("durable"))
        with self._lock, self._connection() as connection:
            if durable:
                connection.execute("BEGIN IMMEDIATE")
                pending = int(
                    connection.execute(
                        """
                        SELECT COUNT(*) FROM api_tasks
                        WHERE durable = 1 AND status = 'pending'
                        """
                    ).fetchone()[0]
                )
                if pending >= self.queue_settings.max_pending:
                    raise DistillerError(
                        ErrorCode.TASK_QUEUE_FULL,
                        "Persistent task queue is full",
                        details={
                            "max_pending": self.queue_settings.max_pending,
                            "retryable": True,
                        },
                    )
            connection.execute(
                """
                INSERT INTO api_tasks(
                    task_id, status, progress, payload_json, created_at, updated_at,
                    task_type, resource_class, durable, worker_id, lease_expires_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, NULL)
                """,
                (
                    task_id,
                    "pending",
                    0.0,
                    _json(payload),
                    created_at,
                    created_at,
                    task_type,
                    resource_class,
                    int(durable),
                ),
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
            worker_id = payload.get("worker_id")
            lease_expires_at = payload.get("lease_expires_at")
            if status in {"completed", "failed", "cancelled"}:
                worker_id = None
                lease_expires_at = None
            connection.execute(
                """
                UPDATE api_tasks
                SET status = ?, progress = ?, payload_json = ?, updated_at = ?,
                    task_type = ?, resource_class = ?, durable = ?,
                    worker_id = ?, lease_expires_at = ?
                WHERE task_id = ?
                """,
                (
                    status,
                    progress,
                    _json(payload),
                    payload["updated_at"],
                    str(payload.get("task_type") or "task"),
                    str(payload.get("resource_class") or "default"),
                    int(bool(payload.get("durable"))),
                    worker_id,
                    lease_expires_at,
                    task_id,
                ),
            )
        return payload

    def get(self, task_id: str) -> TaskData | None:
        with self._lock, self._connection() as connection:
            row = connection.execute(
                """
                SELECT payload_json, status, durable, created_at
                FROM api_tasks WHERE task_id = ?
                """,
                (task_id,),
            ).fetchone()
            if row is None:
                return None
            payload = json.loads(str(row["payload_json"]))
            if not isinstance(payload, dict):
                return None
            if str(row["status"]) == "pending" and bool(row["durable"]):
                payload["queue_position"] = int(
                    connection.execute(
                        """
                        SELECT COUNT(*) FROM api_tasks
                        WHERE durable = 1 AND status = 'pending' AND created_at <= ?
                        """,
                        (str(row["created_at"]),),
                    ).fetchone()[0]
                )
            return payload

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

    def queue_status(self) -> TaskData:
        """Return queue limits and current durable workload counts."""
        with self._lock, self._connection() as connection:
            status_rows = connection.execute(
                """
                SELECT status, COUNT(*) AS count
                FROM api_tasks WHERE durable = 1
                GROUP BY status
                """
            ).fetchall()
            resource_rows = connection.execute(
                """
                SELECT resource_class, status, COUNT(*) AS count
                FROM api_tasks
                WHERE durable = 1 AND status IN ('pending', 'running', 'cancelling')
                GROUP BY resource_class, status
                """
            ).fetchall()
        by_status = {str(row["status"]): int(row["count"]) for row in status_rows}
        by_resource: dict[str, dict[str, int]] = {}
        for row in resource_rows:
            resource = str(row["resource_class"])
            by_resource.setdefault(resource, {})[str(row["status"])] = int(row["count"])
        return {
            "ok": True,
            "limits": {
                "max_concurrent": self.queue_settings.max_concurrent,
                "max_pending": self.queue_settings.max_pending,
                "workflow_concurrency": self.queue_settings.workflow_concurrency,
                "lease_seconds": self.queue_settings.lease_seconds,
            },
            "by_status": by_status,
            "by_resource": by_resource,
        }

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
        """Recover only expired/ownerless work; durable pending jobs remain queued."""
        with self._lock, self._connection() as connection:
            return self._recover_expired(connection, now=_now(), durable_only=False)

    def _recover_expired(
        self,
        connection: sqlite3.Connection,
        *,
        now: str,
        durable_only: bool,
    ) -> int:
        cancelling_rows = connection.execute(
            """
            SELECT task_id, payload_json FROM api_tasks
            WHERE status = 'cancelling'
              AND (? = 0 OR durable = 1)
              AND (
                worker_id IS NULL OR lease_expires_at IS NULL OR lease_expires_at <= ?
              )
            """,
            (int(durable_only), now),
        ).fetchall()
        for row in cancelling_rows:
            payload = json.loads(str(row["payload_json"]))
            if not isinstance(payload, dict):
                payload = {"task_id": str(row["task_id"])}
            payload.update(
                status="cancelled",
                stage="cancelled",
                message="任务已在工作进程退出后完成取消",
                cancel_requested=True,
                worker_id=None,
                lease_expires_at=None,
                updated_at=now,
            )
            connection.execute(
                """
                UPDATE api_tasks
                SET status = 'cancelled', payload_json = ?, updated_at = ?,
                    worker_id = NULL, lease_expires_at = NULL
                WHERE task_id = ?
                """,
                (_json(payload), now, str(row["task_id"])),
            )

        rows = connection.execute(
            """
            SELECT task_id, payload_json FROM api_tasks
            WHERE status = 'running'
              AND (? = 0 OR durable = 1)
              AND (
                worker_id IS NULL OR lease_expires_at IS NULL OR lease_expires_at <= ?
              )
            """,
            (int(durable_only), now),
        ).fetchall()
        for row in rows:
            payload = json.loads(str(row["payload_json"]))
            if not isinstance(payload, dict):
                payload = {"task_id": str(row["task_id"])}
            payload.update(
                status="failed",
                progress=1.0,
                stage="failed",
                message="任务工作进程中断，可从安全检查点重试",
                worker_id=None,
                lease_expires_at=None,
                error={
                    "code": ErrorCode.TASK_INTERRUPTED.value,
                    "message": "Task was interrupted by an API restart",
                    "details": {"retryable": True},
                },
                updated_at=now,
            )
            connection.execute(
                """
                UPDATE api_tasks
                SET status = 'failed', progress = 1.0,
                    payload_json = ?, updated_at = ?,
                    worker_id = NULL, lease_expires_at = NULL
                WHERE task_id = ?
                """,
                (_json(payload), now, str(row["task_id"])),
            )
        return len(rows) + len(cancelling_rows)

    def claim_next(
        self,
        *,
        worker_id: str,
        task_types: tuple[str, ...],
    ) -> TaskData | None:
        """Atomically claim the oldest eligible task while enforcing global quotas."""
        if not task_types:
            return None
        placeholders = ",".join("?" for _ in task_types)
        now = _now()
        lease_expires_at = _lease_deadline(self.queue_settings.lease_seconds)
        with self._lock, self._connection() as connection:
            has_queue_work = connection.execute(
                f"""
                SELECT 1 FROM api_tasks
                WHERE durable = 1 AND (
                    (status = 'pending' AND task_type IN ({placeholders}))
                    OR (
                        status IN ('running', 'cancelling')
                        AND (
                            worker_id IS NULL OR lease_expires_at IS NULL
                            OR lease_expires_at <= ?
                        )
                    )
                )
                LIMIT 1
                """,
                (*task_types, now),
            ).fetchone()
            if has_queue_work is None:
                return None
            connection.execute("BEGIN IMMEDIATE")
            self._recover_expired(connection, now=now, durable_only=True)
            active_total = int(
                connection.execute(
                    """
                    SELECT COUNT(*) FROM api_tasks
                    WHERE durable = 1 AND status IN ('running', 'cancelling')
                    """
                ).fetchone()[0]
            )
            if active_total >= self.queue_settings.max_concurrent:
                return None
            candidates = connection.execute(
                f"""
                SELECT task_id, payload_json, resource_class
                FROM api_tasks
                WHERE durable = 1 AND status = 'pending'
                  AND task_type IN ({placeholders})
                ORDER BY created_at ASC
                LIMIT 100
                """,
                task_types,
            ).fetchall()
            for row in candidates:
                resource_class = str(row["resource_class"])
                active_resource = int(
                    connection.execute(
                        """
                        SELECT COUNT(*) FROM api_tasks
                        WHERE durable = 1
                          AND status IN ('running', 'cancelling')
                          AND resource_class = ?
                        """,
                        (resource_class,),
                    ).fetchone()[0]
                )
                if active_resource >= self.queue_settings.resource_limit(resource_class):
                    continue
                payload = json.loads(str(row["payload_json"]))
                if not isinstance(payload, dict):
                    payload = {"task_id": str(row["task_id"])}
                payload.update(
                    status="running",
                    stage="starting",
                    message="工作进程已认领任务",
                    worker_id=worker_id,
                    lease_expires_at=lease_expires_at,
                    started_at=payload.get("started_at") or now,
                    updated_at=now,
                )
                updated = connection.execute(
                    """
                    UPDATE api_tasks
                    SET status = 'running', payload_json = ?, updated_at = ?,
                        worker_id = ?, lease_expires_at = ?
                    WHERE task_id = ? AND status = 'pending'
                    """,
                    (
                        _json(payload),
                        now,
                        worker_id,
                        lease_expires_at,
                        str(row["task_id"]),
                    ),
                )
                if updated.rowcount == 1:
                    return payload
            return None

    def renew_lease(self, task_id: str, *, worker_id: str) -> bool:
        """Extend one active claim and keep its public payload in sync."""
        deadline = _lease_deadline(self.queue_settings.lease_seconds)
        with self._lock, self._connection() as connection:
            row = connection.execute(
                """
                SELECT payload_json FROM api_tasks
                WHERE task_id = ? AND worker_id = ?
                  AND status IN ('running', 'cancelling')
                """,
                (task_id, worker_id),
            ).fetchone()
            if row is None:
                return False
            payload = json.loads(str(row["payload_json"]))
            if not isinstance(payload, dict):
                return False
            payload["lease_expires_at"] = deadline
            updated = connection.execute(
                """
                UPDATE api_tasks SET lease_expires_at = ?, payload_json = ?
                WHERE task_id = ? AND worker_id = ?
                  AND status IN ('running', 'cancelling')
                """,
                (deadline, _json(payload), task_id, worker_id),
            )
        return updated.rowcount == 1

    def update_claimed(
        self,
        task_id: str,
        *,
        worker_id: str,
        **changes: Any,
    ) -> TaskData:
        """Update a running task only while this worker owns its active lease."""
        with self._lock, self._connection() as connection:
            row = connection.execute(
                """
                SELECT payload_json, worker_id, status FROM api_tasks
                WHERE task_id = ?
                """,
                (task_id,),
            ).fetchone()
            if row is None or str(row["worker_id"] or "") != worker_id:
                raise TaskLeaseLost(task_id)
            payload = json.loads(str(row["payload_json"]))
            if not isinstance(payload, dict):
                raise ValueError(f"Invalid task payload: {task_id}")
            if payload.get("cancel_requested") or str(row["status"]) == "cancelling":
                raise TaskCancellationRequested
            payload.update(changes)
            payload.update(
                worker_id=worker_id,
                lease_expires_at=_lease_deadline(self.queue_settings.lease_seconds),
                updated_at=_now(),
            )
            connection.execute(
                """
                UPDATE api_tasks
                SET status = ?, progress = ?, payload_json = ?, updated_at = ?,
                    lease_expires_at = ?
                WHERE task_id = ? AND worker_id = ?
                """,
                (
                    str(payload.get("status") or "running"),
                    float(payload.get("progress", 0.0)),
                    _json(payload),
                    payload["updated_at"],
                    payload["lease_expires_at"],
                    task_id,
                    worker_id,
                ),
            )
        return payload

    def finish_claimed(
        self,
        task_id: str,
        *,
        worker_id: str,
        status: str,
        **changes: Any,
    ) -> TaskData:
        """Finalize one claimed task without allowing a stale worker to overwrite it."""
        if status not in {"completed", "failed", "cancelled"}:
            raise ValueError(f"Invalid terminal task status: {status}")
        with self._lock, self._connection() as connection:
            row = connection.execute(
                """
                SELECT payload_json, worker_id, status FROM api_tasks
                WHERE task_id = ?
                """,
                (task_id,),
            ).fetchone()
            if row is None or str(row["worker_id"] or "") != worker_id:
                raise TaskLeaseLost(task_id)
            payload = json.loads(str(row["payload_json"]))
            if not isinstance(payload, dict):
                raise ValueError(f"Invalid task payload: {task_id}")
            if payload.get("cancel_requested") or str(row["status"]) == "cancelling":
                status = "cancelled"
                changes = {
                    "stage": "cancelled",
                    "message": "任务已安全取消",
                    "cancel_requested": True,
                }
            payload.update(changes)
            payload.update(
                status=status,
                executed_by=worker_id,
                worker_id=None,
                lease_expires_at=None,
                updated_at=_now(),
            )
            connection.execute(
                """
                UPDATE api_tasks
                SET status = ?, progress = ?, payload_json = ?, updated_at = ?,
                    worker_id = NULL, lease_expires_at = NULL
                WHERE task_id = ? AND worker_id = ?
                """,
                (
                    status,
                    float(payload.get("progress", 0.0)),
                    _json(payload),
                    payload["updated_at"],
                    task_id,
                    worker_id,
                ),
            )
        return payload


@dataclass(frozen=True)
class TaskExecutionContext:
    """Lease-aware callbacks exposed to one durable task handler."""

    tasks: TaskStore
    task_id: str
    worker_id: str

    def raise_if_cancelled(self) -> None:
        if self.tasks.cancellation_requested(self.task_id):
            raise TaskCancellationRequested

    def progress(self, value: float, stage: str, message: str) -> None:
        bounded = min(max(float(value), 0.0), 1.0)
        self.tasks.update_claimed(
            self.task_id,
            worker_id=self.worker_id,
            status="running",
            progress=bounded,
            stage=str(stage),
            message=str(message),
        )

    def checkpoint(self, stage: str, state: dict[str, Any]) -> None:
        self.tasks.update_claimed(
            self.task_id,
            worker_id=self.worker_id,
            checkpoint_stage=str(stage),
            checkpoint=state,
        )


TaskHandler: TypeAlias = Callable[[TaskExecutionContext, dict[str, Any]], Any]


def enqueue_persistent_task(
    tasks: TaskStore,
    *,
    task_type: str,
    resource_class: str,
    job_payload: dict[str, Any],
    task_metadata: TaskData | None = None,
    resume_state: dict[str, Any] | None = None,
    retried_from: str | None = None,
) -> TaskData:
    """Persist a serializable job for atomic cross-process worker claiming."""
    task_id = new_run_id()
    initial: TaskData = {
        "task_type": task_type,
        "resource_class": resource_class,
        "durable": True,
        "stage": "pending",
        "message": "任务已进入持久队列",
        "retryable": task_metadata is not None,
        "job_payload": job_payload,
    }
    if task_metadata is not None:
        initial["task_metadata"] = task_metadata
    if resume_state is not None:
        initial["checkpoint"] = resume_state
    if retried_from is not None:
        initial["retried_from"] = retried_from
    tasks.create(task_id, initial=initial)
    submission: TaskData = {
        "ok": True,
        "task_id": task_id,
        "task_type": task_type,
        "resource_class": resource_class,
        "durable": True,
        "status": "pending",
    }
    if retried_from is not None:
        submission["retried_from"] = retried_from
    return submission


class TaskWorkerPool:
    """Poll and execute durable jobs claimed through one shared SQLite database."""

    def __init__(
        self,
        tasks: TaskStore,
        handlers: Mapping[str, TaskHandler],
    ) -> None:
        self.tasks = tasks
        self.handlers = dict(handlers)
        self.worker_prefix = f"{os.getpid()}:{new_run_id()}"
        self._stop = asyncio.Event()
        self._workers: list[asyncio.Task[None]] = []

    async def start(self) -> None:
        if self._workers:
            return
        self._stop.clear()
        self._workers = [
            asyncio.create_task(
                self._worker_loop(f"{self.worker_prefix}:{index}"),
                name=f"distiller-task-worker-{index}",
            )
            for index in range(self.tasks.queue_settings.max_concurrent)
        ]

    async def stop(self) -> None:
        if not self._workers:
            return
        self._stop.set()
        workers, self._workers = self._workers, []
        await asyncio.gather(*workers, return_exceptions=True)

    async def _worker_loop(self, worker_id: str) -> None:
        task_types = tuple(sorted(self.handlers))
        while not self._stop.is_set():
            task = self.tasks.claim_next(worker_id=worker_id, task_types=task_types)
            if task is None:
                try:
                    await asyncio.wait_for(
                        self._stop.wait(),
                        timeout=self.tasks.queue_settings.poll_interval_seconds,
                    )
                except TimeoutError:
                    continue
                continue
            await self._execute(worker_id, task)

    async def _execute(self, worker_id: str, task: TaskData) -> None:
        task_id = str(task["task_id"])
        task_type = str(task.get("task_type") or "")
        handler = self.handlers.get(task_type)
        payload = task.get("job_payload")
        if handler is None or not isinstance(payload, dict):
            error = DistillerError(
                ErrorCode.SCHEMA_INVALID,
                "Durable task handler or payload is unavailable",
                details={"task_type": task_type},
            )
            self.tasks.finish_claimed(
                task_id,
                worker_id=worker_id,
                status="failed",
                progress=1.0,
                stage="failed",
                message=error.message,
                error=error.as_dict()["error"],
            )
            return

        context = TaskExecutionContext(self.tasks, task_id, worker_id)
        heartbeat = asyncio.create_task(self._heartbeat(task_id, worker_id))
        try:
            context.raise_if_cancelled()
            result = await asyncio.to_thread(handler, context, payload)
            context.raise_if_cancelled()
            self.tasks.finish_claimed(
                task_id,
                worker_id=worker_id,
                status="completed",
                progress=1.0,
                stage="completed",
                message="工作流已完成",
                result=result,
            )
        except TaskCancellationRequested:
            self.tasks.finish_claimed(
                task_id,
                worker_id=worker_id,
                status="cancelled",
                stage="cancelled",
                message="任务已安全取消",
                cancel_requested=True,
            )
        except TaskLeaseLost:
            return
        except DistillerError as exc:
            self.tasks.finish_claimed(
                task_id,
                worker_id=worker_id,
                status="failed",
                progress=1.0,
                stage="failed",
                message=exc.message,
                error=exc.as_dict()["error"],
            )
        except Exception as exc:
            self.tasks.finish_claimed(
                task_id,
                worker_id=worker_id,
                status="failed",
                progress=1.0,
                stage="failed",
                message=str(exc),
                error={"code": "E_INTERNAL", "message": str(exc), "details": {}},
            )
        finally:
            heartbeat.cancel()
            await asyncio.gather(heartbeat, return_exceptions=True)

    async def _heartbeat(self, task_id: str, worker_id: str) -> None:
        interval = max(1.0, min(self.tasks.queue_settings.lease_seconds / 3, 30.0))
        while True:
            await asyncio.sleep(interval)
            if not self.tasks.renew_lease(task_id, worker_id=worker_id):
                return


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
