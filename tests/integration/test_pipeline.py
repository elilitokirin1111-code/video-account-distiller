from __future__ import annotations

import json
from pathlib import Path

import pyarrow.parquet as pq
from typer.testing import CliRunner

from video_account_distiller.cli import app
from video_account_distiller.storage.duckdb_store import DuckDBStore
from video_account_distiller.utils.hashing import sha256_file
from video_account_distiller.utils.ids import stable_id

runner = CliRunner()


def invoke_json(arguments: list[str]) -> tuple[int, dict[str, object]]:
    result = runner.invoke(app, arguments)
    return result.exit_code, json.loads(result.stdout)


def test_complete_offline_pipeline_is_idempotent(tmp_path: Path, fixtures_dir: Path) -> None:
    project = tmp_path / "project"
    normal = fixtures_dir / "normal"
    exit_code, initialized = invoke_json(["init", str(project), "--json"])
    assert exit_code == 0 and initialized["ok"] is True

    for entity, filename in (
        ("accounts", "accounts.csv"),
        ("videos", "videos.csv"),
        ("metrics", "metrics.csv"),
        ("comments", "comments.json"),
    ):
        exit_code, payload = invoke_json(
            [
                "import",
                entity,
                "--project",
                str(project),
                "--file",
                str(normal / filename),
                "--platform",
                "douyin",
                "--json",
            ]
        )
        assert exit_code == 0 and payload["ok"] is True

    exit_code, duplicate = invoke_json(
        [
            "import",
            "accounts",
            "--project",
            str(project),
            "--file",
            str(normal / "accounts.csv"),
            "--platform",
            "douyin",
            "--json",
        ]
    )
    assert exit_code == 0 and duplicate["already_imported"] is True

    assert invoke_json(["validate", "--project", str(project), "--json"])[0] == 0
    exit_code, normalized = invoke_json(["normalize", "--project", str(project), "--json"])
    assert exit_code == 0
    assert normalized["counts"] == {
        "accounts": 1,
        "videos": 6,
        "metrics": 6,
        "comments": 3,
        "transcripts": 0,
    }

    account_id = stable_id("acc_", "douyin", "hotel-demo")
    exit_code, metrics = invoke_json(
        [
            "metrics",
            "--project",
            str(project),
            "--account",
            account_id,
            "--json",
        ]
    )
    assert exit_code == 0
    assert metrics["bands"] == {"S": 1, "A": 1, "B": 2, "C": 1, "D": 1}

    exit_code, status = invoke_json(["status", "--project", str(project), "--json"])
    assert exit_code == 0
    assert status["imports"]["count"] == 4  # type: ignore[index]
    assert status["normalized"]["derived_metrics"] == 6  # type: ignore[index]

    raw_hash = sha256_file(normal / "accounts.csv")
    raw_copy = project / "raw" / "imports" / "accounts" / f"{raw_hash}.csv"
    assert sha256_file(raw_copy) == raw_hash
    state_before = (project / ".distiller-state.json").read_bytes()
    invoke_json(["normalize", "--project", str(project), "--dry-run", "--json"])
    assert (project / ".distiller-state.json").read_bytes() == state_before

    derived = pq.read_table(project / "normalized" / "derived_metrics.parquet").to_pylist()
    assert len(derived) == 6
    missing = next(
        row for row in derived if row["video_id"] == stable_id("vid_", "douyin", "v-bottom")
    )
    assert missing["share_rate_by_view"] is None
    assert missing["save_rate_by_view"] is None

    with DuckDBStore(project / "normalized") as store:
        assert store.count("videos") == 6
        assert store.count("derived_metrics") == 6
