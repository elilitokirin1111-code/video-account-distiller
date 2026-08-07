"""Blind two-stage single-video text analysis."""

from __future__ import annotations

import re
import shutil
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal, TypeVar, cast

from jinja2 import Environment, StrictUndefined
from pydantic import BaseModel

from video_account_distiller.config import load_config
from video_account_distiller.errors import DistillerError, ErrorCode
from video_account_distiller.features.prompts import (
    FACT_PROMPT_VERSION,
    SEMANTIC_PROMPT_VERSION,
    render_prompt,
)
from video_account_distiller.features.providers import (
    LlamaCppTextProvider,
    ModelSchemaFailure,
    OllamaTextProvider,
    StructuredFileProvider,
    TextModelProvider,
)
from video_account_distiller.models import (
    BlindContentAnalysis,
    BlindVideoBundle,
    CtaAnnotation,
    CtaType,
    DataQualityFlag,
    DerivedMetrics,
    EmotionLabel,
    EmotionPoint,
    EvidenceItem,
    EvidenceSource,
    ExtractedFact,
    HookAnnotation,
    HookType,
    MetricSnapshot,
    ModelTaskTrace,
    SingleVideoAnalysis,
    StructureAnnotation,
    StructureFunction,
    TranscriptInputSegment,
    TranscriptSegment,
    VideoAnalysisEvidenceIndex,
    VideoFactExtraction,
    VideoPerformanceContext,
    VideoSemanticAnnotation,
)
from video_account_distiller.storage.parquet import read_models
from video_account_distiller.storage.project import ProjectLayout
from video_account_distiller.utils.hashing import sha256_file, sha256_json
from video_account_distiller.utils.ids import stable_id
from video_account_distiller.utils.io import atomic_write_json, atomic_write_text, read_json
from video_account_distiller.utils.lookup import resolve_video

ANALYSIS_VERSION = "1.1.0"
ResponseT = TypeVar("ResponseT", bound=BaseModel)
ResponseValidator = Callable[[ResponseT, set[str]], None]
CTA_KEYWORDS: tuple[tuple[CtaType, tuple[str, ...]], ...] = (
    (CtaType.FOLLOW, ("关注", "follow")),
    (CtaType.SAVE, ("收藏", "save")),
    (CtaType.COMMENT, ("评论", "留言", "comment")),
    (CtaType.SHARE, ("分享", "转发", "share")),
    (CtaType.DIRECT_MESSAGE, ("私信", "direct message", "dm")),
    (CtaType.PROFILE, ("主页", "profile")),
    (CtaType.PRODUCT, ("购买", "下单", "链接", "buy")),
    (CtaType.NEXT_EPISODE, ("下期", "下一集", "next episode")),
)
FORBIDDEN_BLIND_KEYS = {
    "views",
    "likes",
    "comments",
    "shares",
    "saves",
    "performance_score",
    "performance_band",
    "engagement_rate_by_view",
    "completion_efficiency",
    "is_promoted",
}
LOCAL_PILLAR_KEYWORDS: tuple[tuple[str, tuple[str, ...]], ...] = (
    (
        "酒店经营与运营",
        (
            "酒店",
            "宾馆",
            "民宿",
            "门店",
            "房价",
            "入住率",
            "ota",
            "店长",
            "经营",
            "运营",
        ),
    ),
    (
        "酒店服务与客诉",
        (
            "客诉",
            "投诉",
            "差评",
            "客人",
            "住客",
            "前台",
            "入住",
            "退房",
            "服务",
        ),
    ),
    (
        "客房与清洁管理",
        (
            "客房",
            "保洁",
            "打扫",
            "清洁",
            "布草",
            "床单",
            "卫生",
            "查房",
        ),
    ),
    (
        "职场与求职",
        (
            "上班",
            "下班",
            "员工",
            "工资",
            "面试",
            "面試",
            "求职",
            "求職",
            "打工",
            "同事",
            "职业",
            "職業",
            "工作",
            "简历",
            "簡歷",
            "履历",
            "履歷",
            "毕业生",
            "畢業生",
            "应届",
            "應屆",
            "招聘",
        ),
    ),
    (
        "旅行住宿知识",
        (
            "旅行",
            "旅游",
            "住宿",
            "订房",
            "房型",
            "出差",
            "旅客",
        ),
    ),
)


def _latest_by_snapshot(records: list[ResponseT]) -> ResponseT | None:
    return max(records, key=lambda item: cast(Any, item).snapshot_at) if records else None


