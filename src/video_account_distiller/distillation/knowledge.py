"""Knowledge-first single-video distillation with source-level traceability."""

from __future__ import annotations

import math
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal, cast

from jinja2 import Environment, StrictUndefined
from pydantic import BaseModel

from video_account_distiller.config import load_config
from video_account_distiller.distillation.video import (
    _build_bundle,
    _latest_media_analysis,
    _latest_text_analysis,
    _source,
    build_craft_summary,
)
from video_account_distiller.errors import DistillerError, ErrorCode
from video_account_distiller.features.prompts import (
    KNOWLEDGE_EXTRACTION_PROMPT_VERSION,
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
from video_account_distiller.models import (
    ArtifactEvidenceIndex,
    ContentExpressionNote,
    EvidenceItem,
    KnowledgeSourceRef,
    ModelTaskTrace,
    SingleVideoAnalysis,
    SingleVideoKnowledgeDistillation,
    SingleVideoKnowledgeOutput,
    TranscriptSegment,
    VideoKnowledgeItem,
)
from video_account_distiller.models.video_distillation import KnowledgeItemType
from video_account_distiller.storage.parquet import read_models
from video_account_distiller.storage.project import ProjectLayout
from video_account_distiller.utils.hashing import sha256_json
from video_account_distiller.utils.ids import stable_id
from video_account_distiller.utils.io import atomic_write_json, atomic_write_text, read_json
from video_account_distiller.utils.lookup import resolve_video

SINGLE_VIDEO_KNOWLEDGE_VERSION = "1.1.0"


def _fact_type(category: str) -> KnowledgeItemType:
    return cast(
        KnowledgeItemType,
        {
            "number": "data",
            "instruction": "method",
            "claim": "knowledge_point",
            "entity": "fact",
            "offer": "recommendation",
        }.get(category, "fact"),
    )


def _fallback_knowledge(
    analysis: SingleVideoAnalysis,
    segments: list[TranscriptSegment],
    video_title: str | None = None,
) -> SingleVideoKnowledgeOutput:
    """Preserve the complete transcript when model-backed synthesis is unavailable."""
    segment_map = {item.segment_id: item for item in segments}
    items: list[VideoKnowledgeItem] = []
    covered_segment_ids: set[str] = set()
    for fact in analysis.blind_analysis.facts.facts[:30]:
        refs = []
        for segment_id in fact.evidence_segment_ids:
            segment = segment_map.get(segment_id)
            if segment is None:
                continue
            covered_segment_ids.add(segment.segment_id)
            refs.append(
                KnowledgeSourceRef(
                    source_type="transcript",
                    segment_id=segment.segment_id,
                    start_ms=segment.start_ms,
                    end_ms=segment.end_ms,
                    excerpt=segment.text[:500],
                )
            )
        contextual_content = fact.text
        if len(contextual_content.strip()) < 12 and refs:
            contextual_content = refs[0].excerpt or contextual_content
        items.append(
            VideoKnowledgeItem(
                knowledge_type=_fact_type(fact.category),
                attribution="video_statement",
                title=(fact.text if len(fact.text.strip()) >= 4 else contextual_content)[:80],
                content=contextual_content,
                source_refs=refs,
                limitations=["仅记录视频中的说法，未做外部事实核验"],
            )
        )

    remaining = [item for item in segments if item.segment_id not in covered_segment_ids]
    available_slots = max(0, 30 - len(items))
    if remaining and available_slots:
        group_size = max(1, math.ceil(len(remaining) / available_slots))
        for offset in range(0, len(remaining), group_size):
            group = remaining[offset : offset + group_size]
            content = "\n".join(item.text.strip() for item in group if item.text.strip()).strip()
            if not content:
                continue
            first_sentence = re.split(r"[。！？!?；;\n]", content, maxsplit=1)[0].strip()
            title = first_sentence[:80] or f"视频内容 {len(items) + 1}"
            lowered = content.casefold()
            knowledge_type: KnowledgeItemType = "knowledge_point"
            if any(token in lowered for token in ("步骤", "首先", "然后", "怎么", "方法", "操作")):
                knowledge_type = "method"
            elif any(token in lowered for token in ("例如", "案例", "比如")):
                knowledge_type = "case"
            elif re.search(r"\d", content):
                knowledge_type = "data"
            items.append(
                VideoKnowledgeItem(
                    knowledge_type=knowledge_type,
                    attribution="video_statement",
                    title=title,
                    content=content[:2000],
                    source_refs=[
                        KnowledgeSourceRef(
                            source_type="transcript",
                            segment_id=item.segment_id,
                            start_ms=item.start_ms,
                            end_ms=item.end_ms,
                            excerpt=item.text[:500],
                        )
                        for item in group[:8]
                    ],
                    limitations=["确定性降级保留原视频转写，未进行模型归纳"],
                )
            )
            if len(items) >= 30:
                break

    if not items and segments:
        first = segments[0]
        items.append(
            VideoKnowledgeItem(
                knowledge_type="knowledge_point",
                attribution="video_statement",
                title="视频开场信息",
                content=first.text,
                source_refs=[
                    KnowledgeSourceRef(
                        source_type="transcript",
                        segment_id=first.segment_id,
                        start_ms=first.start_ms,
                        end_ms=first.end_ms,
                        excerpt=first.text[:500],
                    )
                ],
                limitations=["确定性降级仅保留转写内容，未进行模型归纳"],
            )
        )
    semantics = analysis.blind_analysis.semantics
    semantics_reliable = analysis.status == "complete"
    summary_parts = [item.content for item in items[:8]]
    return SingleVideoKnowledgeOutput(
        knowledge_title=(
            video_title
            or next((item.text for item in segments if len(item.text.strip()) >= 12), None)
            or analysis.blind_analysis.facts.opening_text
            or "单视频知识提取"
        )[:200],
        content_summary=(
            "；".join(summary_parts) or "当前转写与事实抽取不足，无法形成可靠内容摘要。"
        )[:3000],
        core_conclusions=[item.content for item in items[:8]],
        knowledge_items=items,
        important_concepts=(list(semantics.secondary_topics)[:15] if semantics_reliable else []),
        methods=[item.content for item in items if item.knowledge_type == "method"][:15],
        cases=[item.content for item in items if item.knowledge_type == "case"][:15],
        key_data=[item.content for item in items if item.knowledge_type == "data"][:15],
        entities=[item.content for item in items if item.knowledge_type == "fact"][:20],
        applicability=(list(semantics.audience_tasks)[:10] if semantics_reliable else []),
        limitations=[
            "本产物不执行外部事实核验",
            "当前为确定性降级整理，未使用知识提取模型",
        ],
        expression_note=ContentExpressionNote(
            summary="表达方式仅作辅助备注；知识内容来自已有转写与事实抽取。",
            useful_devices=[semantics.narrative_type, semantics.hook.primary_type.value],
            limitations=["未据此推断传播效果"],
        ),
        unknowns=list(analysis.blind_analysis.facts.unknowns)[:12],
    )


def _validate_knowledge_quality(
    value: SingleVideoKnowledgeOutput,
    *,
    transcript_character_count: int,
) -> None:
    """Reject structurally valid but obviously empty model summaries."""

    if transcript_character_count < 120:
        return
    total_content = len(value.content_summary.strip()) + sum(
        len(item.content.strip()) for item in value.knowledge_items
    )
    minimum_items = 3 if transcript_character_count >= 600 else 2
    if len(value.knowledge_items) < minimum_items:
        raise ValueError(
            f"knowledge output is too thin: expected at least {minimum_items} knowledge items"
        )
    if len(value.content_summary.strip()) < 60 or total_content < min(
        500, max(180, transcript_character_count // 12)
    ):
        raise ValueError("knowledge output does not cover enough of the source transcript")
    if not any(item.source_refs for item in value.knowledge_items):
        raise ValueError("knowledge output contains no source transcript references")


def _validate_source_refs(
    value: SingleVideoKnowledgeOutput,
    *,
    valid_segments: set[str],
    valid_shots: set[str],
    valid_observations: set[str],
) -> None:
    """Remove model-invented evidence IDs while preserving clearly labelled inference."""
    for item in value.knowledge_items:
        item.source_refs = [
            ref
            for ref in item.source_refs
            if (
                ref.source_type == "transcript"
                and ref.segment_id is not None
                and ref.segment_id in valid_segments
            )
            or (
                ref.source_type == "visual"
                and ref.shot_id is not None
                and ref.shot_id in valid_shots
            )
            or (
                ref.source_type == "ocr"
                and ref.observation_id is not None
                and ref.observation_id in valid_observations
            )
        ]
        if item.attribution != "model_inference" and not item.source_refs:
            item.limitations = list(
                dict.fromkeys([*item.limitations, "模型未提供有效的原视频证据引用"])
            )


def _generate(
    *,
    prompt: str,
    provider: TextModelProvider | None,
    max_attempts: int,
    fallback: SingleVideoKnowledgeOutput,
    valid_segments: set[str],
    valid_shots: set[str],
    valid_observations: set[str],
    strict_model: bool,
    transcript_character_count: int = 0,
) -> tuple[SingleVideoKnowledgeOutput, ModelTaskTrace]:
    provider_name = provider.provider_name if provider else "none"
    model_name = provider.model_name if provider else "none"
    prompt_hash = sha256_json({"prompt": prompt})
    if provider is None:
        if strict_model:
            raise DistillerError(ErrorCode.MODEL_UNAVAILABLE, "No knowledge model configured")
        return fallback, ModelTaskTrace(
            task="single_video_knowledge_extraction",
            prompt_version=KNOWLEDGE_EXTRACTION_PROMPT_VERSION,
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
            response: BaseModel = provider.generate_structured(
                prompt,
                SingleVideoKnowledgeOutput,
                temperature=0.0,
            )
            value = SingleVideoKnowledgeOutput.model_validate(response.model_dump(mode="json"))
            _validate_source_refs(
                value,
                valid_segments=valid_segments,
                valid_shots=valid_shots,
                valid_observations=valid_observations,
            )
            _validate_knowledge_quality(
                value,
                transcript_character_count=transcript_character_count,
            )
            return value, ModelTaskTrace(
                task="single_video_knowledge_extraction",
                prompt_version=KNOWLEDGE_EXTRACTION_PROMPT_VERSION,
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
            f"Knowledge extraction remained invalid after {max_attempts} attempts",
            details={"attempts": max_attempts, "errors": errors},
        )
    return fallback, ModelTaskTrace(
        task="single_video_knowledge_extraction",
        prompt_version=KNOWLEDGE_EXTRACTION_PROMPT_VERSION,
        prompt_hash=prompt_hash,
        provider=provider_name,
        model=model_name,
        attempts=max_attempts,
        status="degraded",
        errors=errors,
    )


class SingleVideoKnowledgeService:
    """Create a mode-isolated knowledge artifact for one video."""

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
        text = _latest_text_analysis(self.project, video.video_id)
        media_pair = _latest_media_analysis(self.project, video.video_id)
        media = media_pair[0] if media_pair else None
        media_feature = media_pair[1] if media_pair else None
        if text is None:
            raise DistillerError(
                ErrorCode.INPUT_MISSING,
                f"No single-video text analysis found: {video.video_id}",
                details={"next": "run distiller analyze video before knowledge distillation"},
            )
        analysis, _analysis_path = text
        if model_output is not None and deep_provider not in (None, "none"):
            raise DistillerError(
                ErrorCode.SCHEMA_INVALID,
                "Pass either a knowledge provider or --deep-output, not both",
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
            local_text_model = deep_model or config.models.llamacpp_text_model
            local_text_base_url = deep_base_url or (
                config.models.llamacpp_text_base_url
                if config.models.llamacpp_text_model
                else config.models.llamacpp_base_url
            )
            provider = LlamaCppTextProvider(
                model=(
                    local_text_model
                    or config.models.llamacpp_model
                    or config.models.vision_model
                    or "local"
                ),
                base_url=local_text_base_url,
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

        segments = [
            item
            for item in read_models(
                self.project.normalized_dir / "transcripts.parquet",
                TranscriptSegment,
            )
            if item.video_id == video.video_id
        ]
        fallback = _fallback_knowledge(analysis, segments, video.title)
        craft = build_craft_summary(media)
        seed = {
            "video_id": video.video_id,
            "mode": "knowledge",
            "version": SINGLE_VIDEO_KNOWLEDGE_VERSION,
            "text_analysis_id": analysis.analysis_id,
            "media_analysis_id": media.analysis_id if media else None,
            "fallback": fallback.model_dump(mode="json"),
            "provider": deep_provider,
            "model": deep_model,
            "provider_input_hash": (
                provider.input_hash if isinstance(provider, StructuredFileProvider) else None
            ),
        }
        knowledge_id = stable_id("svk_", sha256_json(seed))
        output_dir = (
            self.project.root / "analyses" / "videos" / video.video_id / "knowledge" / knowledge_id
        )
        paths = [
            output_dir / "knowledge.json",
            output_dir / "knowledge.md",
            output_dir / "evidence.json",
            output_dir / "warnings.json",
        ]
        relative = [self.project.relative(path) for path in paths]
        if paths[0].is_file() and not dry_run:
            cached = SingleVideoKnowledgeDistillation.model_validate(read_json(paths[0]))
            if not strict_model or cached.status == "complete":
                return {
                    "ok": True,
                    "dry_run": False,
                    "already_generated": True,
                    "knowledge": cached.model_dump(mode="json"),
                    "outputs": relative,
                }

        input_hashes = sorted(
            {
                video.raw_hash,
                *(item.raw_hash for item in segments),
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
            else self.project.begin_run(
                "distill single video knowledge",
                input_hashes=input_hashes,
            )
        )
        run_id = manifest.run_id if manifest else stable_id("run_dry_", knowledge_id)
        generated_at = datetime.now(UTC)
        prompt = render_prompt(
            "single-video-knowledge-extraction.md",
            bundle_json=_build_bundle(self.project, video, analysis, craft, media),
            schema_json=SingleVideoKnowledgeOutput.model_json_schema(),
        )
        valid_shots = {item.shot_id for item in media.shots} if media else set()
        valid_observations = (
            {item.observation_id for item in media.vision.ocr_observations}
            if media is not None and media.vision
            else set()
        )
        knowledge, trace = _generate(
            prompt=prompt,
            provider=provider,
            max_attempts=max_attempts or config.models.max_schema_attempts,
            fallback=fallback,
            valid_segments={item.segment_id for item in segments},
            valid_shots=valid_shots,
            valid_observations=valid_observations,
            strict_model=strict_model or not config.models.allow_degraded_analysis,
            transcript_character_count=sum(len(item.text) for item in segments),
        )
        warnings = list(
            dict.fromkeys(
                [
                    "external_fact_check_not_performed",
                    *(
                        ["knowledge_model_unavailable_deterministic_fallback"]
                        if trace.status == "degraded" and provider is None
                        else []
                    ),
                    *(
                        ["media_analysis_missing_visual_and_ocr_evidence_limited"]
                        if media is None
                        else []
                    ),
                    *trace.errors,
                ]
            )
        )
        status: Literal["complete", "degraded"] = (
            "complete" if trace.status == "success" else "degraded"
        )
        artifact = SingleVideoKnowledgeDistillation(
            knowledge_id=knowledge_id,
            analysis_version=SINGLE_VIDEO_KNOWLEDGE_VERSION,
            video_id=video.video_id,
            account_id=video.account_id,
            generated_at=generated_at,
            run_id=run_id,
            status=status,
            text_analysis_id=analysis.analysis_id,
            media_analysis_id=media.analysis_id if media else None,
            knowledge=knowledge,
            model_trace=trace,
            evidence_path=relative[2],
            warnings_path=relative[3],
            warnings=warnings,
        )
        evidence = ArtifactEvidenceIndex(
            artifact_id=knowledge_id,
            account_ids=[video.account_id],
            run_id=run_id,
            generated_at=generated_at,
            input_hashes=input_hashes,
            items=[
                EvidenceItem(
                    evidence_id=stable_id("evi_", knowledge_id, "video", video.record_id),
                    label="video.metadata",
                    classification="fact",
                    value={"video_id": video.video_id, "title": video.title},
                    calculation="normalized video metadata",
                    sources=[_source("videos", video)],
                ),
                EvidenceItem(
                    evidence_id=stable_id("evi_", knowledge_id, "knowledge"),
                    label="video.knowledge_extraction",
                    classification=(
                        "semantic_annotation" if trace.status == "success" else "warning"
                    ),
                    value=knowledge.model_dump(mode="json"),
                    calculation=(
                        "strict model extraction with source-reference filtering"
                        if trace.status == "success"
                        else "deterministic organization of existing extracted facts"
                    ),
                    sources=[_source("media_features", media_feature)] if media_feature else [],
                ),
            ],
        )
        result = {
            "ok": True,
            "dry_run": dry_run,
            "already_generated": False,
            "knowledge": artifact.model_dump(mode="json"),
            "outputs": relative,
        }
        if dry_run:
            return result
        assert manifest is not None
        output_dir.mkdir(parents=True, exist_ok=True)
        atomic_write_json(paths[0], artifact.model_dump(mode="json"))
        template_path = (
            Path(__file__).resolve().parents[1]
            / "reports"
            / "templates"
            / "single-video-knowledge.md.j2"
        )
        template = Environment(undefined=StrictUndefined, autoescape=False).from_string(
            template_path.read_text(encoding="utf-8")
        )
        atomic_write_text(
            paths[1],
            template.render(knowledge=artifact.model_dump(mode="python")).strip() + "\n",
        )
        atomic_write_json(paths[2], evidence.model_dump(mode="json"))
        atomic_write_json(paths[3], warnings)
        self.project.finish_run(
            manifest,
            success=True,
            processed_counts={"knowledge_items": len(knowledge.knowledge_items)},
            output_files=relative,
            warnings=warnings,
        )
        return result
