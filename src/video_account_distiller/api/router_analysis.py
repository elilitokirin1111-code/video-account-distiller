"""Analysis endpoints with async task support."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import APIRouter, Request

from video_account_distiller.api.deps import resolve_project
from video_account_distiller.api.schemas import (
    CommentAnalysisParams,
    MediaAnalysisParams,
    VideoAnalysisParams,
)
from video_account_distiller.api.tasks import enqueue_task
from video_account_distiller.comments import CommentAnalysisService
from video_account_distiller.features import VideoAnalysisService
from video_account_distiller.media import LocalMediaAnalysisService

router = APIRouter()


# ── video analysis ──────────────────────────────────────────────────


@router.post("/{project_path:path}/analyze/video/{video_id}")
async def analyze_video(
    project_path: str,
    video_id: str,
    request: Request,
    body: VideoAnalysisParams = VideoAnalysisParams(model_output=None, max_attempts=None),
    dry_run: bool = False,
) -> dict[str, Any]:
    layout = resolve_project(project_path)
    return enqueue_task(
        request.app.state.tasks,
        VideoAnalysisService(layout).analyze,
        video_id=video_id,
        model_output=Path(body.model_output) if body.model_output else None,
        max_attempts=body.max_attempts,
        strict_model=body.strict_model,
        dry_run=dry_run,
    )


# ── comment analysis ─────────────────────────────────────────────────


@router.post("/{project_path:path}/analyze/comments/{account_id}")
async def analyze_comments(
    project_path: str,
    account_id: str,
    request: Request,
    body: CommentAnalysisParams = CommentAnalysisParams(model_output=None, max_attempts=None),
    dry_run: bool = False,
) -> dict[str, Any]:
    layout = resolve_project(project_path)
    return enqueue_task(
        request.app.state.tasks,
        CommentAnalysisService(layout).analyze,
        account_id=account_id,
        model_output=Path(body.model_output) if body.model_output else None,
        max_attempts=body.max_attempts,
        strict_model=body.strict_model,
        dry_run=dry_run,
    )


# ── media analysis ───────────────────────────────────────────────────


@router.post("/{project_path:path}/analyze/media/{video_id}")
async def analyze_media(
    project_path: str,
    video_id: str,
    request: Request,
    body: MediaAnalysisParams = MediaAnalysisParams(
        file=None,
        vision_output=None,
        scene_threshold=None,
        max_keyframes=None,
    ),
    dry_run: bool = False,
) -> dict[str, Any]:
    layout = resolve_project(project_path)
    return enqueue_task(
        request.app.state.tasks,
        LocalMediaAnalysisService(layout).analyze,
        video_id=video_id,
        file=Path(body.file) if body.file else None,
        vision_output=Path(body.vision_output) if body.vision_output else None,
        strict_media=body.strict_media,
        strict_vision=body.strict_vision,
        scene_threshold=body.scene_threshold,
        max_keyframes=body.max_keyframes,
        dry_run=dry_run,
    )
