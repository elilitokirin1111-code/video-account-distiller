"""Phase 5 scoring, prediction, publication, and retrospective contracts."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Literal

from pydantic import Field, model_validator

from video_account_distiller.models.core import Platform, StrictModel
from video_account_distiller.models.distillation import PatternScope
from video_account_distiller.version import CLOSED_LOOP_SCHEMA_VERSION


class RuleStatus(StrEnum):
    CANDIDATE = "candidate"
    EXPERIMENTAL = "experimental"
    VALIDATED = "validated"
    DEPRECATED = "deprecated"
    REJECTED = "rejected"


class Rule(StrictModel):
    schema_version: str = CLOSED_LOOP_SCHEMA_VERSION
    rule_id: str
    account_id: str
    source_pattern_ids: list[str] = Field(min_length=1)
    name: str
    instruction: str
    scope: PatternScope
    required_conditions: dict[str, str]
    forbidden_conditions: list[str] = Field(default_factory=list)
    expected_effect: str
    target_metric: str
    confidence: float = Field(ge=0, le=1)
    evidence_count: int = Field(ge=1)
    experiment_count: int = Field(ge=0)
    status: RuleStatus
    version: str
    approved_by: str | None = None
    approved_at: datetime | None = None
    created_at: datetime
    last_updated_at: datetime

    @model_validator(mode="after")
    def validate_approval(self) -> Rule:
        if self.status == RuleStatus.VALIDATED and (
            self.approved_by is None or self.approved_at is None
        ):
            raise ValueError("validated rules require approved_by and approved_at")
        return self


class RubricDimension(StrictModel):
    dimension_id: str
    name: str
    weight: float = Field(gt=0, le=100)
    scoring_guide: list[str] = Field(min_length=1)
    evidence_rule_ids: list[str] = Field(default_factory=list)


class Rubric(StrictModel):
    schema_version: str = CLOSED_LOOP_SCHEMA_VERSION
    rubric_id: str
    account_id: str
    version: str
    dimensions: list[RubricDimension] = Field(min_length=1)
    source_distillation_id: str
    created_at: datetime

    @model_validator(mode="after")
    def validate_weights(self) -> Rubric:
        if abs(sum(item.weight for item in self.dimensions) - 100.0) > 1e-6:
            raise ValueError("rubric dimension weights must sum to 100")
        if len({item.dimension_id for item in self.dimensions}) != len(self.dimensions):
            raise ValueError("rubric dimension IDs must be unique")
        return self


class ContentCandidate(StrictModel):
    schema_version: str = CLOSED_LOOP_SCHEMA_VERSION
    candidate_id: str
    account_id: str
    title: str
    topic: str | None = None
    script_path: str
    script_hash: str
    shot_plan_path: str | None = None
    target_platform: Platform
    target_pillar: str | None = None
    target_metric: str
    planned_publish_hour: int | None = Field(default=None, ge=0, le=23)
    created_at: datetime


class DimensionScore(StrictModel):
    dimension_id: str
    name: str
    raw_score: float = Field(ge=0, le=100)
    weight: float = Field(gt=0, le=100)
    weighted_score: float = Field(ge=0, le=100)
    rationale: str
    evidence_rule_ids: list[str] = Field(default_factory=list)
    evidence_pattern_ids: list[str] = Field(default_factory=list)
    missing_items: list[str] = Field(default_factory=list)


class ScoreResult(StrictModel):
    schema_version: str = CLOSED_LOOP_SCHEMA_VERSION
    score_id: str
    candidate_id: str
    account_id: str
    rubric_id: str
    rubric_version: str
    total_score: float = Field(ge=0, le=100)
    dimension_scores: list[DimensionScore] = Field(min_length=1)
    strengths: list[str]
    weaknesses: list[str]
    required_fixes: list[str]
    risk_flags: list[str]
    evidence_ids: list[str] = Field(min_length=1)
    created_at: datetime
    run_id: str
    input_hashes: list[str]
    evidence_index_path: str
    warnings_path: str
    warnings: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_total(self) -> ScoreResult:
        calculated = sum(item.weighted_score for item in self.dimension_scores)
        if abs(self.total_score - calculated) > 0.02:
            raise ValueError("total_score must equal weighted dimension scores")
        return self


class QuantileInterval(StrictModel):
    p25: float = Field(ge=0)
    p50: float = Field(ge=0)
    p75: float = Field(ge=0)

    @model_validator(mode="after")
    def validate_order(self) -> QuantileInterval:
        if not self.p25 <= self.p50 <= self.p75:
            raise ValueError("prediction quantiles must be ordered p25 <= p50 <= p75")
        return self


class Prediction(StrictModel):
    schema_version: str = CLOSED_LOOP_SCHEMA_VERSION
    prediction_id: str
    candidate_id: str
    score_id: str
    account_id: str
    rubric_id: str
    rubric_version: str
    rule_versions: dict[str, str]
    created_at: datetime
    target_snapshot_age_hours: int = Field(ge=1)
    target_metrics: dict[str, QuantileInterval] = Field(min_length=1)
    confidence: float = Field(ge=0, le=1)
    confidence_band: Literal["low", "medium", "high"]
    positive_factors: list[str]
    negative_factors: list[str]
    uncertainties: list[str]
    assumptions: list[str]
    input_hash: str
    immutable: Literal[True] = True
    run_id: str
    evidence_index_path: str
    warnings_path: str
    warnings: list[str] = Field(default_factory=list)


class SnapshotPlanItem(StrictModel):
    label: Literal["t1h", "t24h", "t3d", "t7d", "custom"]
    target_age_hours: int = Field(ge=1)
    status: Literal["planned", "available"]


class Publication(StrictModel):
    schema_version: str = CLOSED_LOOP_SCHEMA_VERSION
    publication_id: str
    candidate_id: str
    prediction_id: str | None = None
    account_id: str
    video_id: str
    published_at: datetime
    url: str | None = None
    platform: Platform
    notes: str | None = None
    snapshot_plan: list[SnapshotPlanItem] = Field(min_length=1)
    created_at: datetime
    run_id: str
    input_hash: str
    immutable: Literal[True] = True


class PredictionError(StrictModel):
    metric: str
    actual: float | None = Field(default=None, ge=0)
    predicted_p50: float = Field(ge=0)
    absolute_error: float | None = None
    relative_error: float | None = None
    interval_position: Literal["below_p25", "within_p25_p75", "above_p75", "unknown"]


class RuleChangeProposal(StrictModel):
    proposal_id: str
    rule_id: str
    from_version: str
    proposed_version: str
    action: Literal["strengthen", "weaken", "narrow", "hold", "deprecate"]
    proposed_status: RuleStatus
    rationale: str
    approval_status: Literal["pending"] = "pending"
    created_at: datetime


class RubricChangeProposal(StrictModel):
    proposal_id: str
    dimension_id: str
    current_weight: float = Field(gt=0, le=100)
    proposed_weight: float = Field(gt=0, le=100)
    rationale: str
    approval_status: Literal["pending"] = "pending"


class Experiment(StrictModel):
    schema_version: str = CLOSED_LOOP_SCHEMA_VERSION
    experiment_id: str
    account_id: str
    source_retro_id: str
    hypothesis: str
    variable: str
    control: str
    target_metric: str
    minimum_sample_size: int = Field(ge=2)
    status: Literal["proposed"] = "proposed"
    created_at: datetime


class RetroActualMetrics(StrictModel):
    metric_snapshot_id: str
    snapshot_at: datetime
    age_hours: float = Field(ge=0)
    metrics: dict[str, float | None]
    performance_band: Literal["S", "A", "B", "C", "D"] | None = None


class Retro(StrictModel):
    schema_version: str = CLOSED_LOOP_SCHEMA_VERSION
    retro_id: str
    publication_id: str
    prediction_id: str | None = None
    account_id: str
    video_id: str
    evaluated_snapshot_at: datetime
    target_snapshot_label: str
    actual_metrics: RetroActualMetrics
    prediction_errors: list[PredictionError]
    supported_rule_ids: list[str]
    counterexample_rule_ids: list[str]
    inconclusive_rule_ids: list[str]
    external_factors: list[str]
    lessons: list[str]
    rule_change_proposals: list[RuleChangeProposal]
    rubric_change_proposals: list[RubricChangeProposal]
    next_experiments: list[Experiment]
    created_at: datetime
    run_id: str
    evidence_index_path: str
    warnings_path: str
    warnings: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_rule_sets(self) -> Retro:
        support = set(self.supported_rule_ids)
        counter = set(self.counterexample_rule_ids)
        inconclusive = set(self.inconclusive_rule_ids)
        if (
            support.intersection(counter)
            or support.intersection(inconclusive)
            or counter.intersection(inconclusive)
        ):
            raise ValueError("Retro Rule outcome sets must be disjoint")
        return self
