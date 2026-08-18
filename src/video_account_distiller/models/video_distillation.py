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

from pydantic import Field

from video_account_distiller.models.core import StrictModel
from video_account_distiller.models.text_analysis import ModelTaskTrace
from video_account_distiller.version import DISTILLATION_SCHEMA_VERSION

DeepStatus = Literal["complete", "degraded"]


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
