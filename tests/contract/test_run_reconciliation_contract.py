from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from urllib.parse import quote

import pytest
from fastapi.testclient import TestClient

from video_account_distiller.api.app import create_app
from video_account_distiller.models import RunManifest
from video_account_distiller.storage.project import ProjectLayout
from video_account_distiller.utils.io import atomic_write_json, read_json

pytestmark = pytest.mark.enable_socket


def test_run_reconciliation_endpoint_uses_application_task_queue(tmp_path: Path) -> None:
    now = datetime.now(UTC)
    project, _ = ProjectLayout.initialize(tmp_path / "project", project_name="reconcile")
    stale = RunManifest(
        run_id="run_stale",
        command="report narrative",
        started_at=now - timedelta(hours=4),
    )
    stale_path = project.runs_dir / stale.run_id / "manifest.json"
    atomic_write_json(stale_path, stale.model_dump(mode="json"))
    newer = RunManifest(
        run_id="run_newer",
        command="analyze video",
        started_at=now - timedelta(hours=2),
        finished_at=now - timedelta(hours=2) + timedelta(minutes=1),
        status="success",
    )
    newer_path = project.runs_dir / newer.run_id / "manifest.json"
    atomic_write_json(newer_path, newer.model_dump(mode="json"))
    encoded = quote(project.root.as_posix(), safe="")

    with TestClient(create_app(tmp_path / "tasks.sqlite3")) as client:
        response = client.post(f"/api/projects/{encoded}/runs/reconcile")

    assert response.status_code == 200
    payload = response.json()
    assert payload["queue"]["confirmed_inactive"] is True
    assert payload["reconciled_run_ids"] == ["run_stale"]
    assert RunManifest.model_validate(read_json(stale_path)).status == "failed"
