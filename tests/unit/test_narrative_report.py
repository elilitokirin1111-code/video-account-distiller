from __future__ import annotations

from pathlib import Path

import pytest

from video_account_distiller.knowledge.obsidian import ObsidianVaultExporter
from video_account_distiller.reports import NarrativeReportService
from video_account_distiller.storage.project import ProjectLayout
from video_account_distiller.utils.ids import stable_id
from video_account_distiller.utils.io import atomic_write_json, atomic_write_text, read_json


def test_narrative_report_is_deterministic_and_readable(
    phase4_project: ProjectLayout,
    tmp_path: Path,
) -> None:
    account_id = stable_id("acc_", "douyin", "phase2-hotel")
    service = NarrativeReportService(phase4_project)

    first = service.generate(account_id=account_id)
    assert first["already_generated"] is False
    assert len(first["outputs"]) == 2

    document_path = phase4_project.root / first["outputs"][0]
    content = document_path.read_text(encoding="utf-8")
    longform_path = phase4_project.root / first["outputs"][1]
    longform = longform_path.read_text(encoding="utf-8")
    run_id = (document_path.parent / "run_id.txt").read_text(encoding="utf-8")
    manifest = read_json(phase4_project.runs_dir / run_id / "manifest.json")

    assert manifest["status"] == "success"
    assert manifest["finished_at"] is not None
    assert manifest["processed_counts"] == {"accounts": 1, "videos": 30, "reports": 2}
    assert manifest["output_files"] == first["outputs"]

    # Always includes the report shell even without distillation artifacts.
    assert "账号深度运营分析报告" in content
    assert "自动生成" in content
    assert "账号深度学习长文" in longform
    assert "逐条视频学习笔记" in longform
    assert "从案例上升为方法论" in longform
    assert "未来 30 天的行动与复盘路径" in longform
    assert "事实 → 解释假设 → 反证 → 决策" in longform
    assert "竞争解释" in longform
    assert "停止条件" in longform
    assert "哪些结论现在不能说" in longform
    assert "视频标识为" in longform
    assert len(longform) > 5_000
    assert "高热度内容更常使用「未知」" not in longform
    assert "“未知”包装成开头策略" in longform
    combined = content + longform
    assert "Top 5" not in combined
    assert "Bottom 5" not in combined
    assert "robust_outlier_excluded" not in combined

    export = ObsidianVaultExporter(phase4_project).export_account(
        account_id=account_id,
        vault_path=str(tmp_path),
    )
    assert any(path.endswith("分析报告/00-运营学习报告.md") for path in export["files"])
    assert any(path.endswith("AI学习沉淀知识库/数据与证据附件.md") for path in export["files"])
    assert any(path.endswith("报告-账号深度学习长文.md") for path in export["files"])
    readme = tmp_path / export["human_dir"] / "README.md"
    assert "[[00-运营学习报告]]" in readme.read_text(encoding="utf-8")
    assert "[[报告-账号深度学习长文]]" in readme.read_text(encoding="utf-8")
    # Deterministic content addressing: same inputs yield the same artifact.
    again = service.generate(account_id=account_id)
    assert again["already_generated"] is True
    assert again["outputs"] == first["outputs"]


def test_narrative_report_renders_after_distillation_removed(
    phase4_project: ProjectLayout,
) -> None:
    account_id = stable_id("acc_", "douyin", "phase2-hotel")
    report_dir = phase4_project.root / "reports" / "accounts" / account_id
    for path in report_dir.glob("dst_*/distillation.json"):
        path.unlink()
    service = NarrativeReportService(phase4_project)
    result = service.generate(account_id=account_id)
    assert len(result["outputs"]) == 2
    document_path = phase4_project.root / result["outputs"][0]
    content = document_path.read_text(encoding="utf-8")
    longform_path = phase4_project.root / result["outputs"][1]
    longform = longform_path.read_text(encoding="utf-8")
    assert "账号深度运营分析报告" in content
    assert "账号深度学习长文" in longform
    assert "现有产物尚未形成可用的内容聚类" in longform


