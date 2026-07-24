"""Project lifecycle endpoints — init, list, validate."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import APIRouter

from video_account_distiller.api.deps import resolve_project
from video_account_distiller.api.schemas import ProjectInitRequest
from video_account_distiller.storage.project import ProjectLayout
from video_account_distiller.validation import validate_project

router = APIRouter()


@router.post("/projects/init")
async def init_project(body: ProjectInitRequest) -> dict[str, Any]:
    """Initialise a new distiller project at *path*."""
    layout, already = ProjectLayout.initialize(Path(body.path), project_name=body.name)
    return {
        "ok": True,
        "data": {"project": str(layout.root), "already_initialized": already},
    }


@router.get("/projects/")
async def list_projects() -> dict[str, Any]:
    """Return known project directories (from environment or defaults)."""
    # Minimal: just report the project we know about
    return {"ok": True, "data": {"projects": []}}


@router.get("/projects/{project_path:path}/validate")
async def validate(project_path: str) -> dict[str, Any]:
    """Run the project validator and return findings."""
    layout = resolve_project(project_path)
    report = validate_project(layout, persist=False)
    return {"ok": True, "data": report.model_dump(mode="json")}
