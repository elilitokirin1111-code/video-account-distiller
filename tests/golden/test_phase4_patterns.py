from __future__ import annotations

from video_account_distiller.distillation import AccountDistillationService
from video_account_distiller.models import AccountDistillation
from video_account_distiller.storage.project import ProjectLayout
from video_account_distiller.utils.ids import stable_id


def test_phase4_golden_patterns_cover_all_proxy_pillars_and_counterexamples(
    phase4_project: ProjectLayout,
) -> None:
    account_id = stable_id("acc_", "douyin", "phase2-hotel")
    payload = AccountDistillationService(phase4_project).distill(
        account_id=account_id, dry_run=True
    )["distillation"]
    result = AccountDistillation.model_validate(payload)

    assert {item.feature_value for item in result.content_clusters} == {
        "food",
        "room",
        "service",
    }
    assert all(item.video_count == 10 for item in result.content_clusters)
    topic_patterns = [item for item in result.patterns if item.pattern_type in {"topic", "failure"}]
    assert topic_patterns
    assert any(item.counterexample_video_ids for item in topic_patterns)
    assert "no_phase4_pattern_is_a_level4_validated_rule" in result.warnings
