from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from video_account_distiller.api.app import create_app
from video_account_distiller.recovery import run_task_recovery_drill


def test_task_recovery_drill_preserves_checkpoint_and_removes_database(
    tmp_path: Path,
) -> None:
    report = run_task_recovery_drill(tmp_path)

    assert report.ok is True
    assert report.database_scope == "temporary"
    assert report.database_removed is True
    assert report.interruption_detected is True
    assert report.retryable is True
    assert report.checkpoint_preserved is True
    assert report.retried_from_preserved is True
    assert report.retry_completed is True
    assert report.steps == [
        "durable_task_enqueued",
        "checkpoint_persisted",
        "worker_loss_simulated",
        "interruption_recovered",
        "checkpoint_retry_enqueued",
        "retry_completed",
    ]
    assert list(tmp_path.iterdir()) == []


@pytest.mark.enable_socket
def test_task_recovery_drill_api_is_isolated_from_application_queue(
    tmp_path: Path,
) -> None:
    application_database = tmp_path / "application-tasks.sqlite3"
    with TestClient(create_app(application_database)) as client:
        response = client.post("/api/doctor/task-recovery-drill")
        queue = client.get("/api/task-queue")

    assert response.status_code == 200
    payload = response.json()
    assert payload["ok"] is True
    assert payload["data"]["database_scope"] == "temporary"
    assert payload["data"]["database_removed"] is True
    assert queue.json()["by_status"] == {}
