"""Phase 3 transcript and blind text-analysis contracts."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Literal

from pydantic import Field

from video_account_distiller.models.analysis import EvidenceItem
from video_account_distiller.models.core import StrictModel
from video_account_distiller.version import TEXT_ANALYSIS_SCHEMA_VERSION


class HookType(StrEnum):
    RESULT_FIRST = "result_first"
    COUNTERINTUITIVE = "counterintuitive"
    STRONG_CONFLICT = "strong_conflict"
    PAIN_POINT = "pain_point"
    IDENTITY_CALLOUT = "identity_callout"
    NUMBER_LIST = "number_list"
    TIME_PRESSURE = "time_pressure"
    LOSS_AVERSION = "loss_aversion"
    SECRET_REVEAL = "secret_reveal"
    FAILURE_REVIEW = "failure_review"
    BEFORE_AFTER = "before_after"
    QUESTION_CHALLENGE = "question_challenge"
    STORY_SUSPENSE = "story_suspense"
    AUTHORITY = "authority"
    SOCIAL_PROOF = "social_proof"
    CONTROVERSIAL_STANCE = "controversial_stance"
    EXPLICIT_BENEFIT = "explicit_benefit"
    PROCESS_DEMO = "process_demo"
    DIRECT_DEMO = "direct_demo"
    UNKNOWN = "unknown"


class StructureFunction(StrEnum):
    HOOK = "hook"
    PROBLEM = "problem"
    VALUE_PROMISE = "value_promise"
    DEVELOPMENT = "development"
    PROOF = "proof"
    PEAK = "peak"
    CONCLUSION = "conclusion"
    CTA = "cta"
    LOOP = "loop"
    UNKNOWN = "unknown"


class CtaType(StrEnum):
    COMMENT = "comment"
    SAVE = "save"
    SHARE = "share"
    FOLLOW = "follow"
    DIRECT_MESSAGE = "direct_message"
    PROFILE = "profile"
    PRODUCT = "product"
    COMMUNITY = "community"
    NEXT_EPISODE = "next_episode"
    NONE = "none"
    UNKNOWN = "unknown"


class EmotionLabel(StrEnum):
    CALM = "calm"
    CURIOSITY = "curiosity"
    TENSION = "tension"
    CONFLICT = "conflict"
    SURPRISE = "surprise"
    RESONANCE = "resonance"
    ANXIETY = "anxiety"
    SATISFACTION = "satisfaction"
    TRUST = "trust"
    ACTION = "action"
    UNKNOWN = "unknown"


class TranscriptInputSegment(StrictModel):
    """Minimal transcript segment allowed into the blind model bundle."""

    segment_id: str
    start_ms: int | None = Field(default=None, ge=0)
    end_ms: int | None = Field(default=None, ge=0)
    text: str = Field(min_length=1)
    speaker: str | None = None


class BlindVideoBundle(StrictModel):
    """Content-only input that deliberately excludes performance data."""

    schema_version: str = TEXT_ANALYSIS_SCHEMA_VERSION
    video_id: str
    platform: str
    title: str | None = None
    description: str | None = None
    duration_seconds: float | None = Field(default=None, ge=0)
    language: str | None = None
    transcript_segments: list[TranscriptInputSegment] = Field(min_length=1)


class ExtractedFact(StrictModel):
    """One observable text fact linked to exact transcript segments."""

    category: Literal["claim", "number", "entity", "offer", "instruction", "other"]
    text: str = Field(min_length=1)
    evidence_segment_ids: list[str] = Field(min_length=1)


class VideoFactExtraction(StrictModel):
    """Schema-validated first model task with no performance context."""

    schema_version: str = TEXT_ANALYSIS_SCHEMA_VERSION
    transcript_language: str | None = None
    opening_text: str | None = None
    closing_text: str | None = None
    segment_count: int = Field(ge=1)
    character_count: int = Field(ge=0)
    facts: list[ExtractedFact] = Field(default_factory=list)
    explicit_cta_texts: list[str] = Field(default_factory=list)
    unknowns: list[str] = Field(default_factory=list)


class HookAnnotation(StrictModel):
    primary_type: HookType
    secondary_types: list[HookType] = Field(default_factory=list)
    hook_text: str | None = None
    start_ms: int | None = Field(default=None, ge=0)
    end_ms: int | None = Field(default=None, ge=0)
    promise: str | None = None
    curiosity_gap: str | None = None
    evidence_segment_ids: list[str] = Field(default_factory=list)


class StructureAnnotation(StrictModel):
    function: StructureFunction
    start_ms: int | None = Field(default=None, ge=0)
    end_ms: int | None = Field(default=None, ge=0)
    text_summary: str = Field(min_length=1)
    evidence_segment_ids: list[str] = Field(min_length=1)


class EmotionPoint(StrictModel):
    emotion: EmotionLabel
    start_ms: int | None = Field(default=None, ge=0)
    end_ms: int | None = Field(default=None, ge=0)
    evidence_segment_ids: list[str] = Field(min_length=1)


class CtaAnnotation(StrictModel):
    primary_type: CtaType
    text: str | None = None
    alignment_score: float | None = Field(default=None, ge=0, le=1)
    evidence_segment_ids: list[str] = Field(default_factory=list)


class VideoSemanticAnnotation(StrictModel):
    """Text-only semantic labels produced before metrics are disclosed."""

    schema_version: str = TEXT_ANALYSIS_SCHEMA_VERSION
    primary_pillar: str = Field(min_length=1)
    primary_pillar_evidence_segment_ids: list[str] = Field(default_factory=list)
    secondary_topics: list[str] = Field(default_factory=list)
    audience_tasks: list[str] = Field(default_factory=list)
    content_goal: str = Field(min_length=1)
    funnel_stage: str = Field(min_length=1)
    hook: HookAnnotation
    structure_segments: list[StructureAnnotation] = Field(min_length=1)
    narrative_type: str = Field(min_length=1)
    information_density: Literal["low", "medium", "high", "unknown"]
    emotion_timeline: list[EmotionPoint] = Field(default_factory=list)
    cta: CtaAnnotation
    persona_signals: list[str] = Field(default_factory=list)
    language_signals: list[str] = Field(default_factory=list)
    risk_flags: list[str] = Field(default_factory=list)
    unknowns: list[str] = Field(default_factory=list)
    confidence: float = Field(ge=0, le=1)


class ModelTaskTrace(StrictModel):
    task: Literal["video_fact_extraction", "video_semantic_labeling", "comment_intent"]
    prompt_version: str
    prompt_hash: str
    provider: str
    model: str
    attempts: int = Field(ge=0)
    status: Literal["success", "degraded"]
    errors: list[str] = Field(default_factory=list)


class BlindContentAnalysis(StrictModel):
    """Immutable blind-stage output that cannot contain performance fields."""

    schema_version: str = TEXT_ANALYSIS_SCHEMA_VERSION
    video_id: str
    blind_to_performance: Literal[True] = True
    bundle_hash: str
    facts: VideoFactExtraction
    semantics: VideoSemanticAnnotation
    task_traces: list[ModelTaskTrace]
    warnings: list[str] = Field(default_factory=list)


class VideoPerformanceContext(StrictModel):
    """Stage-two metric context merged only after blind labeling is frozen."""

    snapshot_at: datetime | None = None
    views: int | None = Field(default=None, ge=0)
    engagement_rate_by_view: float | None = None
    completion_efficiency: float | None = None
    performance_score: float | None = None
    performance_band: Literal["S", "A", "B", "C", "D"] | None = None
    outlier_flags: list[str] = Field(default_factory=list)
    is_promoted: bool | None = None
    evidence_ids: dict[str, str] = Field(default_factory=dict)


class VideoAnalysisEvidenceIndex(StrictModel):
    """Resolve transcript segment and metric evidence to immutable sources."""

    schema_version: str = TEXT_ANALYSIS_SCHEMA_VERSION
    analysis_id: str
    video_id: str
    run_id: str
    generated_at: datetime
    input_hashes: list[str]
    segment_to_evidence: dict[str, str]
    items: list[EvidenceItem]


class SingleVideoAnalysis(StrictModel):
    """Machine-readable Phase 3 single-video text analysis."""

    schema_version: str = TEXT_ANALYSIS_SCHEMA_VERSION
    analysis_id: str
    analysis_version: str
    video_id: str
    account_id: str
    generated_at: datetime
    run_id: str
    status: Literal["complete", "degraded"]
    blind_analysis_path: str
    evidence_index_path: str
    warnings_path: str
    blind_analysis: BlindContentAnalysis
    performance_context: VideoPerformanceContext
    warnings: list[str] = Field(default_factory=list)
