from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from video_account_distiller.models import (
    PatternScope,
    QuantileInterval,
    Rubric,
    RubricDimension,
    Rule,
    RuleStatus,
)


def test_prediction_quantiles_must_be_ordered() -> None:
    with pytest.raises(ValidationError, match="prediction quantiles"):
        QuantileInterval(p25=20, p50=10, p75=30)


def test_rubric_weights_must_total_one_hundred() -> None:
    with pytest.raises(ValidationError, match="sum to 100"):
        Rubric(
            rubric_id="rub_test",
            account_id="acc_test",
            version="1.0.0",
            dimensions=[
                RubricDimension(
                    dimension_id="dim_test",
                    name="测试",
                    weight=99,
                    scoring_guide=["可解释"],
                )
            ],
            source_distillation_id="dst_test",
            created_at=datetime.now(UTC),
        )


def test_validated_rule_requires_human_approval_metadata() -> None:
    with pytest.raises(ValidationError, match="approved_by"):
        Rule(
            rule_id="rule_test",
            account_id="acc_test",
            source_pattern_ids=["pat_test"],
            name="测试规则",
            instruction="执行对照实验",
            scope=PatternScope(platforms=["douyin"]),
            required_conditions={"feature_type": "hook", "feature_value": "question_challenge"},
            expected_effect="performance_score may improve",
            target_metric="performance_score",
            confidence=0.8,
            evidence_count=10,
            experiment_count=3,
            status=RuleStatus.VALIDATED,
            version="1.0.0",
            created_at=datetime.now(UTC),
            last_updated_at=datetime.now(UTC),
        )
