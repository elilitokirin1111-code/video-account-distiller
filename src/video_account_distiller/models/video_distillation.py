"""Single-video deep distillation contracts: topic selection, expression, craft, copy checklist.

The deep distillation is an optional third stage on top of the blind text
analysis (Phase 3) and local media analysis (Phase 6). It merges both into one
content-addressed reference card so a viewer can distill one interesting video
from an otherwise uninteresting account without needing account-level
performance bands. All model output is strictly validated; without a model the
service falls back to deterministic aggregation of the existing artifacts.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import Field, model_validator

from video_account_distiller.models.core import StrictModel
from video_account_distiller.models.text_analysis import ModelTaskTrace
from video_account_distiller.version import DISTILLATION_SCHEMA_VERSION

DeepStatus = Literal["complete", "degraded"]
KnowledgeItemType = Literal[
    "fact",
    "knowledge_point",
    "concept",
    "method",
    "case",
    "data",
    "news",
    "creator_opinion",
    "inference",
    "recommendation",
]
KnowledgeAttribution = Literal["video_statement", "creator_opinion", "model_inference"]


class SingleVideoCraftSummary(StrictModel):
    """Deterministic per-shot craft counts derived from the media analysis."""

    schema_version: str = DISTILLATION_SCHEMA_VERSION
    analyzed_shots: int = Field(ge=0)
    shot_scale: dict[str, int] = Field(default_factory=dict)
    camera_movement: dict[str, int] = Field(default_factory=dict)
    camera_angle: dict[str, int] = Field(default_factory=dict)
    composition: dict[str, int] = Field(default_factory=dict)
    lighting: dict[str, int] = Field(default_factory=dict)
    text_overlay_style: dict[str, int] = Field(default_factory=dict)
    motion_graphic: dict[str, int] = Field(default_factory=dict)
    branding: dict[str, int] = Field(default_factory=dict)
    opening_techniques: list[str] = Field(default_factory=list)
    pacing_tags: list[str] = Field(default_factory=list)
    average_shot_duration_ms: float | None = Field(default=None, ge=0)
    silence_ratio: float | None = Field(default=None, ge=0, le=1)
    ocr_observation_count: int = Field(ge=0)


class TopicDistillation(StrictModel):
    """Why this video was made and how the topic is framed."""

    topic_statement: str = Field(min_length=1)
    topic_angle: str = Field(min_length=1)
    target_audience: list[str] = Field(default_factory=list)
    information_increment: str = Field(min_length=1)
    memory_point: str = Field(min_length=1)
    topic_formula: str = Field(min_length=1)
    selection_notes: list[str] = Field(default_factory=list)


class ExpressionDistillation(StrictModel):
    """How the video expresses itself: opening, packaging, audio, editing."""

    opening_form: str = Field(min_length=1)
    subtitle_style: str = Field(min_length=1)
    packaging_features: list[str] = Field(default_factory=list)
    audio_expression: str = Field(min_length=1)
    editing_style: str = Field(min_length=1)
    expression_notes: list[str] = Field(default_factory=list)


class CraftDistillation(StrictModel):
    """How the video is shot: shot scale, camera, composition, lighting."""

    shot_scale_profile: str = Field(min_length=1)
    camera_profile: str = Field(min_length=1)
    composition_profile: str = Field(min_length=1)
    lighting_profile: str = Field(min_length=1)
    opening_technique: str = Field(min_length=1)
    pacing: str = Field(min_length=1)
    craft_notes: list[str] = Field(default_factory=list)


class CopyChecklist(StrictModel):
    """What to copy and what to avoid when reproducing this video."""

    topic: list[str] = Field(default_factory=list)
    structure: list[str] = Field(default_factory=list)
    craft: list[str] = Field(default_factory=list)
    expression: list[str] = Field(default_factory=list)
    avoid: list[str] = Field(default_factory=list)


class SingleVideoDeepOutput(StrictModel):
    """Schema-validated model response for one deep single-video distillation."""

    schema_version: str = DISTILLATION_SCHEMA_VERSION
    topic: TopicDistillation
    expression: ExpressionDistillation
    craft: CraftDistillation
    copy_checklist: CopyChecklist
    unknowns: list[str] = Field(default_factory=list)
    evidence_segment_ids: list[str] = Field(default_factory=list)
    evidence_shot_ids: list[str] = Field(default_factory=list)


class SingleVideoDistillation(StrictModel):
    """Content-addressed deep distillation of one video."""

    schema_version: str = DISTILLATION_SCHEMA_VERSION
    distillation_id: str
    analysis_version: str
    video_id: str
    account_id: str
    generated_at: datetime
    run_id: str
    status: DeepStatus
    text_analysis_id: str | None = None
    media_analysis_id: str | None = None
    craft_summary: SingleVideoCraftSummary
    topic: TopicDistillation
    expression: ExpressionDistillation
    craft: CraftDistillation
    copy_checklist: CopyChecklist
    deep_trace: ModelTaskTrace | None = None
    unknowns: list[str] = Field(default_factory=list)
    evidence_index_path: str
    warnings_path: str
    warnings: list[str] = Field(default_factory=list)


class KnowledgeSourceRef(StrictModel):
    """A traceable transcript, OCR, or visual source reference."""

    source_type: Literal["transcript", "ocr", "visual"]
    segment_id: str | None = None
    shot_id: str | None = None
    observation_id: str | None = None
    start_ms: int | None = Field(default=None, ge=0)
    end_ms: int | None = Field(default=None, ge=0)
    excerpt: str | None = Field(default=None, max_length=500)

    @model_validator(mode="after")
    def validate_reference(self) -> KnowledgeSourceRef:
        required_id = {
            "transcript": self.segment_id,
            "ocr": self.observation_id,
            "visual": self.shot_id,
        }[self.source_type]
        if not required_id:
            raise ValueError(f"{self.source_type} source reference is missing its evidence ID")
        if self.start_ms is not None and self.end_ms is not None and self.end_ms < self.start_ms:
            raise ValueError("knowledge source end_ms must be greater than or equal to start_ms")
        return self


class VideoKnowledgeItem(StrictModel):
    knowledge_type: KnowledgeItemType
    attribution: KnowledgeAttribution
    title: str = Field(min_length=1, max_length=160)
    content: str = Field(min_length=1, max_length=2_000)
    source_refs: list[KnowledgeSourceRef] = Field(default_factory=list, max_length=8)
    limitations: list[str] = Field(default_factory=list, max_length=6)


class ContentExpressionNote(StrictModel):
    summary: str = Field(min_length=1, max_length=1_000)
    useful_devices: list[str] = Field(default_factory=list, max_length=5)
    limitations: list[str] = Field(default_factory=list, max_length=5)


class SingleVideoKnowledgeOutput(StrictModel):
    """Independent schema for knowledge-first single-video extraction."""

    schema_version: str = DISTILLATION_SCHEMA_VERSION
    knowledge_title: str = Field(min_length=1, max_length=200)
    content_summary: str = Field(min_length=1, max_length=3_000)
    core_conclusions: list[str] = Field(default_factory=list, max_length=10)
    knowledge_items: list[VideoKnowledgeItem] = Field(default_factory=list, max_length=30)
    important_concepts: list[str] = Field(default_factory=list, max_length=15)
    methods: list[str] = Field(default_factory=list, max_length=15)
    cases: list[str] = Field(default_factory=list, max_length=15)
    key_data: list[str] = Field(default_factory=list, max_length=15)
    entities: list[str] = Field(default_factory=list, max_length=20)
    time_information: list[str] = Field(default_factory=list, max_length=12)
    applicability: list[str] = Field(default_factory=list, max_length=10)
    limitations: list[str] = Field(
        default_factory=lambda: ["未做外部事实核验"],
        min_length=1,
        max_length=12,
    )
    expression_note: ContentExpressionNote = Field(
        default_factory=lambda: ContentExpressionNote(summary="未提供表达方式备注")
    )
    unknowns: list[str] = Field(default_factory=list, max_length=12)


class SingleVideoKnowledgeDistillation(StrictModel):
    schema_version: str = DISTILLATION_SCHEMA_VERSION
    knowledge_id: str
    analysis_version: str
    distillation_mode: Literal["knowledge"] = "knowledge"
    video_id: str
    account_id: str
    generated_at: datetime
    run_id: str
    status: DeepStatus
    text_analysis_id: str | None = None
    media_analysis_id: str | None = None
    knowledge: SingleVideoKnowledgeOutput
    model_trace: ModelTaskTrace | None = None
    evidence_path: str
    warnings_path: str
    warnings: list[str] = Field(default_factory=list)


class AccountVideoKnowledgeDocument(StrictModel):
    video_id: str
    title: str | None = None
    knowledge_id: str
    status: DeepStatus
    source_path: str
    document_path: str
    warnings: list[str] = Field(default_factory=list)


class AccountVideoKnowledgeSkip(StrictModel):
    video_id: str
    title: str | None = None
    reason: str


class AccountVideoKnowledgeManifest(StrictModel):
    """One import-ready account bundle whose Markdown files remain video-scoped."""

    schema_version: str = DISTILLATION_SCHEMA_VERSION
    manifest_id: str
    manifest_version: str
    account_id: str
    generated_at: datetime
    run_id: str
    status: DeepStatus
    requested_count: int
    eligible_count: int
    completed_count: int
    degraded_count: int
    skipped_count: int
    documents: list[AccountVideoKnowledgeDocument] = Field(default_factory=list)
    skipped: list[AccountVideoKnowledgeSkip] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
