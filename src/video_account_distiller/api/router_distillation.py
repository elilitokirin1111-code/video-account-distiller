"""Account distillation and benchmark comparison endpoints."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request

from video_account_distiller.api.deps import resolve_project
from video_account_distiller.api.schemas import CompareParams
from video_account_distiller.api.task_jobs import (
    CompareJob,
    DistillJob,
    enqueue_api_job,
)

router = APIRouter()


@router.post("/{project_path:path}/distill/{account_id}")
async def distill(
    project_path: str,
    account_id: str,
    request: Request,
    dry_run: bool = False,
) -> dict[str, Any]:
    layout = resolve_project(project_path)
    return enqueue_api_job(
        request.app.state.tasks,
        DistillJob(
            project_path=str(layout.root),
            account_id=account_id,
            dry_run=dry_run,
        ),
    )


@router.post("/{project_path:path}/compare")
async def compare(
    project_path: str,
    request: Request,
    body: CompareParams,
    dry_run: bool = False,
) -> dict[str, Any]:
    layout = resolve_project(project_path)
    return enqueue_api_job(
        request.app.state.tasks,
        CompareJob(
            project_path=str(layout.root),
            body=body,
            dry_run=dry_run,
        ),
    )
