from __future__ import annotations

from video_account_distiller.knowledge import KnowledgeExportService
from video_account_distiller.models import Account, Comment
from video_account_distiller.reports import ReportService
from video_account_distiller.storage.parquet import read_models
from video_account_distiller.storage.project import ProjectLayout
from video_account_distiller.utils.ids import stable_id


def test_curated_export_is_redacted_bounded_and_idempotent(
    phase4_project: ProjectLayout,
) -> None:
    account_id = stable_id("acc_", "douyin", "phase2-hotel")
    ReportService(phase4_project).generate_account_health(account_id=account_id)
    service = KnowledgeExportService(phase4_project)

    first = service.export_account(account_id=account_id)
    document_path = phase4_project.root / first["document_path"]
    evidence_document_path = phase4_project.root / first["evidence_document_path"]
    content = document_path.read_text(encoding="utf-8")
    evidence = evidence_document_path.read_text(encoding="utf-8")

    assert first["already_exported"] is False
    assert "contains_raw_comments: false" in content
    assert "privacy_classification: curated_analysis" in content
    assert "账号运营学习报告" in content
    assert "数据与证据附件" in content
    assert "Evidence Backlinks" in content
    assert "Data Availability" not in content
    assert "数据与证据附件" in evidence
    assert "Data Availability" in evidence
    assert first["manifest"]["evidence_document_path"] == first["evidence_document_path"]
    assert all(
        not source.startswith(("raw/", "normalized/"))
        for source in first["manifest"]["source_paths"]
    )

    account = next(
        item
        for item in read_models(phase4_project.normalized_dir / "accounts.parquet", Account)
        if item.account_id == account_id
    )
    for value in (account.handle, account.display_name, account.bio, account.profile_url):
        if value:
            assert value not in content
            assert value not in evidence
    comment = next(
        item
        for item in read_models(phase4_project.normalized_dir / "comments.parquet", Comment)
        if item.text
    )
    assert comment.text not in content
    assert comment.text not in evidence

    before = document_path.stat().st_mtime_ns
    second = service.export_account(account_id=account_id)
    assert second["already_exported"] is True
    assert document_path.stat().st_mtime_ns == before
    assert second["manifest"]["payload_hash"] == first["manifest"]["payload_hash"]


def test_curated_export_dry_run_does_not_write(
    normalized_project: ProjectLayout,
) -> None:
    account_id = stable_id("acc_", "douyin", "hotel-demo")
    service = KnowledgeExportService(normalized_project)

    result = service.export_account(account_id=account_id, dry_run=True)

    assert result["dry_run"] is True
    assert not (normalized_project.root / result["document_path"]).exists()
    assert not (normalized_project.root / result["evidence_document_path"]).exists()
    assert not service.manifest_path.exists()