def _segment_ids_from_semantics(value: VideoSemanticAnnotation) -> set[str]:
    found = set(value.primary_pillar_evidence_segment_ids)
    found.update(value.hook.evidence_segment_ids)
    found.update(value.cta.evidence_segment_ids)
    for segment in value.structure_segments:
        found.update(segment.evidence_segment_ids)
    for point in value.emotion_timeline:
        found.update(point.evidence_segment_ids)
    return found


def _validate_fact_evidence(value: VideoFactExtraction, valid_ids: set[str]) -> None:
    """Drop evidence references to segments the model could not have seen.

    Local models frequently truncate or fabricate long segment IDs; the label
    itself is usually still correct, so filter the citations instead of
    failing the whole analysis. Facts left without any surviving evidence are
    removed because the contract requires at least one citation.
    """
    kept: list[ExtractedFact] = []
    for fact in value.facts:
        surviving = [
            segment_id
            for segment_id in fact.evidence_segment_ids
            if segment_id in valid_ids
        ]
        if not surviving:
            continue  # Drop the fact; assigning [] would trip validate_assignment.
        fact.evidence_segment_ids = surviving
        kept.append(fact)
    value.facts = kept


def _validate_semantic_evidence(value: VideoSemanticAnnotation, valid_ids: set[str]) -> None:
    """Filter fabricated segment citations and downgrade unproven labels.

    The unknown-segment check remains the hard anti-hallucination gate, but
    local models cannot reliably reproduce long segment IDs, so citations are
    filtered in place and labels without surviving evidence become unknown.
    """
    def filtered(ids: list[str]) -> list[str]:
        return [segment_id for segment_id in ids if segment_id in valid_ids]

    value.primary_pillar_evidence_segment_ids = filtered(
        value.primary_pillar_evidence_segment_ids
    )
    value.hook.evidence_segment_ids = filtered(value.hook.evidence_segment_ids)
    value.cta.evidence_segment_ids = filtered(value.cta.evidence_segment_ids)
    # Structure and emotion entries require at least one surviving citation;
    # entries whose citations were fabricated are dropped entirely.
    value.structure_segments = [
        segment
        for segment in value.structure_segments
        if filtered(segment.evidence_segment_ids)
    ]
    value.emotion_timeline = [
        point
        for point in value.emotion_timeline
        if filtered(point.evidence_segment_ids)
    ]
    if value.primary_pillar != "unknown" and not value.primary_pillar_evidence_segment_ids:
        value.primary_pillar = "unknown"
    if value.hook.primary_type != HookType.UNKNOWN and not value.hook.evidence_segment_ids:
        value.hook.primary_type = HookType.UNKNOWN
    if (
        value.cta.primary_type not in {CtaType.NONE, CtaType.UNKNOWN}
        and not value.cta.evidence_segment_ids
    ):
        value.cta.primary_type = CtaType.UNKNOWN


def _assert_blind_payload(value: Any) -> None:
    if isinstance(value, dict):
        forbidden = FORBIDDEN_BLIND_KEYS.intersection(value)
        if forbidden:
            raise DistillerError(
                ErrorCode.INTERNAL,
                "Blind content bundle contains performance fields",
                details={"fields": sorted(forbidden)},
            )
        for item in value.values():
            _assert_blind_payload(item)
    elif isinstance(value, list):
        for item in value:
            _assert_blind_payload(item)


def _cta(text: str) -> tuple[CtaType, str | None]:
    lowered = text.casefold()
    for cta_type, keywords in CTA_KEYWORDS:
        if any(keyword.casefold() in lowered for keyword in keywords):
            return cta_type, text[:160]
    return CtaType.NONE, None


def _fallback_facts(bundle: BlindVideoBundle) -> VideoFactExtraction:
    segments = bundle.transcript_segments
    facts: list[ExtractedFact] = []
    cta_texts: list[str] = []
    for segment in segments:
        numbers = re.findall(r"(?<!\w)\d+(?:\.\d+)?%?", segment.text)
        for number in numbers[:3]:
            facts.append(
                ExtractedFact(
                    category="number",
                    text=number,
                    evidence_segment_ids=[segment.segment_id],
                )
            )
        cta_type, cta_text = _cta(segment.text)
        if cta_type != CtaType.NONE and cta_text is not None:
            cta_texts.append(cta_text)
    return VideoFactExtraction(
        transcript_language=bundle.language,
        opening_text=segments[0].text[:240],
        closing_text=segments[-1].text[-240:],
        segment_count=len(segments),
        character_count=sum(len(segment.text) for segment in segments),
        facts=facts[:20],
        explicit_cta_texts=cta_texts[:10],
        unknowns=["named entities and implied claims were not inferred in fallback mode"],
    )


