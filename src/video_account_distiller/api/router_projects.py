"""Project lifecycle endpoints — init, list, validate."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from fastapi import APIRouter

from video_account_distiller.api.deps import resolve_project
from video_account_distiller.api.schemas import (
    CloudModelSettingsUpdate,
    ProjectInitRequest,
)
from video_account_distiller.config import load_config
from video_account_distiller.insights import OPENAI_API_KEY_ENV
from video_account_distiller.storage.project import ProjectLayout
from video_account_distiller.utils.io import atomic_write_text
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


@router.get("/projects/{project_path:path}/settings/cloud-model")
async def cloud_model_settings(project_path: str) -> dict[str, Any]:
    """Return the project-level cloud-upload permission without any credential."""

    layout = resolve_project(project_path)
    config = load_config(layout.config_path)
    return {
        "ok": True,
        "allow_cloud_model_upload": config.privacy.allow_cloud_model_upload,
        "api_key_persisted": False,
        "api_key_configured": bool(os.environ.get(OPENAI_API_KEY_ENV, "").strip()),
        "api_key_env": OPENAI_API_KEY_ENV,
    }


@router.put("/projects/{project_path:path}/settings/cloud-model")
async def update_cloud_model_settings(
    project_path: str,
    body: CloudModelSettingsUpdate,
) -> dict[str, Any]:
    """Persist only the project permission flag; API keys remain environment-only."""

    layout = resolve_project(project_path)
    config = load_config(layout.config_path)
    privacy = config.privacy.model_copy(
        update={"allow_cloud_model_upload": body.allow_cloud_model_upload}
    )
    updated = config.model_copy(update={"privacy": privacy})
    atomic_write_text(layout.config_path, updated.as_yaml())
    return {
        "ok": True,
        "allow_cloud_model_upload": updated.privacy.allow_cloud_model_upload,
        "api_key_persisted": False,
        "api_key_configured": bool(os.environ.get(OPENAI_API_KEY_ENV, "").strip()),
        "api_key_env": OPENAI_API_KEY_ENV,
    }
