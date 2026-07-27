from __future__ import annotations

from pathlib import Path

from video_account_distiller.benchmarking import AccountBenchmarkProfileService
from video_account_distiller.distillation import (
    AccountDistillationService,
    BenchmarkComparisonService,
)
from video_account_distiller.models import (
    AccountBenchmarkProfile,
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
    raw_before = {
        path.relative_to(phase4_benchmark_project.root): path.read_bytes()
        for path in (phase4_benchmark_project.root / "raw").rglob("*")
        if path.is_file()
    }
    profile_result = AccountBenchmarkProfileService(phase4_benchmark_project).build(
        account_id=benchmark_id
    )
    profile = AccountBenchmarkProfile.model_validate(profile_result["profile"])

    assert profile.sampled_video_count == 6
    assert profile.interactions.metric_video_count == 6
    assert profile.interactions.totals["likes"] == 19142
    assert profile.interactions.totals["comments"] == 1128
    assert profile.interactions.totals["shares"] == 1845
    assert profile.interactions.totals["saves"] == 4058
    assert profile.comment_content.comment_count == 3
    assert profile.comment_content.comment_like_count_coverage == 1.0
    assert profile.comment_content.comment_like_total == 23
    assert profile.comment_content.comment_like_median == 8.0
    assert profile.comment_content.question_rate is not None
    assert all(len(item) <= 160 for item in profile.comment_content.top_questions)
    assert profile.content_interactions
    assert all("views" not in item.medians_per_video for item in profile.content_interactions)
    assert "views" not in profile.interactions.medians_per_video
    assert "view_metrics_unavailable_not_ranked" not in profile.warnings
    repeated_profile = AccountBenchmarkProfileService(phase4_benchmark_project).build(
        account_id=benchmark_id
    )
    assert repeated_profile["already_generated"] is True

    result = BenchmarkComparisonService(phase4_benchmark_project).compare(
        target_account_id=target_id,
        benchmark_account_ids=[benchmark_id],
    )
    paths = [phase4_benchmark_project.root / Path(item) for item in result["outputs"]]
    comparison = BenchmarkComparison.model_validate(read_json(paths[0]))
    evidence = ArtifactEvidenceIndex.model_validate(read_json(paths[2]))
    evidence_ids = {item.evidence_id for item in evidence.items}

    assert comparison.transfer_matrix
    assert len(comparison.profiles) == 2
    assert len(comparison.rankings) == 2
    assert [item.rank for item in comparison.rankings] == [1, 2]
    assert all(
        "views_not_used_platform_visibility_limit" in item.limitations
        for item in comparison.rankings
    )
    assert all(set(item.evidence_ids) <= evidence_ids for item in comparison.transfer_matrix)
    assert all(item.platform_alignment == "same" for item in comparison.transfer_matrix)
    assert all(item.verdict != "understand_only" for item in comparison.transfer_matrix)
    assert "对标迁移矩阵" in paths[1].read_text(encoding="utf-8")

    status = project_status(phase4_benchmark_project)
    assert status["artifacts"]["account_distillations"] == 2
    assert status["artifacts"]["benchmark_profiles"] == 2
    assert status["artifacts"]["benchmark_comparisons"] == 1
    assert status["last_comparison_at"] is not None

    validated = validate_project(phase4_benchmark_project)
    assert validated.error_count == 0
    assert validated.stats["phase4_artifacts"] == 5
    assert validated.stats["benchmark_profiles"] == 2
    assert raw_before == {
        path.relative_to(phase4_benchmark_project.root): path.read_bytes()
        for path in (phase4_benchmark_project.root / "raw").rglob("*")
        if path.is_file()
    }


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
    assert len(comparison.rankings) == 1
    assert comparison.rankings[0].account_id == target_id
    assert any(
        warning.startswith("cross_platform_accounts_excluded_from_interaction_ranking")
        for warning in comparison.warnings
    )