def _fallback_hook(opening: TranscriptInputSegment) -> HookType:
    text = opening.text.casefold()
    if re.search(r"\d+", text):
        return HookType.NUMBER_LIST
    if any(value in text for value in ("为什么", "?", "？", "你知道")):
        return HookType.QUESTION_CHALLENGE
    if any(value in text for value in ("千万别", "不要", "避坑", "损失")):
        return HookType.LOSS_AVERSION
    if any(value in text for value in ("如何", "教你", "方法", "how to")):
        return HookType.EXPLICIT_BENEFIT
    return HookType.UNKNOWN


def _local_semantic_labels(
    bundle: BlindVideoBundle,
    *,
    cta_type: CtaType,
) -> tuple[
    str,
    list[str],
    list[str],
    str,
    str,
    list[str],
    list[str],
    list[str],
    str,
    float,
]:
    """Infer bounded Chinese semantic labels from explicit transcript keywords only."""

    segments = bundle.transcript_segments
    scored: list[tuple[int, int, str, tuple[str, ...], list[str]]] = []
    for order, (pillar, keywords) in enumerate(LOCAL_PILLAR_KEYWORDS):
        evidence = [
            item.segment_id
            for item in segments
            if any(keyword.casefold() in item.text.casefold() for keyword in keywords)
        ]
        scored.append((len(evidence), -order, pillar, keywords, evidence))
    count, _, primary_pillar, _, evidence = max(scored)
    if count == 0:
        primary_pillar = "unknown"
        evidence = []
    secondary_topics = [
        pillar
        for matched, _, pillar, _, _ in sorted(scored, reverse=True)
        if matched > 0 and pillar != primary_pillar
    ][:3]
    joined = " ".join(item.text for item in segments)
    audience_tasks: list[str] = []
    if primary_pillar == "酒店经营与运营":
        audience_tasks.append("提升酒店经营与门店运营效率")
    elif primary_pillar == "酒店服务与客诉":
        audience_tasks.append("处理住客服务问题与客诉")
    elif primary_pillar == "客房与清洁管理":
        audience_tasks.append("改善客房清洁与房务流程")
    elif primary_pillar == "职场与求职":
        audience_tasks.append("了解求职、面试与职场选择")
    elif primary_pillar == "旅行住宿知识":
        audience_tasks.append("获取订房与住宿决策信息")
    instructional = any(
        keyword in joined for keyword in ("怎么", "如何", "方法", "技巧", "流程", "注意", "教你")
    )
    story = any(keyword in joined for keyword in ("今天", "有一次", "遇到", "后来", "结果", "当时"))
    list_like = bool(re.search(r"(?:^|\D)[一二三四五六七八九十123456789][、.，]", joined))
    if cta_type in {CtaType.PRODUCT, CtaType.DIRECT_MESSAGE, CtaType.PROFILE}:
        content_goal = "conversion"
        funnel_stage = "conversion"
    elif instructional:
        content_goal = "education"
        funnel_stage = "consideration"
    elif story:
        content_goal = "experience_sharing"
        funnel_stage = "awareness"
    else:
        content_goal = "information_sharing" if primary_pillar != "unknown" else "unknown"
        funnel_stage = "awareness" if primary_pillar != "unknown" else "unknown"
    narrative_type = (
        "list_explainer"
        if list_like
        else "process_explainer"
        if instructional
        else "case_story"
        if story
        else "direct_explainer"
        if primary_pillar != "unknown"
        else "unknown"
    )
    persona_signals: list[str] = []
    if any(keyword in joined for keyword in ("我们酒店", "我们店", "前台", "客房", "店长")):
        persona_signals.append("酒店一线从业者")
    if any(keyword in joined for keyword in ("我做酒店", "经营酒店", "酒店老板", "我的酒店")):
        persona_signals.append("酒店经营者")
    language_signals = (
        ["中文口语化表达"] if re.search(r"[\u4e00-\u9fff]", joined) is not None else []
    )
    confidence = 0.45 if primary_pillar != "unknown" else 0.2
    return (
        primary_pillar,
        evidence,
        secondary_topics,
        content_goal,
        funnel_stage,
        audience_tasks,
        persona_signals,
        language_signals,
        narrative_type,
        confidence,
    )


