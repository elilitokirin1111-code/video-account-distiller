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
