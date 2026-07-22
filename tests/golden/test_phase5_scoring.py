from __future__ import annotations

from pathlib import Path

from video_account_distiller.closed_loop import PredictionService, ScoringService
from video_account_distiller.models import Prediction, ScoreResult
from video_account_distiller.storage.project import ProjectLayout
from video_account_distiller.utils.ids import stable_id


def test_phase5_default_rubric_and_prediction_contract_are_stable(
    phase5_project: ProjectLayout,
    fixtures_dir: Path,
) -> None:
    account_id = stable_id("acc_", "douyin", "phase2-hotel")
    script = fixtures_dir / "phase5" / "hotel-script.md"
    scored = ScoreResult.model_validate(
        ScoringService(phase5_project).score(
            account_id=account_id,
            script=script,
            target_pillar="room",
            planned_publish_hour=9,
            dry_run=True,
        )["score"]
    )
    assert [item.dimension_id for item in scored.dimension_scores] == [
        "account_match",
        "audience_need",
        "topic_strength",
        "hook",
        "structure_value",
        "credibility",
        "interaction_cta",
        "feasibility",
        "risk_control",
    ]
    assert [item.weight for item in scored.dimension_scores] == [15, 15, 15, 15, 15, 10, 5, 5, 5]

    prediction = Prediction.model_validate(
        PredictionService(phase5_project).predict(
            account_id=account_id,
            script=script,
            target_pillar="room",
            planned_publish_hour=9,
            dry_run=True,
        )["prediction"]
    )
    assert set(prediction.target_metrics) == {"views", "engagement_rate_by_view"}
    assert "prediction_is_an_account_local_interval_not_a_guarantee" in prediction.warnings
    assert any(item.startswith("baseline_snapshot_age_mismatch:") for item in prediction.warnings)
    assert prediction.rule_versions
