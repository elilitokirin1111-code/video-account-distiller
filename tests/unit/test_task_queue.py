from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import pytest

from video_account_distiller.api.tasks import (
    TaskExecutionContext,
    TaskQueueSettings,
    TaskStore,
    TaskWorkerPool,
    enqueue_persistent_task,
)
from video_account_distiller.errors import DistillerError, ErrorCode


def _settings(
    *,
    max_concurrent: int = 2,
    max_pending: int = 10,
    workflow_concurrency: int = 1,
) -> TaskQueueSettings:
    return TaskQueueSettings(
        max_concurrent=max_concurrent,
        max_pending=max_pending,
        workflow_concurrency=workflow_concurrency,
        poll_interval_seconds=0.01,
    )


def _enqueue(
    store: TaskStore,
    *,
    task_type: str = "fixture",
    resource_class: str = "workflow",
    value: int = 1,
) -> dict[str, Any]:
    return enqueue_persistent_task(
        store,
        task_type=task_type,
        resource_class=resource_class,
        job_payload={"value": value},
        task_metadata={"safe": True},
    )


def test_durable_pending_task_survives_reopen_and_can_be_claimed(
    tmp_path: Path,
) -> None:
    path = tmp_path / "tasks.sqlite3"
    settings = _settings()
    first = TaskStore(path, queue_settings=settings)
    task_id = str(_enqueue(first)["task_id"])

    second = TaskStore(path, queue_settings=settings)
    pending = second.get(task_id)
    assert pending is not None
    assert pending["status"] == "pending"
    assert pending["queue_position"] == 1

    claimed = second.claim_next(worker_id="worker-b", task_types=("fixture",))
    assert claimed is not None
    assert claimed["task_id"] == task_id
    assert claimed["status"] == "running"
    assert claimed["worker_id"] == "worker-b"

    third = TaskStore(path, queue_settings=settings)
    active = third.get(task_id)
    assert active is not None
    assert active["status"] == "running"

    completed = second.finish_claimed(
        task_id,
        worker_id="worker-b",
        status="completed",
        progress=1.0,
        result={"ok": True},
    )
    assert completed["status"] == "completed"
    assert completed["executed_by"] == "worker-b"


def test_queue_limits_pending_work_and_enforces_cross_store_resource_quota(
    tmp_path: Path,
) -> None:
    path = tmp_path / "tasks.sqlite3"
    settings = _settings(max_pending=2)
    first = TaskStore(path, queue_settings=settings)
    second = TaskStore(path, queue_settings=settings)
    first_id = str(_enqueue(first, value=1)["task_id"])
    second_id = str(_enqueue(first, value=2)["task_id"])

    with pytest.raises(DistillerError) as exc_info:
        _enqueue(first, value=3)
    assert exc_info.value.code is ErrorCode.TASK_QUEUE_FULL
    assert exc_info.value.details == {"max_pending": 2, "retryable": True}

    first_claim = first.claim_next(worker_id="worker-a", task_types=("fixture",))
    assert first_claim is not None
    assert first_claim["task_id"] == first_id
    assert second.claim_next(worker_id="worker-b", task_types=("fixture",)) is None

    first.finish_claimed(
        first_id,
        worker_id="worker-a",
        status="completed",
        progress=1.0,
    )
    second_claim = second.claim_next(worker_id="worker-b", task_types=("fixture",))
    assert second_claim is not None
    assert second_claim["task_id"] == second_id
    second.finish_claimed(
        second_id,
        worker_id="worker-b",
        status="completed",
        progress=1.0,
    )


@pytest.mark.enable_socket
def test_worker_pool_executes_task_submitted_through_another_store(
    tmp_path: Path,
) -> None:
    path = tmp_path / "tasks.sqlite3"
    settings = _settings()
    submitter = TaskStore(path, queue_settings=settings)
    task_id = str(_enqueue(submitter, value=7)["task_id"])
    worker_store = TaskStore(path, queue_settings=settings)

    def handler(
        context: TaskExecutionContext,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        context.progress(0.5, "fixture", "halfway")
        context.checkpoint("fixture", {"value": payload["value"]})
        return {"doubled": int(payload["value"]) * 2}

    async def scenario() -> dict[str, Any]:
        pool = TaskWorkerPool(worker_store, {"fixture": handler})
        await pool.start()
        try:
            for _ in range(200):
                current = submitter.get(task_id) or {}
                if current.get("status") == "completed":
                    return current
                await asyncio.sleep(0.01)
            raise AssertionError("Durable task did not complete")
        finally:
            await pool.stop()

    task = asyncio.run(scenario())

    assert task["result"] == {"doubled": 14}
    assert task["checkpoint"] == {"value": 7}
    assert str(task["executed_by"]).count(":") >= 2