def _fallback_semantics(bundle: BlindVideoBundle) -> VideoSemanticAnnotation:
    segments = bundle.transcript_segments
    first = segments[0]
    last = segments[-1]
    hook_type = _fallback_hook(first)
    cta_type, cta_text = _cta(last.text)
    (
        primary_pillar,
        primary_evidence,
        secondary_topics,
        content_goal,
        funnel_stage,
        audience_tasks,
        persona_signals,
        language_signals,
        narrative_type,
        confidence,
    ) = _local_semantic_labels(bundle, cta_type=cta_type)
    structure = [
        StructureAnnotation(
            function=StructureFunction.HOOK,
            start_ms=first.start_ms,
            end_ms=first.end_ms,
            text_summary=first.text[:160],
            evidence_segment_ids=[first.segment_id],
        )
    ]
    if len(segments) > 2:
        middle = segments[1:-1]
        structure.append(
            StructureAnnotation(
                function=StructureFunction.DEVELOPMENT,
                start_ms=middle[0].start_ms,
                end_ms=middle[-1].end_ms,
                text_summary=" ".join(item.text for item in middle)[:240],
                evidence_segment_ids=[item.segment_id for item in middle],
            )
        )
    if len(segments) > 1:
        structure.append(
            StructureAnnotation(
                function=(
                    StructureFunction.CTA
                    if cta_type != CtaType.NONE
                    else StructureFunction.CONCLUSION
                ),
                start_ms=last.start_ms,
                end_ms=last.end_ms,
                text_summary=last.text[:160],
                evidence_segment_ids=[last.segment_id],
            )
        )
    duration = bundle.duration_seconds
    density: str = "unknown"
    if duration and duration > 0:
        characters_per_second = sum(len(item.text) for item in segments) / duration
        density = (
            "high"
            if characters_per_second >= 5
            else "medium"
            if characters_per_second >= 2
            else "low"
        )
    emotion_timeline: list[EmotionPoint] = []
    emotion_keywords = {
        EmotionLabel.CURIOSITY: ("为什么", "好奇", "秘密", "真相"),
        EmotionLabel.ANXIETY: ("焦虑", "担心", "害怕", "千万"),
        EmotionLabel.SURPRISE: ("竟然", "没想到", "惊讶"),
        EmotionLabel.TRUST: ("证据", "实测", "数据", "验证"),
    }
    for segment in segments:
        for emotion, keywords in emotion_keywords.items():
            if any(keyword in segment.text for keyword in keywords):
                emotion_timeline.append(
                    EmotionPoint(
                        emotion=emotion,
                        start_ms=segment.start_ms,
                        end_ms=segment.end_ms,
                        evidence_segment_ids=[segment.segment_id],
                    )
                )
                break
    return VideoSemanticAnnotation(
        primary_pillar=primary_pillar,
        primary_pillar_evidence_segment_ids=primary_evidence,
        secondary_topics=secondary_topics,
        audience_tasks=audience_tasks,
        content_goal=content_goal,
        funnel_stage=funnel_stage,
        hook=HookAnnotation(
            primary_type=hook_type,
            hook_text=first.text[:240],
            start_ms=first.start_ms,
            end_ms=first.end_ms,
            evidence_segment_ids=([first.segment_id] if hook_type != HookType.UNKNOWN else []),
        ),
        structure_segments=structure,
        narrative_type=narrative_type,
        information_density=cast(Any, density),
        emotion_timeline=emotion_timeline,
        cta=CtaAnnotation(
            primary_type=cta_type,
            text=cta_text,
            alignment_score=None,
            evidence_segment_ids=([last.segment_id] if cta_type != CtaType.NONE else []),
        ),
        persona_signals=persona_signals,
        language_signals=language_signals,
        risk_flags=["local_keyword_heuristic_requires_human_or_model_review"],
        unknowns=[
            *([] if primary_pillar != "unknown" else ["content pillar"]),
            *([] if audience_tasks else ["audience task"]),
            *([] if narrative_type != "unknown" else ["narrative type"]),
            "visual and audio features",
        ],
        confidence=confidence,
    )


