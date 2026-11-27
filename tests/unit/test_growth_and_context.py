from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

from video_account_distiller.growth import AccountGrowthService
from video_account_distiller.insights import AnalysisContextService
from video_account_distiller.models import AccountSnapshot, Platform
from video_account_distiller.storage.parquet import write_models
from video_account_distiller.storage.project import ProjectLayout
from video_account_distiller.utils.ids import stable_id


def _snapshot(
    *,
    account_id: str,
    snapshot_id: str,
    snapshot_at: datetime,
    followers: int | None,
    total_likes: int | None,
) -> AccountSnapshot:
    return AccountSnapshot(
        record_id=snapshot_id,
        source_platform=Platform.DOUYIN,
        source_type="test",
        source_record_id=snapshot_id,
        collected_at=snapshot_at,
        run_id="run_test",
        raw_hash="0" * 64,
        account_snapshot_id=snapshot_id,
        account_id=account_id,
        snapshot_at=snapshot_at,
        followers=followers,
        total_likes=total_likes,
        video_count=10,
        source="test",
    )


def test_growth_uses_observed_snapshots_and_preserves_unknowns(project: ProjectLayout) -> None:
    account_id = "acc_growth"
    start = datetime(2026, 7, 1, tzinfo=UTC)
    write_models(
        project.normalized_dir / "account_snapshots.parquet",
        [
            _snapshot(
                account_id=account_id,
                snapshot_id="acs_1",
                snapshot_at=start,
                followers=100,
                total_likes=None,
            ),
            _snapshot(
                account_id=account_id,
                snapshot_id="acs_2",
                snapshot_at=start + timedelta(days=10),
                followers=130,
                total_likes=800,
            ),
        ],
    )

    result = AccountGrowthService(project).summarize(account_id=account_id)

    assert result["status"] == "ready"
    assert result["period_days"] == 10
    assert result["changes"]["followers"]["delta"] == 30
    assert result["changes"]["followers"]["per_day"] == 3
    assert result["changes"]["total_likes"]["delta"] is None
    assert "growth_fields_unavailable:" in result["warnings"][0]


def test_analysis_context_is_bounded_and_does_not_expose_comment_text(
    normalized_project: ProjectLayout,
) -> None:
    account_id = stable_id("acc_", "douyin", "hotel-demo")
    comment_dir = normalized_project.root / "analyses" / "comments" / account_id / "cma_context"
    comment_dir.mkdir(parents=True)
    comment_dir.joinpath("analysis.json").write_text(
        json.dumps(
            {
                "analysis_id": "cma_context",
                "account_id": account_id,
                "generated_at": "2026-07-27T00:00:00+00:00",
                "status": "complete",
                "comment_count": 1,
                "video_count": 1,
                "signals": [{"redacted_text": "must not leave context"}],
                "need_clusters": [{"name": "price"}],
                "warnings": [],
            }
        ),
        encoding="utf-8",
    )

    result = AnalysisContextService(normalized_project).build(account_id=account_id)

    assert result["account"]["account_id"] == account_id
    assert result["data_availability"]["account_videos"] > 0
    comment_context = result["artifacts"]["comment_analysis"]["data"]
    assert "signals" not in comment_context
    assert comment_context["need_clusters"] == [{"name": "price"}]
    assert "missing_values_are_unknown_and_must_not_be_treated_as_zero" in result["limitations"]
