from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path

import pytest

from video_account_distiller.closed_loop import (
    PredictionService,
    PublicationService,
    RetroService,
    ScoringService,
)
from video_account_distiller.errors import DistillerError, ErrorCode
from video_account_distiller.ingestion import ImportService
from video_account_distiller.metrics import MetricsService
from video_account_distiller.models import (
    Platform,
    Prediction,
    Publication,
    Retro,
    Rule,
    RuleStatus,
    ScoreResult,
)
from video_account_distiller.normalization import NormalizationService
from video_account_distiller.status import project_status
from video_account_distiller.storage.project import ProjectLayout
from video_account_distiller.utils.ids import stable_id
from video_account_distiller.utils.io import read_json
from video_account_distiller.validation import validate_project


def _import_publication_export(
    project: ProjectLayout,
    *,
    platform_video_id: str,
    published_at: datetime,
    snapshot_age_hours: int,
    promoted: bool = False,
) -> str:
    export_dir = project.root / "phase5-actual"
    export_dir.mkdir(parents=True, exist_ok=True)
    video_path = export_dir / f"{platform_video_id}-video.csv"
    metric_path = export_dir / f"{platform_video_id}-metric.csv"
    snapshot_at = published_at + timedelta(hours=snapshot_age_hours)
    video_path.write_text(
        "platform_video_id,account_id,title,published_at,duration_seconds,content_type,"
        "is_ad,is_pinned,is_repost,follower_count_at_publish,hashtags\n"
        f"{platform_video_id},phase2-hotel,Phase 5 publication,{published_at.isoformat()},"
        "30,room,false,false,false,48000,hotel|room\n",
        encoding="utf-8",
    )
    metric_path.write_text(
        "video_id,snapshot_at,age_hours,views,likes,comments,shares,saves,"
        "follows_gained,profile_visits,avg_watch_time_seconds,completion_rate,"
        "is_promoted,promotion_spend,metric_source\n"
        f"{platform_video_id},{snapshot_at.isoformat()},{snapshot_age_hours},"
        f"18000,900,120,80,160,45,600,19,0.58,{str(promoted).lower()},0,export\n",
        encoding="utf-8",
    )
    importer = ImportService(project)
    importer.import_file(entity="videos", source=video_path, platform=Platform.DOUYIN)
    importer.import_file(entity="metrics", source=metric_path, platform=Platform.DOUYIN)
    NormalizationService(project).normalize()
    account_id = stable_id("acc_", "douyin", "phase2-hotel")
    MetricsService(project).calculate(account_id=account_id)
    return stable_id("vid_", "douyin", platform_video_id)


