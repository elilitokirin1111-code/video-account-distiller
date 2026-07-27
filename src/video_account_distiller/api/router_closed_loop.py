"""Scoring, prediction, publication, and retro endpoints."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import APIRouter, Request

from video_account_distiller.api.deps import resolve_project
from video_account_distiller.api.schemas import (
    PredictParams,
    PublishParams,
    RetroParams,
    ScoreParams,
)
from video_account_distiller.api.tasks import enqueue_task
from video_account_distiller.closed_loop import (
    PredictionService,
    PublicationService,
    RetroService,
    ScoringService,
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
    return enqueue_task(
        request.app.state.tasks,
        ScoringService(layout).score,
        account_id=account_id,
        script=Path(body.script),
        title=body.title,
        topic=body.topic,
        target_pillar=body.target_pillar,
        target_metric=body.target_metric,
        planned_publish_hour=body.planned_publish_hour,
        dry_run=dry_run,
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
    return enqueue_task(
        request.app.state.tasks,
        PredictionService(layout).predict,
        account_id=account_id,
        script=Path(body.script),
        title=body.title,
        topic=body.topic,
        target_pillar=body.target_pillar,
        target_metric=body.target_metric,
        target_age_hours=body.target_age_hours,
        planned_publish_hour=body.planned_publish_hour,
        dry_run=dry_run,
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
    return enqueue_task(
        request.app.state.tasks,
        PublicationService(layout).register,
        prediction_id=prediction_id,
        video_id=body.video_id,
        published_at=body.published_at,
        url=body.url,
        notes=body.notes,
        dry_run=dry_run,
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
    return enqueue_task(
        request.app.state.tasks,
        RetroService(layout).run,
        publication_id=publication_id,
        snapshot=body.snapshot,
        target_age_hours=body.target_age_hours,
        dry_run=dry_run,
    )
