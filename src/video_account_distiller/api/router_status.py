"""Project status aggregation endpoint."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request

from video_account_distiller.api.deps import resolve_project
from video_account_distiller.run_reconciliation import reconcile_stale_project_runs
from video_account_distiller.status import project_status

router = APIRouter()


@router.get("/{project_path:path}/status")
async def get_status(project_path: str) -> dict[str, Any]:
    """Return a machine-readable snapshot of project state."""
    layout = resolve_project(project_path)
    return project_status(layout)


@router.post("/{project_path:path}/runs/reconcile")
async def reconcile_runs(project_path: str, request: Request) -> dict[str, Any]:
    """Close only timed-out runs after the active queue proves the project is idle."""

    layout = resolve_project(project_path)
    return reconcile_stale_project_runs(layout, request.app.state.tasks)
