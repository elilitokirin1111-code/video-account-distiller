from __future__ import annotations

from pathlib import Path

from video_account_distiller.knowledge.obsidian import ObsidianVaultExporter
from video_account_distiller.reports import NarrativeReportService
from video_account_distiller.storage.project import ProjectLayout
from video_account_distiller.utils.ids import stable_id


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
