"""Self-service workflow endpoints."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request

from video_account_distiller.api.deps import resolve_project
from video_account_distiller.api.schemas import AccountDistillWorkflowParams
from video_account_distiller.api.task_jobs import AccountDistillJob
from video_account_distiller.api.tasks import (
    TaskData,
    TaskStore,
    enqueue_persistent_task,
)
from video_account_distiller.errors import DistillerError, ErrorCode

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
    job = AccountDistillJob(
        project_path=str(layout.root),
        body=body,
        dry_run=dry_run,
        resume_state=resume_state,
    )
    return enqueue_persistent_task(
        tasks,
        task_type="account_distill",
        resource_class="workflow",
        job_payload=job.model_dump(mode="json"),
        task_metadata={
            "project_path": str(layout.root),
            "body": body.model_dump(mode="json"),
            "dry_run": dry_run,
        },
        resume_state=resume_state,
        retried_from=retried_from,
    )


_RETRY_OVERRIDE_FIELDS = frozenset(
    {
        "provider",
        "count",
        "all_videos",
        "sort",
        "comments_per_video",
        "comment_video_limit",
        "max_provider_calls",
        "media_limit",
        "text_provider",
        "whisper_backend",
        "whisper_model",
        "whisper_command",
        "vision_provider",
        "vision_model",
        "cloud_base_url",
        "cloud_text_model",
        "cloud_vision_model",
        "vision_batch_size",
        "knowledge_analysis",
        "export_knowledge",
    }
)


def retry_account_distill_task(
    tasks: TaskStore,
    task: TaskData,
    *,
    overrides: dict[str, Any] | None = None,
) -> TaskData:
    """Recreate a self-service workflow from its persisted, secret-free inputs.

    Optional *overrides* replace allowlisted workflow inputs (cloud provider,
    models, endpoint, scope) before re-enqueueing, so a failed run can resume
    from its last safe checkpoint with, for example, a different Qwen model.
    """
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
    retry_body_payload = dict(body_payload)
    error = task.get("error")
    if (
        isinstance(error, dict)
        and error.get("code") == ErrorCode.COLLECTION_BUDGET_EXCEEDED.value
    ):
        retry_body_payload["max_provider_calls"] = None
    if overrides:
        for field, value in overrides.items():
            if field not in _RETRY_OVERRIDE_FIELDS:
                raise DistillerError(
                    ErrorCode.SCHEMA_INVALID,
                    f"Field is not overridable on retry: {field}",
                    details={"allowlist": sorted(_RETRY_OVERRIDE_FIELDS)},
                )
            if field == "knowledge_analysis":
                retry_body_payload["knowledge_analysis"] = value
            else:
                retry_body_payload[field] = value
    body = AccountDistillWorkflowParams.model_validate(retry_body_payload)
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
