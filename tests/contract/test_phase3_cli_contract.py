from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from video_account_distiller.cli import app
from video_account_distiller.storage.project import ProjectLayout

runner = CliRunner()


def test_phase3_commands_expose_help() -> None:
    assert runner.invoke(app, ["import", "transcripts", "--help"]).exit_code == 0
    assert runner.invoke(app, ["analyze", "video", "--help"]).exit_code == 0


def test_transcript_import_dry_run_emits_json(
    phase2_project: ProjectLayout,
    fixtures_dir: Path,
) -> None:
    imported = runner.invoke(
        app,
        [
            "import",
            "transcripts",
            "--project",
            str(phase2_project.root),
            "--video",
            "p2-01",
            "--file",
            str(fixtures_dir / "phase3" / "hotel-video.srt"),
            "--dry-run",
            "--json",
        ],
    )
    import_payload = json.loads(imported.stdout)
    assert imported.exit_code == 0
    assert import_payload["quality"]["stats"]["accepted_rows"] == 4
    assert import_payload["receipt"] is None


def test_analysis_dry_run_emits_json(
    phase3_project: ProjectLayout,
    fixtures_dir: Path,
) -> None:
    analyzed = runner.invoke(
        app,
        [
            "analyze",
            "video",
            "--project",
            str(phase3_project.root),
            "--video",
            "p2-01",
            "--model-output",
            str(fixtures_dir / "phase3" / "model-output-retry.json"),
            "--max-attempts",
            "2",
            "--dry-run",
            "--json",
        ],
    )
    analysis_payload = json.loads(analyzed.stdout)
    assert analyzed.exit_code == 0
    assert analysis_payload["analysis"]["status"] == "complete"
    assert all(not (phase3_project.root / path).exists() for path in analysis_payload["outputs"])


def test_strict_model_uses_stable_unavailable_and_schema_errors(
    phase3_project: ProjectLayout,
    fixtures_dir: Path,
) -> None:
    base = [
        "analyze",
        "video",
        "--project",
        str(phase3_project.root),
        "--video",
        "p2-01",
        "--strict-model",
        "--dry-run",
        "--json",
    ]
    unavailable = runner.invoke(app, base)
    assert unavailable.exit_code == 13
    assert json.loads(unavailable.stdout)["error"]["code"] == "E_MODEL_UNAVAILABLE"

    invalid = runner.invoke(
        app,
        [
            *base[:-2],
            "--model-output",
            str(fixtures_dir / "phase3" / "model-output-invalid.json"),
            "--max-attempts",
            "2",
            "--dry-run",
            "--json",
        ],
    )
    assert invalid.exit_code == 14
    assert json.loads(invalid.stdout)["error"]["code"] == "E_MODEL_SCHEMA_INVALID"
