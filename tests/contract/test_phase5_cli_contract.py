from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from video_account_distiller.cli import app
from video_account_distiller.storage.project import ProjectLayout
from video_account_distiller.utils.ids import stable_id

runner = CliRunner()


def test_phase5_commands_expose_help() -> None:
    for command in ("score", "predict", "publish", "retro"):
        result = runner.invoke(app, [command, "--help"])
        assert result.exit_code == 0, command


def test_score_and_prediction_dry_runs_emit_json_without_writing(
    phase5_project: ProjectLayout,
    fixtures_dir: Path,
) -> None:
    account_id = stable_id("acc_", "douyin", "phase2-hotel")
    script = fixtures_dir / "phase5" / "hotel-script.md"
    common = [
        "--project",
        str(phase5_project.root),
        "--account",
        account_id,
        "--script",
        str(script),
        "--target-pillar",
        "room",
        "--dry-run",
        "--json",
    ]
    scored = runner.invoke(app, ["score", *common])
    assert scored.exit_code == 0
    assert len(json.loads(scored.stdout)["score"]["dimension_scores"]) == 9

    predicted = runner.invoke(app, ["predict", *common])
    assert predicted.exit_code == 0
    payload = json.loads(predicted.stdout)
    assert payload["prediction"]["immutable"] is True
    assert not list((phase5_project.root / "predictions").glob("*/prediction.json"))
    assert not list((phase5_project.root / "candidates").glob("*/candidate.json"))


def test_publish_missing_prediction_uses_stable_error(
    phase5_project: ProjectLayout,
) -> None:
    result = runner.invoke(
        app,
        [
            "publish",
            "--project",
            str(phase5_project.root),
            "--prediction",
            "pred_missing",
            "--video",
            "vid_missing",
            "--json",
        ],
    )
    assert result.exit_code == 2
    assert json.loads(result.stdout)["error"]["code"] == "E_INPUT_MISSING"
