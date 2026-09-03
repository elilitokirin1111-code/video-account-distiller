"""Single-video deep distillation: topic selection, expression form, shooting craft.

A viewer may find one video interesting inside an account they do not follow.
This service merges the blind text analysis and the local media analysis into
one content-addressed reference card: how the video is selected (选材), how it
expresses itself (表现形式), how it is shot (拍摄手法), and a concrete copy
checklist. The deep model stage is optional; without a provider the service
degrades visibly to deterministic aggregation of the existing artifacts.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal, cast

from jinja2 import Environment, StrictUndefined
from pydantic import BaseModel

from video_account_distiller.config import load_config
from video_account_distiller.errors import DistillerError, ErrorCode
from video_account_distiller.features.prompts import (
    DEEP_DISTILLATION_PROMPT_VERSION,
    render_prompt,
)
from video_account_distiller.features.providers import (
    CloudChatTextProvider,
    LlamaCppTextProvider,
    ModelSchemaFailure,
    OllamaTextProvider,
    StructuredFileProvider,
    TextModelProvider,
)
from video_account_distiller.media.pipeline import _opening_technique_tags, _pacing_tags
from video_account_distiller.models import (
    ArtifactEvidenceIndex,
    CopyChecklist,
    CraftDistillation,
    EvidenceItem,
    EvidenceSource,
    ExpressionDistillation,
    MediaAnalysis,
    MediaFeatureRecord,
    ModelTaskTrace,
    SingleVideoAnalysis,
    SingleVideoCraftSummary,
    SingleVideoDeepOutput,
    SingleVideoDistillation,
    TopicDistillation,
    TranscriptSegment,
    Video,
)
from video_account_distiller.models.video_distillation import (
    CreativeFinding,
    CreativeScoreDimension,
    CreativeScoreDimensionKey,
    CreativeStructureBeat,
    PriorityImprovement,
    VideoCreativeEvaluation,
    VideoExecutiveSummary,
)
from video_account_distiller.storage.parquet import read_models
from video_account_distiller.storage.project import ProjectLayout
from video_account_distiller.utils.hashing import sha256_json
from video_account_distiller.utils.ids import stable_id
from video_account_distiller.utils.io import atomic_write_json, atomic_write_text, read_json
from video_account_distiller.utils.lookup import resolve_video

SINGLE_VIDEO_DISTILLATION_VERSION = "2.0.0"

_SCORE_DIMENSION_WEIGHTS: dict[CreativeScoreDimensionKey, int] = {
    "topic": 10,
    "hook": 15,
    "content_value": 15,
    "structure": 15,
    "expression": 10,
    "visual_craft": 10,
    "pacing": 8,
    "audio_packaging": 7,
    "emotion": 5,
    "conversion": 5,
}

_SCORE_DIMENSION_LABELS: dict[CreativeScoreDimensionKey, str] = {
    "topic": "选题",
    "hook": "钩子",
    "content_value": "内容价值",
    "structure": "结构",
    "expression": "表达",
    "visual_craft": "镜头与画面",
    "pacing": "节奏",
    "audio_packaging": "声音与包装",
    "emotion": "情绪",
    "conversion": "转化",
}

_CRAFT_COUNT_ATTRIBUTES: tuple[tuple[str, str], ...] = (
    ("shot_scale", "shot_scale"),
    ("camera_movement", "camera_movement"),
    ("camera_angle", "camera_angle"),
    ("composition", "composition"),
    ("lighting", "lighting"),
    ("text_overlay_style", "text_overlay_styles"),
    ("motion_graphic", "motion_graphics"),
    ("branding", "branding"),
)

_HOOK_ANGLE_LABELS = {
    "question_challenge": "提问挑战切入：用问题制造认知缺口",
    "loss_aversion": "损失厌恶切入：先讲不这么做会损失什么",
    "secret_reveal": "秘密揭示切入：抛出反常识或内部信息",
    "result_first": "结果前置切入：先给结论/成果再倒推过程",
    "counterintuitive": "反直觉切入：先说与常识相反的观点",
    "strong_conflict": "强冲突切入：开篇即对立或矛盾",
    "pain_point": "痛点切入：直接点出目标人群的困扰",
    "identity_callout": "身份点名切入：喊话特定职业/人群",
    "number_list": "数字清单切入：用可数条目承诺信息量",
    "time_pressure": "时间压力切入：强调时效或机会窗口",
    "failure_review": "失败复盘切入：以翻车/教训建立信任",
    "before_after": "前后对比切入：用变化制造期待",
    "story_suspense": "悬念叙事切入：以故事悬念留住观看",
    "authority": "权威背书切入：以从业者/专业身份开场",
    "social_proof": "社会证明切入：用多数人或案例背书",
    "controversial_stance": "争议立场切入：站队式表达激发讨论",
    "explicit_benefit": "利益直给切入：直接承诺可获得的收益",
    "process_demo": "过程演示切入：以真实操作过程开场",
    "direct_demo": "直接演示切入：不铺垫直接展示结果",
    "none": "无明确钩子",
}

_NARRATIVE_LABELS = {
    "list_explainer": "清单式讲解",
    "process_explainer": "流程式讲解",
    "case_story": "案例叙事",
    "direct_explainer": "直给式讲解",
}


def _source(table: str, row: Any) -> EvidenceSource:
    return EvidenceSource(
        table=cast(Any, table),
        record_id=row.record_id,
        source_record_id=row.source_record_id,
        raw_hash=row.raw_hash,
        run_id=row.run_id,
    )


def _latest_text_analysis(
    project: ProjectLayout, video_id: str
) -> tuple[SingleVideoAnalysis, Path] | None:
    selected: tuple[SingleVideoAnalysis, Path] | None = None
    for path in sorted((project.root / "analyses" / "videos" / video_id).glob("*/analysis.json")):
        try:
            value = SingleVideoAnalysis.model_validate(read_json(path))
        except (OSError, ValueError):
            continue
        if selected is None or (value.generated_at, value.analysis_id) > (
            selected[0].generated_at,
            selected[0].analysis_id,
        ):
            selected = (value, path)
    return selected


def _latest_media_analysis(
    project: ProjectLayout, video_id: str
) -> tuple[MediaAnalysis, MediaFeatureRecord | None] | None:
    selected: tuple[MediaFeatureRecord, datetime] | None = None
    for item in read_models(project.normalized_dir / "media_features.parquet", MediaFeatureRecord):
        if item.video_id != video_id:
            continue
        generated_at = datetime.min.replace(tzinfo=UTC)
        analysis_path = project.root / item.analysis_path
        if analysis_path.is_file():
            try:
                generated_at = MediaAnalysis.model_validate(read_json(analysis_path)).generated_at
            except (OSError, ValueError):
                pass
        if selected is None or (generated_at, item.analysis_id) > (
            selected[1],
            selected[0].analysis_id,
        ):
            selected = (item, generated_at)
    if selected is None:
        return None
    feature, _ = selected
    analysis_path = project.root / feature.analysis_path
    if not analysis_path.is_file():
        return None
    try:
        analysis = MediaAnalysis.model_validate(read_json(analysis_path))
    except (OSError, ValueError):
        return None
    return analysis, feature


def build_craft_summary(media: MediaAnalysis | None) -> SingleVideoCraftSummary:
    """Aggregate per-shot craft labels into one deterministic per-video summary."""
    if media is None:
        return SingleVideoCraftSummary(
            analyzed_shots=0,
            ocr_observation_count=0,
        )
    annotations = media.vision.shot_annotations if media.vision else []
    counts: dict[str, dict[str, int]] = {}
    for key, attribute in _CRAFT_COUNT_ATTRIBUTES:
        tallies: dict[str, int] = {}
        for annotation in annotations:
            for value in getattr(annotation, attribute):
                tallies[value] = tallies.get(value, 0) + 1
        counts[key] = tallies
    first = None
    if media.shots:
        first_shot = min(media.shots, key=lambda item: (item.start_ms, item.index))
        first = next(
            (item for item in annotations if item.shot_id == first_shot.shot_id),
            None,
        )
    average_shot_duration_ms = (
        sum(item.duration_ms for item in media.shots) / len(media.shots) if media.shots else None
    )
    return SingleVideoCraftSummary(
        analyzed_shots=len(media.shots),
        shot_scale=counts["shot_scale"],
        camera_movement=counts["camera_movement"],
        camera_angle=counts["camera_angle"],
        composition=counts["composition"],
        lighting=counts["lighting"],
        text_overlay_style=counts["text_overlay_style"],
        motion_graphic=counts["motion_graphic"],
        branding=counts["branding"],
        opening_techniques=_opening_technique_tags(first),
        pacing_tags=_pacing_tags(average_shot_duration_ms),
        average_shot_duration_ms=average_shot_duration_ms,
        silence_ratio=media.audio.silence_ratio,
        ocr_observation_count=len(media.vision.ocr_observations) if media.vision else 0,
    )


def _top_tags(counts: dict[str, int], limit: int = 3) -> str:
    ordered = sorted(counts.items(), key=lambda pair: (-pair[1], pair[0]))[:limit]
    return "、".join(f"{tag}×{count}" for tag, count in ordered) or "未见标注"


def _deduplicate(values: list[str]) -> list[str]:
    return list(dict.fromkeys(item for item in values if item))


def _rating_for_score(
    score: float | None,
) -> Literal["优先复刻候选", "值得借鉴", "改写后复用", "不建议直接复刻", "证据不足"]:
    if score is None:
        return "证据不足"
    if score >= 85:
        return "优先复刻候选"
    if score >= 70:
        return "值得借鉴"
    if score >= 55:
        return "改写后复用"
    return "不建议直接复刻"


def _normalize_evaluation(
    evaluation: VideoCreativeEvaluation,
    *,
    score_basis: Literal["model_assessment", "provisional_rule_score"],
) -> VideoCreativeEvaluation:
    """Apply fixed weights and withhold the total when scored coverage is below 60%."""
    supplied = {item.dimension: item for item in evaluation.dimensions}
    normalized: list[CreativeScoreDimension] = []
    active_weight = 0
    weighted_points = 0.0
    for dimension, weight in _SCORE_DIMENSION_WEIGHTS.items():
        item = supplied.get(dimension)
        if item is None:
            item = CreativeScoreDimension(
                dimension=dimension,
                score=None,
                weight=weight,
                rationale="输入未提供该维度的可靠判断，暂不评分。",
            )
        else:
            item = CreativeScoreDimension(
                dimension=dimension,
                score=round(item.score, 1) if item.score is not None else None,
                weight=weight,
                rationale=item.rationale,
                evidence_segment_ids=_deduplicate(item.evidence_segment_ids),
                evidence_shot_ids=_deduplicate(item.evidence_shot_ids),
            )
        normalized.append(item)
        if item.score is not None:
            active_weight += weight
            weighted_points += item.score * weight

    coverage = round(active_weight / 100, 2)
    overall = round(weighted_points / active_weight * 10, 1) if active_weight >= 60 else None
    if overall is None:
        confidence: Literal["high", "medium", "low", "insufficient"] = "insufficient"
        verdict = (
            f"仅有 {active_weight}% 的评分权重具备足够输入，低于 60% 门槛；"
            "保留分维度观察，但暂不形成综合分数。"
        )
        replicability: Literal["high", "medium", "low", "unknown"] = "unknown"
    else:
        confidence = (
            "low"
            if score_basis == "provisional_rule_score"
            else "high"
            if coverage >= 0.9
            else "medium"
            if coverage >= 0.75
            else "low"
        )
        verdict = evaluation.verdict
        replicability = evaluation.replicability
    return VideoCreativeEvaluation(
        score_basis=score_basis,
        overall_score=overall,
        rating=_rating_for_score(overall),
        score_confidence=confidence,
        evidence_coverage=coverage,
        verdict=verdict,
        replicability=replicability,
        dimensions=normalized,
    )


def _fallback_evaluation(
    analysis: SingleVideoAnalysis,
    media: MediaAnalysis | None,
    craft: SingleVideoCraftSummary,
) -> VideoCreativeEvaluation:
    """Produce conservative, deterministic provisional scores from observable signals."""
    semantics = analysis.blind_analysis.semantics
    facts = analysis.blind_analysis.facts
    text_reliable = analysis.status == "complete" and semantics.confidence >= 0.6
    media_reliable = bool(
        media is not None
        and media.status == "complete"
        and media.vision is not None
        and media.vision_trace.status == "success"
    )
    fact_ids = _deduplicate(
        [segment_id for item in facts.facts for segment_id in item.evidence_segment_ids]
    )
    structure_ids = _deduplicate(
        [
            segment_id
            for item in semantics.structure_segments
            for segment_id in item.evidence_segment_ids
        ]
    )
    visual_ids = (
        _deduplicate([item.shot_id for item in media.vision.shot_annotations])
        if media_reliable and media is not None and media.vision is not None
        else []
    )

    def dimension(
        key: CreativeScoreDimensionKey,
        score: float | None,
        rationale: str,
        *,
        segment_ids: list[str] | None = None,
        shot_ids: list[str] | None = None,
    ) -> CreativeScoreDimension:
        return CreativeScoreDimension(
            dimension=key,
            score=round(min(score, 10), 1) if score is not None else None,
            weight=_SCORE_DIMENSION_WEIGHTS[key],
            rationale=rationale,
            evidence_segment_ids=_deduplicate(segment_ids or [])[:20],
            evidence_shot_ids=_deduplicate(shot_ids or [])[:30],
        )

    topic_score: float | None
    hook_score: float | None
    value_score: float | None
    structure_score: float | None
    expression_score: float | None
    emotion_score: float | None
    conversion_score: float | None
    if text_reliable:
        topic_score = 4.0
        topic_score += 1.0 if semantics.primary_pillar.lower() != "unknown" else 0.0
        topic_score += 1.0 if semantics.audience_tasks else 0.0
        topic_score += 1.0 if semantics.information_density in {"medium", "high"} else 0.0
        topic_score += min(len(facts.facts), 3) * 0.5
        hook_score = 3.0
        hook_score += 2.0 if semantics.hook.primary_type.value != "unknown" else 0.0
        hook_score += 1.0 if semantics.hook.hook_text else 0.0
        hook_score += 1.0 if semantics.hook.promise else 0.0
        hook_score += 1.0 if semantics.hook.curiosity_gap else 0.0
        hook_score += 1.0 if (semantics.hook.start_ms or 0) <= 3_000 else 0.0
        value_score = 3.0 + min(len(facts.facts), 5) * 0.8
        value_score += {"high": 2.0, "medium": 1.0}.get(semantics.information_density, 0.0)
        value_score += 1.0 if semantics.audience_tasks else 0.0
        roles = {item.function.value for item in semantics.structure_segments}
        timed = sum(
            item.start_ms is not None and item.end_ms is not None
            for item in semantics.structure_segments
        )
        structure_score = 3.0 + min(len(roles), 4) * 0.8
        structure_score += 1.0 if "hook" in roles else 0.0
        structure_score += 1.0 if roles & {"cta", "conclusion", "loop"} else 0.0
        structure_score += 0.5 if timed == len(semantics.structure_segments) else 0.0
        expression_score = 3.0
        expression_score += min(len(semantics.persona_signals), 2) * 0.75
        expression_score += min(len(semantics.language_signals), 2) * 0.75
        expression_score += 1.0 if facts.opening_text else 0.0
        expression_score += 0.5 if facts.closing_text else 0.0
        emotion_score = (
            min(4.0 + len(semantics.emotion_timeline), 8.0) if semantics.emotion_timeline else None
        )
        conversion_score = (
            min(
                4.0
                + (1.0 if semantics.cta.text else 0.0)
                + (semantics.cta.alignment_score or 0.0) * 2,
                8.0,
            )
            if semantics.cta.primary_type.value not in {"unknown", "none"}
            else None
        )
    else:
        topic_score = hook_score = value_score = structure_score = expression_score = None
        emotion_score = conversion_score = None

    annotation_count = (
        len(media.vision.shot_annotations)
        if media_reliable and media is not None and media.vision is not None
        else 0
    )
    visual_score = None
    if media_reliable and annotation_count:
        visual_score = 4.0
        visual_score += min(len(craft.shot_scale), 3) * 0.5
        visual_score += 0.5 if craft.camera_movement else 0.0
        visual_score += 0.5 if craft.composition else 0.0
        visual_score += 0.5 if craft.lighting else 0.0
        visual_score += 0.5 if craft.opening_techniques else 0.0
    pacing_score = None
    if media_reliable and media is not None and len(media.shots) >= 2:
        average = craft.average_shot_duration_ms or 0
        pacing_score = 7.0 if 700 <= average <= 3_500 else 5.0
        pacing_score += 0.5 if craft.pacing_tags else 0.0
    audio_score = None
    if (
        media_reliable
        and media is not None
        and media.audio.status == "complete"
        and craft.silence_ratio is not None
    ):
        audio_score = 6.0 if craft.silence_ratio <= 0.5 else 4.5
        audio_score += 0.5 if craft.text_overlay_style or craft.motion_graphic else 0.0

    dimensions = [
        dimension(
            "topic",
            topic_score,
            "依据主题聚焦、受众任务、信息密度与事实数量进行暂定评分。"
            if text_reliable
            else "文本分析状态或语义置信度不足，暂不评分。",
            segment_ids=_deduplicate([*semantics.primary_pillar_evidence_segment_ids, *fact_ids]),
        ),
        dimension(
            "hook",
            hook_score,
            "依据钩子类型、原文、利益承诺、好奇缺口与出现时点进行暂定评分。"
            if text_reliable
            else "文本分析状态或语义置信度不足，暂不评分。",
            segment_ids=semantics.hook.evidence_segment_ids,
        ),
        dimension(
            "content_value",
            value_score,
            "依据可核验信息条数、信息密度与受众任务进行暂定评分。"
            if text_reliable
            else "文本分析状态或语义置信度不足，暂不评分。",
            segment_ids=fact_ids,
        ),
        dimension(
            "structure",
            structure_score,
            "依据结构角色完整度、时点覆盖以及收束环节进行暂定评分。"
            if text_reliable
            else "文本分析状态或语义置信度不足，暂不评分。",
            segment_ids=structure_ids,
        ),
        dimension(
            "expression",
            expression_score,
            "依据开闭场文本、人设与语言信号进行暂定评分。"
            if text_reliable
            else "文本分析状态或语义置信度不足，暂不评分。",
            segment_ids=structure_ids,
        ),
        dimension(
            "visual_craft",
            visual_score,
            "依据镜头级景别、运镜、构图、光线及开场视觉标注进行暂定评分。"
            if visual_score is not None
            else "缺少成功的镜头级视觉标注，暂不评分。",
            shot_ids=visual_ids,
        ),
        dimension(
            "pacing",
            pacing_score,
            "依据镜头数量、平均镜头时长与节奏标签进行暂定评分。"
            if pacing_score is not None
            else "镜头切分或视觉分析不足，暂不评分。",
            shot_ids=visual_ids,
        ),
        dimension(
            "audio_packaging",
            audio_score,
            "依据声音检测、静音占比及画面包装标签进行暂定评分。"
            if audio_score is not None
            else "音频或包装测量不足，暂不评分。",
            shot_ids=visual_ids,
        ),
        dimension(
            "emotion",
            emotion_score,
            "依据带时间证据的情绪节点数量进行暂定评分。"
            if emotion_score is not None
            else "未见可靠情绪时间线，暂不评分。",
            segment_ids=_deduplicate(
                [
                    segment_id
                    for item in semantics.emotion_timeline
                    for segment_id in item.evidence_segment_ids
                ]
            ),
        ),
        dimension(
            "conversion",
            conversion_score,
            "依据 CTA 类型、原文及内容目标一致性进行暂定评分。"
            if conversion_score is not None
            else "未见明确且可靠的 CTA，暂不评分。",
            segment_ids=semantics.cta.evidence_segment_ids,
        ),
    ]
    return _normalize_evaluation(
        VideoCreativeEvaluation(
            score_basis="provisional_rule_score",
            overall_score=None,
            rating="证据不足",
            score_confidence="insufficient",
            evidence_coverage=0,
            verdict="确定性规则仅评估可观察的创作信号，不代表平台表现或因果效果。",
            replicability="medium" if text_reliable and media_reliable else "unknown",
            dimensions=dimensions,
        ),
        score_basis="provisional_rule_score",
    )


def _fallback_structure_breakdown(
    analysis: SingleVideoAnalysis,
    media: MediaAnalysis | None,
    *,
    audio_expression: str,
    pacing: str,
) -> list[CreativeStructureBeat]:
    semantics = analysis.blind_analysis.semantics
    shots = media.shots if media is not None else []
    annotations = (
        {item.shot_id: item for item in media.vision.shot_annotations}
        if media is not None and media.vision is not None
        else {}
    )
    purpose_by_role = {
        "hook": "在最短时间建立注意力与观看理由",
        "problem": "明确受众痛点与内容要解决的问题",
        "value_promise": "说明继续观看可以获得的具体价值",
        "development": "展开信息、方法或故事主体",
        "proof": "提供案例、数据或演示以支撑观点",
        "peak": "集中释放最强信息或情绪峰值",
        "conclusion": "收束信息并强化记忆点",
        "cta": "引导观众采取下一步行动",
        "loop": "回扣开场并制造完整观看闭环",
        "unknown": "该段创作功能缺少可靠判断",
    }
    structure_segments = semantics.structure_segments[:30]

    def overlaps(start_ms: int | None, end_ms: int | None, shot_start: int, shot_end: int) -> bool:
        if start_ms is None or end_ms is None:
            return False
        return shot_start < end_ms and shot_end > start_ms

    result: list[CreativeStructureBeat] = []
    for index, item in enumerate(structure_segments):
        related_shots = [
            shot
            for shot in shots
            if overlaps(item.start_ms, item.end_ms, shot.start_ms, shot.end_ms)
        ]
        related_annotations = [
            annotations[shot.shot_id] for shot in related_shots if shot.shot_id in annotations
        ]
        visual_parts = _deduplicate(
            [
                part
                for annotation in related_annotations
                for part in [
                    annotation.summary or "",
                    *annotation.labels,
                    *annotation.shot_scale,
                    *annotation.camera_movement,
                    *annotation.text_overlay_styles,
                ]
            ]
        )
        if visual_parts:
            visual = "、".join(visual_parts)[:600]
        elif related_shots:
            visual = f"该段覆盖 {len(related_shots)} 个镜头，但缺少可靠视觉语义标注。"
        else:
            visual = "未见可与该段时间对齐的镜头证据。"
        related_emotions = [
            point.emotion.value
            for point in semantics.emotion_timeline
            if (
                item.start_ms is not None
                and item.end_ms is not None
                and point.start_ms is not None
                and point.end_ms is not None
                and point.start_ms < item.end_ms
                and point.end_ms > item.start_ms
            )
        ]
        next_role = (
            structure_segments[index + 1].function.value
            if index + 1 < len(structure_segments)
            else None
        )
        result.append(
            CreativeStructureBeat(
                sequence=index + 1,
                role=item.function.value,
                start_ms=item.start_ms,
                end_ms=item.end_ms,
                content_summary=item.text_summary,
                creative_purpose=purpose_by_role.get(item.function.value, "承接整体内容并推进信息"),
                expression=f"{semantics.narrative_type}；围绕“{item.text_summary}”推进"[:600],
                visual=visual,
                audio=audio_expression,
                pacing=(
                    f"{pacing}；该段覆盖 {len(related_shots)} 个镜头"
                    if related_shots
                    else f"{pacing}；缺少分段镜头对齐"
                ),
                emotion="、".join(_deduplicate(related_emotions)) or "未见可靠情绪标注",
                transition=f"转入下一段“{next_role}”" if next_role else "视频在此收束",
                evidence_segment_ids=_deduplicate(item.evidence_segment_ids)[:20],
                evidence_shot_ids=_deduplicate([shot.shot_id for shot in related_shots])[:30],
            )
        )
    return result


def _fallback_deep_output(
    analysis: SingleVideoAnalysis,
    media: MediaAnalysis | None,
    craft: SingleVideoCraftSummary,
    video: Video | None = None,
) -> SingleVideoDeepOutput:
    """Deterministic degradation that still organizes every observable signal."""
    semantics = analysis.blind_analysis.semantics
    facts = analysis.blind_analysis.facts
    hook_type = semantics.hook.primary_type.value
    hook_label = _HOOK_ANGLE_LABELS.get(hook_type, hook_type)
    narrative_label = _NARRATIVE_LABELS.get(semantics.narrative_type, semantics.narrative_type)
    structure = (
        "、".join(
            f"{item.function.value}({item.text_summary[:24]})"
            for item in semantics.structure_segments
        )
        or "未见结构标注"
    )
    fact_text = "；".join(item.text[:40] for item in facts.facts[:5]) or "未见可核验事实"
    subtitle = "、".join(sorted(craft.text_overlay_style)) or "未见字幕/艺术字标注"
    motion = "、".join(sorted(craft.motion_graphic)) or "未见动效标注"
    branding = "、".join(sorted(craft.branding)) or "未见品牌露出"
    if media is None or media.audio.silence_ratio is None:
        audio_expression = "音频活跃度未知（无本地媒体分析）"
    elif media.audio.silence_ratio <= 0.2:
        audio_expression = "声音持续活跃、留白少（静音占比 ≤20%）"
    elif media.audio.silence_ratio < 0.5:
        audio_expression = "声音活跃度中等（静音占比中等）"
    else:
        audio_expression = "声音留白较多（静音占比 >50%）"
    pacing = "、".join(craft.pacing_tags) or "剪辑节奏未知"
    opening = "、".join(craft.opening_techniques) or "开场手法未知（无视觉标注）"
    structure_breakdown = _fallback_structure_breakdown(
        analysis,
        media,
        audio_expression=audio_expression,
        pacing=pacing,
    )
    all_segment_ids = _deduplicate(
        [
            *semantics.primary_pillar_evidence_segment_ids,
            *semantics.hook.evidence_segment_ids,
            *semantics.cta.evidence_segment_ids,
            *[segment_id for item in facts.facts for segment_id in item.evidence_segment_ids],
            *[
                segment_id
                for item in semantics.structure_segments
                for segment_id in item.evidence_segment_ids
            ],
        ]
    )
    all_shot_ids = _deduplicate(
        [shot_id for item in structure_breakdown for shot_id in item.evidence_shot_ids]
    )
    subject = f"“{video.title}”" if video is not None and video.title else "该视频"
    one_sentence = (
        f"{subject}围绕“{semantics.primary_pillar}”，以{hook_label}切入并采用"
        f"{narrative_label}传递核心信息。"
    )[:300]
    detailed_summary = (
        f"{subject}以“{semantics.hook.hook_text or facts.opening_text or '未见明确开场原文'}”"
        f"建立开场，随后按“{structure}”推进。主要可核验信息包括：{fact_text}。"
        f"内容目标标注为“{semantics.content_goal}”，结尾动作是“"
        f"{semantics.cta.text or semantics.cta.primary_type.value}”。"
    )[:4_000]
    reliable_text = analysis.status == "complete" and semantics.confidence >= 0.6
    strength_items = [
        CreativeFinding(
            finding=f"选题使用{hook_label}",
            why_it_matters="开场策略与主题方向已被结构化标注，可作为同类内容的选题参考。",
            evidence_segment_ids=_deduplicate(semantics.hook.evidence_segment_ids)[:20],
        ),
        CreativeFinding(
            finding=f"内容采用{narrative_label}",
            why_it_matters=(
                f"现有分析识别出 {len(semantics.structure_segments)} 个结构节点，便于复刻内容骨架。"
            ),
            evidence_segment_ids=_deduplicate(
                [
                    segment_id
                    for item in semantics.structure_segments
                    for segment_id in item.evidence_segment_ids
                ]
            )[:20],
        ),
    ]
    if craft.analyzed_shots:
        strength_items.append(
            CreativeFinding(
                finding=f"已形成 {craft.analyzed_shots} 个镜头的视觉画像",
                why_it_matters="景别、运镜、构图和包装标签能够直接支持拍摄执行参考。",
                evidence_shot_ids=all_shot_ids[:30],
            )
        )
    weakness_items: list[CreativeFinding] = []
    if not reliable_text:
        weakness_items.append(
            CreativeFinding(
                finding="文本语义证据置信度不足",
                why_it_matters="选题、钩子、结构和表达判断只能作为待复核线索，不能据此形成正式总分。",
                evidence_segment_ids=all_segment_ids[:20],
            )
        )
    if media is None or not craft.shot_scale:
        weakness_items.append(
            CreativeFinding(
                finding="镜头级画面语义覆盖不足",
                why_it_matters="无法完整判断镜头设计、画面衔接、字幕包装和视觉节奏。",
                evidence_shot_ids=all_shot_ids[:30],
            )
        )
    if not semantics.emotion_timeline:
        weakness_items.append(
            CreativeFinding(
                finding="未识别出可靠情绪时间线",
                why_it_matters="当前报告不能确认情绪峰值、张力变化及其与内容结构的配合。",
                evidence_segment_ids=all_segment_ids[:20],
            )
        )
    if not weakness_items:
        weakness_items.append(
            CreativeFinding(
                finding="缺少账号内表现对照与上线验证",
                why_it_matters="单条视频创作拆解不能证明任何设计与播放、互动或转化之间的因果关系。",
            )
        )
    improvement_items = [
        PriorityImprovement(
            priority=1,
            problem=weakness_items[0].finding,
            action=(
                "补齐可靠字幕、逐镜头语义和时间对齐后重新蒸馏；如素材已齐全，则人工复核开场"
                "承诺、关键转折和结尾动作。"
            ),
            expected_effect="提高创作拆解的可执行性与评分可信度，实际表现仍需上线验证。",
            evidence_segment_ids=weakness_items[0].evidence_segment_ids,
            evidence_shot_ids=weakness_items[0].evidence_shot_ids,
        ),
        PriorityImprovement(
            priority=2,
            problem="结构节点目前以内容标签为主，段落间承接仍需显式设计",
            action="为每个结构节点补写进入句、退出句、画面动作与字幕关键词，形成可直接拍摄的分段脚本。",
            expected_effect="降低复刻执行中的信息断层，使节奏与内容推进更一致。",
            evidence_segment_ids=all_segment_ids[:20],
            evidence_shot_ids=all_shot_ids[:30],
        ),
    ]
    return SingleVideoDeepOutput(
        executive_summary=VideoExecutiveSummary(
            one_sentence=one_sentence,
            detailed_summary=detailed_summary,
            core_message=(fact_text if facts.facts else semantics.primary_pillar)[:1_000],
            content_goal=semantics.content_goal,
            target_viewer=list(semantics.audience_tasks)[:10],
            viewer_takeaways=[item.text for item in facts.facts[:10]],
        ),
        structure_breakdown=structure_breakdown,
        topic=TopicDistillation(
            topic_statement=(
                f"围绕“{semantics.primary_pillar}”展开，"
                f"核心 Hook 为“{semantics.hook.hook_text or hook_type}”。"
            ),
            topic_angle=hook_label,
            target_audience=list(semantics.audience_tasks) or ["受众任务未知"],
            information_increment=f"盲分析提取 {len(facts.facts)} 条可核验信息，例如：{fact_text}",
            memory_point=semantics.hook.hook_text or facts.opening_text or "未见明显记忆点",
            topic_formula=f"{hook_label} + {narrative_label}",
            selection_notes=["确定性降级：未经过深度模型拆解，选材分析基于盲分析标签"],
        ),
        expression=ExpressionDistillation(
            opening_form=(
                f"文本开场“{(facts.opening_text or '未见')[:40]}”"
                + (f"；画面开场：{opening}" if craft.opening_techniques else "")
            ),
            subtitle_style=subtitle,
            packaging_features=[item for item in (motion, branding) if not item.startswith("未见")],
            audio_expression=audio_expression,
            editing_style=f"{pacing}（镜头时长中位数 "
            f"{(craft.average_shot_duration_ms / 1000):.1f} 秒）"
            if craft.average_shot_duration_ms is not None
            else "剪辑节奏未知",
            expression_notes=["确定性降级：包装与声音表现基于测量与视觉标签"],
        ),
        craft=CraftDistillation(
            shot_scale_profile=_top_tags(craft.shot_scale),
            camera_profile=_top_tags({**craft.camera_movement, **craft.camera_angle}),
            composition_profile=_top_tags(craft.composition),
            lighting_profile=_top_tags(craft.lighting),
            opening_technique=opening,
            pacing=pacing,
            craft_notes=["确定性降级：拍摄手法为视觉标注的确定性聚合"],
        ),
        copy_checklist=CopyChecklist(
            topic=[
                f"选题公式：{hook_label} + {narrative_label}",
                f"目标人群：{'、'.join(semantics.audience_tasks) or '待补充'}",
            ],
            structure=[
                f"结构骨架：{structure}",
                f"CTA：{semantics.cta.primary_type.value}"
                + (f"（{semantics.cta.text[:40]}）" if semantics.cta.text else ""),
            ],
            craft=[
                f"景别：{_top_tags(craft.shot_scale)}",
                f"运镜与机位：{_top_tags({**craft.camera_movement, **craft.camera_angle})}",
                f"构图：{_top_tags(craft.composition)}",
                f"光线：{_top_tags(craft.lighting)}",
                f"开场：{opening}",
                f"节奏：{pacing}",
            ],
            expression=[
                f"字幕/艺术字：{subtitle}",
                f"包装：{motion}；{branding}" if motion or branding else "包装：未见标注",
                f"声音：{audio_expression}",
            ],
            avoid=["未经账号内对照验证，单视频表现不能代表选题普适效果"],
        ),
        strengths=strength_items[:10],
        weaknesses=weakness_items[:10],
        priority_improvements=improvement_items,
        evaluation=_fallback_evaluation(analysis, media, craft),
        unknowns=[
            "确定性降级：未调用深度模型，选材/表现形式点评为标签级推断",
            *([] if media is not None else ["缺少本地媒体分析，拍摄手法与画面表现未覆盖"]),
            *(
                ["缺少视觉语义标注，景别/运镜/构图/光线为未知"]
                if media is not None and craft.analyzed_shots > 0 and not craft.shot_scale
                else []
            ),
        ],
        evidence_segment_ids=all_segment_ids,
        evidence_shot_ids=all_shot_ids,
    )


def _transcript_segments(project: ProjectLayout, video_id: str) -> list[TranscriptSegment]:
    return [
        item
        for item in read_models(project.normalized_dir / "transcripts.parquet", TranscriptSegment)
        if item.video_id == video_id
    ]


def _build_bundle(
    project: ProjectLayout,
    video: Video,
    analysis: SingleVideoAnalysis,
    craft: SingleVideoCraftSummary,
    media: MediaAnalysis | None,
) -> dict[str, Any]:
    semantics = analysis.blind_analysis.semantics
    ocr_observations = (
        media.vision.ocr_observations[:20] if media is not None and media.vision else []
    )
    return {
        "title": video.title,
        "description": video.description,
        "duration_seconds": video.duration_seconds,
        "language": video.language,
        "platform": video.platform.value,
        "transcript_segments": [
            {
                "segment_id": item.segment_id,
                "start_ms": item.start_ms,
                "end_ms": item.end_ms,
                "text": item.text,
            }
            for item in _transcript_segments(project, video.video_id)
        ],
        "shots": [
            {"shot_id": item.shot_id, "start_ms": item.start_ms, "end_ms": item.end_ms}
            for item in (media.shots if media is not None else [])
        ],
        "shot_annotations": [
            {
                "shot_id": item.shot_id,
                "summary": item.summary,
                "labels": item.labels,
                "shot_scale": item.shot_scale,
                "camera_movement": item.camera_movement,
                "camera_angle": item.camera_angle,
                "composition": item.composition,
                "lighting": item.lighting,
                "text_overlay_styles": item.text_overlay_styles,
                "motion_graphics": item.motion_graphics,
                "branding": item.branding,
                "confidence": item.confidence,
            }
            for item in (
                media.vision.shot_annotations
                if media is not None and media.vision is not None
                else []
            )
        ],
        "audio": media.audio.model_dump(mode="json") if media is not None else None,
        "opening_text": analysis.blind_analysis.facts.opening_text,
        "closing_text": analysis.blind_analysis.facts.closing_text,
        "facts": [
            {
                "category": item.category,
                "text": item.text,
                "evidence_segment_ids": item.evidence_segment_ids,
            }
            for item in analysis.blind_analysis.facts.facts[:20]
        ],
        "semantics": {
            "primary_pillar": semantics.primary_pillar,
            "primary_pillar_evidence_segment_ids": (semantics.primary_pillar_evidence_segment_ids),
            "secondary_topics": semantics.secondary_topics,
            "audience_tasks": semantics.audience_tasks,
            "content_goal": semantics.content_goal,
            "funnel_stage": semantics.funnel_stage,
            "hook": {
                "primary_type": semantics.hook.primary_type.value,
                "hook_text": semantics.hook.hook_text,
                "promise": semantics.hook.promise,
                "curiosity_gap": semantics.hook.curiosity_gap,
                "start_ms": semantics.hook.start_ms,
                "end_ms": semantics.hook.end_ms,
                "evidence_segment_ids": semantics.hook.evidence_segment_ids,
            },
            "structure": [
                {
                    "function": item.function.value,
                    "start_ms": item.start_ms,
                    "end_ms": item.end_ms,
                    "text_summary": item.text_summary,
                    "evidence_segment_ids": item.evidence_segment_ids,
                }
                for item in semantics.structure_segments
            ],
            "narrative_type": semantics.narrative_type,
            "information_density": semantics.information_density,
            "emotion_timeline": [
                {
                    "emotion": item.emotion.value,
                    "start_ms": item.start_ms,
                    "end_ms": item.end_ms,
                    "evidence_segment_ids": item.evidence_segment_ids,
                }
                for item in semantics.emotion_timeline
            ],
            "cta": {
                "primary_type": semantics.cta.primary_type.value,
                "text": semantics.cta.text,
                "alignment_score": semantics.cta.alignment_score,
                "evidence_segment_ids": semantics.cta.evidence_segment_ids,
            },
            "persona_signals": semantics.persona_signals,
            "language_signals": semantics.language_signals,
            "risk_flags": semantics.risk_flags,
            "confidence": semantics.confidence,
        },
        "craft_summary": craft.model_dump(mode="json"),
        "ocr_texts": [item.text for item in ocr_observations],
        "ocr_observations": [
            {
                "observation_id": item.observation_id,
                "text": item.text,
                "shot_id": item.shot_id,
                "start_ms": item.start_ms,
                "end_ms": item.end_ms,
            }
            for item in ocr_observations
        ],
    }


def _validate_deep_output(
    value: SingleVideoDeepOutput,
    valid_segments: set[str],
    valid_shots: set[str],
) -> None:
    """Drop fabricated citations at every report level; narrative remains usable."""

    def filter_citations(item: Any) -> None:
        item.evidence_segment_ids = [
            evidence_id
            for evidence_id in item.evidence_segment_ids
            if evidence_id in valid_segments
        ]
        item.evidence_shot_ids = [
            evidence_id for evidence_id in item.evidence_shot_ids if evidence_id in valid_shots
        ]

    filter_citations(value)
    for item in [
        *value.structure_breakdown,
        *value.strengths,
        *value.weaknesses,
        *value.priority_improvements,
        *value.evaluation.dimensions,
    ]:
        filter_citations(item)


def _generate_with_retry(
    *,
    prompt: str,
    response_model: type[BaseModel],
    provider: TextModelProvider | None,
    max_attempts: int,
    valid_segments: set[str],
    valid_shots: set[str],
    fallback: SingleVideoDeepOutput,
    strict_model: bool,
) -> tuple[SingleVideoDeepOutput, ModelTaskTrace]:
    provider_name = provider.provider_name if provider is not None else "none"
    model_name = provider.model_name if provider is not None else "none"
    prompt_hash = sha256_json({"prompt": prompt})
    _validate_deep_output(fallback, valid_segments, valid_shots)
    if provider is None:
        if strict_model:
            raise DistillerError(
                ErrorCode.MODEL_UNAVAILABLE,
                "No deep-distillation model provider configured",
            )
        return fallback, ModelTaskTrace(
            task="single_video_deep_distillation",
            prompt_version=DEEP_DISTILLATION_PROMPT_VERSION,
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
            value = SingleVideoDeepOutput.model_validate(response.model_dump(mode="json"))
            _validate_deep_output(value, valid_segments, valid_shots)
            value.evaluation = _normalize_evaluation(
                value.evaluation,
                score_basis="model_assessment",
            )
            return value, ModelTaskTrace(
                task="single_video_deep_distillation",
                prompt_version=DEEP_DISTILLATION_PROMPT_VERSION,
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
            f"Deep distillation output remained invalid after {max_attempts} attempts",
            details={"attempts": max_attempts, "errors": errors},
        )
    return fallback, ModelTaskTrace(
        task="single_video_deep_distillation",
        prompt_version=DEEP_DISTILLATION_PROMPT_VERSION,
        prompt_hash=prompt_hash,
        provider=provider_name,
        model=model_name,
        attempts=max_attempts,
        status="degraded",
        errors=errors,
    )


class SingleVideoDistillationService:
    """Build one content-addressed deep distillation reference card per video."""

    def __init__(self, project: ProjectLayout) -> None:
        self.project = project

    def distill(
        self,
        *,
        video_id: str,
        deep_provider: Literal["ollama", "llamacpp", "cloud", "none"] | None = None,
        deep_model: str | None = None,
        deep_base_url: str | None = None,
        deep_api_key: str | None = None,
        model_output: Path | None = None,
        max_attempts: int | None = None,
        strict_model: bool = False,
        dry_run: bool = False,
    ) -> dict[str, Any]:
        video = resolve_video(self.project, video_id)
        video_id = video.video_id
        text = _latest_text_analysis(self.project, video_id)
        media_pair = _latest_media_analysis(self.project, video_id)
        media = media_pair[0] if media_pair else None
        media_feature = media_pair[1] if media_pair else None
        if text is None:
            raise DistillerError(
                ErrorCode.INPUT_MISSING,
                f"No single-video text analysis found: {video_id}",
                details={"next": "run distiller analyze video before deep distillation"},
            )
        analysis, analysis_path = text
        craft = build_craft_summary(media)
        if model_output is not None and deep_provider not in (None, "none"):
            raise DistillerError(
                ErrorCode.SCHEMA_INVALID,
                "Pass either a deep provider or --deep-output, not both",
            )
        config = load_config(self.project.config_path)
        provider: TextModelProvider | None = None
        if model_output is not None:
            provider = StructuredFileProvider(model_output)
        elif deep_provider == "ollama":
            provider = OllamaTextProvider(
                model=deep_model or config.models.vision_model or "qwen3:8b",
                base_url=deep_base_url or config.models.ollama_base_url,
                timeout_seconds=config.models.vision_timeout_seconds,
            )
        elif deep_provider == "llamacpp":
            provider = LlamaCppTextProvider(
                model=deep_model or config.models.llamacpp_text_model or "local",
                base_url=deep_base_url or config.models.llamacpp_text_base_url,
                timeout_seconds=config.models.vision_timeout_seconds,
                api_key=deep_api_key or config.models.llamacpp_api_key,
            )
        elif deep_provider == "cloud":
            provider = CloudChatTextProvider(
                model=deep_model or config.models.cloud_text_model or "local",
                base_url=deep_base_url
                or config.models.cloud_base_url
                or "https://api.deepseek.com",
                timeout_seconds=config.models.vision_timeout_seconds,
                api_key=deep_api_key or config.models.cloud_api_key,
            )
        fallback = _fallback_deep_output(analysis, media, craft, video)
        from video_account_distiller.models import TranscriptSegment

        transcript_records = [
            item
            for item in read_models(
                self.project.normalized_dir / "transcripts.parquet", TranscriptSegment
            )
            if item.video_id == video_id
        ]
        transcript_ids = {item.segment_id for item in transcript_records}
        valid_shots = {item.shot_id for item in media.shots} if media is not None else set()
        prompt = render_prompt(
            "single-video-deep-distillation.md",
            bundle_json=_build_bundle(self.project, video, analysis, craft, media),
            schema_json=SingleVideoDeepOutput.model_json_schema(),
        )
        attempts = max_attempts or config.models.max_schema_attempts
        effective_strict = strict_model or not config.models.allow_degraded_analysis
        provider_name = provider.provider_name if provider is not None else "none"
        provider_model = provider.model_name if provider is not None else "none"
        provider_base_url = str(getattr(provider, "base_url", "") or "") or None
        prompt_hash = sha256_json({"prompt": prompt})

        seed = {
            "video_id": video_id,
            "version": SINGLE_VIDEO_DISTILLATION_VERSION,
            "prompt_version": DEEP_DISTILLATION_PROMPT_VERSION,
            "prompt_hash": prompt_hash,
            "text_analysis_id": analysis.analysis_id,
            "media_analysis_id": media.analysis_id if media else None,
            "craft_summary": craft.model_dump(mode="json"),
            "fallback": fallback.model_dump(mode="json"),
            "provider": provider_name,
            "model": provider_model,
            "base_url": provider_base_url,
            "requested_provider": deep_provider,
            "requested_model": deep_model,
            "provider_input_hash": (
                provider.input_hash if isinstance(provider, StructuredFileProvider) else None
            ),
        }
        distillation_id = stable_id("svd_", sha256_json(seed))
        output_dir = self.project.root / "analyses" / "videos" / video_id / distillation_id
        paths = [
            output_dir / "distillation.json",
            output_dir / "report.md",
            output_dir / "evidence-index.json",
            output_dir / "warnings.json",
        ]
        relative = [self.project.relative(path) for path in paths]
        if all(path.is_file() for path in paths) and not dry_run:
            try:
                cached = SingleVideoDistillation.model_validate(read_json(paths[0]))
                cached_evidence = ArtifactEvidenceIndex.model_validate(read_json(paths[2]))
                cached_warnings = read_json(paths[3])
                cached_report = paths[1].read_text(encoding="utf-8")
                if (
                    cached.distillation_id != distillation_id
                    or cached.video_id != video_id
                    or cached.analysis_version != SINGLE_VIDEO_DISTILLATION_VERSION
                    or cached_evidence.artifact_id != distillation_id
                    or cached_evidence.run_id != cached.run_id
                    or not isinstance(cached_warnings, list)
                    or not all(isinstance(item, str) for item in cached_warnings)
                    or cached_warnings != cached.warnings
                    or not cached_report.strip()
                ):
                    raise ValueError("incomplete or inconsistent single-video cache")
            except (OSError, TypeError, ValueError):
                pass
            else:
                if not effective_strict or cached.status == "complete":
                    return {
                        "ok": True,
                        "dry_run": False,
                        "already_generated": True,
                        "distillation": cached.model_dump(mode="json"),
                        "outputs": relative,
                    }
        input_hashes = sorted(
            {
                video.raw_hash,
                *(item.raw_hash for item in transcript_records),
                *([media_feature.raw_hash] if media_feature is not None else []),
                *(
                    [provider.input_hash]
                    if isinstance(provider, StructuredFileProvider) and provider.input_hash
                    else []
                ),
            }
        )
        manifest = (
            None
            if dry_run
            else self.project.begin_run("distill single video", input_hashes=input_hashes)
        )
        run_id = manifest.run_id if manifest else stable_id("run_dry_", distillation_id)
        generated_at = datetime.now(UTC)

        deep, deep_trace = _generate_with_retry(
            prompt=prompt,
            response_model=SingleVideoDeepOutput,
            provider=provider,
            max_attempts=attempts,
            valid_segments=transcript_ids,
            valid_shots=valid_shots,
            fallback=fallback,
            strict_model=effective_strict,
        )
        status: Literal["complete", "degraded"] = (
            "complete" if deep_trace.status == "success" else "degraded"
        )

        collector_items: list[EvidenceItem] = []
        collector_items.append(
            EvidenceItem(
                evidence_id=stable_id("evi_", distillation_id, "video", video.record_id),
                label="video.metadata",
                classification="fact",
                value={
                    "platform": video.platform.value,
                    "title": video.title,
                    "description": video.description,
                    "duration_seconds": video.duration_seconds,
                },
                calculation="normalized video metadata",
                sources=[_source("videos", video)],
            )
        )
        if analysis_path.is_file():
            collector_items.append(
                EvidenceItem(
                    evidence_id=stable_id("evi_", distillation_id, "text", analysis.analysis_id),
                    label="source.text_analysis",
                    classification="fact",
                    value={"analysis_id": analysis.analysis_id},
                    calculation="latest blind single-video text analysis",
                    sources=[],
                )
            )
        if media is not None and media_feature is not None:
            collector_items.append(
                EvidenceItem(
                    evidence_id=stable_id("evi_", distillation_id, "media", media.analysis_id),
                    label="source.media_analysis",
                    classification="fact",
                    value={
                        "analysis_id": media.analysis_id,
                        "analyzed_shots": craft.analyzed_shots,
                        "ocr_observations": craft.ocr_observation_count,
                    },
                    calculation="latest local media analysis",
                    sources=[_source("media_features", media_feature)],
                )
            )
        collector_items.append(
            EvidenceItem(
                evidence_id=stable_id("evi_", distillation_id, "craft"),
                label="video.craft_summary",
                classification="semantic_annotation",
                value=craft.model_dump(mode="json"),
                calculation=(
                    "deterministic per-shot aggregation of vision labels, opening "
                    "technique, and measured editing rhythm"
                ),
                sources=[_source("media_features", media_feature)] if media_feature else [],
            )
        )
        collector_items.append(
            EvidenceItem(
                evidence_id=stable_id("evi_", distillation_id, "deep"),
                label="video.deep_distillation",
                classification=(
                    "semantic_annotation" if deep_trace.status == "success" else "warning"
                ),
                value=deep.model_dump(mode="json"),
                calculation=(
                    "strictly validated deep model output with citation filtering"
                    if deep_trace.status == "success"
                    else "deterministic fallback aggregation"
                ),
                sources=[],
            )
        )
        evidence = ArtifactEvidenceIndex(
            artifact_id=distillation_id,
            account_ids=[video.account_id],
            run_id=run_id,
            generated_at=generated_at,
            input_hashes=input_hashes,
            items=collector_items,
        )
        warnings = list(
            dict.fromkeys(
                [
                    *(
                        ["deep_model_unavailable_deterministic_fallback"]
                        if deep_trace.status == "degraded" and provider is None
                        else []
                    ),
                    *(
                        ["deep_model_output_degraded_after_retries"]
                        if deep_trace.status == "degraded" and provider is not None
                        else []
                    ),
                    *(
                        ["media_analysis_missing_craft_and_expression_limited"]
                        if media is None
                        else []
                    ),
                    *deep_trace.errors,
                    *(
                        ["no_visual_annotations_shot_craft_unknown"]
                        if media is not None and not craft.shot_scale
                        else []
                    ),
                ]
            )
        )
        unknowns = list(
            dict.fromkeys(
                [
                    *deep.unknowns,
                    *(["缺少本地媒体分析，拍摄手法与画面表现未覆盖"] if media is None else []),
                    *(
                        ["缺少视觉语义标注，景别/运镜/构图/光线为未知"]
                        if media is not None and craft.analyzed_shots > 0 and not craft.shot_scale
                        else []
                    ),
                ]
            )
        )
        distillation = SingleVideoDistillation(
            distillation_id=distillation_id,
            analysis_version=SINGLE_VIDEO_DISTILLATION_VERSION,
            video_id=video_id,
            account_id=video.account_id,
            generated_at=generated_at,
            run_id=run_id,
            status=status,
            text_analysis_id=analysis.analysis_id,
            media_analysis_id=media.analysis_id if media is not None else None,
            craft_summary=craft,
            executive_summary=deep.executive_summary,
            structure_breakdown=deep.structure_breakdown,
            topic=deep.topic,
            expression=deep.expression,
            craft=deep.craft,
            copy_checklist=deep.copy_checklist,
            strengths=deep.strengths,
            weaknesses=deep.weaknesses,
            priority_improvements=deep.priority_improvements,
            evaluation=deep.evaluation,
            deep_trace=deep_trace,
            unknowns=unknowns,
            evidence_segment_ids=deep.evidence_segment_ids,
            evidence_shot_ids=deep.evidence_shot_ids,
            evidence_index_path=relative[2],
            warnings_path=relative[3],
            warnings=warnings,
        )
        result = {
            "ok": True,
            "dry_run": dry_run,
            "already_generated": False,
            "distillation": distillation.model_dump(mode="json"),
            "outputs": relative,
        }
        if dry_run:
            return result
        assert manifest is not None
        output_dir.mkdir(parents=True, exist_ok=True)
        atomic_write_json(paths[0], distillation.model_dump(mode="json"))
        template_path = (
            Path(__file__).resolve().parents[1]
            / "reports"
            / "templates"
            / "single-video-distillation.md.j2"
        )
        template = Environment(undefined=StrictUndefined, autoescape=False).from_string(
            template_path.read_text(encoding="utf-8")
        )
        atomic_write_text(
            paths[1],
            template.render(distillation=distillation.model_dump(mode="python")).strip() + "\n",
        )
        atomic_write_json(paths[2], evidence.model_dump(mode="json"))
        atomic_write_json(paths[3], warnings)
        self.project.finish_run(
            manifest,
            success=True,
            processed_counts={
                "analyzed_shots": craft.analyzed_shots,
                "ocr_observations": craft.ocr_observation_count,
            },
            output_files=relative,
            warnings=warnings,
        )
        return result
