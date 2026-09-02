"""Self-service account collection, media enrichment, and distillation workflow."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any, Literal

from video_account_distiller.benchmarking import AccountBenchmarkProfileService
from video_account_distiller.collection import (
    AccountCollectionProvider,
    AccountCollectionService,
    CollectionProfile,
)
from video_account_distiller.config import load_config
from video_account_distiller.distillation import AccountDistillationService
from video_account_distiller.distillation.account_knowledge import AccountVideoKnowledgeService
from video_account_distiller.distillation.video import (
    SingleVideoDistillationService,
    _latest_text_analysis,
)
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
    DeepSeekVisionProvider,
    DownloadedMediaCleanupService,
    LlamaCppVisionProvider,
    OllamaVisionProvider,
    QwenNativeVideoProvider,
    VisionModelProvider,
    build_local_transcriber,
)
from video_account_distiller.models import AccountCollectionRequest, CollectionProviderKind, Video
from video_account_distiller.reports import NarrativeReportService, ReportService
from video_account_distiller.storage.parquet import read_models
from video_account_distiller.storage.project import ProjectLayout

WorkflowProgress = Callable[[float, str, str], None]
WorkflowCheckpoint = Callable[[str, dict[str, Any]], None]


def _ignore_progress(progress: float, stage: str, message: str) -> None:
    del progress, stage, message


def _ignore_checkpoint(stage: str, state: dict[str, Any]) -> None:
    del stage, state


def _select_video_distillation_targets(
    project: ProjectLayout,
    *,
    account_id: str,
    media_enrichment: Any,
    limit: int,
) -> dict[str, Any]:
    """Resolve one shared, ordered target list for both per-video distillers."""

    enrichment = media_enrichment.get("enrichment") if isinstance(media_enrichment, dict) else None
    enrichment_videos = enrichment.get("videos") if isinstance(enrichment, dict) else None
    if isinstance(enrichment_videos, list):
        target_ids: list[str] = []
        seen: set[str] = set()
        for item in enrichment_videos:
            if not isinstance(item, dict) or item.get("status") == "failed":
                continue
            video_id = str(item.get("video_id") or "").strip()
            if not video_id or video_id in seen:
                continue
            if (
                not item.get("text_analysis_id")
                and _latest_text_analysis(project, video_id) is None
            ):
                continue
            seen.add(video_id)
            target_ids.append(video_id)
        target_ids = target_ids[: max(limit, 0)]
        return {
            "source": "current_media_enrichment",
            "video_ids": target_ids,
            "target_count": len(target_ids),
            "media_selected_count": len(enrichment_videos),
        }

    eligible = [
        video
        for video in sorted(
            (
                video
                for video in read_models(project.normalized_dir / "videos.parquet", Video)
                if video.account_id == account_id
            ),
            key=lambda item: item.video_id,
        )
        if _latest_text_analysis(project, video.video_id) is not None
    ]
    target_ids = [video.video_id for video in eligible[: max(limit, 0)]]
    return {
        "source": "existing_text_analysis_fallback",
        "video_ids": target_ids,
        "target_count": len(target_ids),
        "eligible_before_limit": len(eligible),
    }


def _distill_account_creative_cards(
    project: ProjectLayout,
    *,
    account_id: str,
    video_ids: Sequence[str],
    provider: Literal["ollama", "llamacpp", "cloud", "none"] | None,
    model: str | None,
    base_url: str | None,
    api_key: str | None,
    strict_model: bool,
    progress: WorkflowProgress,
) -> dict[str, Any]:
    """Create one evidence-bound topic/expression/craft card per eligible video."""

    requested_video_ids = list(dict.fromkeys(item for item in video_ids if item))
    videos_by_id = {
        video.video_id: video
        for video in read_models(project.normalized_dir / "videos.parquet", Video)
        if video.account_id == account_id
    }
    videos = [
        videos_by_id[video_id] for video_id in requested_video_ids if video_id in videos_by_id
    ]
    service = SingleVideoDistillationService(project)
    cards: list[dict[str, Any]] = []
    skipped: list[dict[str, str]] = [
        {
            "video_id": video_id,
            "title": video_id,
            "reason": "本次媒体增强选择的视频不属于该账号或缺少标准化记录",
        }
        for video_id in requested_video_ids
        if video_id not in videos_by_id
    ]
    eligible: list[Video] = []
    for video in videos:
        if _latest_text_analysis(project, video.video_id) is None:
            skipped.append(
                {
                    "video_id": video.video_id,
                    "title": video.title or video.video_id,
                    "reason": "缺少单视频文字盲分析",
                }
            )
        else:
            eligible.append(video)
    total = len(eligible)
    for index, video in enumerate(eligible, start=1):
        video_id = video.video_id
        title = video.title or video_id
        if not video_id:
            continue
        progress(
            0.82 + (0.04 * (index - 1) / max(total, 1)),
            "video_creative_distillation",
            f"正在拆解第 {index}/{total} 条视频的选材、表达与拍摄：{title[:32]}",
        )
        try:
            result = service.distill(
                video_id=video_id,
                deep_provider=provider,
                deep_model=model,
                deep_base_url=base_url,
                deep_api_key=api_key,
                strict_model=strict_model,
            )
            artifact = result["distillation"]
            report_path = next(
                (
                    str(path)
                    for path in result.get("outputs") or []
                    if str(path).endswith("report.md")
                ),
                "",
            )
            cards.append(
                {
                    "video_id": video_id,
                    "distillation_id": artifact["distillation_id"],
                    "status": artifact["status"],
                    "report_path": report_path,
                }
            )
        except (DistillerError, OSError, TypeError, ValueError, KeyError) as exc:
            if strict_model:
                raise
            skipped.append({"video_id": video_id, "title": title, "reason": str(exc)})

    degraded_count = sum(item["status"] == "degraded" for item in cards)
    return {
        "ok": True,
        "account_id": account_id,
        "status": "complete" if cards and not skipped and degraded_count == 0 else "degraded",
        "target_video_ids": requested_video_ids,
        "requested_count": len(requested_video_ids),
        "eligible_count": total,
        "completed_count": len(cards) - degraded_count,
        "degraded_count": degraded_count,
        "skipped_count": len(skipped),
        "cards": cards,
        "outputs": [item["report_path"] for item in cards if item["report_path"]],
        "skipped": skipped,
        "document_shape": "one_creative_card_per_video",
    }


def _count_value(value: Any, default: int = 0) -> int:
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.isdigit():
        return int(value)
    return default


def _summarize_video_distillation(
    *,
    target_video_ids: Sequence[str],
    knowledge_result: dict[str, Any],
    creative_result: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Summarize real per-video outcomes without upgrading degraded/skipped batches."""

    target_ids = list(dict.fromkeys(item for item in target_video_ids if item))
    manifest = knowledge_result.get("manifest") or {}
    documents = manifest.get("documents") or []
    inferred_knowledge_degraded = sum(
        item.get("status") == "degraded" for item in documents if isinstance(item, dict)
    )
    knowledge_degraded = _count_value(manifest.get("degraded_count"), inferred_knowledge_degraded)
    knowledge_completed = _count_value(
        manifest.get("completed_count"), max(len(documents) - knowledge_degraded, 0)
    )
    knowledge_skipped = _count_value(manifest.get("skipped_count"))
    knowledge_requested = _count_value(manifest.get("requested_count"), len(target_ids))
    knowledge_status = (
        "complete"
        if target_ids
        and manifest.get("status") != "degraded"
        and knowledge_requested == len(target_ids)
        and knowledge_completed == len(target_ids)
        and knowledge_degraded == 0
        and knowledge_skipped == 0
        and len(documents) == len(target_ids)
        else "degraded"
    )
    knowledge_summary = {
        "status": knowledge_status,
        "requested_count": knowledge_requested,
        "completed_count": knowledge_completed,
        "degraded_count": knowledge_degraded,
        "skipped_count": knowledge_skipped,
        "document_count": len(documents),
    }
    required_statuses = [knowledge_status]
    result: dict[str, Any] = {
        "target_video_ids": target_ids,
        "target_count": len(target_ids),
        "knowledge": knowledge_summary,
    }
    if creative_result is not None:
        cards = creative_result.get("cards") or []
        inferred_creative_degraded = sum(
            item.get("status") == "degraded" for item in cards if isinstance(item, dict)
        )
        creative_requested = _count_value(creative_result.get("requested_count"), len(target_ids))
        creative_degraded = _count_value(
            creative_result.get("degraded_count"), inferred_creative_degraded
        )
        creative_completed = _count_value(
            creative_result.get("completed_count"), max(len(cards) - creative_degraded, 0)
        )
        creative_skipped = _count_value(creative_result.get("skipped_count"))
        creative_status = (
            "complete"
            if target_ids
            and creative_result.get("status") != "degraded"
            and creative_requested == len(target_ids)
            and creative_completed == len(target_ids)
            and creative_degraded == 0
            and creative_skipped == 0
            and len(cards) == len(target_ids)
            else "degraded"
        )
        creative_summary: dict[str, Any] = {
            "status": creative_status,
            "requested_count": creative_requested,
            "completed_count": creative_completed,
            "degraded_count": creative_degraded,
            "skipped_count": creative_skipped,
            "card_count": len(cards),
        }
        result["creative"] = creative_summary
        required_statuses.append(creative_status)
    result["status"] = (
        "complete"
        if target_ids and all(item == "complete" for item in required_statuses)
        else "degraded"
    )
    return result


