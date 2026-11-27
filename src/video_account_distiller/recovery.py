"""Isolated production drill for durable task interruption and checkpoint recovery."""

from __future__ import annotations

import sqlite3
import tempfile
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path

from video_account_distiller.api.tasks import (
    TaskQueueSettings,
    TaskStore,
    enqueue_persistent_task,
    retry_persistent_task,
)
from video_account_distiller.errors import ErrorCode
from video_account_distiller.models import TaskRecoveryDrillResult


def _expire_isolated_lease(database: Path, task_id: str) -> None:
    """Expire one lease in a drill-owned database to simulate abrupt worker loss."""

    with closing(sqlite3.connect(database)) as connection:
        with connection:
            updated = connection.execute(
                """
                UPDATE api_tasks
                SET lease_expires_at = '1970-01-01T00:00:00+00:00'
                WHERE task_id = ? AND status = 'running'
                """,
                (task_id,),
            )
            if updated.rowcount != 1:
                raise RuntimeError("Recovery drill could not expire the isolated task lease")


def run_task_recovery_drill(workdir: Path | None = None) -> TaskRecoveryDrillResult:
    """Exercise interruption, recovery, checkpoint retry, and completion in a temp queue."""

    started_at = datetime.now(UTC)
    base_dir = workdir.expanduser().resolve() if workdir is not None else None
    if base_dir is not None:
        base_dir.mkdir(parents=True, exist_ok=True)
    steps: list[str] = []
    original_task_id = ""
    retry_task_id = ""
    interruption_detected = False
    retryable = False
    checkpoint_preserved = False
    retried_from_preserved = False
    retry_completed = False
    temporary_root: Path | None = None
    settings = TaskQueueSettings(
        max_concurrent=1,
        workflow_concurrency=1,
        provider_concurrency=1,
        model_concurrency=1,
    )

    with tempfile.TemporaryDirectory(
        prefix="distiller-recovery-drill-",
        dir=base_dir,
    ) as temporary:
        temporary_root = Path(temporary).resolve()
        database = temporary_root / "tasks.sqlite3"
        store = TaskStore(database, queue_settings=settings)
        submission = enqueue_persistent_task(
            store,
            task_type="recovery_drill",
            resource_class="workflow",
            job_payload={"drill": True},
            task_metadata={"scope": "isolated"},
            retryable=True,
        )
        original_task_id = str(submission["task_id"])
        steps.append("durable_task_enqueued")

        claimed = store.claim_next(
            worker_id="recovery-drill-lost-worker",
            task_types=("recovery_drill",),
        )
        if claimed is None or str(claimed["task_id"]) != original_task_id:
            raise RuntimeError("Recovery drill could not claim the isolated task")
        store.update_claimed(
            original_task_id,
            worker_id="recovery-drill-lost-worker",
            checkpoint_stage="drill_checkpoint",
            checkpoint={"sequence": 1, "safe": True},
        )
        steps.append("checkpoint_persisted")

        _expire_isolated_lease(database, original_task_id)
        steps.append("worker_loss_simulated")
        recovered_store = TaskStore(database, queue_settings=settings)
        recovered = recovered_store.get(original_task_id)
        if recovered is None:
            raise RuntimeError("Recovery drill lost the interrupted task record")
        error = recovered.get("error")
        interruption_detected = (
            recovered.get("status") == "failed"
            and isinstance(error, dict)
            and error.get("code") == ErrorCode.TASK_INTERRUPTED.value
        )
        retryable = bool(
            isinstance(error, dict)
            and isinstance(error.get("details"), dict)
            and error["details"].get("retryable") is True
        )
        checkpoint_preserved = recovered.get("checkpoint") == {
            "sequence": 1,
            "safe": True,
        }
        steps.append("interruption_recovered")

        retry_submission = retry_persistent_task(recovered_store, recovered)
        retry_task_id = str(retry_submission["task_id"])
        retry_task = recovered_store.get(retry_task_id)
        retried_from_preserved = bool(
            retry_task is not None
            and retry_task.get("retried_from") == original_task_id
            and retry_task.get("checkpoint") == {"sequence": 1, "safe": True}
        )
        steps.append("checkpoint_retry_enqueued")

        retry_claim = recovered_store.claim_next(
            worker_id="recovery-drill-retry-worker",
            task_types=("recovery_drill",),
        )
        if retry_claim is None or str(retry_claim["task_id"]) != retry_task_id:
            raise RuntimeError("Recovery drill could not claim the retried task")
        completed = recovered_store.finish_claimed(
            retry_task_id,
            worker_id="recovery-drill-retry-worker",
            status="completed",
            progress=1.0,
            stage="completed",
            result={"drill": "passed"},
        )
        retry_completed = completed.get("status") == "completed"
        steps.append("retry_completed")

    database_removed = temporary_root is not None and not temporary_root.exists()
    ok = all(
        (
            interruption_detected,
            retryable,
            checkpoint_preserved,
            retried_from_preserved,
            retry_completed,
            database_removed,
        )
    )
    return TaskRecoveryDrillResult(
        ok=ok,
        started_at=started_at,
        completed_at=datetime.now(UTC),
        database_scope="temporary",
        database_removed=database_removed,
        original_task_id=original_task_id,
        retry_task_id=retry_task_id,
        interruption_detected=interruption_detected,
        retryable=retryable,
        checkpoint_preserved=checkpoint_preserved,
        retried_from_preserved=retried_from_preserved,
        retry_completed=retry_completed,
        steps=steps,
    )
