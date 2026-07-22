from __future__ import annotations

from pathlib import Path

from video_account_distiller.distillation import (
    AccountDistillationService,
    BenchmarkComparisonService,
)
from video_account_distiller.models import (
    AccountDistillation,
    ArtifactEvidenceIndex,
    BenchmarkComparison,
)
from video_account_distiller.status import project_status
from video_account_distiller.storage.project import ProjectLayout
from video_account_distiller.utils.ids import stable_id
from video_account_distiller.utils.io import read_json
from video_account_distiller.validation import validate_project


def test_account_distillation_keeps_support_counterexamples_and_knowledge(
    phase4_project: ProjectLayout,
) -> None:
    account_id = stable_id("acc_", "douyin", "phase2-hotel")
    service = AccountDistillationService(phase4_project)
    result = service.distill(account_id=account_id)
    paths = [phase4_project.root / Path(item) for item in result["outputs"]]
    distillation = AccountDistillation.model_validate(read_json(paths[0]))
    evidence = ArtifactEvidenceIndex.model_validate(read_json(paths[2]))
    evidence_ids = {item.evidence_id for item in evidence.items}

    assert distillation.content_clusters
    assert distillation.patterns
    assert any(item.counterexample_count > 0 for item in distillation.patterns)
    assert all(item.support_count > 0 for item in distillation.patterns)
    assert all(item.maturity_level <= 1 for item in distillation.patterns)
    assert all(
        set(item.support_video_ids).isdisjoint(item.counterexample_video_ids)
        for item in distillation.patterns
    )
    assert all(set(item.evidence_ids) <= evidence_ids for item in distillation.patterns)
    assert distillation.action_recommendations
    assert "Pattern 与反例" in paths[1].read_text(encoding="utf-8")
    assert (phase4_project.root / "knowledge-base" / "accounts" / f"{account_id}.md").is_file()
    assert all(
        (phase4_project.root / "knowledge-base" / "patterns" / f"{item.pattern_id}.json").is_file()
        for item in distillation.patterns
    )

    repeated = service.distill(account_id=account_id)
    assert repeated["already_generated"] is True
    assert repeated["distillation"]["distillation_id"] == distillation.distillation_id


def test_benchmark_comparison_produces_traceable_transfer_matrix(
    phase4_benchmark_project: ProjectLayout,
) -> None:
    target_id = stable_id("acc_", "douyin", "phase2-hotel")
    benchmark_id = stable_id("acc_", "douyin", "hotel-demo")
    result = BenchmarkComparisonService(phase4_benchmark_project).compare(
        target_account_id=target_id,
        benchmark_account_ids=[benchmark_id],
    )
    paths = [phase4_benchmark_project.root / Path(item) for item in result["outputs"]]
    comparison = BenchmarkComparison.model_validate(read_json(paths[0]))
    evidence = ArtifactEvidenceIndex.model_validate(read_json(paths[2]))
    evidence_ids = {item.evidence_id for item in evidence.items}

    assert comparison.transfer_matrix
    assert all(set(item.evidence_ids) <= evidence_ids for item in comparison.transfer_matrix)
    assert all(item.platform_alignment == "same" for item in comparison.transfer_matrix)
    assert all(item.verdict != "understand_only" for item in comparison.transfer_matrix)
    assert "对标迁移矩阵" in paths[1].read_text(encoding="utf-8")

    status = project_status(phase4_benchmark_project)
    assert status["artifacts"]["account_distillations"] == 2
    assert status["artifacts"]["benchmark_comparisons"] == 1
    assert status["last_comparison_at"] is not None

    validated = validate_project(phase4_benchmark_project)
    assert validated.error_count == 0
    assert validated.stats["phase4_artifacts"] == 5


def test_cross_platform_comparison_keeps_baselines_separate(
    phase4_cross_platform_project: ProjectLayout,
) -> None:
    target_id = stable_id("acc_", "douyin", "phase2-hotel")
    benchmark_id = stable_id("acc_", "youtube", "phase4-youtube")
    result = BenchmarkComparisonService(phase4_cross_platform_project).compare(
        target_account_id=target_id,
        benchmark_account_ids=[benchmark_id],
        dry_run=True,
    )
    comparison = BenchmarkComparison.model_validate(result["comparison"])

    assert comparison.transfer_matrix
    assert all(item.platform_alignment == "different" for item in comparison.transfer_matrix)
    assert all(
        item.verdict in {"understand_only", "do_not_migrate"} for item in comparison.transfer_matrix
    )
    assert any(
        warning.startswith("cross_platform_baselines_kept_separate")
        for warning in comparison.warnings
    )
