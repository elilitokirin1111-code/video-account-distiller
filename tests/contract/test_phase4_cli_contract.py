from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from video_account_distiller.cli import app
from video_account_distiller.storage.project import ProjectLayout
from video_account_distiller.utils.ids import stable_id

runner = CliRunner()


def test_phase4_commands_expose_help() -> None:
    for command in (
        ["analyze", "comments", "--help"],
        ["account", "benchmark-profile", "--help"],
        ["distill", "--help"],
        ["compare", "--help"],
    ):
        assert runner.invoke(app, command).exit_code == 0


def test_comment_analysis_and_distillation_dry_runs_emit_json(
    phase4_project: ProjectLayout,
) -> None:
    account_id = stable_id("acc_", "douyin", "phase2-hotel")
    comments = runner.invoke(
        app,
        [
            "analyze",
            "comments",
            "--project",
            str(phase4_project.root),
            "--account",
            account_id,
            "--dry-run",
            "--json",
        ],
    )
    assert comments.exit_code == 0
    assert json.loads(comments.stdout)["analysis"]["comment_count"] == 18

    distilled = runner.invoke(
        app,
        [
            "distill",
            "--project",
            str(phase4_project.root),
            "--account",
            account_id,
            "--dry-run",
            "--json",
        ],
    )
    assert distilled.exit_code == 0
    assert json.loads(distilled.stdout)["distillation"]["patterns"]


def test_comparison_dry_run_emits_transfer_matrix(
    phase4_benchmark_project: ProjectLayout,
) -> None:
    target_id = stable_id("acc_", "douyin", "phase2-hotel")
    benchmark_id = stable_id("acc_", "douyin", "hotel-demo")
    compared = runner.invoke(
        app,
        [
            "compare",
            "--project",
            str(phase4_benchmark_project.root),
            "--target",
            target_id,
            "--benchmarks",
            benchmark_id,
            "--dry-run",
            "--json",
        ],
    )
    assert compared.exit_code == 0
    payload = json.loads(compared.stdout)
    assert payload["comparison"]["transfer_matrix"]
    assert len(payload["comparison"]["profiles"]) == 2
    assert len(payload["comparison"]["rankings"]) == 2

    profiled = runner.invoke(
        app,
        [
            "account",
            "benchmark-profile",
            "--project",
            str(phase4_benchmark_project.root),
            "--account",
            benchmark_id,
            "--dry-run",
            "--json",
        ],
    )
    assert profiled.exit_code == 0
    profile_payload = json.loads(profiled.stdout)
    assert profile_payload["profile"]["interactions"]["totals"]["likes"] > 0
    assert profile_payload["profile"]["comment_content"]["comment_count"] == 3


def test_comment_strict_mode_uses_stable_model_errors(
    phase4_project: ProjectLayout,
    fixtures_dir: Path,
) -> None:
    account_id = stable_id("acc_", "douyin", "phase2-hotel")
    base = [
        "analyze",
        "comments",
        "--project",
        str(phase4_project.root),
        "--account",
        account_id,
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
            *base[:-3],
            "--model-output",
            str(fixtures_dir / "phase4" / "comment-output-retry.json"),
            "--strict-model",
            "--dry-run",
            "--json",
        ],
    )
    assert invalid.exit_code == 14
    assert json.loads(invalid.stdout)["error"]["code"] == "E_MODEL_SCHEMA_INVALID"
