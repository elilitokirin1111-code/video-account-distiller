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
from video_account_distiller.doctor import doctor_report
from video_account_distiller.errors import DistillerError, ErrorCode
from video_account_distiller.insights import AnalysisContextService
from video_account_distiller.knowledge import KnowledgeExportService
from video_account_distiller.media import (
    AccountMediaEnrichmentService,
    OllamaVisionProvider,
    VisionModelProvider,
    WhisperCliTranscriber,
)
from video_account_distiller.models import AccountCollectionRequest, CollectionProviderKind
from video_account_distiller.reports import ReportService
from video_account_distiller.storage.project import ProjectLayout

WorkflowProgress = Callable[[float, str, str], None]


def _ignore_progress(progress: float, stage: str, message: str) -> None:
    del progress, stage, message


def _vision_provider(
    *,
    provider: str | None,
    model: str,
    base_url: str,
    batch_size: int,
    timeout_seconds: int,
) -> VisionModelProvider | None:
    if provider is None:
        return None
    if provider != "ollama":
        raise DistillerError(
            ErrorCode.SCHEMA_INVALID,
            "Self-service visual analysis currently supports only local Ollama",
        )
    return OllamaVisionProvider(
        model=model,
        base_url=base_url,
        batch_size=batch_size,
        timeout_seconds=timeout_seconds,
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
        media_limit: int = 20,
        whisper_model: str = "base",
        whisper_command: Path | None = None,
        vision_provider: str | None = "ollama",
        vision_model: str = "qwen3-vl:8b",
        ollama_base_url: str = "http://127.0.0.1:11434",
        vision_batch_size: int = 4,
        vision_timeout_seconds: int = 180,
        strict_media_enrichment: bool = False,
        strict_vision: bool = False,
        export_knowledge: bool = True,
        dry_run: bool = False,
        progress: WorkflowProgress = _ignore_progress,
    ) -> dict[str, Any]:
        """Run the bounded local-first workflow and report durable stage progress."""

        progress(0.03, "preflight", "正在检查采集范围与本机能力")
        if media_limit > 0 and request.provider != CollectionProviderKind.MEDIACRAWLER:
            raise DistillerError(
                ErrorCode.SCHEMA_INVALID,
                "Video-content enrichment currently requires the MediaCrawler provider",
            )

        local_vision = _vision_provider(
            provider=vision_provider if media_limit > 0 else None,
            model=vision_model,
            base_url=ollama_base_url,
            batch_size=vision_batch_size,
            timeout_seconds=vision_timeout_seconds,
        )
        transcriber = WhisperCliTranscriber(
            command=whisper_command,
            model=whisper_model,
        )
        collection_service = AccountCollectionService(self.project, self.provider)

        if dry_run:
            result = collection_service.analyze_url(
                request=request,
                confirm_provider_cost=confirm_provider_cost,
                dry_run=True,
                collection_profile=collection_profile,
                max_provider_calls=max_provider_calls,
            )
            diagnostics = doctor_report(self.project.root).model_dump(mode="json")
            result["workflow_plan"] = {
                "mode": "self_service_account_distill",
                "media_limit": media_limit,
                "transcription": {
                    "provider": transcriber.provider_name,
                    "model": transcriber.model_name,
                    "available": transcriber.available,
                },
                "vision": {
                    "provider": local_vision.provider_name if local_vision else "none",
                    "model": local_vision.model_name if local_vision else None,
                    "network_uploads": 0,
                },
                "knowledge_export": export_knowledge,
                "external_model_calls": 0,
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
                    "knowledge_export",
                ],
            }
            result["diagnostics"] = diagnostics
            progress(1.0, "ready", "预检完成，可以开始蒸馏")
            return result

        progress(0.08, "collect", "正在采集账号、作品、互动指标与公开评论")
        result = collection_service.analyze_url(
            request=request,
            confirm_provider_cost=confirm_provider_cost,
            dry_run=False,
            collection_profile=collection_profile,
            max_provider_calls=max_provider_calls,
        )
        account_id = str(result["account"]["account_id"])
        progress(0.34, "collection_complete", "采集与基础数据分析完成")

        if media_limit > 0:
            progress(0.38, "media", f"正在处理 {media_limit} 条视频的画面、音频与字幕")
            result["media_enrichment"] = AccountMediaEnrichmentService(
                self.project,
                transcriber=transcriber,
                vision_provider=local_vision,
            ).enrich(
                account_id=account_id,
                limit=media_limit,
                strict=strict_media_enrichment,
                strict_vision=strict_vision,
            )
            progress(0.78, "media_complete", "视频内容分析与转写完成")

        progress(0.82, "report", "正在重建账号画像、报告与分析上下文")
        result["report"] = ReportService(self.project).generate_account_health(
            account_id=account_id
        )
        result["benchmark_profile"] = AccountBenchmarkProfileService(self.project).build(
            account_id=account_id
        )
        context_limit = max(1, min(media_limit or 10, 25))
        result["analysis_context"] = AnalysisContextService(self.project).build(
            account_id=account_id,
            max_video_analyses=context_limit,
        )

        if export_knowledge:
            progress(0.93, "knowledge_export", "正在生成 GPT/OpenKB 可用的本地知识包")
            result["knowledge_export"] = KnowledgeExportService(self.project).export_account(
                account_id=account_id,
                max_video_analyses=context_limit,
                max_export_bytes=1_000_000,
            )

        result["workflow"] = {
            "mode": "self_service_account_distill",
            "account_id": account_id,
            "media_limit": media_limit,
            "external_model_calls": 0,
            "knowledge_exported": export_knowledge,
        }
        progress(1.0, "completed", "账号蒸馏完成")
        return result
