"""Serializable handlers for durable API task execution."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated, Any, Literal, TypeAlias, cast

from pydantic import BaseModel, Field, TypeAdapter

from video_account_distiller.api.schemas import (
    AccountDistillWorkflowParams,
    AccountMediaReparseParams,
    CollectionAnalyzeParams,
    CommentAnalysisParams,
    CompareParams,
    MediaAnalysisParams,
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
    resolve_comment_video_limit,
    resolve_profile_options,
)
from video_account_distiller.comments import CommentAnalysisService
from video_account_distiller.config import load_config
from video_account_distiller.distillation import (
    AccountDistillationService,
    BenchmarkComparisonService,
)
from video_account_distiller.distillation.video import SingleVideoDistillationService
from video_account_distiller.features import VideoAnalysisService
from video_account_distiller.insights import (
    KeyringCloudCredentialStore,
    build_account_analysis_provider,
    resolve_cloud_credential,
)
from video_account_distiller.media import (
    AccountMediaEnrichmentService,
    DownloadedMediaCleanupService,
    LocalMediaAnalysisService,
    build_local_transcriber,
)
from video_account_distiller.reports import ReportService
from video_account_distiller.sampling import SamplingService
from video_account_distiller.storage.project import ProjectLayout
from video_account_distiller.workflows import AccountDistillWorkflow
from video_account_distiller.workflows.account_distill import build_vision_provider


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


class AccountMediaReparseJob(_DryRunProjectJob):
    kind: Literal["account_media_reparse"] = "account_media_reparse"
    account_id: str
    body: AccountMediaReparseParams


ApiTaskJob: TypeAlias = Annotated[
    CollectionAnalyzeJob
    | SampleJob
    | ReportJob
    | DistillJob
    | CompareJob
    | ScoreJob
    | PredictJob
    | PublishJob
    | RetroJob
    | AnalyzeVideoJob
    | AnalyzeCommentsJob
    | AnalyzeMediaJob
    | AccountMediaReparseJob,
    Field(discriminator="kind"),
]

_API_JOB_ADAPTER: TypeAdapter[ApiTaskJob] = TypeAdapter(ApiTaskJob)
_RESOURCE_CLASSES: dict[str, str] = {
    "collection_analyze": "provider",
    "analyze_video": "model",
    "analyze_comments": "model",
    "analyze_media": "model",
    "account_media_reparse": "model",
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
            comment_video_limit=resolve_comment_video_limit(
                count=count,
                configured_limit=job.body.comment_video_limit,
            ),
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
        result = VideoAnalysisService(layout).analyze(
            video_id=job.video_id,
            model_output=Path(job.body.model_output) if job.body.model_output else None,
            max_attempts=job.body.max_attempts,
            strict_model=job.body.strict_model,
            dry_run=job.dry_run,
        )
        if job.body.deep:
            deep_provider = (
                cast(
                    Literal["ollama", "llamacpp", "cloud", "none"],
                    job.body.deep_provider,
                )
                if job.body.deep_provider in {"ollama", "llamacpp", "cloud", "none"}
                else None
            )
            deep_result = SingleVideoDistillationService(layout).distill(
                video_id=job.video_id,
                deep_provider=deep_provider,
                deep_model=job.body.deep_model,
                deep_base_url=job.body.deep_base_url,
                model_output=Path(job.body.deep_output) if job.body.deep_output else None,
                max_attempts=job.body.max_attempts,
                strict_model=job.body.strict_deep,
                dry_run=job.dry_run,
            )
            result["deep_distillation"] = deep_result
        return result

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

    if isinstance(job, AccountMediaReparseJob):
        config = load_config(layout.config_path)
        if job.body.vision_provider == "llamacpp":
            vision_base_url = config.models.llamacpp_base_url
            vision_model = config.models.llamacpp_model or job.body.vision_model
            vision_api_key = config.models.llamacpp_api_key
        else:
            vision_base_url = job.body.ollama_base_url
            vision_model = job.body.vision_model
            vision_api_key = None
        vision = build_vision_provider(
            provider=job.body.vision_provider,
            model=vision_model,
            base_url=vision_base_url,
            batch_size=job.body.vision_batch_size,
            timeout_seconds=job.body.vision_timeout_seconds,
            api_key=vision_api_key,
        )
        transcriber = build_local_transcriber(
            backend=job.body.whisper_backend,
            command=Path(job.body.whisper_command) if job.body.whisper_command else None,
            model=job.body.whisper_model,
            batch_size=job.body.whisper_batch_size,
        )
        result = AccountMediaEnrichmentService(
            layout,
            transcriber=transcriber,
            vision_provider=vision,
        ).enrich(
            account_id=job.account_id,
            limit=job.body.limit,
            strict=job.body.strict_media_enrichment,
            strict_vision=job.body.strict_vision,
            dry_run=job.dry_run,
            selection_mode=job.body.mode,
            video_ids=job.body.video_ids,
            refresh_media=job.body.refresh_media,
            progress=lambda value, message: context.progress(value, "media_reparse", message),
        )
        enrichment = result.get("enrichment") or {}
        media_analysis_paths = [
            str(item["media_analysis_path"])
            for item in enrichment.get("videos", [])
            if isinstance(item, dict) and item.get("media_analysis_path")
        ]
        if not job.dry_run and media_analysis_paths:
            context.progress(0.99, "media_cleanup", "正在删除重新解析完成后的本地原视频")
            result["media_cleanup"] = DownloadedMediaCleanupService(layout).cleanup_account(
                account_id=job.account_id,
                media_analysis_paths=media_analysis_paths,
                reason="post_media_reparse_storage_cleanup",
            )
        result["project_root"] = str(layout.root)
        return result

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
        comment_video_limit=resolve_comment_video_limit(
            count=count,
            configured_limit=body.comment_video_limit,
        ),
    )
    provider = build_account_provider(body.provider)
    analysis_options = body.knowledge_analysis.options() if body.knowledge_analysis else None
    analysis_provider = None
    if analysis_options is not None and not job.dry_run:
        resolved = resolve_cloud_credential(
            KeyringCloudCredentialStore(),
            analysis_options.provider.value,
        )
        analysis_provider = build_account_analysis_provider(
            analysis_options,
            credential=resolved.value if resolved is not None else None,
            credential_source=resolved.source if resolved is not None else None,
        )
    media_limit = body.media_limit
    if media_limit is None:
        media_limit = 20_000 if count is None else count
    return AccountDistillWorkflow(layout, provider).run(
        request=collection_request,
        collection_profile=body.profile,
        confirm_provider_cost=body.confirm_provider_cost,
        max_provider_calls=body.max_provider_calls,
        media_limit=media_limit,
        whisper_backend=body.whisper_backend,
        whisper_model=body.whisper_model,
        whisper_command=Path(body.whisper_command) if body.whisper_command else None,
        whisper_batch_size=body.whisper_batch_size,
        vision_provider=body.vision_provider,
        vision_model=body.vision_model,
        ollama_base_url=body.ollama_base_url,
        vision_batch_size=body.vision_batch_size,
        vision_timeout_seconds=body.vision_timeout_seconds,
        strict_media_enrichment=body.strict_media_enrichment,
        strict_vision=body.strict_vision,
        account_analysis_provider=analysis_provider,
        account_analysis_options=analysis_options,
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
