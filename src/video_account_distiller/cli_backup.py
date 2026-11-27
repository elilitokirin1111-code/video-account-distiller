"""Modular project backup and rollback command group."""

from __future__ import annotations

from pathlib import Path

import typer

from video_account_distiller.cli_runtime import emit, execute
from video_account_distiller.project_archive import (
    create_project_backup,
    restore_project_backup,
    run_backup_recovery_drill,
    verify_project_backup,
)
from video_account_distiller.storage.project import ProjectLayout

backup_app = typer.Typer(
    help="Create, verify, restore, and drill immutable project backups.",
    no_args_is_help=True,
)


@backup_app.command("create")
def backup_create_command(
    project: Path = typer.Option(..., "--project", help="Initialized project directory."),
    output: Path = typer.Option(..., "--output", help="New .zip archive outside the project."),
    json_output: bool = typer.Option(False, "--json", help="Emit one JSON object."),
) -> None:
    """Create a ZIP and SHA-256 file ledger without overwriting existing output."""

    layout = execute(lambda: ProjectLayout.open(project), json_output=json_output)
    manifest = execute(
        lambda: create_project_backup(layout, output),
        json_output=json_output,
    )
    emit(
        manifest.model_dump(mode="json"),
        json_output=json_output,
        human=f"Backup created: {output.expanduser().resolve()} ({manifest.file_count} files)",
    )


@backup_app.command("verify")
def backup_verify_command(
    archive: Path = typer.Option(..., "--archive", help="Backup .zip to verify."),
    json_output: bool = typer.Option(False, "--json", help="Emit one JSON object."),
) -> None:
    """Verify archive checksum, allowlisted members, sizes, and file hashes."""

    result = execute(lambda: verify_project_backup(archive), json_output=json_output)
    emit(
        result.model_dump(mode="json"),
        json_output=json_output,
        human=f"Backup verified: {result.file_count} files",
    )


@backup_app.command("restore")
def backup_restore_command(
    archive: Path = typer.Option(..., "--archive", help="Verified backup .zip."),
    destination: Path = typer.Option(
        ...,
        "--destination",
        help="New destination directory; existing paths are rejected.",
    ),
    json_output: bool = typer.Option(False, "--json", help="Emit one JSON object."),
) -> None:
    """Restore into a new directory and run read-only project validation."""

    result = execute(
        lambda: restore_project_backup(archive, destination),
        json_output=json_output,
    )
    emit(
        result.model_dump(mode="json"),
        json_output=json_output,
        human=(
            f"Backup restored to {result.destination}; validation errors={result.validation_errors}"
        ),
    )


@backup_app.command("drill")
def backup_drill_command(
    project: Path = typer.Option(..., "--project", help="Initialized project directory."),
    json_output: bool = typer.Option(False, "--json", help="Emit one JSON object."),
) -> None:
    """Exercise create, verify, restore, and cleanup in an isolated workspace."""

    layout = execute(lambda: ProjectLayout.open(project), json_output=json_output)
    result = execute(lambda: run_backup_recovery_drill(layout), json_output=json_output)
    emit(
        result.model_dump(mode="json"),
        json_output=json_output,
        human=("Backup recovery drill passed" if result.ok else "Backup recovery drill failed"),
    )
