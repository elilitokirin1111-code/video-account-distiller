"""Serializable handlers for durable API task execution."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from pydantic import BaseModel

from video_account_distiller.api.schemas import AccountDistillWorkflowParams
from video_account_distiller.api.tasks import TaskExecutionContext, TaskHandler
from video_account_distiller.collection import (
    build_account_provider,
    build_collection_request,
    resolve_profile_options,
)
from video_account_distiller.storage.project import ProjectLayout
from video_account_distiller.workflows import AccountDistillWorkflow


class AccountDistillJob(BaseModel):
    """Secret-free inputs needed to rebuild one self-service workflow."""

    project_path: str
    body: dict[str, Any]
    dry_run: bool = False
    resume_state: dict[str, Any] | None = None


def execute_account_distill(
    context: TaskExecutionContext,
    payload: dict[str, Any],
) -> dict[str, Any]:
    """Rebuild and execute a workflow in whichever process claims the task."""
    job = AccountDistillJob.model_validate(payload)
    body = AccountDistillWorkflowParams.model_validate(job.body)
    layout = ProjectLayout.open(Path(job.project_path))
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
    return AccountDistillWorkflow(layout, provider).run(
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
        dry_run=job.dry_run,
        progress=context.progress,
        checkpoint=context.checkpoint,
        resume_state=job.resume_state,
    )


TASK_HANDLERS: dict[str, TaskHandler] = {
    "account_distill": execute_account_distill,
}
