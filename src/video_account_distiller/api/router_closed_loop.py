"""Scoring, prediction, publication, and retro endpoints."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request

from video_account_distiller.api.deps import resolve_project
from video_account_distiller.api.schemas import (
    PredictParams,
    PublishParams,
    RetroParams,
    ScoreParams,
)
from video_account_distiller.api.task_jobs import (
    PredictJob,
    PublishJob,
    RetroJob,
    ScoreJob,
    enqueue_api_job,
)

router = APIRouter()


@router.post("/{project_path:path}/score/{account_id}")
async def score(
    project_path: str,
    account_id: str,
    request: Request,
    body: ScoreParams,
    dry_run: bool = False,
) -> dict[str, Any]:
    layout = resolve_project(project_path)
    return enqueue_api_job(
        request.app.state.tasks,
        ScoreJob(
            project_path=str(layout.root),
            account_id=account_id,
            body=body,
            dry_run=dry_run,
        ),
    )


@router.post("/{project_path:path}/predict/{account_id}")
async def predict(
    project_path: str,
    account_id: str,
    request: Request,
    body: PredictParams,
    dry_run: bool = False,
) -> dict[str, Any]:
    layout = resolve_project(project_path)
    return enqueue_api_job(
        request.app.state.tasks,
        PredictJob(
            project_path=str(layout.root),
            account_id=account_id,
            body=body,
            dry_run=dry_run,
        ),
    )


@router.post("/{project_path:path}/publish/{prediction_id}")
async def publish(
    project_path: str,
    prediction_id: str,
    request: Request,
    body: PublishParams,
    dry_run: bool = False,
) -> dict[str, Any]:
    layout = resolve_project(project_path)
    return enqueue_api_job(
        request.app.state.tasks,
        PublishJob(
            project_path=str(layout.root),
            prediction_id=prediction_id,
            body=body,
            dry_run=dry_run,
        ),
    )


@router.post("/{project_path:path}/retro/{publication_id}")
async def retro(
    project_path: str,
    publication_id: str,
    request: Request,
    body: RetroParams = RetroParams(target_age_hours=None),
    dry_run: bool = False,
) -> dict[str, Any]:
    layout = resolve_project(project_path)
    return enqueue_api_job(
        request.app.state.tasks,
        RetroJob(
            project_path=str(layout.root),
            publication_id=publication_id,
            body=body,
            dry_run=dry_run,
        ),
    )