def test_narrative_report_closes_failed_run_manifest(
    phase4_project: ProjectLayout,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    account_id = stable_id("acc_", "douyin", "phase2-hotel")
    service = NarrativeReportService(phase4_project)

    def _fail_render(_: dict[str, object]) -> str:
        raise RuntimeError("forced narrative render failure")

    monkeypatch.setattr(service, "_render", _fail_render)

    with pytest.raises(RuntimeError, match="forced narrative render failure"):
        service.generate(account_id=account_id)

    state = phase4_project.load_state()
    assert state.last_run_id is not None
    manifest = read_json(phase4_project.runs_dir / state.last_run_id / "manifest.json")
    assert manifest["status"] == "failed"
    assert manifest["finished_at"] is not None
    assert manifest["output_files"] == []
    assert manifest["errors"] == ["RuntimeError: forced narrative render failure"]


def test_obsidian_human_reports_localize_machine_enums(
    phase4_project: ProjectLayout,
) -> None:
    exporter = ObsidianVaultExporter(phase4_project)
    payload = {
        "analysis_id": "gpt_test",
        "account_id": "acc_test",
        "generated_at": "2026-09-03T00:00:00Z",
        "provider": "cloud",
        "requested_model": "test-model",
        "template": "account_health",
        "reasoning_effort": "xhigh",
        "result": {
            "executive_summary": "status=degraded",
            "findings": [
                {
                    "title": "unknown",
                    "classification": "statistical_association",
                    "confidence": "low",
                    "statement": "classification=statistical_association",
                    "evidence_refs": ["context://account"],
                }
            ],
            "knowledge_cards": [
                {
                    "title": "candidate",
                    "claim": "status=degraded",
                    "knowledge_type": "hypothesis",
                    "maturity_level": 1,
                    "mechanism": "unknown",
                    "competing_explanations": ["insufficient"],
                    "falsifier": "unknown",
                    "decision": "recommendation",
                    "scope": ["public"],
                    "boundary_conditions": ["insufficient"],
                    "success_condition": "complete",
                    "stop_condition": "failed",
                    "target_metric": "engagement_rate_by_view",
                    "evidence_refs": ["context://account"],
                }
            ],
            "priority_actions": [],
            "experiments": [],
            "limitations": ["deep_model_unavailable_deterministic_fallback"],
        },
    }

    note = exporter._render_gpt_note(payload)
    frontmatter, body = note.split("---", 2)[1:]

    assert "provider: cloud" in frontmatter
    assert "template: account_health" in frontmatter
    assert "服务商：云端模型" in body
    assert "模板：账号体检" in body
    assert "推理强度：很高" in body
    assert "类型：统计关联" in body
    assert "置信度：低" in body
    assert "类型 / 成熟度：待验证假设 / 第 1 级" in body
    assert "目标指标：按播放量计算的互动率" in body
    assert "深度模型未成功启用" in body
    assert "statistical_association" not in body
    assert "status=degraded" not in body
    assert "Level 1" not in body


def test_obsidian_exports_latest_cloud_report_for_each_template(
    phase4_project: ProjectLayout,
    tmp_path: Path,
) -> None:
    account_id = stable_id("acc_", "douyin", "phase2-hotel")
    gpt_root = phase4_project.root / "analyses" / "gpt" / account_id
    templates = {
        "account_health": ("gpta_health", "06-云端账号体检.md", "云端账号体检报告"),
        "content_strategy": (
            "gpta_strategy",
            "07-云端内容策略.md",
            "云端内容策略报告",
        ),
        "growth_plan": ("gpta_growth", "08-云端增长计划.md", "云端增长计划报告"),
    }
    for offset, (template, (analysis_id, _filename, title)) in enumerate(templates.items()):
        analysis_dir = gpt_root / analysis_id
        payload = {
            "analysis_id": analysis_id,
            "account_id": account_id,
            "generated_at": f"2026-09-03T00:0{offset}:00Z",
            "provider": "cloud",
            "requested_model": "test-model",
            "template": template,
            "reasoning_effort": "high",
            "result": {"executive_summary": title},
        }
        atomic_write_json(analysis_dir / "analysis.json", payload)
        atomic_write_text(
            analysis_dir / "report.md",
            f"# 旧通用标题\n\n- 类型：recommendation\n- 置信度：high\n- {title}\n",
        )

    exporter = ObsidianVaultExporter(phase4_project)
    first = exporter.export_account(account_id=account_id, vault_path=str(tmp_path))
    human_dir = tmp_path / first["human_dir"]

    for _template, (_analysis_id, filename, title) in templates.items():
        report_path = human_dir / filename
        assert report_path.is_file()
        body = report_path.read_text(encoding="utf-8")
        assert f"# {title}" in body
        assert "类型：建议" in body
        assert "置信度：高" in body
    readme = (human_dir / "README.md").read_text(encoding="utf-8")
    assert "[[06-云端账号体检]]" in readme
    assert "[[07-云端内容策略]]" in readme
    assert "[[08-云端增长计划]]" in readme
    assert not (human_dir / "06-云端深度分析.md").exists()


def test_obsidian_distillation_human_report_localizes_warnings(
    phase4_project: ProjectLayout,
) -> None:
    exporter = ObsidianVaultExporter(phase4_project)
    payload = {
        "artifacts": {
            "account_distillation": {
                "data": {
                    "data_scope": {},
                    "positioning": {
                        "statement": "status=degraded",
                        "visual_and_audio_identity": ["status=degraded"],
                    },
                    "warnings": ["actionable_patterns_withheld_due_to_low_semantic_quality"],
                }
            }
        }
    }

    body = exporter._render_distillation_human(payload=payload, video_meta={})

    assert "状态=部分环节未完成（已保留有效结果）" in body
    assert "语义质量不足" in body
    assert "status=degraded" not in body
    assert "actionable_patterns_withheld_due_to_low_semantic_quality" not in body
