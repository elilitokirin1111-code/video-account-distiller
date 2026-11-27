"""Modular release-candidate audit command group."""

from __future__ import annotations

from pathlib import Path

import typer

from video_account_distiller.cli_runtime import emit, execute
from video_account_distiller.models.release import PublicBetaIncidentSeverity
from video_account_distiller.project_migration import (
    apply_project_migration,
    plan_project_migration,
)
from video_account_distiller.release import (
    PublicBetaService,
    audit_release_candidate,
    write_checksum_manifest,
)
from video_account_distiller.storage.project import ProjectLayout
from video_account_distiller.version import PACKAGE_VERSION

release_app = typer.Typer(
    help="Audit release notices, versions, artifacts, and checksums.",
    no_args_is_help=True,
)
migration_app = typer.Typer(
    help="Preview and apply backup-first project schema migrations.",
    no_args_is_help=True,
)
beta_app = typer.Typer(
    help="Record public-beta evidence and enforce release-freeze gates.",
    no_args_is_help=True,
)
release_app.add_typer(migration_app, name="migrate")
release_app.add_typer(beta_app, name="beta")


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
    public_beta_evidence: Path | None = typer.Option(
        None,
        "--public-beta-evidence",
        help="Optional frozen campaign directory, freeze.json, or evidence ZIP.",
    ),
    require_public_beta_freeze: bool = typer.Option(
        False,
        "--require-public-beta-freeze",
        help="Fail unless verified public-beta evidence is supplied.",
    ),
    json_output: bool = typer.Option(False, "--json", help="Emit one JSON object."),
) -> None:
    """Run a read-only, machine-readable release candidate audit."""

    report = execute(
        lambda: audit_release_candidate(
            repository,
            artifact_dir=artifacts,
            public_beta_evidence=public_beta_evidence,
            require_public_beta_freeze=require_public_beta_freeze,
        ),
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


@migration_app.command("preview")
def migration_preview_command(
    project_dir: Path = typer.Option(..., "--project", help="Initialized project directory."),
    json_output: bool = typer.Option(False, "--json", help="Emit one JSON object."),
) -> None:
    """Inspect the project schema and planned writes without changing files."""

    plan = execute(
        lambda: plan_project_migration(ProjectLayout.open(project_dir)),
        json_output=json_output,
    )
    emit(
        plan.model_dump(mode="json"),
        json_output=json_output,
        human=(
            f"Migration required: {plan.migration_required}; supported: {plan.supported}; "
            f"{plan.source_schema_version} -> {plan.target_schema_version}"
        ),
    )


@migration_app.command("apply")
def migration_apply_command(
    project_dir: Path = typer.Option(..., "--project", help="Initialized project directory."),
    backup: Path = typer.Option(
        ...,
        "--backup",
        help="New pre-migration ZIP path outside the project.",
    ),
    confirm: bool = typer.Option(
        False,
        "--confirm-migration",
        help="Confirm the reviewed backup-first migration plan.",
    ),
    json_output: bool = typer.Option(False, "--json", help="Emit one JSON object."),
) -> None:
    """Create a verified backup, migrate state, validate, and write a receipt."""

    result = execute(
        lambda: apply_project_migration(
            ProjectLayout.open(project_dir),
            backup_path=backup,
            confirm=confirm,
        ),
        json_output=json_output,
    )
    emit(
        result.model_dump(mode="json"),
        json_output=json_output,
        human=(
            f"Migration {'applied' if result.applied else 'not required'}: "
            f"{result.source_schema_version} -> {result.target_schema_version}"
        ),
    )


@beta_app.command("init")
def beta_init_command(
    evidence: Path = typer.Option(..., "--evidence", help="Public-beta evidence root."),
    campaign_id: str = typer.Option(..., "--campaign", help="Stable campaign identifier."),
    target_version: str = typer.Option(
        PACKAGE_VERSION,
        "--target-version",
        help="Package version being qualified.",
    ),
    min_days: int = typer.Option(7, "--min-days", min=7, max=14),
    min_machine_profiles: int = typer.Option(
        2,
        "--min-machine-profiles",
        min=2,
        max=20,
    ),
    min_account_labels: int = typer.Option(
        3,
        "--min-account-labels",
        min=2,
        max=100,
    ),
    json_output: bool = typer.Option(False, "--json", help="Emit one JSON object."),
) -> None:
    """Create an immutable 7-14 day public-beta campaign configuration."""

    result = execute(
        lambda: PublicBetaService(evidence).initialize(
            campaign_id=campaign_id,
            target_version=target_version,
            min_calendar_days=min_days,
            min_distinct_observation_days=min_days,
            min_machine_profiles=min_machine_profiles,
            min_account_labels=min_account_labels,
        ),
        json_output=json_output,
    )
    emit(
        result,
        json_output=json_output,
        human=(
            f"Public-beta campaign {campaign_id} "
            f"{'already exists' if result['already_initialized'] else 'initialized'}"
        ),
    )


@beta_app.command("observe")
def beta_observe_command(
    evidence: Path = typer.Option(..., "--evidence", help="Public-beta evidence root."),
    campaign_id: str = typer.Option(..., "--campaign", help="Campaign identifier."),
    project_dir: Path = typer.Option(..., "--project", help="Initialized project directory."),
    machine_label: str = typer.Option(
        ...,
        "--machine-label",
        help="Non-secret operator label; only a hash is persisted.",
    ),
    account_labels: list[str] = typer.Option(
        ...,
        "--account-label",
        help="Repeat for each account exercised; only hashes are persisted.",
    ),
    notes: str = typer.Option("", "--notes", help="Short non-secret observation note."),
    json_output: bool = typer.Option(False, "--json", help="Emit one JSON object."),
) -> None:
    """Run isolated drills and append one immutable daily observation."""

    result = execute(
        lambda: PublicBetaService(evidence).observe(
            campaign_id=campaign_id,
            project=ProjectLayout.open(project_dir),
            machine_label=machine_label,
            account_labels=account_labels,
            notes=notes,
        ),
        json_output=json_output,
    )
    observation = result["observation"]
    emit(
        result,
        json_output=json_output,
        human=(
            f"Public-beta observation {observation['observation_id']}: "
            f"{'passed' if observation['ok'] else 'failed'}"
        ),
    )


@beta_app.command("incident")
def beta_incident_command(
    evidence: Path = typer.Option(..., "--evidence", help="Public-beta evidence root."),
    campaign_id: str = typer.Option(..., "--campaign", help="Campaign identifier."),
    severity: PublicBetaIncidentSeverity = typer.Option(..., "--severity"),
    summary: str = typer.Option(..., "--summary", help="Concise non-secret incident summary."),
    json_output: bool = typer.Option(False, "--json", help="Emit one JSON object."),
) -> None:
    """Append an immutable incident; high/critical incidents block freezing."""

    result = execute(
        lambda: PublicBetaService(evidence).record_incident(
            campaign_id=campaign_id,
            severity=severity,
            summary=summary,
        ),
        json_output=json_output,
    )
    emit(
        result,
        json_output=json_output,
        human=f"Incident recorded: {result['incident']['severity']}",
    )


@beta_app.command("status")
def beta_status_command(
    evidence: Path = typer.Option(..., "--evidence", help="Public-beta evidence root."),
    campaign_id: str = typer.Option(..., "--campaign", help="Campaign identifier."),
    json_output: bool = typer.Option(False, "--json", help="Emit one JSON object."),
) -> None:
    """Evaluate duration, compatibility, account, incident, and drill gates."""

    status = execute(
        lambda: PublicBetaService(evidence).status(campaign_id),
        json_output=json_output,
    )
    emit(
        status.model_dump(mode="json"),
        json_output=json_output,
        human=(
            f"Freeze eligible: {status.eligible_for_freeze}; "
            f"blockers: {', '.join(status.blockers) or 'none'}"
        ),
    )


@beta_app.command("freeze")
def beta_freeze_command(
    evidence: Path = typer.Option(..., "--evidence", help="Public-beta evidence root."),
    campaign_id: str = typer.Option(..., "--campaign", help="Campaign identifier."),
    confirm: bool = typer.Option(
        False,
        "--confirm-freeze",
        help="Confirm creation of the immutable freeze record.",
    ),
    json_output: bool = typer.Option(False, "--json", help="Emit one JSON object."),
) -> None:
    """Freeze a target version only after every public-beta gate passes."""

    result = execute(
        lambda: PublicBetaService(evidence).freeze(campaign_id, confirm=confirm),
        json_output=json_output,
    )
    emit(
        result,
        json_output=json_output,
        human=f"Release freeze evidence: {result['freeze_path']}",
    )


@beta_app.command("verify")
def beta_verify_command(
    evidence: Path = typer.Option(..., "--evidence", help="Public-beta evidence root."),
    campaign_id: str = typer.Option(..., "--campaign", help="Campaign identifier."),
    json_output: bool = typer.Option(False, "--json", help="Emit one JSON object."),
) -> None:
    """Recompute frozen evidence and detect any post-freeze change or mismatch."""

    verification = execute(
        lambda: PublicBetaService(evidence).verify_freeze(campaign_id),
        json_output=json_output,
    )
    emit(
        verification.model_dump(mode="json"),
        json_output=json_output,
        human=(
            f"Public-beta freeze verification "
            f"{'passed' if verification.ok else 'failed'}: "
            f"{len(verification.issues)} issue(s)"
        ),
    )
    if not verification.ok:
        raise typer.Exit(4)


@beta_app.command("bundle")
def beta_bundle_command(
    evidence: Path = typer.Option(..., "--evidence", help="Public-beta evidence root."),
    campaign_id: str = typer.Option(..., "--campaign", help="Campaign identifier."),
    output: Path = typer.Option(..., "--output", help="New evidence ZIP path."),
    json_output: bool = typer.Option(False, "--json", help="Emit one JSON object."),
) -> None:
    """Create a deterministic checksummable ZIP from verified frozen evidence."""

    result = execute(
        lambda: PublicBetaService(evidence).bundle(campaign_id, output=output),
        json_output=json_output,
    )
    emit(
        result,
        json_output=json_output,
        human=f"Public-beta evidence bundle: {result['bundle_path']}",
    )
