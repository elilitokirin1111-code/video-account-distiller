"""Self-service workflow endpoints."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import APIRouter, Request

from video_account_distiller.api.deps import resolve_project
from video_account_distiller.api.schemas import AccountDistillWorkflowParams
from video_account_distiller.api.tasks import TaskData, TaskStore, enqueue_progress_task
from video_account_distiller.collection import (
    build_account_provider,
    build_collection_request,
    resolve_profile_options,
)
from video_account_distiller.errors import DistillerError, ErrorCode
from video_account_distiller.workflows import AccountDistillWorkflow

router = APIRouter()


def _enqueue_account_distill(
    tasks: TaskStore,
    *,
    project_path: str,
    body: AccountDistillWorkflowParams,
    dry_run: bool = False,
    resume_state: dict[str, Any] | None = None,
    retried_from: str | None = None,
) -> dict[str, Any]:
    layout = resolve_project(project_path)
    count, comments_per_video = resolve_profile_options(
        profile=body.profile,
        count=body.count,
        all_videos=body.all_videos,
        comments_per_video=body.comments_per_video,
    )
    collection_request = build_collection_request(
        profile_url=body.url,
        count=count,
        sort=body.sort,
        provider=body.provider,
        comments_per_video=comments_per_video,
        comment_video_limit=body.comment_video_limit,
    )
    provider = build_account_provider(body.provider)
    workflow = AccountDistillWorkflow(layout, provider)
    return enqueue_progress_task(
        tasks,
        workflow.run,
        task_type="account_distill",
        task_metadata={
            "project_path": str(layout.root),
            "body": body.model_dump(mode="json"),
            "dry_run": dry_run,
        },
        resume_state=resume_state,
        retried_from=retried_from,
        request=collection_request,
        collection_profile=body.profile,
        confirm_provider_cost=body.confirm_provider_cost,
        max_provider_calls=body.max_provider_calls,
        media_limit=body.media_limit,
        whisper_model=body.whisper_model,
        whisper_command=Path(body.whisper_command) if body.whisper_command else None,
        vision_provider=body.vision_provider,
        vision_model=body.vision_model,
        ollama_base_url=body.ollama_base_url,
        vision_batch_size=body.vision_batch_size,
        vision_timeout_seconds=body.vision_timeout_seconds,
        strict_media_enrichment=body.strict_media_enrichment,
        strict_vision=body.strict_vision,
        export_knowledge=body.export_knowledge,
        dry_run=dry_run,
    )


def retry_account_distill_task(tasks: TaskStore, task: TaskData) -> TaskData:
    """Recreate a self-service workflow from its persisted, secret-free inputs."""
    metadata = task.get("task_metadata")
    if not isinstance(metadata, dict):
        raise DistillerError(
            ErrorCode.SCHEMA_INVALID,
            "Task does not contain retry metadata",
        )
    project_path = metadata.get("project_path")
    body_payload = metadata.get("body")
    if not isinstance(project_path, str) or not isinstance(body_payload, dict):
        raise DistillerError(
            ErrorCode.SCHEMA_INVALID,
            "Task retry metadata is incomplete",
        )
    body = AccountDistillWorkflowParams.model_validate(body_payload)
    checkpoint = task.get("checkpoint")
    resume_state = checkpoint if isinstance(checkpoint, dict) else None
    return _enqueue_account_distill(
        tasks,
        project_path=project_path,
        body=body,
        dry_run=bool(metadata.get("dry_run")),
        resume_state=resume_state,
        retried_from=str(task["task_id"]),
    )


@router.post("/{project_path:path}/workflows/account-distill")
async def account_distill_workflow(
    project_path: str,
    request: Request,
    body: AccountDistillWorkflowParams,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Submit one complete homepage-to-knowledge workflow."""
    return _enqueue_account_distill(
        request.app.state.tasks,
        project_path=project_path,
        body=body,
        dry_run=dry_run,
    )
