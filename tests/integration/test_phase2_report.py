from __future__ import annotations

from pathlib import Path
from typing import Any

from video_account_distiller.models import AccountHealthReport, EvidenceIndex, SampleManifest
from video_account_distiller.reports import ReportService
from video_account_distiller.status import project_status
from video_account_distiller.storage.project import ProjectLayout
from video_account_distiller.utils.ids import stable_id
from video_account_distiller.utils.io import read_json


def _collect_evidence_ids(value: Any) -> set[str]:
    if isinstance(value, dict):
        found = {
            str(item)
            for key, item in value.items()
            if key == "evidence_id" and isinstance(item, str)
        }
        evidence_ids = value.get("evidence_ids")
        if isinstance(evidence_ids, dict):
            found.update(str(item) for item in evidence_ids.values())
        elif isinstance(evidence_ids, list):
            found.update(str(item) for item in evidence_ids)
        for item in value.values():
            found.update(_collect_evidence_ids(item))
        return found
    if isinstance(value, list):
        list_found: set[str] = set()
        for item in value:
            list_found.update(_collect_evidence_ids(item))
        return list_found
    return set()


def test_account_health_report_outputs_are_traceable_and_idempotent(
    phase2_project: ProjectLayout,
) -> None:
    account_id = stable_id("acc_", "douyin", "phase2-hotel")
    raw_before = {
        path.relative_to(phase2_project.root): path.read_bytes()
        for path in (phase2_project.root / "raw").rglob("*")
        if path.is_file()
    }
    service = ReportService(phase2_project)
    result = service.generate_account_health(account_id=account_id, sample_size=15)
    output_paths = [phase2_project.root / Path(path) for path in result["outputs"]]
    assert all(path.is_file() for path in output_paths)

    report = AccountHealthReport.model_validate(read_json(output_paths[0]))
    evidence = EvidenceIndex.model_validate(read_json(output_paths[2]))
    sample = SampleManifest.model_validate(
        read_json(phase2_project.root / Path(report.sample_manifest_path))
    )
    evidence_ids = {item.evidence_id for item in evidence.items}
    referenced = _collect_evidence_ids(report.model_dump(mode="json"))
    referenced.update(
        evidence_id for finding in report.findings for evidence_id in finding.evidence_ids
    )
    referenced.update(item.evidence_id for item in sample.selected)
    assert referenced <= evidence_ids
    assert report.data_scope.population_size == 30
    assert report.statistics.content_pillars.counts == {"food": 10, "room": 10, "service": 10}
    assert "账号体检报告" in output_paths[1].read_text(encoding="utf-8")
    assert report.warnings

    repeated = service.generate_account_health(account_id=account_id, sample_size=15)
    assert repeated["already_generated"] is True
    assert repeated["report"]["run_id"] == report.run_id
    assert raw_before == {
        path.relative_to(phase2_project.root): path.read_bytes()
        for path in (phase2_project.root / "raw").rglob("*")
        if path.is_file()
    }

    state = phase2_project.load_state()
    assert state.last_sample_at is not None
    assert state.last_report_at is not None
    status = project_status(phase2_project)
    assert status["artifacts"] == {
        "sample_manifests": 1,
        "account_health_reports": 1,
        "video_analyses": 0,
        "comment_analyses": 0,
        "account_distillations": 0,
        "benchmark_comparisons": 0,
        "content_scores": 0,
        "predictions": 0,
        "publications": 0,
        "retros": 0,
        "pending_rule_changes": 0,
        "pending_rubric_changes": 0,
    }
