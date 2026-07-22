from __future__ import annotations

import json
from pathlib import Path

from video_account_distiller.comments import CommentAnalysisService
from video_account_distiller.models import ArtifactEvidenceIndex, CommentAnalysis
from video_account_distiller.status import project_status
from video_account_distiller.storage.project import ProjectLayout
from video_account_distiller.utils.ids import stable_id
from video_account_distiller.utils.io import read_json


def _latest_analysis(project: ProjectLayout, account_id: str) -> Path:
    return max((project.root / "analyses" / "comments" / account_id).glob("*/analysis.json"))


def test_comment_analysis_is_redacted_traceable_and_idempotent(
    phase4_project: ProjectLayout,
) -> None:
    account_id = stable_id("acc_", "douyin", "phase2-hotel")
    analysis_path = _latest_analysis(phase4_project, account_id)
    analysis = CommentAnalysis.model_validate(read_json(analysis_path))
    evidence = ArtifactEvidenceIndex.model_validate(
        read_json(phase4_project.root / analysis.evidence_index_path)
    )
    serialized = json.dumps(analysis.model_dump(mode="json"), ensure_ascii=False)
    report_text = (analysis_path.parent / "report.md").read_text(encoding="utf-8")

    assert analysis.comment_count == 18
    assert analysis.need_clusters
    assert "guest-11" not in serialized
    assert "13812345678" not in serialized
    assert "13812345678" not in report_text
    assert "[REDACTED_PHONE]" in serialized
    assert all(item.sources for item in evidence.items)
    evidence_ids = {item.evidence_id for item in evidence.items}
    assert {item.evidence_id for item in analysis.signals} <= evidence_ids
    assert {item.evidence_id for item in analysis.need_clusters} <= evidence_ids

    repeated = CommentAnalysisService(phase4_project).analyze(account_id=account_id)
    assert repeated["already_generated"] is True
    assert repeated["analysis"]["analysis_id"] == analysis.analysis_id

    status = project_status(phase4_project)
    assert status["artifacts"]["comment_analyses"] == 1
    assert status["last_comment_analysis_at"] is not None
