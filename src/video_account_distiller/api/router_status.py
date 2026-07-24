"""Project status aggregation endpoint."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter

from video_account_distiller.api.deps import resolve_project
from video_account_distiller.status import project_status

router = APIRouter()


@router.get("/{project_path:path}/status")
async def get_status(project_path: str) -> dict[str, Any]:
    """Return a machine-readable snapshot of project state."""
    layout = resolve_project(project_path)
    return project_status(layout)
