from __future__ import annotations

from video_account_distiller.distillation import AccountDistillationService
from video_account_distiller.distillation.pipeline import (
    _build_clusters,
    _EvidenceCollector,
    _is_unknown_label,
    _resolve_pattern_performance,
)
from video_account_distiller.models import AccountDistillation
from video_account_distiller.sampling.dataset import (
    AccountDataset,
    AccountVideoRecord,
    load_account_dataset,
)
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


def test_unknown_proxy_values_do_not_become_strategy_clusters(
    phase4_project: ProjectLayout,
) -> None:
    account_id = stable_id("acc_", "douyin", "phase2-hotel")
    source = load_account_dataset(phase4_project, account_id)
    dataset = AccountDataset(
        account=source.account,
        records=[
            AccountVideoRecord(
                video=record.video.model_copy(update={"content_type": "unknown"}),
                metric=record.metric,
                derived=record.derived,
            )
            for record in source.records
        ],
        input_hashes=source.input_hashes,
    )

    performance = _resolve_pattern_performance(dataset)
    clusters = _build_clusters(dataset, {}, _EvidenceCollector("dst_test"), performance)

    assert clusters == []
    assert _is_unknown_label("未识别需求") is True


def test_public_interaction_proxy_replaces_missing_performance_for_pattern_mining(
    phase4_project: ProjectLayout,
) -> None:
    account_id = stable_id("acc_", "douyin", "phase2-hotel")
    source = load_account_dataset(phase4_project, account_id)
    dataset = AccountDataset(
        account=source.account,
        records=[
            AccountVideoRecord(
                video=record.video,
                metric=record.metric,
                derived=(
                    record.derived.model_copy(
                        update={"performance_score": None, "performance_band": None}
                    )
                    if record.derived is not None
                    else None
                ),
            )
            for record in source.records
        ],
        input_hashes=source.input_hashes,
    )

    performance = _resolve_pattern_performance(dataset)

    assert performance.basis == "public_interaction_proxy"
    assert len(performance.bands) == len(dataset.records)
    assert "A" in performance.bands.values()
    assert "D" in performance.bands.values()