def _generate_with_retry(
    *,
    task: str,
    prompt: str,
    prompt_version: str,
    response_model: type[ResponseT],
    provider: TextModelProvider | None,
    max_attempts: int,
    valid_segment_ids: set[str],
    validator: ResponseValidator[ResponseT],
    fallback: ResponseT,
    strict_model: bool,
) -> tuple[ResponseT, ModelTaskTrace]:
    provider_name = provider.provider_name if provider is not None else "none"
    model_name = provider.model_name if provider is not None else "none"
    prompt_hash = sha256_json({"prompt": prompt})
    if provider is None:
        if strict_model:
            raise DistillerError(
                ErrorCode.MODEL_UNAVAILABLE,
                f"No text model provider configured for {task}",
            )
        return fallback, ModelTaskTrace(
            task=cast(Any, task),
            prompt_version=prompt_version,
            prompt_hash=prompt_hash,
            provider=provider_name,
            model=model_name,
            attempts=0,
            status="degraded",
            errors=["model provider unavailable; deterministic fallback used"],
        )
    errors: list[str] = []
    for attempt in range(1, max_attempts + 1):
        try:
            response = provider.generate_structured(prompt, response_model, temperature=0.0)
            validator(response, valid_segment_ids)
            return response, ModelTaskTrace(
                task=cast(Any, task),
                prompt_version=prompt_version,
                prompt_hash=prompt_hash,
                provider=provider_name,
                model=model_name,
                attempts=attempt,
                status="success",
                errors=errors,
            )
        except (ModelSchemaFailure, ValueError, TypeError) as exc:
            errors.append(str(exc)[:500])
    if strict_model:
        raise DistillerError(
            ErrorCode.MODEL_SCHEMA_INVALID,
            f"Model output remained invalid after {max_attempts} attempts: {task}",
            details={"task": task, "attempts": max_attempts, "errors": errors},
        )
    return fallback, ModelTaskTrace(
        task=cast(Any, task),
        prompt_version=prompt_version,
        prompt_hash=prompt_hash,
        provider=provider_name,
        model=model_name,
        attempts=max_attempts,
        status="degraded",
        errors=errors,
    )


def _evidence_source(table: str, record: Any) -> EvidenceSource:
    return EvidenceSource(
        table=cast(Any, table),
        record_id=record.record_id,
        source_record_id=record.source_record_id,
        raw_hash=record.raw_hash,
        run_id=record.run_id,
    )


