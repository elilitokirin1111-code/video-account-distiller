"""Analysis endpoints with async task support."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Request

from video_account_distiller.api.deps import resolve_project
from video_account_distiller.api.schemas import (
    CommentAnalysisParams,
    MediaAnalysisParams,
    VideoAnalysisParams,
)
from video_account_distiller.comments import CommentAnalysisService
from video_account_distiller.errors import DistillerError
from video_account_distiller.features import VideoAnalysisService
from video_account_distiller.media import LocalMediaAnalysisService
from video_account_distiller.utils.ids import new_run_id

router = APIRouter()


def _next_task_id() -> str:
    return new_run_id()


def _enqueue(
    tasks: dict,
    task_id: str,
    fn: Any,
    *args: Any,
    **kwargs: Any,
) -> None:
    tasks[task_id] = {"task_id": task_id, "status": "pending", "progress": 0}

    async def _runner() -> None:
        try:
            tasks[task_id]["status"] = "running"
            result = await asyncio.to_thread(fn, *args, **kwargs)
            tasks[task_id].update(status="completed", result=result)
        except DistillerError as exc:
            tasks[task_id].update(
                status="failed",
                error={"code": exc.code.value, "message": exc.message, "details": exc.details},
            )
        except Exception as exc:
            tasks[task_id].update(
                status="failed",
                error={"code": "E_INTERNAL", "message": str(exc)},
            )

    asyncio.ensure_future(_runner())


# ── video analysis ──────────────────────────────────────────────────


@router.post("/{project_path:path}/analyze/video/{video_id}")
async def analyze_video(
    project_path: str,
    video_id: str,
    body: VideoAnalysisParams = VideoAnalysisParams(),
    dry_run: bool = False,
    request: Request = None,  # type: ignore[assignment]
) -> dict[str, Any]:
    layout = resolve_project(project_path)
    task_id = _next_task_id()
    _enqueue(
        request.app.state.tasks,
        task_id,
        VideoAnalysisService(layout).analyze,
        video_id=video_id,
        model_output=Path(body.model_output) if body.model_output else None,
        max_attempts=body.max_attempts,
        strict_model=body.strict_model,
        dry_run=dry_run,
    )
    return {"ok": True, "task_id": task_id, "status": "pending"}


# ── comment analysis ─────────────────────────────────────────────────


@router.post("/{project_path:path}/analyze/comments/{account_id}")
async def analyze_comments(
    project_path: str,
    account_id: str,
    body: CommentAnalysisParams = CommentAnalysisParams(),
    dry_run: bool = False,
    request: Request = None,  # type: ignore[assignment]
) -> dict[str, Any]:
    layout = resolve_project(project_path)
    task_id = _next_task_id()
    _enqueue(
        request.app.state.tasks,
        task_id,
        CommentAnalysisService(layout).analyze,
        account_id=account_id,
        model_output=Path(body.model_output) if body.model_output else None,
        max_attempts=body.max_attempts,
        strict_model=body.strict_model,
        dry_run=dry_run,
    )
    return {"ok": True, "task_id": task_id, "status": "pending"}


# ── media analysis ───────────────────────────────────────────────────


@router.post("/{project_path:path}/analyze/media/{video_id}")
async def analyze_media(
    project_path: str,
    video_id: str,
    body: MediaAnalysisParams = MediaAnalysisParams(),
    dry_run: bool = False,
    request: Request = None,  # type: ignore[assignment]
) -> dict[str, Any]:
    layout = resolve_project(project_path)
    task_id = _next_task_id()
    _enqueue(
        request.app.state.tasks,
        task_id,
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
    return {"ok": True, "task_id": task_id, "status": "pending"}
