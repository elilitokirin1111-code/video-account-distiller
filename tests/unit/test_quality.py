from __future__ import annotations

from video_account_distiller.models import DataQualityIssue
from video_account_distiller.quality import QualityReport


def test_quality_report_renders_machine_and_markdown() -> None:
    issue = DataQualityIssue(
        issue_id="dqi_test",
        run_id="run_test",
        severity="error",
        code="schema_invalid",
        entity="metrics",
        message="negative views",
        row_number=2,
    )
    report = QualityReport(
        run_id="run_test",
        entity="metrics",
        input_hashes=["a" * 64],
        stats={"accepted_rows": 0},
        issues=[issue],
    )
    assert report.error_count == 1
    assert report.as_dict()["schema_version"] == "0.1.0"
    markdown = report.as_markdown()
    assert "negative views" in markdown
    assert "run_test" in markdown