def test_score_predict_publish_and_retro_keep_an_immutable_learning_loop(
    phase5_project: ProjectLayout,
    fixtures_dir: Path,
) -> None:
    account_id = stable_id("acc_", "douyin", "phase2-hotel")
    script = fixtures_dir / "phase5" / "hotel-script.md"

    scored = ScoringService(phase5_project).score(
        account_id=account_id,
        script=script,
        target_pillar="room",
        planned_publish_hour=9,
    )
    score = ScoreResult.model_validate(scored["score"])
    assert len(score.dimension_scores) == 9
    assert sum(item.weight for item in score.dimension_scores) == 100
    assert score.total_score == round(
        sum(item.weighted_score for item in score.dimension_scores), 2
    )
    assert score.required_fixes == []
    assert score.risk_flags == []
    assert (phase5_project.root / scored["candidate"]["script_path"]).is_file()

    rule_paths = sorted((phase5_project.root / "knowledge-base" / "rules").glob("*/*.json"))
    rules = [Rule.model_validate(read_json(path)) for path in rule_paths]
    assert rules
    assert all(rule.status == RuleStatus.CANDIDATE for rule in rules)
    rules_before_retro = {path: path.read_bytes() for path in rule_paths}

    predicted = PredictionService(phase5_project).predict(
        account_id=account_id,
        script=script,
        target_pillar="room",
        planned_publish_hour=9,
    )
    prediction = Prediction.model_validate(predicted["prediction"])
    prediction_path = (
        phase5_project.root / "predictions" / prediction.prediction_id / "prediction.json"
    )
    prediction_before = prediction_path.read_bytes()
    assert prediction.immutable is True
    assert prediction.target_metrics
    assert all(
        interval.p25 <= interval.p50 <= interval.p75
        for interval in prediction.target_metrics.values()
    )
    assert prediction.confidence_band in {"low", "medium"}

    repeated = PredictionService(phase5_project).predict(
        account_id=account_id,
        script=script,
        target_pillar="room",
        planned_publish_hour=9,
    )
    assert repeated["already_generated"] is True
    assert prediction_path.read_bytes() == prediction_before

    published_at = prediction.created_at + timedelta(minutes=1)
    video_id = _import_publication_export(
        phase5_project,
        platform_video_id="phase5-published",
        published_at=published_at,
        snapshot_age_hours=72,
    )

    registered = PublicationService(phase5_project).register(
        prediction_id=prediction.prediction_id,
        video_id=video_id,
        notes="offline fixture publication",
    )
    publication = Publication.model_validate(registered["publication"])
    assert publication.immutable is True
    assert publication.snapshot_plan
    assert prediction_path.read_bytes() == prediction_before

    reviewed = RetroService(phase5_project).run(
        publication_id=publication.publication_id,
        snapshot="t3d",
    )
    retro = Retro.model_validate(reviewed["retro"])
    assert retro.prediction_errors
    assert retro.next_experiments
    assert all(item.approval_status == "pending" for item in retro.rule_change_proposals)
    assert all(item.approval_status == "pending" for item in retro.rubric_change_proposals)
    assert set(retro.supported_rule_ids).isdisjoint(retro.counterexample_rule_ids)
    assert prediction_path.read_bytes() == prediction_before
    assert {path: path.read_bytes() for path in rule_paths} == rules_before_retro

    status = project_status(phase5_project)
    assert status["artifacts"]["content_scores"] == 1
    assert status["artifacts"]["predictions"] == 1
    assert status["artifacts"]["publications"] == 1
    assert status["artifacts"]["retros"] == 1
    assert status["last_retro_at"] is not None
    assert status["videos"]["total"] == 31
    assert status["videos"]["truncated"] is True
    assert any(item["video_id"] == video_id for item in status["videos"]["recent"])

    validation = validate_project(phase5_project)
    assert validation.error_count == 0
    assert validation.stats["phase5_artifacts"] == 4


def test_retro_does_not_propose_changes_from_a_misaligned_snapshot(
    phase5_project: ProjectLayout,
    fixtures_dir: Path,
) -> None:
    account_id = stable_id("acc_", "douyin", "phase2-hotel")
    predicted = PredictionService(phase5_project).predict(
        account_id=account_id,
        script=fixtures_dir / "phase5" / "hotel-script.md",
        target_pillar="room",
        planned_publish_hour=9,
    )
    prediction = Prediction.model_validate(predicted["prediction"])
    published_at = prediction.created_at + timedelta(minutes=1)
    video_id = _import_publication_export(
        phase5_project,
        platform_video_id="phase5-misaligned",
        published_at=published_at,
        snapshot_age_hours=456,
    )
    registered = PublicationService(phase5_project).register(
        prediction_id=prediction.prediction_id,
        video_id=video_id,
    )
    publication = Publication.model_validate(registered["publication"])

    reviewed = RetroService(phase5_project).run(
        publication_id=publication.publication_id,
        snapshot="t3d",
    )
    retro = Retro.model_validate(reviewed["retro"])

    assert retro.supported_rule_ids == []
    assert retro.counterexample_rule_ids == []
    assert retro.inconclusive_rule_ids
    assert retro.rule_change_proposals == []
    assert retro.rubric_change_proposals == []
    assert "retro_snapshot_not_eligible_for_rule_or_rubric_updates" in retro.warnings


def test_publication_requires_prediction_to_precede_the_normalized_video(
    phase5_project: ProjectLayout,
    fixtures_dir: Path,
) -> None:
    account_id = stable_id("acc_", "douyin", "phase2-hotel")
    prediction = Prediction.model_validate(
        PredictionService(phase5_project).predict(
            account_id=account_id,
            script=fixtures_dir / "phase5" / "hotel-script.md",
            target_pillar="room",
            planned_publish_hour=9,
        )["prediction"]
    )

    with pytest.raises(DistillerError) as caught:
        PublicationService(phase5_project).register(
            prediction_id=prediction.prediction_id,
            video_id=stable_id("vid_", "douyin", "p2-01"),
        )

    assert caught.value.code == ErrorCode.SCHEMA_INVALID
    assert "earlier than" in caught.value.message
