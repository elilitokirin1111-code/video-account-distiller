from __future__ import annotations

from video_account_distiller.reports import NarrativeReportService
from video_account_distiller.storage.project import ProjectLayout
from video_account_distiller.utils.ids import stable_id


def test_narrative_report_is_deterministic_and_readable(phase4_project: ProjectLayout) -> None:
    account_id = stable_id("acc_", "douyin", "phase2-hotel")
    service = NarrativeReportService(phase4_project)

    first = service.generate(account_id=account_id)
    assert first["already_generated"] is False
    assert first["outputs"]

    document_path = phase4_project.root / first["outputs"][0]
    content = document_path.read_text(encoding="utf-8")

    # Always includes the report shell even without distillation artifacts.
    assert "账号深度运营分析报告" in content
    assert "自动生成" in content
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
    document_path = phase4_project.root / result["outputs"][0]
    content = document_path.read_text(encoding="utf-8")
    assert "账号深度运营分析报告" in content
