from __future__ import annotations

from video_account_distiller.knowledge import KnowledgeExportService
from video_account_distiller.reports import ReportService
from video_account_distiller.storage.project import ProjectLayout
from video_account_distiller.utils.ids import stable_id
from video_account_distiller.utils.io import atomic_write_json, read_json
from video_account_distiller.validation import validate_project


def test_project_validation_accepts_curated_openkb_export(
    phase4_project: ProjectLayout,
) -> None:
    account_id = stable_id("acc_", "douyin", "phase2-hotel")
    ReportService(phase4_project).generate_account_health(account_id=account_id)
    KnowledgeExportService(phase4_project).export_account(account_id=account_id)

    report = validate_project(phase4_project, persist=False)

    assert report.stats["openkb_artifacts"] == 2
    assert not [issue for issue in report.issues if issue.entity == "openkb_knowledge"]


def test_project_validation_rejects_unsafe_openkb_backlink(
    phase4_project: ProjectLayout,
) -> None:
    account_id = stable_id("acc_", "douyin", "phase2-hotel")
    ReportService(phase4_project).generate_account_health(account_id=account_id)
    service = KnowledgeExportService(phase4_project)
    service.export_account(account_id=account_id)
    payload = read_json(service.manifest_path)
    payload["documents"][f"account:{account_id}"]["source_paths"] = [
        "raw/account-collections/private.json"
    ]
    atomic_write_json(service.manifest_path, payload)

    report = validate_project(phase4_project, persist=False)

    issues = [issue for issue in report.issues if issue.entity == "openkb_knowledge"]
    assert len(issues) == 1
    assert issues[0].code == "knowledge_artifact_invalid"
    assert "unsafe evidence backlink" in issues[0].message
