"""Conservative reconciliation for abandoned project run manifests."""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from video_account_distiller.api.tasks import TaskStore
from video_account_distiller.models import RunManifest
from video_account_distiller.storage.project import ProjectLayout
from video_account_distiller.utils.io import atomic_write_json, read_json

SUPERSEDED_RUN_GRACE = timedelta(hours=4)
ORPHANED_RUN_TIMEOUT = timedelta(hours=24)

_RECONCILIATION_WARNING = "系统已对账这条未正常收口的历史运行记录；已有输出文件保持不变。"
_RECONCILIATION_ERROR = "运行记录已明显超时，且任务队列确认该项目没有活动任务；已按进程中断收口。"


@dataclass(frozen=True)
class ProjectQueueActivity:
    """The queue evidence required before project files may be reconciled."""

    project_task_ids: tuple[str, ...]
    unscoped_task_ids: tuple[str, ...]

    @property
    def confirmed_inactive(self) -> bool:
        """Whether the complete active queue proves this project is inactive."""

        return not self.project_task_ids and not self.unscoped_task_ids


def _normalized_path(value: object) -> str | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        resolved = Path(value).expanduser().resolve()
    except (OSError, ValueError):
        return None
    return os.path.normcase(os.path.normpath(str(resolved)))


def _task_project_paths(task: Mapping[str, Any]) -> tuple[set[str], bool]:
    candidates: set[str] = set()
    unusable_candidate = False
    containers: list[Mapping[str, Any]] = [task]
    for key in ("job_payload", "task_metadata"):
        nested = task.get(key)
        if isinstance(nested, Mapping):
            containers.append(nested)
    for container in containers:
        if "project_path" not in container:
            continue
        candidate = _normalized_path(container.get("project_path"))
        if candidate is None:
            unusable_candidate = True
        else:
            candidates.add(candidate)
    return candidates, unusable_candidate


def inspect_project_queue(tasks: TaskStore, project: ProjectLayout) -> ProjectQueueActivity:
    """Inspect the complete active queue and classify exact project ownership.

    An active task without a trustworthy project path is intentionally treated
    as uncertainty.  Reconciliation must stop rather than assume it belongs to
    another project.
    """

    project_path = _normalized_path(str(project.root))
    if project_path is None:  # pragma: no cover - ProjectLayout always resolves its root.
        raise ValueError(f"Invalid project path: {project.root}")
    matching: list[str] = []
    unscoped: list[str] = []
    for task in tasks.active_tasks():
        task_id = str(task.get("task_id") or "")
        candidates, unusable_candidate = _task_project_paths(task)
        if project_path in candidates:
            matching.append(task_id)
        elif unusable_candidate or len(candidates) != 1:
            # No path, an invalid path, or conflicting paths means the queue
            # cannot prove that this active task is unrelated.
            unscoped.append(task_id)
    return ProjectQueueActivity(
        project_task_ids=tuple(sorted(matching)),
        unscoped_task_ids=tuple(sorted(unscoped)),
    )


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _load_run_manifests(
    project: ProjectLayout,
) -> tuple[list[tuple[Path, RunManifest]], list[str]]:
    manifests: list[tuple[Path, RunManifest]] = []
    invalid_paths: list[str] = []
    for manifest_path in sorted(project.runs_dir.glob("*/manifest.json")):
        try:
            manifest = RunManifest.model_validate(read_json(manifest_path))
        except (OSError, ValueError):
            invalid_paths.append(project.relative(manifest_path))
            continue
        if manifest.run_id != manifest_path.parent.name:
            invalid_paths.append(project.relative(manifest_path))
            continue
        manifests.append((manifest_path, manifest))
    return manifests, invalid_paths


def reconcile_stale_project_runs(
    project: ProjectLayout,
    tasks: TaskStore,
    *,
    now: datetime | None = None,
    superseded_after: timedelta = SUPERSEDED_RUN_GRACE,
    orphaned_after: timedelta = ORPHANED_RUN_TIMEOUT,
) -> dict[str, Any]:
    """Close only clearly abandoned ``running`` manifests.

    A run is eligible only when the complete task queue confirms that the
    project has no active or pending work.  Runs superseded by a later terminal
    manifest receive a short grace period; a last, unsuperseded run must exceed
    the much longer orphan timeout.  Project state pointers are never changed.
    """

    if superseded_after < timedelta(0) or orphaned_after < timedelta(0):
        raise ValueError("Run reconciliation timeouts cannot be negative")
    checked_at = _as_utc(now or datetime.now(UTC))
    activity = inspect_project_queue(tasks, project)
    result: dict[str, Any] = {
        "ok": True,
        "project_path": str(project.root),
        "checked_at": checked_at.isoformat(),
        "queue": {
            "confirmed_inactive": activity.confirmed_inactive,
            "active_project_task_ids": list(activity.project_task_ids),
            "unscoped_active_task_ids": list(activity.unscoped_task_ids),
        },
        "policy": {
            "superseded_after_seconds": int(superseded_after.total_seconds()),
            "orphaned_after_seconds": int(orphaned_after.total_seconds()),
        },
        "scanned_run_count": 0,
        "running_run_count": 0,
        "reconciled_run_ids": [],
        "recent_run_ids": [],
        "changed_before_write_run_ids": [],
        "invalid_manifest_paths": [],
    }
    if not activity.confirmed_inactive:
        result["action"] = "skipped_active_queue"
        return result

    manifests, invalid_paths = _load_run_manifests(project)
    result["scanned_run_count"] = len(manifests)
    result["invalid_manifest_paths"] = invalid_paths
    terminal_starts = [
        _as_utc(manifest.started_at)
        for _, manifest in manifests
        if manifest.status in {"success", "failed"}
    ]
    running = [(path, manifest) for path, manifest in manifests if manifest.status == "running"]
    result["running_run_count"] = len(running)

    reconciled: list[str] = []
    recent: list[str] = []
    changed: list[str] = []
    for manifest_path, manifest in running:
        started_at = _as_utc(manifest.started_at)
        superseded = any(terminal_start > started_at for terminal_start in terminal_starts)
        timeout = superseded_after if superseded else orphaned_after
        if checked_at - started_at < timeout:
            recent.append(manifest.run_id)
            continue

        # Re-read immediately before replacing the file.  If its owner closed
        # it after our scan, preserve that terminal result.
        try:
            current = RunManifest.model_validate(read_json(manifest_path))
        except (OSError, ValueError):
            changed.append(manifest.run_id)
            continue
        if current.status != "running" or current.started_at != manifest.started_at:
            changed.append(manifest.run_id)
            continue

        current.status = "failed"
        current.finished_at = checked_at
        if _RECONCILIATION_WARNING not in current.warnings:
            current.warnings.append(_RECONCILIATION_WARNING)
        if _RECONCILIATION_ERROR not in current.errors:
            current.errors.append(_RECONCILIATION_ERROR)
        atomic_write_json(manifest_path, current.model_dump(mode="json"))
        reconciled.append(current.run_id)

    result["reconciled_run_ids"] = reconciled
    result["recent_run_ids"] = recent
    result["changed_before_write_run_ids"] = changed
    result["action"] = "reconciled" if reconciled else "no_change"
    return result


__all__ = [
    "ORPHANED_RUN_TIMEOUT",
    "SUPERSEDED_RUN_GRACE",
    "ProjectQueueActivity",
    "inspect_project_queue",
    "reconcile_stale_project_runs",
]
