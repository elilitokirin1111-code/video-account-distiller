"""Phase 4 comment, pattern, distillation, and comparison contracts."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Literal

from pydantic import Field, model_validator

from video_account_distiller.models.analysis import EvidenceItem
from video_account_distiller.models.core import StrictModel
from video_account_distiller.models.text_analysis import ModelTaskTrace
from video_account_distiller.version import DISTILLATION_SCHEMA_VERSION


class CommentSentiment(StrEnum):
    SUPPORTIVE = "supportive"
    OPPOSED = "opposed"
    NEUTRAL = "neutral"
    MIXED = "mixed"
    UNKNOWN = "unknown"


class CommentIntent(StrEnum):
    SUPPORT = "support"
    OPPOSE = "oppose"
    FOLLOW_UP = "follow_up"
    REQUEST_TUTORIAL = "request_tutorial"
    REQUEST_LINK = "request_link"
    PURCHASE_INTENT = "purchase_intent"
    SHARE_EXPERIENCE = "share_experience"
    SUGGESTION = "suggestion"
    KNOWLEDGE_CONTRIBUTION = "knowledge_contribution"
    QUESTION_EVIDENCE = "question_evidence"
    PRICE_OBJECTION = "price_objection"
    FEATURE_OBJECTION = "feature_objection"
    IDENTITY_SIGNAL = "identity_signal"
    EMOTIONAL_EXPRESSION = "emotional_expression"
    JOKE = "joke"
    IRRELEVANT = "irrelevant"
    SPAM_OR_AD = "spam_or_ad"
    UNKNOWN = "unknown"


class CommentSignalAnnotation(StrictModel):
    """Schema-validated semantic output for one redacted comment."""

    schema_version: str = DISTILLATION_SCHEMA_VERSION
    sentiment: CommentSentiment
    intent_labels: list[CommentIntent] = Field(min_length=1)
    pain_points: list[str] = Field(default_factory=list)
    questions: list[str] = Field(default_factory=list)
    objections: list[str] = Field(default_factory=list)
    purchase_intent: float | None = Field(default=None, ge=0, le=1)
    identity_signal: str | None = None
    content_opportunities: list[str] = Field(default_factory=list)
    spam_probability: float = Field(ge=0, le=1)
    confidence: float = Field(ge=0, le=1)
    unknowns: list[str] = Field(default_factory=list)


class CommentSignal(StrictModel):
    schema_version: str = DISTILLATION_SCHEMA_VERSION
    comment_signal_id: str
    comment_id: str
    video_id: str
    redacted_text: str
    redaction_count: int = Field(ge=0)
    annotation: CommentSignalAnnotation
    task_trace: ModelTaskTrace
    evidence_id: str


class CommentNeedCluster(StrictModel):
    schema_version: str = DISTILLATION_SCHEMA_VERSION
    cluster_id: str
    name: str
    primary_intent: CommentIntent
    description: str
    frequency: int = Field(ge=1)
    intensity: float = Field(ge=0, le=1)
    comment_ids: list[str] = Field(min_length=1)
    video_ids: list[str] = Field(min_length=1)
    representative_comment_ids: list[str] = Field(min_length=1)
    pain_points: list[str] = Field(default_factory=list)
    objections: list[str] = Field(default_factory=list)
    content_opportunities: list[str] = Field(default_factory=list)
    evidence_id: str


class ArtifactEvidenceIndex(StrictModel):
    schema_version: str = DISTILLATION_SCHEMA_VERSION
    artifact_id: str
    account_ids: list[str]
    run_id: str
    generated_at: datetime
    input_hashes: list[str]
    items: list[EvidenceItem]


class CommentAnalysis(StrictModel):
    schema_version: str = DISTILLATION_SCHEMA_VERSION
    analysis_id: str
    account_id: str
    generated_at: datetime
    run_id: str
    status: Literal["complete", "degraded"]
    comment_count: int = Field(ge=1)
    video_count: int = Field(ge=1)
    signals: list[CommentSignal]
    need_clusters: list[CommentNeedCluster]
    input_hashes: list[str]
    evidence_index_path: str
    warnings_path: str
    warnings: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_counts(self) -> CommentAnalysis:
        if self.comment_count != len(self.signals):
            raise ValueError("comment_count must equal the number of signals")
        if self.video_count != len({item.video_id for item in self.signals}):
            raise ValueError("video_count must equal unique signal video IDs")
        return self


class ContentCluster(StrictModel):
    schema_version: str = DISTILLATION_SCHEMA_VERSION
    cluster_id: str
    name: str
    method: Literal["semantic_pillar", "content_type_proxy", "mixed"]
    feature_value: str
    video_ids: list[str] = Field(min_length=1)
    video_count: int = Field(ge=1)
    performance_band_counts: dict[str, int]
    median_performance_score: float | None = None
    high_performance_rate: float | None = Field(default=None, ge=0, le=1)
    source_analysis_ids: list[str] = Field(default_factory=list)
    evidence_id: str

    @model_validator(mode="after")
    def validate_video_count(self) -> ContentCluster:
        if self.video_count != len(set(self.video_ids)):
            raise ValueError("video_count must equal unique video_ids")
        return self


class PatternScope(StrictModel):
    platforms: list[str] = Field(min_length=1)
    pillars: list[str] = Field(default_factory=list)
    account_stages: list[str] = Field(default_factory=list)
    duration_range: str | None = None


class Pattern(StrictModel):
    schema_version: str = DISTILLATION_SCHEMA_VERSION
    pattern_id: str
    account_id: str
    pattern_type: Literal[
        "topic",
        "hook",
        "structure",
        "persona",
        "cta",
        "posting_time",
        "comment_trigger",
        "conversion",
        "craft",
        "failure",
    ]
    name: str
    description: str
    feature_conditions: dict[str, str]
    target_metrics: list[str]
    support_video_ids: list[str]
    counterexample_video_ids: list[str]
    support_count: int = Field(ge=0)
    counterexample_count: int = Field(ge=0)
    effect_summary: str
    confounders: list[str] = Field(default_factory=list)
    scope: PatternScope
    confidence: float = Field(ge=0, le=1)
    maturity_level: Literal[0, 1, 2, 3, 4]
    replicability: Literal["low", "medium", "high", "unknown"]
    risks: list[str] = Field(default_factory=list)
    evidence_ids: list[str] = Field(min_length=1)
    created_at: datetime
    last_validated_at: datetime
    version: str

    @model_validator(mode="after")
    def validate_evidence_sets(self) -> Pattern:
        if self.support_count != len(set(self.support_video_ids)):
            raise ValueError("support_count must equal unique support_video_ids")
        if self.counterexample_count != len(set(self.counterexample_video_ids)):
            raise ValueError("counterexample_count must equal unique counterexample_video_ids")
        overlap = set(self.support_video_ids).intersection(self.counterexample_video_ids)
        if overlap:
            raise ValueError("support and counterexample video IDs must be disjoint")
        if not self.support_video_ids:
            raise ValueError("every pattern requires at least one support video")
        return self


class AccountPositioning(StrictModel):
    statement: str
    observed_content_focus: list[str]
    audience_need_clusters: list[str]
    persona_signals: list[str]
    visual_and_audio_identity: list[str] = Field(default_factory=list)
    confidence: Literal["low", "medium", "high"]
    evidence_ids: list[str]
    unknowns: list[str] = Field(default_factory=list)


class CraftTagSummary(StrictModel):
    """One shooting-technique or expression-form tag with its video coverage."""

    schema_version: str = DISTILLATION_SCHEMA_VERSION
    tag: str
    video_count: int = Field(ge=1)
    video_ids: list[str] = Field(min_length=1)
    coverage: float = Field(ge=0, le=1)

    @model_validator(mode="after")
    def validate_count(self) -> CraftTagSummary:
        if self.video_count != len(set(self.video_ids)):
            raise ValueError("video_count must equal unique video_ids")
        return self


class CraftEditingRhythm(StrictModel):
    """Deterministic editing-rhythm summary over analyzed media."""

    schema_version: str = DISTILLATION_SCHEMA_VERSION
    analyzed_with_shots: int = Field(ge=0)
    median_shot_duration_ms: float | None = Field(default=None, ge=0)
    pace_label: str | None = None
    shot_count_median: float | None = Field(default=None, ge=0)


class CraftProfile(StrictModel):
    """Account-level distillation of visible shooting techniques and expression forms.

    Categories aggregate per-video craft tags deterministically. Each summary's
    coverage is relative to the category denominator stored in
    `category_denominators` (vision-annotated media for visual categories, all
    shot-bearing media for pacing). Tags come from the local vision model and
    remain observations, not causal rules.
    """

    schema_version: str = DISTILLATION_SCHEMA_VERSION
    analyzed_media_count: int = Field(ge=0)
    annotated_media_count: int = Field(ge=0)
    categories: dict[str, list[CraftTagSummary]] = Field(default_factory=dict)
    category_denominators: dict[str, int] = Field(default_factory=dict)
    editing_rhythm: CraftEditingRhythm | None = None
    signature_style: list[str] = Field(default_factory=list)
    unknowns: list[str] = Field(default_factory=list)


class AccountDistillation(StrictModel):
    schema_version: str = DISTILLATION_SCHEMA_VERSION
    distillation_id: str
    account_id: str
    generated_at: datetime
    run_id: str
    data_scope: dict[str, int | float | str | None]
    positioning: AccountPositioning
    content_clusters: list[ContentCluster]
    comment_need_clusters: list[CommentNeedCluster]
    patterns: list[Pattern]
    strengths: list[str]
    weaknesses: list[str]
    copyable_factors: list[str]
    noncopyable_factors: list[str]
    action_recommendations: list[str]
    experiment_plan: list[str]
    craft_profile: CraftProfile | None = None
    evidence_index_path: str
    warnings_path: str
    warnings: list[str] = Field(default_factory=list)


class TransferMatrixItem(StrictModel):
    source_account_id: str
    target_account_id: str
    pattern_id: str
    pattern_name: str
    user_alignment: Literal["high", "medium", "low", "unknown"]
    value_alignment: Literal["high", "medium", "low", "unknown"]
    account_stage_alignment: Literal["same", "different", "unknown"]
    resource_alignment: Literal["high", "medium", "low", "unknown"]
    platform_alignment: Literal["same", "different"]
    business_alignment: Literal["high", "medium", "low", "unknown"]
    replicability: Literal["low", "medium", "high", "unknown"]
    verdict: Literal["directly_test", "adapt_then_test", "understand_only", "do_not_migrate"]
    preserve: list[str]
    replace: list[str]
    remove: list[str]
    risks: list[str]
    evidence_ids: list[str] = Field(min_length=1)


class InteractionBenchmarkSummary(StrictModel):
    metric_video_count: int = Field(ge=0)
    totals: dict[str, int]
    medians_per_video: dict[str, float | None]
    interaction_mix: dict[str, float | None]
    median_interactions_per_video: float | None = Field(default=None, ge=0)
    interactions_per_1000_followers: float | None = Field(default=None, ge=0)
    unavailable_fields: list[str] = Field(default_factory=list)


class CommentContentBenchmarkSummary(StrictModel):
    comment_count: int = Field(ge=0)
    video_count: int = Field(ge=0)
    sentiment_counts: dict[str, int]
    intent_counts: dict[str, int]
    comment_like_count_coverage: float | None = Field(default=None, ge=0, le=1)
    comment_like_total: int | None = Field(default=None, ge=0)
    comment_like_median: float | None = Field(default=None, ge=0)
    question_rate: float | None = Field(default=None, ge=0, le=1)
    pain_point_rate: float | None = Field(default=None, ge=0, le=1)
    objection_rate: float | None = Field(default=None, ge=0, le=1)
    purchase_intent_mean: float | None = Field(default=None, ge=0, le=1)
    spam_rate: float | None = Field(default=None, ge=0, le=1)
    need_clusters: list[str] = Field(default_factory=list)
    top_questions: list[str] = Field(default_factory=list)
    top_pain_points: list[str] = Field(default_factory=list)
    top_objections: list[str] = Field(default_factory=list)
    top_content_opportunities: list[str] = Field(default_factory=list)


class ContentInteractionSummary(StrictModel):
    feature_name: str
    feature_value: str
    video_count: int = Field(ge=1)
    source_video_ids: list[str] = Field(min_length=1)
    medians_per_video: dict[str, float | None]
    limitations: list[str] = Field(default_factory=lambda: ["descriptive_association_only"])


class AccountBenchmarkProfile(StrictModel):
    schema_version: str = DISTILLATION_SCHEMA_VERSION
    profile_id: str
    account_id: str
    platform: str
    generated_at: datetime
    run_id: str
    source_distillation_id: str
    account_snapshot_at: datetime
    latest_metric_snapshot_at: datetime | None = None
    follower_count: int | None = Field(default=None, ge=0)
    sampled_video_count: int = Field(ge=1)
    analyzed_video_count: int = Field(ge=0)
    analyzed_media_count: int = Field(ge=0)
    interactions: InteractionBenchmarkSummary
    comment_content: CommentContentBenchmarkSummary
    content_interactions: list[ContentInteractionSummary] = Field(default_factory=list)
    content_pillars: list[str] = Field(default_factory=list)
    visual_and_audio_identity: list[str] = Field(default_factory=list)
    craft_identity: CraftProfile | None = None
    input_hashes: list[str]
    warnings: list[str] = Field(default_factory=list)


class AccountRankingEntry(StrictModel):
    account_id: str
    rank: int = Field(ge=1)
    composite_score: float = Field(ge=0, le=100)
    dimension_scores: dict[str, float | None]
    raw_indicators: dict[str, float | None]
    data_coverage: float = Field(ge=0, le=1)
    limitations: list[str] = Field(default_factory=list)


class BenchmarkComparison(StrictModel):
    schema_version: str = DISTILLATION_SCHEMA_VERSION
    comparison_id: str
    target_account_id: str
    benchmark_account_ids: list[str] = Field(min_length=1)
    generated_at: datetime
    run_id: str
    profiles: list[AccountBenchmarkProfile] = Field(default_factory=list)
    rankings: list[AccountRankingEntry] = Field(default_factory=list)
    ranking_basis: list[str] = Field(default_factory=list)
    transfer_matrix: list[TransferMatrixItem]
    recommended_experiments: list[str]
    evidence_index_path: str
    warnings_path: str
    warnings: list[str] = Field(default_factory=list)
