"""Self-service account collection, media enrichment, and distillation workflow."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

from video_account_distiller.benchmarking import AccountBenchmarkProfileService
from video_account_distiller.collection import (
    AccountCollectionProvider,
    AccountCollectionService,
    CollectionProfile,
)
from video_account_distiller.config import load_config
from video_account_distiller.distillation import AccountDistillationService
from video_account_distiller.doctor import doctor_report
from video_account_distiller.errors import DistillerError, ErrorCode
from video_account_distiller.features import CloudChatTextProvider, TextModelProvider
from video_account_distiller.insights import (
    AnalysisContextService,
    GptAnalysisOptions,
    RemoteAccountAnalysisService,
)
from video_account_distiller.insights.gpt_analysis import AccountAnalysisProvider
from video_account_distiller.knowledge import KnowledgeExportService
from video_account_distiller.media import (
    AccountMediaEnrichmentService,
    CloudVisionProvider,
    DownloadedMediaCleanupService,
    LlamaCppVisionProvider,
    OllamaVisionProvider,
    VisionModelProvider,
    build_local_transcriber,
)
from video_account_distiller.models import AccountCollectionRequest, CollectionProviderKind
from video_account_distiller.reports import NarrativeReportService, ReportService
from video_account_distiller.storage.project import ProjectLayout

WorkflowProgress = Callable[[float, str, str], None]
WorkflowCheckpoint = Callable[[str, dict[str, Any]], None]


def _ignore_progress(progress: float, stage: str, message: str) -> None:
    del progress, stage, message


def _ignore_checkpoint(stage: str, state: dict[str, Any]) -> None:
    del stage, state


def _ratio(completed: int, requested: int) -> float | None:
    if requested <= 0:
        return None
    return round(min(max(completed / requested, 0.0), 1.0), 4)


def _workflow_coverage(
    result: dict[str, Any],
    *,
    request: AccountCollectionRequest,
    media_limit: int,
    vision_requested: bool,
) -> dict[str, Any]:
    """Summarize declared-scope coverage without implying platform completeness."""
    account = result.get("account") or {}
    collection = result.get("collection") or {}
    provider_coverage = result.get("coverage") or {}
    collected_videos = int(collection.get("videos") or 0)
    collected_metrics = int(collection.get("metrics") or 0)
    collected_comments = int(collection.get("comments") or 0)
    requested_videos = request.count
    video_target = collected_videos if requested_videos is None else requested_videos

    snapshot_fields = {
        "followers": account.get("follower_count_current") is not None,
        "following": account.get("following_count_current") is not None,
        "total_likes": account.get("total_likes_current") is not None,
        "video_count": account.get("video_count_current") is not None,
    }
    snapshot_available = sum(snapshot_fields.values())

    comment_video_target = min(request.comment_video_limit, collected_videos)
    comment_target = request.comments_per_video * comment_video_target
    comments_provider = provider_coverage.get("comments") or {}

    enrichment = (result.get("media_enrichment") or {}).get("enrichment") or {}
    media_items = enrichment.get("videos") or []
    valid_media_items = [item for item in media_items if isinstance(item, dict)]
    media_selected = int(enrichment.get("selected_count") or 0)
    media_target = min(media_limit, collected_videos) if media_limit > 0 else 0
    media_analyzed = sum(bool(item.get("media_analysis_id")) for item in valid_media_items)
    transcript_ready = sum(
        (item.get("transcription") or {}).get("status") in {"complete", "reused"}
        for item in valid_media_items
    )
    text_analyzed = sum(bool(item.get("text_analysis_id")) for item in valid_media_items)
    vision_success = sum(item.get("vision_status") == "success" for item in valid_media_items)
    vision_degraded = sum(item.get("vision_status") == "degraded" for item in valid_media_items)

    partial = (
        collected_videos < video_target
        or collected_metrics < collected_videos
        or (
            request.comments_per_video > 0
            and str(comments_provider.get("status"))
            in {"partial_degraded", "no_usable_public_comments"}
        )
        or (media_target > 0 and media_analyzed < media_selected)
        or int(enrichment.get("failed_count") or 0) > 0
    )
    return {
        "status": "partial" if partial else "complete_for_declared_scope",
        "scope_note": (
            "覆盖率仅针对本次明确选择的范围；公开评论是有限一级评论样本，不代表平台全部评论。"
        ),
        "account_snapshot": {
            "available_fields": snapshot_available,
            "total_fields": len(snapshot_fields),
            "ratio": _ratio(snapshot_available, len(snapshot_fields)),
            "fields": snapshot_fields,
        },
        "videos": {
            "requested": requested_videos if requested_videos is not None else "all_available",
            "collected": collected_videos,
            "ratio": _ratio(collected_videos, video_target),
            "status": (provider_coverage.get("videos") or {}).get("status"),
        },
        "metrics": {
            "expected_videos": collected_videos,
            "covered_videos": min(collected_metrics, collected_videos),
            "records": collected_metrics,
            "ratio": _ratio(min(collected_metrics, collected_videos), collected_videos),
        },
        "comments": {
            "requested_per_video": request.comments_per_video,
            "requested_video_limit": request.comment_video_limit,
            "sampled_videos": int(collection.get("comment_videos") or 0),
            "bounded_target": comment_target,
            "collected": collected_comments,
            "ratio": _ratio(collected_comments, comment_target),
            "status": comments_provider.get("status"),
        },
        "media": {
            "requested": media_limit,
            "effective_target": media_target,
            "selected": media_selected,
            "analyzed": media_analyzed,
            "ratio": _ratio(media_analyzed, media_target),
            "completed": int(enrichment.get("completed_count") or 0),
            "degraded": int(enrichment.get("degraded_count") or 0),
            "failed": int(enrichment.get("failed_count") or 0),
        },
        "transcripts": {
            "requested": media_selected,
            "ready": transcript_ready,
            "ratio": _ratio(transcript_ready, media_selected),
        },
        "text_analysis": {
            "requested": media_selected,
            "ready": text_analyzed,
            "ratio": _ratio(text_analyzed, media_selected),
        },
        "vision": {
            "requested": media_selected if vision_requested else 0,
            "success": vision_success,
            "degraded": vision_degraded,
            "ratio": _ratio(vision_success, media_selected) if vision_requested else None,
            "status": "not_requested" if not vision_requested else "requested",
        },
        "warnings": list(collection.get("warnings") or []) + list(enrichment.get("warnings") or []),
    }


def build_vision_provider(
    *,
    provider: str | None,
    model: str,
    base_url: str,
    batch_size: int,
    timeout_seconds: int,
    api_key: str | None = None,
) -> VisionModelProvider | None:
    if provider is None:
        return None
    if provider == "ollama":
        return OllamaVisionProvider(
            model=model,
            base_url=base_url,
            batch_size=batch_size,
            timeout_seconds=timeout_seconds,
        )
    if provider == "llamacpp":
        return LlamaCppVisionProvider(
            model=model,
            base_url=base_url,
            batch_size=batch_size,
            timeout_seconds=timeout_seconds,
            api_key=api_key,
        )
    if provider == "cloud":
        return CloudVisionProvider(
            model=model,
            base_url=base_url,
            batch_size=batch_size,
            timeout_seconds=timeout_seconds,
            api_key=api_key,
        )
    raise DistillerError(
        ErrorCode.SCHEMA_INVALID,
        "Self-service visual analysis supports local Ollama or llama.cpp",
    )


class AccountDistillWorkflow:
    """Turn one public account homepage into reusable local analysis artifacts."""

    def __init__(
        self,
        project: ProjectLayout,
        provider: AccountCollectionProvider,
    ) -> None:
        self.project = project
        self.provider = provider

    def run(
        self,
        *,
        request: AccountCollectionRequest,
        collection_profile: CollectionProfile,
        confirm_provider_cost: bool = False,
        max_provider_calls: int | None = None,
        media_limit: int = 50,
        whisper_backend: str = "auto",
        whisper_model: str = "base",
        whisper_command: Path | None = None,
        whisper_batch_size: int = 8,
        vision_provider: str | None = "ollama",
        vision_model: str = "qwen3-vl-8b",
        text_provider: str | None = None,
        ollama_base_url: str = "http://127.0.0.1:11434",
        cloud_base_url: str | None = None,
        cloud_api_key: str | None = None,
        cloud_text_model: str | None = None,
        cloud_vision_model: str | None = None,
        vision_batch_size: int = 4,
        vision_timeout_seconds: int = 180,
        strict_media_enrichment: bool = False,
        strict_vision: bool = False,
        account_analysis_provider: AccountAnalysisProvider | None = None,
        account_analysis_options: GptAnalysisOptions | None = None,
        export_knowledge: bool = True,
        dry_run: bool = False,
        progress: WorkflowProgress = _ignore_progress,
        checkpoint: WorkflowCheckpoint = _ignore_checkpoint,
        resume_state: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Run the bounded local-first workflow and report durable stage progress."""

        progress(0.03, "preflight", "正在检查采集范围与本机能力")
        if media_limit > 0 and request.provider != CollectionProviderKind.MEDIACRAWLER:
            raise DistillerError(
                ErrorCode.SCHEMA_INVALID,
                "Video-content enrichment currently requires the MediaCrawler provider",
            )

        config = load_config(self.project.config_path)
        if vision_provider == "llamacpp":
            local_base_url = config.models.llamacpp_base_url
            local_vision_model = config.models.llamacpp_model or vision_model
            local_api_key = config.models.llamacpp_api_key
        elif vision_provider == "cloud":
            local_base_url = (
                cloud_base_url or config.models.cloud_base_url or "https://api.deepseek.com"
            )
            local_vision_model = cloud_vision_model or vision_model
            local_api_key = cloud_api_key or config.models.cloud_api_key
        else:
            local_base_url = ollama_base_url
            local_vision_model = vision_model
            local_api_key = None
        local_vision = build_vision_provider(
            provider=vision_provider if media_limit > 0 else None,
            model=local_vision_model,
            base_url=local_base_url,
            batch_size=vision_batch_size,
            timeout_seconds=vision_timeout_seconds,
            api_key=local_api_key,
        )
        local_text: TextModelProvider | None = None
        if text_provider == "cloud":
            local_text = CloudChatTextProvider(
                model=cloud_text_model or config.models.cloud_text_model or vision_model or "local",
                base_url=(
                    cloud_base_url or config.models.cloud_base_url or "https://api.deepseek.com"
                ),
                timeout_seconds=vision_timeout_seconds,
                api_key=cloud_api_key or config.models.cloud_api_key,
            )
        transcriber = build_local_transcriber(
            backend=whisper_backend,
            command=whisper_command,
            model=whisper_model,
            batch_size=whisper_batch_size,
        )
        collection_service = AccountCollectionService(self.project, self.provider)

        if dry_run:
            result = collection_service.analyze_url(
                request=request,
                confirm_provider_cost=confirm_provider_cost,
                dry_run=True,
                collection_profile=collection_profile,
                max_provider_calls=max_provider_calls,
                text_provider=local_text,
            )
            diagnostics = doctor_report(self.project.root).model_dump(mode="json")
            result["workflow_plan"] = {
                "mode": "self_service_account_distill",
                "media_limit": media_limit,
                "transcription": {
                    "provider": transcriber.provider_name,
                    "model": transcriber.model_name,
                    "available": transcriber.available,
                    "diagnostics": getattr(transcriber, "diagnostics", {}),
                },
                "vision": {
                    "provider": local_vision.provider_name if local_vision else "none",
                    "model": local_vision.model_name if local_vision else None,
                    "network_uploads": 0,
                },
                "knowledge_export": export_knowledge,
                "media_retention": {
                    "raw_video": "delete_after_success",
                    "derived_analysis": "preserve",
                    "keep_on_failure": True,
                },
                "external_model_calls": (1 if account_analysis_options is not None else 0),
                "stages": [
                    "collect",
                    "normalize",
                    "metrics",
                    "comments",
                    "media",
                    "transcribe",
                    "video_analysis",
                    "distill",
                    "report",
                    "knowledge_synthesis",
                    "knowledge_export",
                ],
            }
            result["diagnostics"] = diagnostics
            result["project_root"] = str(self.project.root)
            progress(1.0, "ready", "预检完成，可以开始蒸馏")
            return result

        request_payload = request.model_dump(mode="json")
        resumed_result: dict[str, Any] | None = None
        resume_stage = ""
        if (
            isinstance(resume_state, dict)
            and resume_state.get("request") == request_payload
            and resume_state.get("collection_profile") == collection_profile.value
            and isinstance(resume_state.get("result"), dict)
        ):
            resumed_result = dict(resume_state["result"])
            resume_stage = str(resume_state.get("stage") or "")

        if resumed_result is None:
            progress(0.08, "collect", "正在采集账号、作品、互动指标与公开评论")
            result = collection_service.analyze_url(
                request=request,
                confirm_provider_cost=confirm_provider_cost,
                dry_run=False,
                collection_profile=collection_profile,
                max_provider_calls=max_provider_calls,
                text_provider=local_text,
            )
            account_id = str(result["account"]["account_id"])
            checkpoint(
                "collection_complete",
                {
                    "version": "1.0.0",
                    "stage": "collection_complete",
                    "request": request_payload,
                    "collection_profile": collection_profile.value,
                    "account_id": account_id,
                    "result": result,
                },
            )
            progress(0.34, "collection_complete", "采集与基础数据分析完成")
        else:
            assert isinstance(resume_state, dict)
            result = resumed_result
            account_id = str(
                resume_state.get("account_id") or (result.get("account") or {}).get("account_id")
            )
            progress(0.34, "resuming", f"已从 {resume_stage or '安全检查点'} 恢复任务")

        media_already_complete = (
            media_limit > 0
            and isinstance(result.get("media_enrichment"), dict)
            and resume_stage
            in {
                "media_complete",
                "report_complete",
                "knowledge_export_complete",
                "narrative_complete",
                "media_cleanup_complete",
            }
        )
        if media_limit > 0 and not media_already_complete:
            progress(0.38, "media", f"正在处理 {media_limit} 条视频的画面、音频与字幕")

            def _media_progress(value: float, message: str) -> None:
                progress(0.38 + (min(max(value, 0.0), 1.0) * 0.4), "media", message)

            result["media_enrichment"] = AccountMediaEnrichmentService(
                self.project,
                transcriber=transcriber,
                vision_provider=local_vision,
                text_provider=local_text,
            ).enrich(
                account_id=account_id,
                limit=media_limit,
                strict=strict_media_enrichment,
                strict_vision=strict_vision,
                progress=_media_progress,
            )
            checkpoint(
                "media_complete",
                {
                    "version": "1.0.0",
                    "stage": "media_complete",
                    "request": request_payload,
                    "collection_profile": collection_profile.value,
                    "account_id": account_id,
                    "result": result,
                },
            )
            progress(0.78, "media_complete", "视频内容分析与转写完成")
        elif media_already_complete:
            progress(0.78, "resuming", "已复用检查点中的视频内容分析")

        progress(0.80, "distill", "正在从完整视频证据中重建账号模式与反例")
        result["distillation"] = AccountDistillationService(self.project).distill(
            account_id=account_id
        )
        progress(0.84, "report", "正在重建账号画像、报告与分析上下文")
        result["report"] = ReportService(self.project).generate_account_health(
            account_id=account_id
        )
        result["benchmark_profile"] = AccountBenchmarkProfileService(self.project).build(
            account_id=account_id
        )
        context_limit = max(1, min(media_limit or 100, 1_000))
        result["analysis_context"] = AnalysisContextService(self.project).build(
            account_id=account_id,
            max_video_analyses=context_limit,
        )
        checkpoint(
            "report_complete",
            {
                "version": "1.0.0",
                "stage": "report_complete",
                "request": request_payload,
                "collection_profile": collection_profile.value,
                "account_id": account_id,
                "result": result,
            },
        )

        if account_analysis_provider is not None and account_analysis_options is not None:
            progress(
                0.90,
                "knowledge_synthesis",
                "正在提炼可模仿打法、运营启发与可验证创意",
            )
            result["knowledge_synthesis"] = RemoteAccountAnalysisService(
                self.project,
                account_analysis_provider,
            ).analyze(
                account_id=account_id,
                options=account_analysis_options,
            )
        else:
            result["knowledge_synthesis"] = {
                "ok": True,
                "status": "evidence_ready",
                "knowledge_distilled": False,
                "message": "数据与证据已整理，但尚未运行模型知识蒸馏。",
            }

        if export_knowledge:
            progress(
                0.93,
                "knowledge_export",
                "正在生成运营学习报告与数据证据附件",
            )
            result["knowledge_export"] = KnowledgeExportService(self.project).export_account(
                account_id=account_id,
                max_video_analyses=context_limit,
                max_export_bytes=5_000_000,
            )
            checkpoint(
                "knowledge_export_complete",
                {
                    "version": "1.0.0",
                    "stage": "knowledge_export_complete",
                    "request": request_payload,
                    "collection_profile": collection_profile.value,
                    "account_id": account_id,
                    "result": result,
                },
            )

        progress(0.96, "narrative", "正在生成中文长文运营分析报告")
        result["narrative_report"] = NarrativeReportService(self.project).generate(
            account_id=account_id
        )
        checkpoint(
            "narrative_complete",
            {
                "version": "1.0.0",
                "stage": "narrative_complete",
                "request": request_payload,
                "collection_profile": collection_profile.value,
                "account_id": account_id,
                "result": result,
            },
        )

        enrichment_payload = result.get("media_enrichment") or {}
        enrichment = enrichment_payload.get("enrichment") or {}
        media_analysis_paths = [
            str(item["media_analysis_path"])
            for item in enrichment.get("videos", [])
            if isinstance(item, dict) and item.get("media_analysis_path")
        ]
        if media_analysis_paths:
            progress(0.99, "media_cleanup", "正在删除已完成分析的本地原视频")
            result["media_cleanup"] = DownloadedMediaCleanupService(
                self.project
            ).cleanup_account(
                account_id=account_id,
                media_analysis_paths=media_analysis_paths,
            )
            checkpoint(
                "media_cleanup_complete",
                {
                    "version": "1.0.0",
                    "stage": "media_cleanup_complete",
                    "request": request_payload,
                    "collection_profile": collection_profile.value,
                    "account_id": account_id,
                    "result": result,
                },
            )
        else:
            result["media_cleanup"] = {
                "ok": True,
                "deleted_count": 0,
                "deleted_bytes": 0,
                "message": "本次任务没有新增或复用需要清理的原视频。",
            }

        result["workflow"] = {
            "mode": "self_service_account_distill",
            "account_id": account_id,
            "media_limit": media_limit,
            "external_model_calls": (
                1
                if account_analysis_provider is not None and account_analysis_options is not None
                else 0
            ),
            "knowledge_status": (
                "distilled"
                if account_analysis_provider is not None and account_analysis_options is not None
                else "evidence_ready"
            ),
            "knowledge_exported": export_knowledge,
            "raw_videos_deleted_after_success": True,
        }
        result["workflow_coverage"] = _workflow_coverage(
            result,
            request=request,
            media_limit=media_limit,
            vision_requested=local_vision is not None,
        )
        result["project_root"] = str(self.project.root)
        progress(
            1.0,
            "completed",
            (
                "账号知识蒸馏完成"
                if account_analysis_provider is not None and account_analysis_options is not None
                else "账号数据与证据分析完成；经营知识蒸馏待运行"
            ),
        )
        return result
