"""Serializable handlers for durable API task execution."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated, Any, Literal, TypeAlias

from pydantic import BaseModel, Field, TypeAdapter

from video_account_distiller.api.schemas import (
    AccountDistillWorkflowParams,
    CollectionAnalyzeParams,
    CommentAnalysisParams,
    CompareParams,
    MediaAnalysisParams,
    OpenKBQueryParams,
    OpenKBSyncParams,
    PredictParams,
    PublishParams,
    ReportParams,
    RetroParams,
    SampleParams,
    ScoreParams,
    VideoAnalysisParams,
)
from video_account_distiller.api.tasks import (
    TaskData,
    TaskExecutionContext,
    TaskHandler,
    TaskStore,
    enqueue_persistent_task,
)
from video_account_distiller.closed_loop import (
    PredictionService,
    PublicationService,
    RetroService,
    ScoringService,
)
from video_account_distiller.collection import (
    AccountCollectionService,
    build_account_provider,
    build_collection_request,
    resolve_profile_options,
)
from video_account_distiller.comments import CommentAnalysisService
from video_account_distiller.distillation import (
    AccountDistillationService,
    BenchmarkComparisonService,
)
from video_account_distiller.features import VideoAnalysisService
from video_account_distiller.knowledge import (
    OpenKBIntegrationService,
    resolve_openkb_target,
)
from video_account_distiller.media import LocalMediaAnalysisService
from video_account_distiller.reports import ReportService
from video_account_distiller.sampling import SamplingService
from video_account_distiller.storage.project import ProjectLayout
from video_account_distiller.workflows import AccountDistillWorkflow


class AccountDistillJob(BaseModel):
    """Secret-free inputs needed to rebuild one self-service workflow."""

    project_path: str
    body: AccountDistillWorkflowParams
    dry_run: bool = False
    resume_state: dict[str, Any] | None = None


class _DryRunProjectJob(BaseModel):
    project_path: str
    dry_run: bool = False


class CollectionAnalyzeJob(_DryRunProjectJob):
    kind: Literal["collection_analyze"] = "collection_analyze"
    body: CollectionAnalyzeParams


class SampleJob(_DryRunProjectJob):
    kind: Literal["sample"] = "sample"
    account_id: str
    body: SampleParams


class ReportJob(_DryRunProjectJob):
    kind: Literal["report"] = "report"
    account_id: str
    body: ReportParams


class OpenKBSyncJob(_DryRunProjectJob):
    kind: Literal["openkb_sync"] = "openkb_sync"
    account_id: str
    body: OpenKBSyncParams


class OpenKBQueryJob(BaseModel):
    kind: Literal["openkb_query"] = "openkb_query"
    project_path: str
    body: OpenKBQueryParams


class DistillJob(_DryRunProjectJob):
    kind: Literal["distill"] = "distill"
    account_id: str


class CompareJob(_DryRunProjectJob):
    kind: Literal["compare"] = "compare"
    body: CompareParams


class ScoreJob(_DryRunProjectJob):
    kind: Literal["score"] = "score"
    account_id: str
    body: ScoreParams


class PredictJob(_DryRunProjectJob):
    kind: Literal["predict"] = "predict"
    account_id: str
    body: PredictParams


class PublishJob(_DryRunProjectJob):
    kind: Literal["publish"] = "publish"
    prediction_id: str
    body: PublishParams


class RetroJob(_DryRunProjectJob):
    kind: Literal["retro"] = "retro"
    publication_id: str
    body: RetroParams


class AnalyzeVideoJob(_DryRunProjectJob):
    kind: Literal["analyze_video"] = "analyze_video"
    video_id: str
    body: VideoAnalysisParams


class AnalyzeCommentsJob(_DryRunProjectJob):
    kind: Literal["analyze_comments"] = "analyze_comments"
    account_id: str
    body: CommentAnalysisParams


class AnalyzeMediaJob(_DryRunProjectJob):
    kind: Literal["analyze_media"] = "analyze_media"
    video_id: str
    body: MediaAnalysisParams


ApiTaskJob: TypeAlias = Annotated[
    CollectionAnalyzeJob
    | SampleJob
    | ReportJob
    | OpenKBSyncJob
    | OpenKBQueryJob
    | DistillJob
    | CompareJob
    | ScoreJob
    | PredictJob
    | PublishJob
    | RetroJob
    | AnalyzeVideoJob
    | AnalyzeCommentsJob
    | AnalyzeMediaJob,
    Field(discriminator="kind"),
]

_API_JOB_ADAPTER: TypeAdapter[ApiTaskJob] = TypeAdapter(ApiTaskJob)
_RESOURCE_CLASSES: dict[str, str] = {
    "collection_analyze": "provider",
    "openkb_sync": "provider",
    "openkb_query": "provider",
    "analyze_video": "model",
    "analyze_comments": "model",
    "analyze_media": "model",
    "sample": "analysis",
    "report": "analysis",
    "distill": "analysis",
    "compare": "analysis",
    "score": "analysis",
    "predict": "analysis",
    "publish": "analysis",
    "retro": "analysis",
}


def enqueue_api_job(tasks: TaskStore, job: ApiTaskJob) -> TaskData:
    """Submit one validated, retryable API job to the durable queue."""
    task_type = job.kind
    return enqueue_persistent_task(
        tasks,
        task_type=task_type,
        resource_class=_RESOURCE_CLASSES[task_type],
        job_payload=job.model_dump(mode="json"),
        retryable=True,
    )


def _openkb_integration(
    layout: ProjectLayout,
    *,
    require_remote_token: bool,
) -> OpenKBIntegrationService:
    target, token = resolve_openkb_target(
        layout,
        require_remote_token=require_remote_token,
    )
    return OpenKBIntegrationService.from_target(layout, target, token=token)


def execute_api_job(
    context: TaskExecutionContext,
    payload: dict[str, Any],
) -> Any:
    """Validate and execute one durable short-running API job."""
    context.raise_if_cancelled()
    job = _API_JOB_ADAPTER.validate_python(payload)
    layout = ProjectLayout.open(Path(job.project_path))

    if isinstance(job, CollectionAnalyzeJob):
        count, comments_per_video = resolve_profile_options(
            profile=job.body.profile,
            count=job.body.count,
            all_videos=job.body.all_videos,
            comments_per_video=job.body.comments_per_video,
        )
        collection_request = build_collection_request(
            profile_url=job.body.url,
            count=count,
            sort=job.body.sort,
            provider=job.body.provider,
            comments_per_video=comments_per_video,
            comment_video_limit=job.body.comment_video_limit,
        )
        provider = build_account_provider(job.body.provider)
        return AccountCollectionService(layout, provider).analyze_url(
            request=collection_request,
            confirm_provider_cost=job.body.confirm_provider_cost,
            dry_run=job.dry_run,
            collection_profile=job.body.profile,
            max_provider_calls=job.body.max_provider_calls,
        )

    if isinstance(job, SampleJob):
        return SamplingService(layout).select(
            account_id=job.account_id,
            size=job.body.size,
            dry_run=job.dry_run,
        )

    if isinstance(job, ReportJob):
        return ReportService(layout).generate_account_health(
            account_id=job.account_id,
            sample_size=job.body.sample_size,
            dry_run=job.dry_run,
        )

    if isinstance(job, OpenKBSyncJob):
        service = _openkb_integration(
            layout,
            require_remote_token=not job.dry_run,
        )
        if not job.dry_run:
            service.require_model_confirmation(job.body.confirm_model_processing)
        return service.sync_account(
            account_id=job.account_id,
            confirm_model_processing=job.body.confirm_model_processing,
            create_kb=job.body.create_kb,
            force=job.body.force,
            max_video_analyses=job.body.max_video_analyses,
            max_export_bytes=job.body.max_export_bytes,
            dry_run=job.dry_run,
        )

    if isinstance(job, OpenKBQueryJob):
        service = _openkb_integration(layout, require_remote_token=True)
        service.require_model_confirmation(job.body.confirm_model_processing)
        return service.query(
            question=job.body.question,
            confirm_model_processing=job.body.confirm_model_processing,
            save=job.body.save,
        )

    if isinstance(job, DistillJob):
        return AccountDistillationService(layout).distill(
            account_id=job.account_id,
            dry_run=job.dry_run,
        )

    if isinstance(job, CompareJob):
        return BenchmarkComparisonService(layout).compare(
            target_account_id=job.body.target_account_id,
            benchmark_account_ids=job.body.benchmark_account_ids,
            dry_run=job.dry_run,
        )

    if isinstance(job, ScoreJob):
        return ScoringService(layout).score(
            account_id=job.account_id,
            script=Path(job.body.script),
            title=job.body.title,
            topic=job.body.topic,
            target_pillar=job.body.target_pillar,
            target_metric=job.body.target_metric,
            planned_publish_hour=job.body.planned_publish_hour,
            dry_run=job.dry_run,
        )

    if isinstance(job, PredictJob):
        return PredictionService(layout).predict(
            account_id=job.account_id,
            script=Path(job.body.script),
            title=job.body.title,
            topic=job.body.topic,
            target_pillar=job.body.target_pillar,
            target_metric=job.body.target_metric,
            target_age_hours=job.body.target_age_hours,
            planned_publish_hour=job.body.planned_publish_hour,
            dry_run=job.dry_run,
        )

    if isinstance(job, PublishJob):
        return PublicationService(layout).register(
            prediction_id=job.prediction_id,
            video_id=job.body.video_id,
            published_at=job.body.published_at,
            url=job.body.url,
            notes=job.body.notes,
            dry_run=job.dry_run,
        )

    if isinstance(job, RetroJob):
        return RetroService(layout).run(
            publication_id=job.publication_id,
            snapshot=job.body.snapshot,
            target_age_hours=job.body.target_age_hours,
            dry_run=job.dry_run,
        )

    if isinstance(job, AnalyzeVideoJob):
        return VideoAnalysisService(layout).analyze(
            video_id=job.video_id,
            model_output=Path(job.body.model_output) if job.body.model_output else None,
            max_attempts=job.body.max_attempts,
            strict_model=job.body.strict_model,
            dry_run=job.dry_run,
        )

    if isinstance(job, AnalyzeCommentsJob):
        return CommentAnalysisService(layout).analyze(
            account_id=job.account_id,
            model_output=Path(job.body.model_output) if job.body.model_output else None,
            max_attempts=job.body.max_attempts,
            strict_model=job.body.strict_model,
            dry_run=job.dry_run,
        )

    if isinstance(job, AnalyzeMediaJob):
        return LocalMediaAnalysisService(layout).analyze(
            video_id=job.video_id,
            file=Path(job.body.file) if job.body.file else None,
            vision_output=Path(job.body.vision_output) if job.body.vision_output else None,
            strict_media=job.body.strict_media,
            strict_vision=job.body.strict_vision,
            scene_threshold=job.body.scene_threshold,
            max_keyframes=job.body.max_keyframes,
            dry_run=job.dry_run,
        )

    raise AssertionError(f"Unsupported API task job: {type(job).__name__}")


def execute_account_distill(
    context: TaskExecutionContext,
    payload: dict[str, Any],
) -> dict[str, Any]:
    """Rebuild and execute a workflow in whichever process claims the task."""
    job = AccountDistillJob.model_validate(payload)
    body = job.body
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
    **{task_type: execute_api_job for task_type in _RESOURCE_CLASSES},
}
