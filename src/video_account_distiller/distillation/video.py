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
from video_account_distiller.storage.parquet import read_models
from video_account_distiller.storage.project import ProjectLayout
from video_account_distiller.utils.hashing import sha256_json
from video_account_distiller.utils.ids import stable_id
from video_account_distiller.utils.io import atomic_write_json, atomic_write_text, read_json
from video_account_distiller.utils.lookup import resolve_video

SINGLE_VIDEO_DISTILLATION_VERSION = "1.0.0"

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


def _fallback_deep_output(
    analysis: SingleVideoAnalysis,
    media: MediaAnalysis | None,
    craft: SingleVideoCraftSummary,
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
    return SingleVideoDeepOutput(
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
        unknowns=[
            "确定性降级：未调用深度模型，选材/表现形式点评为标签级推断",
            *([] if media is not None else ["缺少本地媒体分析，拍摄手法与画面表现未覆盖"]),
            *(
                ["缺少视觉语义标注，景别/运镜/构图/光线为未知"]
                if media is not None and craft.analyzed_shots > 0 and not craft.shot_scale
                else []
            ),
        ],
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
    ocr_texts = [
        item.text for item in (media.vision.ocr_observations if media and media.vision else [])[:20]
    ]
    return {
        "title": video.title,
        "description": video.description,
        "duration_seconds": video.duration_seconds,
        "language": video.language,
        "platform": video.platform.value,
        "transcript_segments": [
            {"segment_id": item.segment_id, "text": item.text}
            for item in _transcript_segments(project, video.video_id)
        ],
        "shots": [
            {"shot_id": item.shot_id, "start_ms": item.start_ms, "end_ms": item.end_ms}
            for item in (media.shots if media is not None else [])
        ],
        "facts": [
            {"category": item.category, "text": item.text}
            for item in analysis.blind_analysis.facts.facts[:20]
        ],
        "semantics": {
            "primary_pillar": semantics.primary_pillar,
            "secondary_topics": semantics.secondary_topics,
            "audience_tasks": semantics.audience_tasks,
            "content_goal": semantics.content_goal,
            "funnel_stage": semantics.funnel_stage,
            "hook": {
                "primary_type": semantics.hook.primary_type.value,
                "hook_text": semantics.hook.hook_text,
                "promise": semantics.hook.promise,
            },
            "structure": [
                {
                    "function": item.function.value,
                    "text_summary": item.text_summary,
                }
                for item in semantics.structure_segments
            ],
            "narrative_type": semantics.narrative_type,
            "information_density": semantics.information_density,
            "emotion_timeline": [
                {"emotion": item.emotion.value} for item in semantics.emotion_timeline
            ],
            "cta": {"primary_type": semantics.cta.primary_type.value, "text": semantics.cta.text},
            "persona_signals": semantics.persona_signals,
            "language_signals": semantics.language_signals,
        },
        "craft_summary": craft.model_dump(mode="json"),
        "ocr_texts": ocr_texts,
    }


def _validate_deep_output(
    value: SingleVideoDeepOutput,
    valid_segments: set[str],
    valid_shots: set[str],
) -> None:
    """Drop fabricated citations; the labels themselves remain usable."""
    value.evidence_segment_ids = [
        item for item in value.evidence_segment_ids if item in valid_segments
    ]
    value.evidence_shot_ids = [item for item in value.evidence_shot_ids if item in valid_shots]


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
        fallback = _fallback_deep_output(analysis, media, craft)
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

        seed = {
            "video_id": video_id,
            "version": SINGLE_VIDEO_DISTILLATION_VERSION,
            "text_analysis_id": analysis.analysis_id,
            "media_analysis_id": media.analysis_id if media else None,
            "craft_summary": craft.model_dump(mode="json"),
            "fallback": fallback.model_dump(mode="json"),
            "deep_provider": deep_provider,
            "deep_model": deep_model,
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
        if paths[0].is_file() and not dry_run:
            return {
                "ok": True,
                "dry_run": False,
                "already_generated": True,
                "distillation": read_json(paths[0]),
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

        prompt = render_prompt(
            "single-video-deep-distillation.md",
            bundle_json=_build_bundle(self.project, video, analysis, craft, media),
            schema_json=SingleVideoDeepOutput.model_json_schema(),
        )
        attempts = max_attempts or config.models.max_schema_attempts
        effective_strict = strict_model or not config.models.allow_degraded_analysis
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
            topic=deep.topic,
            expression=deep.expression,
            craft=deep.craft,
            copy_checklist=deep.copy_checklist,
            deep_trace=deep_trace,
            unknowns=unknowns,
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
