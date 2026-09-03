from __future__ import annotations

import pytest

from video_account_distiller.distillation import AccountDistillationService
from video_account_distiller.distillation.pipeline import (
    _build_clusters,
    _EvidenceCollector,
    _is_unknown_label,
    _is_usable_content_type_proxy,
    _resolve_pattern_performance,
)
from video_account_distiller.features import VideoAnalysisService
from video_account_distiller.models import AccountDistillation, SingleVideoDistillation
from video_account_distiller.sampling.dataset import (
    AccountDataset,
    AccountVideoRecord,
    load_account_dataset,
)
from video_account_distiller.storage.project import ProjectLayout
from video_account_distiller.utils.ids import stable_id
from video_account_distiller.utils.io import atomic_write_json, atomic_write_text


def _write_video_creative_report(
    project: ProjectLayout,
    *,
    account_id: str,
    video_id: str,
) -> str:
    distillation_id = "svd_account_report_index"
    relative_directory = f"analyses/videos/{video_id}/{distillation_id}"
    payload = {
        "distillation_id": distillation_id,
        "analysis_version": "1.0.0",
        "video_id": video_id,
        "account_id": account_id,
        "generated_at": "2026-09-03T00:00:00Z",
        "run_id": "run_account_report_index",
        "status": "degraded",
        "text_analysis_id": "vta_account_report_index",
        "media_analysis_id": None,
        "craft_summary": {
            "analyzed_shots": 0,
            "ocr_observation_count": 0,
        },
        "topic": {
            "topic_statement": "客房清洁流程拆解",
            "topic_angle": "住客痛点切入",
            "target_audience": ["酒店住客"],
            "information_increment": "解释清洁检查步骤",
            "memory_point": "三步检查法",
            "topic_formula": "痛点+流程+结果",
            "selection_notes": [],
        },
        "expression": {
            "opening_form": "问题开场",
            "subtitle_style": "大字标题",
            "packaging_features": [],
            "audio_expression": "口播",
            "editing_style": "流程快剪",
            "expression_notes": [],
        },
        "craft": {
            "shot_scale_profile": "近景与特写",
            "camera_profile": "手持跟拍",
            "composition_profile": "主体居中",
            "lighting_profile": "自然光",
            "opening_technique": "问题字幕",
            "pacing": "分步骤推进",
            "craft_notes": [],
        },
        "copy_checklist": {
            "topic": ["从住客痛点切入"],
            "structure": ["三段式流程"],
            "craft": ["关键动作特写"],
            "expression": ["步骤字幕"],
            "avoid": [],
        },
        "deep_trace": None,
        "unknowns": ["缺少完整媒体语义"],
        "evidence_index_path": f"{relative_directory}/evidence-index.json",
        "warnings_path": f"{relative_directory}/warnings.json",
        "warnings": ["deep_model_unavailable_deterministic_fallback"],
    }
    value = SingleVideoDistillation.model_validate(payload)
    directory = project.root / relative_directory
    directory.mkdir(parents=True)
    report_path = directory / "report.md"
    atomic_write_json(directory / "distillation.json", value.model_dump(mode="json"))
    atomic_write_text(report_path, "# 单视频完整创作报告\n\n客房清洁流程拆解。\n")
    return project.relative(report_path)


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


def test_numeric_content_type_proxy_is_not_promoted_to_a_strategy_cluster(
    phase4_project: ProjectLayout,
) -> None:
    account_id = stable_id("acc_", "douyin", "phase2-hotel")
    source = load_account_dataset(phase4_project, account_id)
    dataset = AccountDataset(
        account=source.account,
        records=[
            AccountVideoRecord(
                video=record.video.model_copy(update={"content_type": "55"}),
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
    assert _is_usable_content_type_proxy("55") is False
    assert _is_usable_content_type_proxy("room") is True


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


def test_low_semantic_coverage_withholds_actions_and_does_not_claim_maturity(
    phase4_project: ProjectLayout,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    account_id = stable_id("acc_", "douyin", "phase2-hotel")
    source = load_account_dataset(phase4_project, account_id)
    high_scale_dataset = AccountDataset(
        account=source.account.model_copy(
            update={"follower_count_current": 200_000, "video_count_current": 150}
        ),
        records=source.records,
        input_hashes=source.input_hashes,
    )
    monkeypatch.setattr(
        "video_account_distiller.distillation.pipeline.load_account_dataset",
        lambda *_args, **_kwargs: high_scale_dataset,
    )

    response = AccountDistillationService(phase4_project).distill(account_id=account_id)
    result = AccountDistillation.model_validate(response["distillation"])
    report_relative = next(path for path in response["outputs"] if path.endswith("report.md"))
    report = (phase4_project.root / report_relative).read_text(encoding="utf-8")

    assert result.positioning.confidence == "low"
    assert result.data_scope["complete_semantic_coverage"] == 0
    assert result.data_scope["actionable_pattern_count"] == 0
    assert result.strengths == []
    assert result.copyable_factors == []
    assert "成熟账号" not in result.positioning.statement
    assert "成熟账号" not in report
    assert "无法据此判断运营成熟度" in result.positioning.statement
    assert "不等同于账号成熟度" in report


def test_degraded_semantic_analysis_keeps_positioning_low_and_patterns_non_actionable(
    phase3_project: ProjectLayout,
) -> None:
    account_id = stable_id("acc_", "douyin", "phase2-hotel")
    VideoAnalysisService(phase3_project).analyze(video_id=stable_id("vid_", "douyin", "p2-01"))

    response = AccountDistillationService(phase3_project).distill(
        account_id=account_id,
        dry_run=True,
    )
    result = AccountDistillation.model_validate(response["distillation"])

    assert result.data_scope["complete_video_analysis_count"] == 0
    assert result.data_scope["degraded_video_analysis_count"] == 1
    assert result.data_scope["complete_semantic_coverage"] == 0
    assert result.positioning.confidence == "low"
    assert result.data_scope["actionable_pattern_count"] == 0
    assert result.strengths == []
    assert result.copyable_factors == []
    assert "0/30 条完整语义分析、1 条降级分析" in result.positioning.statement


def test_account_report_indexes_available_per_video_creative_reports(
    phase4_project: ProjectLayout,
) -> None:
    account_id = stable_id("acc_", "douyin", "phase2-hotel")
    source = load_account_dataset(phase4_project, account_id)
    video = source.records[0].video
    single_report_relative = _write_video_creative_report(
        phase4_project,
        account_id=account_id,
        video_id=video.video_id,
    )

    response = AccountDistillationService(phase4_project).distill(account_id=account_id)
    result = AccountDistillation.model_validate(response["distillation"])
    report_relative = next(path for path in response["outputs"] if path.endswith("report.md"))
    report = (phase4_project.root / report_relative).read_text(encoding="utf-8")

    assert result.data_scope["video_creative_report_count"] == 1
    assert result.data_scope["degraded_video_creative_report_count"] == 1
    assert response["video_creative_reports"][0]["video_id"] == video.video_id
    assert "## 逐视频完整创作报告索引" in report
    assert video.title in report
    assert single_report_relative in report
    assert "完整 0，降级 1" in report