def _video_distillation_completion_message(summary: dict[str, Any], *, full_mode: bool) -> str:
    if summary.get("status") == "complete":
        return (
            "逐视频内容、选材、表达、拍摄与账号规律蒸馏完成"
            if full_mode
            else "账号逐视频内容知识提取完成"
        )
    knowledge = summary.get("knowledge") or {}
    knowledge_counts = (
        f"知识完整 {int(knowledge.get('completed_count') or 0)}、"
        f"降级 {int(knowledge.get('degraded_count') or 0)}、"
        f"跳过 {int(knowledge.get('skipped_count') or 0)}"
    )
    if not full_mode:
        return f"逐视频知识提取结束，但存在降级或跳过（{knowledge_counts}）"
    creative = summary.get("creative") or {}
    creative_counts = (
        f"创作卡完整 {int(creative.get('completed_count') or 0)}、"
        f"降级 {int(creative.get('degraded_count') or 0)}、"
        f"跳过 {int(creative.get('skipped_count') or 0)}"
    )
    return f"账号级归纳已完成；逐视频批次存在降级或跳过（{knowledge_counts}；{creative_counts}）"


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
        normalized_model = model.casefold()
        if normalized_model.startswith("qwen3.7-plus"):
            return QwenNativeVideoProvider(
                model=model,
                base_url=base_url,
                batch_size=batch_size,
                timeout_seconds=timeout_seconds,
                api_key=api_key,
            )
        if normalized_model.startswith("deepseek-v4-flash-vision"):
            return DeepSeekVisionProvider(
                model=model,
                base_url=base_url,
                batch_size=batch_size,
                timeout_seconds=timeout_seconds,
                api_key=api_key,
            )
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
        analysis_focus: Literal["general", "hospitality"] = "general",
        distillation_mode: Literal["creative_learning", "knowledge"] = "creative_learning",
        distill_video_knowledge: bool = False,
        video_knowledge_provider: Literal["ollama", "llamacpp", "cloud", "none"] | None = None,
        video_knowledge_model: str | None = None,
        video_knowledge_base_url: str | None = None,
        video_knowledge_api_key: str | None = None,
        strict_video_knowledge: bool = False,
        export_knowledge: bool = True,
        dry_run: bool = False,
        progress: WorkflowProgress = _ignore_progress,
        checkpoint: WorkflowCheckpoint = _ignore_checkpoint,
        resume_state: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Run the bounded local-first workflow and report durable stage progress."""

        knowledge_mode = distillation_mode == "knowledge"
        full_mode = distillation_mode == "creative_learning" and distill_video_knowledge
        video_knowledge_enabled = knowledge_mode or distill_video_knowledge
        effective_mode: Literal["creative_learning", "knowledge"] = (
            "knowledge" if knowledge_mode else "creative_learning"
        )
        progress(0.03, "preflight", "正在检查采集范围与本机能力")
        if video_knowledge_enabled and media_limit <= 0:
            raise DistillerError(
                ErrorCode.SCHEMA_INVALID,
                "Video-content knowledge extraction requires video download and analysis",
                details={"next": "set media_limit above zero for full or knowledge mode"},
            )
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
                include_operational_analysis=not knowledge_mode,
            )
            diagnostics = doctor_report(self.project.root).model_dump(mode="json")
            result["workflow_plan"] = {
                "mode": (
                    "account_video_knowledge"
                    if knowledge_mode
                    else "full_creative_account_distill"
                    if full_mode
                    else "self_service_account_distill"
                ),
                "distillation_mode": effective_mode,
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
                "knowledge_export": export_knowledge and not knowledge_mode,
                "video_knowledge": {
                    "enabled": video_knowledge_enabled,
                    "document_shape": "one_markdown_per_video",
                    "provider": video_knowledge_provider,
                    "model": video_knowledge_model,
                    "external_model_calls": (
                        "per_eligible_video"
                        if video_knowledge_enabled
                        and video_knowledge_provider not in {None, "none"}
                        else 0
                    ),
                },
                "video_creative_distillation": {
                    "enabled": full_mode,
                    "document_shape": "one_creative_card_per_video",
                    "provider": video_knowledge_provider,
                    "model": video_knowledge_model,
                    "external_model_calls": (
                        "per_eligible_video"
                        if full_mode and video_knowledge_provider not in {None, "none"}
                        else 0
                    ),
                },
                "analysis_focus": analysis_focus,
                "media_retention": {
                    "raw_video": "delete_after_success",
                    "derived_analysis": "preserve",
                    "keep_on_failure": True,
                },
                "external_model_calls": (1 if account_analysis_options is not None else 0),
                "stages": (
                    [
                        "collect",
                        "normalize",
                        "metrics",
                        "media",
                        "transcribe",
                        "video_analysis",
                        "video_knowledge",
                    ]
                    if knowledge_mode
                    else [
                        "collect",
                        "normalize",
                        "metrics",
                        "comments",
                        "media",
                        "transcribe",
                        "video_analysis",
                        "video_knowledge",
                        "video_creative_distillation",
                        "distill",
                        "report",
                        "knowledge_synthesis",
                        "knowledge_export",
                    ]
                    if full_mode
                    else [
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
                    ]
                ),
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
            and resume_state.get("analysis_focus", "general") == analysis_focus
            and resume_state.get("distillation_mode", "creative_learning") == effective_mode
            and bool(
                resume_state.get(
                    "video_knowledge_enabled",
                    effective_mode == "knowledge",
                )
            )
            == video_knowledge_enabled
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
                include_operational_analysis=not knowledge_mode,
            )
            account_id = str(result["account"]["account_id"])
            checkpoint(
                "collection_complete",
                {
                    "version": "1.0.0",
                    "stage": "collection_complete",
                    "request": request_payload,
                    "collection_profile": collection_profile.value,
                    "analysis_focus": analysis_focus,
                    "distillation_mode": effective_mode,
                    "video_knowledge_enabled": video_knowledge_enabled,
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
                "video_full_complete",
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
                    "analysis_focus": analysis_focus,
                    "distillation_mode": effective_mode,
                    "video_knowledge_enabled": video_knowledge_enabled,
                    "account_id": account_id,
                    "result": result,
                },
            )
            progress(0.78, "media_complete", "视频内容分析与转写完成")
        elif media_already_complete:
            progress(0.78, "resuming", "已复用检查点中的视频内容分析")

        if video_knowledge_enabled:
            targets = _select_video_distillation_targets(
                self.project,
                account_id=account_id,
                media_enrichment=result.get("media_enrichment"),
                limit=media_limit,
            )
            result["video_distillation_targets"] = targets
            target_video_ids = targets["video_ids"]
            progress(
                0.80,
                "video_knowledge",
                "正在从每条视频内容中提取事实、概念、方法与适用边界",
            )
            result["video_knowledge"] = AccountVideoKnowledgeService(self.project).distill(
                account_id=account_id,
                video_ids=target_video_ids,
                provider=video_knowledge_provider,
                model=video_knowledge_model,
                base_url=video_knowledge_base_url,
                api_key=video_knowledge_api_key,
                strict_model=strict_video_knowledge,
            )
            if full_mode:
                result["video_creative_distillation"] = _distill_account_creative_cards(
                    self.project,
                    account_id=account_id,
                    video_ids=target_video_ids,
                    provider=video_knowledge_provider,
                    model=video_knowledge_model,
                    base_url=video_knowledge_base_url,
                    api_key=video_knowledge_api_key,
                    strict_model=strict_video_knowledge,
                    progress=progress,
                )
                result["video_creative_card_index"] = {
                    "document_shape": "one_creative_card_per_video",
                    "target_video_ids": target_video_ids,
                    "cards": result["video_creative_distillation"].get("cards") or [],
                }
            result["video_distillation_summary"] = _summarize_video_distillation(
                target_video_ids=target_video_ids,
                knowledge_result=result["video_knowledge"],
                creative_result=result.get("video_creative_distillation") if full_mode else None,
            )
            if full_mode:
                checkpoint(
                    "video_full_complete",
                    {
                        "version": "1.0.0",
                        "stage": "video_full_complete",
                        "request": request_payload,
                        "collection_profile": collection_profile.value,
                        "analysis_focus": analysis_focus,
                        "distillation_mode": effective_mode,
                        "video_knowledge_enabled": video_knowledge_enabled,
                        "account_id": account_id,
                        "result": result,
                    },
                )

        if knowledge_mode:
            for operational_key in (
                "report",
                "comment_analysis",
                "distillation",
                "benchmark_profile",
                "analysis_context",
                "knowledge_synthesis",
                "knowledge_export",
                "narrative_report",
            ):
                if result.get(operational_key) is None:
                    result.pop(operational_key, None)

            enrichment_payload = result.get("media_enrichment") or {}
            enrichment = enrichment_payload.get("enrichment") or {}
            media_analysis_paths = [
                str(item["media_analysis_path"])
                for item in enrichment.get("videos", [])
                if isinstance(item, dict) and item.get("media_analysis_path")
            ]
            if media_analysis_paths:
                progress(0.97, "media_cleanup", "正在删除已完成分析的本地原视频")
                result["media_cleanup"] = DownloadedMediaCleanupService(
                    self.project
                ).cleanup_account(
                    account_id=account_id,
                    media_analysis_paths=media_analysis_paths,
                )
            else:
                result["media_cleanup"] = {
                    "ok": True,
                    "deleted_count": 0,
                    "deleted_bytes": 0,
                    "message": "本次任务没有新增或复用需要清理的原视频。",
                }
            manifest = (result.get("video_knowledge") or {}).get("manifest") or {}
            video_summary = result.get("video_distillation_summary") or {}
            result["workflow"] = {
                "mode": "account_video_knowledge",
                "distillation_mode": "knowledge",
                "status": video_summary.get("status") or "degraded",
                "account_id": account_id,
                "media_limit": media_limit,
                "operational_analysis_run": False,
                "video_knowledge_exported": bool(manifest.get("documents")),
                "video_knowledge_document_shape": "one_markdown_per_video",
                "knowledge_documents": len(manifest.get("documents", [])),
                "skipped_videos": int(manifest.get("skipped_count") or 0),
                "raw_videos_deleted_after_success": True,
            }
            result["workflow_coverage"] = _workflow_coverage(
                result,
                request=request,
                media_limit=media_limit,
                vision_requested=local_vision is not None,
            )
            result["project_root"] = str(self.project.root)
            checkpoint(
                "video_knowledge_complete",
                {
                    "version": "1.0.0",
                    "stage": "video_knowledge_complete",
                    "request": request_payload,
                    "collection_profile": collection_profile.value,
                    "analysis_focus": analysis_focus,
                    "distillation_mode": effective_mode,
                    "video_knowledge_enabled": video_knowledge_enabled,
                    "account_id": account_id,
                    "result": result,
                },
            )
            progress(
                1.0,
                "completed",
                _video_distillation_completion_message(video_summary, full_mode=False),
            )
            return result

        progress(
            0.86 if full_mode else 0.80,
            "distill",
            "正在从完整视频证据中重建账号模式与反例",
        )
        result["distillation"] = AccountDistillationService(self.project).distill(
            account_id=account_id
        )
        progress(
            0.88 if full_mode else 0.84,
            "report",
            "正在重建账号画像、报告与分析上下文",
        )
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
                "analysis_focus": analysis_focus,
                "distillation_mode": effective_mode,
                "video_knowledge_enabled": video_knowledge_enabled,
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
                    "analysis_focus": analysis_focus,
                    "distillation_mode": effective_mode,
                    "video_knowledge_enabled": video_knowledge_enabled,
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
                "analysis_focus": analysis_focus,
                "distillation_mode": effective_mode,
                "video_knowledge_enabled": video_knowledge_enabled,
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
            result["media_cleanup"] = DownloadedMediaCleanupService(self.project).cleanup_account(
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
                    "analysis_focus": analysis_focus,
                    "distillation_mode": effective_mode,
                    "video_knowledge_enabled": video_knowledge_enabled,
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

        video_summary = result.get("video_distillation_summary") or {}
        full_video_status = video_summary.get("status") if full_mode else None
        result["workflow"] = {
            "mode": "full_creative_account_distill"
            if full_mode
            else "self_service_account_distill",
            "distillation_mode": effective_mode,
            "status": full_video_status or "complete",
            "account_id": account_id,
            "media_limit": media_limit,
            "analysis_focus": analysis_focus,
            "external_model_calls": (
                1
                if account_analysis_provider is not None and account_analysis_options is not None
                else 0
            ),
            "knowledge_status": (
                "full_video_and_account_distilled"
                if full_mode and full_video_status == "complete"
                else "account_distilled_with_video_batch_warnings"
                if full_mode
                else "distilled"
                if account_analysis_provider is not None and account_analysis_options is not None
                else "evidence_ready"
            ),
            "knowledge_exported": export_knowledge,
            "video_knowledge_exported": bool(
                ((result.get("video_knowledge") or {}).get("manifest") or {}).get("documents")
            )
            if full_mode
            else False,
            "video_knowledge_document_shape": ("one_markdown_per_video" if full_mode else None),
            "video_creative_cards": len(
                (result.get("video_creative_distillation") or {}).get("cards") or []
            ),
            "video_creative_document_shape": ("one_creative_card_per_video" if full_mode else None),
            "account_report_includes_video_creative_cards": False,
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
                _video_distillation_completion_message(video_summary, full_mode=True)
                if full_mode
                else "账号知识蒸馏完成"
                if account_analysis_provider is not None and account_analysis_options is not None
                else "账号数据与证据分析完成；经营知识蒸馏待运行"
            ),
        )
        return result
