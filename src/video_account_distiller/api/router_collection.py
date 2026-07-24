"""Phase 8 online collection endpoint."""

from __future__ import annotations

import asyncio
from typing import Any

from fastapi import APIRouter, Request

from video_account_distiller.api.deps import resolve_project
from video_account_distiller.api.schemas import CollectionAnalyzeParams
from video_account_distiller.collection import (
    AccountCollectionService,
    build_account_provider,
    build_collection_request,
)
from video_account_distiller.utils.ids import new_run_id

router = APIRouter()


@router.post("/{project_path:path}/collection/analyze")
async def collection_analyze(
    project_path: str,
    body: CollectionAnalyzeParams,
    dry_run: bool = False,
    request: Request = None,  # type: ignore[assignment]
) -> dict[str, Any]:
    layout = resolve_project(project_path)
    collection_request = build_collection_request(
        profile_url=body.url,
        count=body.count,
        sort=body.sort,
        provider=body.provider,
        comments_per_video=body.comments_per_video,
        comment_video_limit=body.comment_video_limit,
    )
    provider = build_account_provider(body.provider)

    task_id = new_run_id()
    tasks = request.app.state.tasks
    tasks[task_id] = {"task_id": task_id, "status": "pending", "progress": 0}

    async def _runner() -> None:
        try:
            tasks[task_id]["status"] = "running"
            result = await asyncio.to_thread(
                AccountCollectionService(layout, provider).analyze_url,
                request=collection_request,
                confirm_provider_cost=body.confirm_provider_cost,
                dry_run=dry_run,
            )
            tasks[task_id].update(status="completed", result=result)
        except Exception as exc:
            tasks[task_id].update(
                status="failed",
                error={"code": getattr(exc, "code", "E_INTERNAL"), "message": str(exc)},
            )

    asyncio.ensure_future(_runner())
    return {"ok": True, "task_id": task_id, "status": "pending"}
