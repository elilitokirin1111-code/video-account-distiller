from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

from video_account_distiller.api.tasks import TaskStore, enqueue_persistent_task
from video_account_distiller.models import RunManifest
from video_account_distiller.run_reconciliation import reconcile_stale_project_runs
from video_account_distiller.storage.project import ProjectLayout
from video_account_distiller.utils.io import atomic_write_json, read_json


def _write_run(
    project: ProjectLayout,
    run_id: str,
    *,
    started_at: datetime,
    status: str = "running",
) -> Path:
    manifest = RunManifest(
        run_id=run_id,
        command="fixture command",
        started_at=started_at,
        finished_at=started_at + timedelta(minutes=1) if status != "running" else None,
        status=status,  # type: ignore[arg-type]
    )
    path = project.runs_dir / run_id / "manifest.json"
    atomic_write_json(path, manifest.model_dump(mode="json"))
    return path


def test_reconciles_only_superseded_stale_run_without_changing_last_run(
    project: ProjectLayout,
    tmp_path: Path,
) -> None:
    now = datetime(2026, 9, 3, 8, tzinfo=UTC)
    stale_path = _write_run(
        project,
        "run_stale",
        started_at=now - timedelta(hours=4),
    )
    _write_run(
        project,
        "run_newer",
        started_at=now - timedelta(minutes=30),
        status="success",
    )
    state = project.load_state()
    state.last_run_id = "run_newer"
    project.save_state(state)

    result = reconcile_stale_project_runs(
        project,
        TaskStore(tmp_path / "tasks.sqlite3"),
        now=now,
    )

    reconciled = RunManifest.model_validate(read_json(stale_path))
    assert result["action"] == "reconciled"
    assert result["reconciled_run_ids"] == ["run_stale"]
    assert reconciled.status == "failed"
    assert reconciled.finished_at == now
    assert "任务队列确认该项目没有活动任务" in reconciled.errors[-1]
    assert project.load_state().last_run_id == "run_newer"


def test_active_project_task_blocks_reconciliation(
    project: ProjectLayout,
    tmp_path: Path,
) -> None:
    now = datetime(2026, 9, 3, 8, tzinfo=UTC)
    stale_path = _write_run(
        project,
        "run_stale",
        started_at=now - timedelta(days=2),
    )
    tasks = TaskStore(tmp_path / "tasks.sqlite3")
    submission = enqueue_persistent_task(
        tasks,
        task_type="fixture",
        resource_class="workflow",
        job_payload={"project_path": str(project.root)},
    )

    result = reconcile_stale_project_runs(project, tasks, now=now)

    assert result["action"] == "skipped_active_queue"
    assert result["queue"]["active_project_task_ids"] == [submission["task_id"]]
    assert RunManifest.model_validate(read_json(stale_path)).status == "running"


def test_queue_inspection_does_not_recover_a_live_unleased_task(
    project: ProjectLayout,
    tmp_path: Path,
) -> None:
    now = datetime(2026, 9, 3, 8, tzinfo=UTC)
    stale_path = _write_run(
        project,
        "run_stale",
        started_at=now - timedelta(days=2),
    )
    tasks = TaskStore(tmp_path / "tasks.sqlite3")
    tasks.create(
        "task_live",
        initial={"task_metadata": {"project_path": str(project.root)}},
    )
    tasks.update("task_live", status="running")

    result = reconcile_stale_project_runs(project, tasks, now=now)

    assert result["action"] == "skipped_active_queue"
    assert tasks.get("task_live")["status"] == "running"  # type: ignore[index]
    assert RunManifest.model_validate(read_json(stale_path)).status == "running"


def test_unscoped_active_task_blocks_but_other_project_task_does_not(
    project: ProjectLayout,
    tmp_path: Path,
) -> None:
    now = datetime(2026, 9, 3, 8, tzinfo=UTC)
    stale_path = _write_run(
        project,
        "run_stale",
        started_at=now - timedelta(days=2),
    )
    tasks = TaskStore(tmp_path / "tasks.sqlite3")
    tasks.create("task_unscoped")

    blocked = reconcile_stale_project_runs(project, tasks, now=now)

    assert blocked["action"] == "skipped_active_queue"
    assert blocked["queue"]["unscoped_active_task_ids"] == ["task_unscoped"]
    assert RunManifest.model_validate(read_json(stale_path)).status == "running"

    tasks.update("task_unscoped", status="completed", progress=1.0)
    enqueue_persistent_task(
        tasks,
        task_type="fixture",
        resource_class="workflow",
        job_payload={"project_path": str(tmp_path / "another-project")},
    )
    reconciled = reconcile_stale_project_runs(project, tasks, now=now)

    assert reconciled["action"] == "reconciled"
    assert RunManifest.model_validate(read_json(stale_path)).status == "failed"


def test_recent_and_unsuperseded_runs_receive_conservative_grace_periods(
    project: ProjectLayout,
    tmp_path: Path,
) -> None:
    now = datetime(2026, 9, 3, 8, tzinfo=UTC)
    recent_path = _write_run(
        project,
        "run_recent",
        started_at=now - timedelta(minutes=45),
    )
    orphan_path = _write_run(
        project,
        "run_orphan",
        started_at=now - timedelta(hours=4),
    )
    _write_run(
        project,
        "run_terminal_between",
        started_at=now - timedelta(hours=2),
        status="success",
    )

    result = reconcile_stale_project_runs(
        project,
        TaskStore(tmp_path / "tasks.sqlite3"),
        now=now,
    )

    assert result["recent_run_ids"] == ["run_recent"]
    assert RunManifest.model_validate(read_json(recent_path)).status == "running"
    assert RunManifest.model_validate(read_json(orphan_path)).status == "failed"


def test_unsuperseded_run_requires_full_orphan_timeout(
    project: ProjectLayout,
    tmp_path: Path,
) -> None:
    now = datetime(2026, 9, 3, 8, tzinfo=UTC)
    recent_orphan = _write_run(
        project,
        "run_recent_orphan",
        started_at=now - timedelta(hours=12),
    )
    old_orphan = _write_run(
        project,
        "run_old_orphan",
        started_at=now - timedelta(hours=25),
    )

    result = reconcile_stale_project_runs(
        project,
        TaskStore(tmp_path / "tasks.sqlite3"),
        now=now,
    )

    assert result["reconciled_run_ids"] == ["run_old_orphan"]
    assert result["recent_run_ids"] == ["run_recent_orphan"]
    assert RunManifest.model_validate(read_json(recent_orphan)).status == "running"
    assert RunManifest.model_validate(read_json(old_orphan)).status == "failed"
