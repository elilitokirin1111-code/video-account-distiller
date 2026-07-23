"""Run production-like acceptance against an installed wheel in a clean environment."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
import tempfile
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


class AcceptanceFailure(RuntimeError):
    pass


def _run_json(label: str, arguments: list[str], steps: list[dict[str, Any]]) -> dict[str, Any]:
    started = time.perf_counter()
    completed = subprocess.run(
        [sys.executable, "-m", "video_account_distiller", *arguments],
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    duration = round(time.perf_counter() - started, 3)
    step = {"name": label, "exit_code": completed.returncode, "duration_seconds": duration}
    steps.append(step)
    if completed.returncode != 0:
        raise AcceptanceFailure(
            f"{label} failed with exit {completed.returncode}: {completed.stderr.strip()}"
        )
    try:
        payload = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise AcceptanceFailure(f"{label} did not emit one JSON object") from exc
    if not isinstance(payload, dict):
        raise AcceptanceFailure(f"{label} emitted a non-object JSON root")
    return {str(key): value for key, value in payload.items()}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _assert_counts(status: dict[str, Any], *, media_expected: bool) -> None:
    normalized = status.get("normalized", {})
    expected = {"accounts": 1, "videos": 30, "metric_snapshots": 30, "comments": 18}
    for table, count in expected.items():
        if normalized.get(table) != count:
            raise AcceptanceFailure(
                f"normalized {table} expected {count}, received {normalized.get(table)}"
            )
    artifacts = status.get("artifacts", {})
    for key in ("sample_manifests", "account_health_reports", "comment_analyses"):
        if artifacts.get(key, 0) < 1:
            raise AcceptanceFailure(f"missing required acceptance artifact: {key}")
    if media_expected and artifacts.get("media_analyses", 0) < 1:
        raise AcceptanceFailure("real-media acceptance did not create a media analysis")


def run_acceptance(
    *,
    fixtures: Path,
    report_path: Path,
    media: Path | None,
    keep_workspace: bool,
) -> dict[str, Any]:
    fixtures = fixtures.expanduser().resolve()
    phase2 = fixtures / "phase2"
    phase4 = fixtures / "phase4"
    required = [
        phase2 / "accounts.csv",
        phase2 / "videos.csv",
        phase2 / "metrics.csv",
        phase4 / "comments.json",
    ]
    missing = [str(path) for path in required if not path.is_file()]
    if missing:
        raise AcceptanceFailure(f"missing acceptance fixtures: {missing}")
    if media is not None:
        media = media.expanduser().resolve()
        if not media.is_file():
            raise AcceptanceFailure(f"media file not found: {media}")

    temporary = Path(tempfile.mkdtemp(prefix="distiller-1.0-验收-"))
    project = temporary / "酒店账号验收项目"
    steps: list[dict[str, Any]] = []
    started_at = datetime.now(UTC)
    try:
        _run_json("doctor-installation", ["doctor", "--json"], steps)
        _run_json(
            "init", ["init", str(project), "--name", "1.0 production acceptance", "--json"], steps
        )
        homepage_plan = _run_json(
            "account-homepage-dry-run",
            [
                "account",
                "analyze",
                "--project",
                str(project),
                "--url",
                "https://www.douyin.com/user/acceptance",
                "--count",
                "10",
                "--dry-run",
                "--json",
            ],
            steps,
        )
        if (
            homepage_plan.get("dry_run") is not True
            or homepage_plan.get("provider_calls", {}).get("total_max") != 3
        ):
            raise AcceptanceFailure("account homepage dry-run contract was not available")
        for entity, source in (
            ("accounts", phase2 / "accounts.csv"),
            ("videos", phase2 / "videos.csv"),
            ("metrics", phase2 / "metrics.csv"),
            ("comments", phase4 / "comments.json"),
        ):
            _run_json(
                f"import-{entity}",
                [
                    "import",
                    entity,
                    "--project",
                    str(project),
                    "--file",
                    str(source),
                    "--platform",
                    "douyin",
                    "--json",
                ],
                steps,
            )
        _run_json("validate-imports", ["validate", "--project", str(project), "--json"], steps)
        _run_json("normalize", ["normalize", "--project", str(project), "--json"], steps)
        status = _run_json(
            "status-normalized", ["status", "--project", str(project), "--json"], steps
        )
        accounts = status.get("accounts", [])
        if not accounts:
            raise AcceptanceFailure("normalized status did not expose an account ID")
        account_id = str(accounts[0]["account_id"])

        _run_json(
            "metrics",
            ["metrics", "--project", str(project), "--account", account_id, "--json"],
            steps,
        )
        _run_json(
            "sample",
            [
                "sample",
                "--project",
                str(project),
                "--account",
                account_id,
                "--size",
                "30",
                "--json",
            ],
            steps,
        )
        _run_json(
            "report",
            [
                "report",
                "--project",
                str(project),
                "--account",
                account_id,
                "--sample-size",
                "30",
                "--json",
            ],
            steps,
        )
        _run_json(
            "analyze-comments",
            ["analyze", "comments", "--project", str(project), "--account", account_id, "--json"],
            steps,
        )
        _run_json(
            "distill",
            ["distill", "--project", str(project), "--account", account_id, "--json"],
            steps,
        )
        media_evidence: dict[str, Any] | None = None
        if media is not None:
            media_result = _run_json(
                "analyze-real-media",
                [
                    "analyze",
                    "media",
                    "--project",
                    str(project),
                    "--video",
                    "p2-01",
                    "--file",
                    str(media),
                    "--max-keyframes",
                    "2",
                    "--json",
                ],
                steps,
            )
            media_evidence = {
                "sha256": _sha256(media),
                "size_bytes": media.stat().st_size,
                "status": media_result.get("analysis", {}).get("status"),
            }
        final_validation = _run_json(
            "validate-final", ["validate", "--project", str(project), "--json"], steps
        )
        final_doctor = _run_json(
            "doctor-project", ["doctor", "--project", str(project), "--json"], steps
        )
        final_status = _run_json(
            "status-final", ["status", "--project", str(project), "--json"], steps
        )
        _assert_counts(final_status, media_expected=media is not None)
        if not final_validation.get("ok") or not final_doctor.get("ok"):
            raise AcceptanceFailure("final validation or doctor report was not ready")

        report = {
            "ok": True,
            "release": "1.0.0",
            "started_at": started_at.isoformat(),
            "finished_at": datetime.now(UTC).isoformat(),
            "python_version": final_doctor.get("python_version"),
            "operating_system": final_doctor.get("operating_system"),
            "capabilities": final_doctor.get("capabilities"),
            "steps": steps,
            "normalized": final_status.get("normalized"),
            "artifacts": final_status.get("artifacts"),
            "validation": {
                "errors": final_validation.get("quality", {}).get("stats", {}).get("errors"),
                "warnings": final_validation.get("quality", {}).get("stats", {}).get("warnings"),
            },
            "media": media_evidence,
            "workspace_retained": keep_workspace,
        }
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(
            json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        return report
    finally:
        if not keep_workspace:
            shutil.rmtree(temporary, ignore_errors=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fixtures", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--media", type=Path)
    parser.add_argument("--keep-workspace", action="store_true")
    args = parser.parse_args()
    try:
        report = run_acceptance(
            fixtures=args.fixtures,
            report_path=args.report.expanduser().resolve(),
            media=args.media,
            keep_workspace=args.keep_workspace,
        )
    except AcceptanceFailure as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=True))
        return 1
    print(json.dumps(report, ensure_ascii=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