class VideoAnalysisService:
    """Create a content-addressed blind analysis and stage-two metric context."""

    def __init__(self, project: ProjectLayout) -> None:
        self.project = project

    def analyze(
        self,
        *,
        video_id: str,
        model_output: Path | None = None,
        provider: TextModelProvider | None = None,
        max_attempts: int | None = None,
        strict_model: bool = False,
        dry_run: bool = False,
    ) -> dict[str, Any]:
        """Run blind facts/semantics, then attach metrics without relabeling content."""

        video = resolve_video(self.project, video_id)
        video_id = video.video_id
        transcript_segments = [
            item
            for item in read_models(
                self.project.normalized_dir / "transcripts.parquet", TranscriptSegment
            )
            if item.video_id == video_id
        ]
        transcript_segments.sort(
            key=lambda item: (
                item.start_ms is None,
                item.start_ms or 0,
                item.end_ms or 0,
                item.segment_id,
            )
        )
        if not transcript_segments:
            raise DistillerError(
                ErrorCode.INPUT_MISSING,
                f"No normalized transcript found for video: {video_id}",
                details={"next": "import transcripts and run normalize"},
            )
        if provider is not None and model_output is not None:
            raise DistillerError(
                ErrorCode.SCHEMA_INVALID,
                "Pass either provider or model_output, not both",
            )
        file_provider = StructuredFileProvider(model_output) if model_output is not None else None
        selected_provider = provider or file_provider
        config = load_config(self.project.config_path)
        if selected_provider is None and config.models.text_provider == "ollama":
            selected_provider = OllamaTextProvider(
                base_url=config.models.ollama_base_url,
                timeout_seconds=config.models.vision_timeout_seconds,
            )
        elif selected_provider is None and config.models.text_provider == "llamacpp":
            selected_provider = LlamaCppTextProvider(
                model=(
                    config.models.llamacpp_text_model
                    or config.models.llamacpp_model
                    or config.models.vision_model
                    or "local"
                ),
                base_url=config.models.llamacpp_text_base_url,
                timeout_seconds=config.models.vision_timeout_seconds,
                api_key=config.models.llamacpp_api_key,
            )
        attempts = max_attempts or config.models.max_schema_attempts
        effective_strict_model = strict_model or not config.models.allow_degraded_analysis
        bundle = BlindVideoBundle(
            video_id=video.video_id,
            platform=video.platform.value,
            title=video.title,
            description=video.description,
            duration_seconds=video.duration_seconds,
            language=video.language,
            transcript_segments=[
                TranscriptInputSegment(
                    segment_id=item.segment_id,
                    start_ms=item.start_ms,
                    end_ms=item.end_ms,
                    text=item.text,
                    speaker=item.speaker,
                )
                for item in transcript_segments
            ],
        )
        bundle_payload = bundle.model_dump(mode="json")
        _assert_blind_payload(bundle_payload)
        blind_bundle_hash = sha256_json(bundle_payload)
        valid_segment_ids = {item.segment_id for item in transcript_segments}

        def validate_facts(value: VideoFactExtraction, valid_ids: set[str]) -> None:
            _validate_fact_evidence(value, valid_ids)
            # Correct descriptive counts programmatically; local models cannot
            # reliably count long transcripts, and the values are derivable.
            value.segment_count = len(bundle.transcript_segments)
            value.character_count = sum(
                len(item.text) for item in bundle.transcript_segments
            )
            all_texts = [item.text for item in bundle.transcript_segments]
            if value.opening_text and not any(
                value.opening_text in text for text in all_texts
            ):
                raise ModelSchemaFailure(
                    "opening_text is not observable in the transcript"
                )
            if value.closing_text and not any(
                value.closing_text in text for text in all_texts
            ):
                raise ModelSchemaFailure(
                    "closing_text is not observable in the transcript"
                )

        fact_prompt = render_prompt(
            "video-fact-extraction.md",
            bundle_json=bundle_payload,
            schema_json=VideoFactExtraction.model_json_schema(),
        )
        facts, fact_trace = _generate_with_retry(
            task="video_fact_extraction",
            prompt=fact_prompt,
            prompt_version=FACT_PROMPT_VERSION,
            response_model=VideoFactExtraction,
            provider=selected_provider,
            max_attempts=attempts,
            valid_segment_ids=valid_segment_ids,
            validator=validate_facts,
            fallback=_fallback_facts(bundle),
            strict_model=effective_strict_model,
        )
        semantic_prompt = render_prompt(
            "video-semantic-labeling.md",
            bundle_json=bundle_payload,
            facts_json=facts.model_dump(mode="json"),
            schema_json=VideoSemanticAnnotation.model_json_schema(),
        )
        semantics, semantic_trace = _generate_with_retry(
            task="video_semantic_labeling",
            prompt=semantic_prompt,
            prompt_version=SEMANTIC_PROMPT_VERSION,
            response_model=VideoSemanticAnnotation,
            provider=selected_provider,
            max_attempts=attempts,
            valid_segment_ids=valid_segment_ids,
            validator=_validate_semantic_evidence,
            fallback=_fallback_semantics(bundle),
            strict_model=effective_strict_model,
        )
        blind_warnings = [
            error
            for trace in (fact_trace, semantic_trace)
            if trace.status == "degraded"
            for error in trace.errors
        ]
        blind = BlindContentAnalysis(
            video_id=video_id,
            bundle_hash=blind_bundle_hash,
            facts=facts,
            semantics=semantics,
            task_traces=[fact_trace, semantic_trace],
            warnings=blind_warnings,
        )

        metrics = [
            item
            for item in read_models(
                self.project.normalized_dir / "metric_snapshots.parquet", MetricSnapshot
            )
            if item.video_id == video_id
        ]
        derived = [
            item
            for item in read_models(
                self.project.normalized_dir / "derived_metrics.parquet", DerivedMetrics
            )
            if item.video_id == video_id
        ]
        metric = _latest_by_snapshot(metrics)
        derived_metric = _latest_by_snapshot(derived)
        performance_payload = {
            "metric_record_id": metric.record_id if metric else None,
            "derived_record_id": derived_metric.record_id if derived_metric else None,
            "snapshot_at": (
                derived_metric.snapshot_at.isoformat()
                if derived_metric
                else metric.snapshot_at.isoformat()
                if metric
                else None
            ),
            "views": metric.views if metric else None,
            "engagement_rate_by_view": (
                derived_metric.engagement_rate_by_view if derived_metric else None
            ),
            "completion_efficiency": (
                derived_metric.completion_efficiency if derived_metric else None
            ),
            "performance_score": derived_metric.performance_score if derived_metric else None,
            "performance_band": derived_metric.performance_band if derived_metric else None,
            "outlier_flags": derived_metric.outlier_flags if derived_metric else [],
            "is_promoted": (
                metric.is_promoted if metric and metric.is_promoted is not None else video.is_ad
            ),
        }
        provider_hash = file_provider.input_hash if file_provider is not None else None
        analysis_id = stable_id(
            "vta_",
            sha256_json(
                {
                    "video_id": video_id,
                    "analysis_version": ANALYSIS_VERSION,
                    "bundle_hash": blind_bundle_hash,
                    "facts": facts.model_dump(mode="json"),
                    "semantics": semantics.model_dump(mode="json"),
                    "task_traces": [
                        fact_trace.model_dump(mode="json"),
                        semantic_trace.model_dump(mode="json"),
                    ],
                    "performance": performance_payload,
                    "provider_input_hash": provider_hash,
                }
            ),
        )
        output_dir = self.project.root / "analyses" / "videos" / video_id / analysis_id
        output_paths = [
            output_dir / "analysis.json",
            output_dir / "report.md",
            output_dir / "blind-analysis.json",
            output_dir / "evidence-index.json",
            output_dir / "warnings.json",
        ]
        if output_paths[0].is_file() and not dry_run:
            return {
                "ok": True,
                "dry_run": False,
                "already_generated": True,
                "analysis": read_json(output_paths[0]),
                "outputs": [self.project.relative(path) for path in output_paths],
            }

        input_hashes = sorted(
            {
                video.raw_hash,
                *(item.raw_hash for item in transcript_segments),
                *(item.raw_hash for item in metrics),
                *(item.raw_hash for item in derived),
                *([provider_hash] if provider_hash else []),
            }
        )
        manifest = (
            None if dry_run else self.project.begin_run("analyze video", input_hashes=input_hashes)
        )
        run_id = manifest.run_id if manifest else stable_id("run_dry_", analysis_id)
        generated_at = datetime.now(UTC)
        evidence_items: list[EvidenceItem] = []
        segment_to_evidence: dict[str, str] = {}
        for segment in transcript_segments:
            evidence_id = stable_id("evi_", analysis_id, "transcript", segment.segment_id)
            segment_to_evidence[segment.segment_id] = evidence_id
            evidence_items.append(
                EvidenceItem(
                    evidence_id=evidence_id,
                    label=f"transcript.segment.{segment.segment_id}",
                    classification="fact",
                    value={
                        "text": segment.text,
                        "start_ms": segment.start_ms,
                        "end_ms": segment.end_ms,
                    },
                    calculation="direct normalized transcript segment",
                    sources=[_evidence_source("transcripts", segment)],
                )
            )
        video_evidence_id = stable_id("evi_", analysis_id, "video", video.record_id)
        evidence_items.append(
            EvidenceItem(
                evidence_id=video_evidence_id,
                label="video.metadata",
                classification="fact",
                value={
                    "platform": video.platform.value,
                    "title": video.title,
                    "description": video.description,
                    "duration_seconds": video.duration_seconds,
                    "language": video.language,
                    "is_ad": video.is_ad,
                },
                calculation="direct normalized video metadata used by the blind bundle",
                sources=[_evidence_source("videos", video)],
            )
        )
        performance_evidence: dict[str, str] = {"video": video_evidence_id}
        if metric is not None:
            evidence_id = stable_id("evi_", analysis_id, "metric", metric.record_id)
            performance_evidence["metric_snapshot"] = evidence_id
            evidence_items.append(
                EvidenceItem(
                    evidence_id=evidence_id,
                    label="performance.metric_snapshot",
                    classification="fact",
                    value={"views": metric.views, "is_promoted": metric.is_promoted},
                    calculation="latest metric snapshot for the video",
                    sources=[_evidence_source("metric_snapshots", metric)],
                )
            )
        if derived_metric is not None:
            evidence_id = stable_id("evi_", analysis_id, "derived", derived_metric.record_id)
            performance_evidence["derived_metrics"] = evidence_id
            evidence_items.append(
                EvidenceItem(
                    evidence_id=evidence_id,
                    label="performance.derived_metrics",
                    classification="statistical_association",
                    value={
                        "engagement_rate_by_view": derived_metric.engagement_rate_by_view,
                        "completion_efficiency": derived_metric.completion_efficiency,
                        "performance_score": derived_metric.performance_score,
                        "performance_band": derived_metric.performance_band,
                        "outlier_flags": derived_metric.outlier_flags,
                    },
                    calculation="account-local Phase 1 derived metrics",
                    sources=[_evidence_source("derived_metrics", derived_metric)],
                )
            )
        evidence_index = VideoAnalysisEvidenceIndex(
            analysis_id=analysis_id,
            video_id=video_id,
            run_id=run_id,
            generated_at=generated_at,
            input_hashes=input_hashes,
            segment_to_evidence=segment_to_evidence,
            items=evidence_items,
        )
        performance = VideoPerformanceContext(
            snapshot_at=(
                derived_metric.snapshot_at
                if derived_metric
                else metric.snapshot_at
                if metric
                else None
            ),
            views=metric.views if metric else None,
            engagement_rate_by_view=(
                derived_metric.engagement_rate_by_view if derived_metric else None
            ),
            completion_efficiency=(
                derived_metric.completion_efficiency if derived_metric else None
            ),
            performance_score=derived_metric.performance_score if derived_metric else None,
            performance_band=derived_metric.performance_band if derived_metric else None,
            outlier_flags=derived_metric.outlier_flags if derived_metric else [],
            is_promoted=(
                metric.is_promoted if metric and metric.is_promoted is not None else video.is_ad
            ),
            evidence_ids=performance_evidence,
        )
        warnings = list(
            dict.fromkeys(
                [
                    *blind_warnings,
                    "single_video_analysis_not_account_rule",
                    "text_only_analysis_does_not_infer_visual_or_audio_features",
                    "performance_was_attached_after_blind_labels_and_does_not_prove_causality",
                    *(
                        ["transcript_contains_low_confidence_segments"]
                        if any(
                            DataQualityFlag.TRANSCRIPT_LOW_CONFIDENCE in item.data_quality_flags
                            for item in transcript_segments
                        )
                        else []
                    ),
                ]
            )
        )
        status: Literal["complete", "degraded"] = (
            "degraded"
            if any(trace.status == "degraded" for trace in blind.task_traces)
            else "complete"
        )
        relative_paths = [self.project.relative(path) for path in output_paths]
        analysis = SingleVideoAnalysis(
            analysis_id=analysis_id,
            analysis_version=ANALYSIS_VERSION,
            video_id=video_id,
            account_id=video.account_id,
            generated_at=generated_at,
            run_id=run_id,
            status=status,
            blind_analysis_path=relative_paths[2],
            evidence_index_path=relative_paths[3],
            warnings_path=relative_paths[4],
            blind_analysis=blind,
            performance_context=performance,
            warnings=warnings,
        )
        result = {
            "ok": True,
            "dry_run": dry_run,
            "already_generated": False,
            "analysis": analysis.model_dump(mode="json"),
            "outputs": relative_paths,
        }
        if dry_run:
            return result

        assert manifest is not None
        if file_provider is not None:
            raw_model_path = (
                self.project.root / "raw" / "model-outputs" / f"{file_provider.input_hash}.json"
            )
            raw_model_path.parent.mkdir(parents=True, exist_ok=True)
            if not raw_model_path.exists():
                shutil.copyfile(file_provider.path, raw_model_path)
            if sha256_file(raw_model_path) != file_provider.input_hash:
                raise DistillerError(
                    ErrorCode.RAW_INTEGRITY,
                    f"Model output raw copy hash mismatch: {raw_model_path}",
                )
        output_dir.mkdir(parents=True, exist_ok=True)
        atomic_write_json(output_paths[0], analysis.model_dump(mode="json"))
        atomic_write_json(output_paths[2], blind.model_dump(mode="json"))
        atomic_write_json(output_paths[3], evidence_index.model_dump(mode="json"))
        atomic_write_json(output_paths[4], warnings)
        template_path = (
            Path(__file__).resolve().parents[1] / "reports" / "templates" / "video-analysis.md.j2"
        )
        template = Environment(undefined=StrictUndefined, autoescape=False).from_string(
            template_path.read_text(encoding="utf-8")
        )
        atomic_write_text(
            output_paths[1],
            template.render(
                analysis=analysis.model_dump(mode="python"),
                segment_evidence=segment_to_evidence,
            ).strip()
            + "\n",
        )
        state = self.project.load_state()
        state.last_video_analysis_at = datetime.now(UTC)
        self.project.save_state(state)
        self.project.finish_run(
            manifest,
            success=True,
            processed_counts={
                "transcript_segments": len(transcript_segments),
                "extracted_facts": len(facts.facts),
                "structure_segments": len(semantics.structure_segments),
            },
            output_files=relative_paths,
            warnings=warnings,
        )
        return result
