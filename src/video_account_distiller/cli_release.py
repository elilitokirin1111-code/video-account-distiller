"""Modular release-candidate audit command group."""

from __future__ import annotations

from pathlib import Path

import typer

from video_account_distiller.cli_runtime import emit, execute
from video_account_distiller.release import audit_release_candidate, write_checksum_manifest

release_app = typer.Typer(
    help="Audit release notices, versions, artifacts, and checksums.",
    no_args_is_help=True,
)


@release_app.command("audit")
def release_audit_command(
    repository: Path = typer.Option(
        Path("."),
        "--repository",
        help="Source repository root.",
    ),
    artifacts: Path | None = typer.Option(
        None,
        "--artifacts",
        help="Optional wheel/sdist/checksum directory.",
    ),
    json_output: bool = typer.Option(False, "--json", help="Emit one JSON object."),
) -> None:
    """Run a read-only, machine-readable release candidate audit."""

    report = execute(
        lambda: audit_release_candidate(repository, artifact_dir=artifacts),
        json_output=json_output,
    )
    emit(
        report.model_dump(mode="json"),
        json_output=json_output,
        human=(
            f"Release audit {'passed' if report.ok else 'failed'}: {len(report.issues)} issue(s)"
        ),
    )
    if not report.ok:
        raise typer.Exit(4)


@release_app.command("checksums")
def release_checksums_command(
    artifacts: Path = typer.Option(..., "--artifacts", help="Release artifact directory."),
    json_output: bool = typer.Option(False, "--json", help="Emit one JSON object."),
) -> None:
    """Create SHA256SUMS.txt once; existing manifests are never overwritten."""

    path = execute(lambda: write_checksum_manifest(artifacts), json_output=json_output)
    payload = {"ok": True, "checksum_manifest": str(path)}
    emit(payload, json_output=json_output, human=f"Checksum manifest created: {path}")
