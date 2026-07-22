"""Typer command-line interface for the offline data and report workflow."""

from __future__ import annotations

import json
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any, TypeVar

import typer

from video_account_distiller.comments import CommentAnalysisService
from video_account_distiller.distillation import (
    AccountDistillationService,
    BenchmarkComparisonService,
)
from video_account_distiller.errors import EXIT_CODES, DistillerError, ErrorCode
from video_account_distiller.features import VideoAnalysisService
from video_account_distiller.ingestion import ImportService
from video_account_distiller.metrics import MetricsService
from video_account_distiller.models import Platform
from video_account_distiller.normalization import NormalizationService
from video_account_distiller.reports import ReportService
from video_account_distiller.sampling import SamplingService
from video_account_distiller.status import project_status
from video_account_distiller.storage.project import ProjectLayout
from video_account_distiller.transcripts import TranscriptImportService
from video_account_distiller.validation import validate_project

app = typer.Typer(
    name="distiller",
    help="Offline-first video account data distillation toolkit.",
    no_args_is_help=True,
)
import_app = typer.Typer(help="Import user-provided offline exports.", no_args_is_help=True)
analyze_app = typer.Typer(
    help="Run blind, schema-validated content analysis.", no_args_is_help=True
)
app.add_typer(import_app, name="import")
app.add_typer(analyze_app, name="analyze")

T = TypeVar("T")


def _emit(payload: Any, *, json_output: bool, human: str | None = None) -> None:
    if json_output:
        typer.echo(json.dumps(payload, ensure_ascii=False, default=str))
    else:
        typer.echo(human or json.dumps(payload, ensure_ascii=False, indent=2, default=str))


def _execute(operation: Callable[[], T], *, json_output: bool) -> T:
    try:
        return operation()
    except DistillerError as exc:
        if json_output:
            typer.echo(json.dumps(exc.as_dict(), ensure_ascii=False), file=sys.stdout)
        else:
            typer.echo(f"{exc.code.value}: {exc.message}", err=True)
        raise typer.Exit(exc.exit_code) from exc
    except Exception as exc:
        wrapped = DistillerError(
            ErrorCode.INTERNAL,
            "Unexpected internal error",
            details={"type": type(exc).__name__, "reason": str(exc)},
        )
        if json_output:
            typer.echo(json.dumps(wrapped.as_dict(), ensure_ascii=False), file=sys.stdout)
        else:
            typer.echo(f"{wrapped.code.value}: {wrapped.message}: {exc}", err=True)
        raise typer.Exit(wrapped.exit_code) from exc


@app.command("init")
def init_command(
    project_dir: Path = typer.Argument(..., help="Directory to initialize."),
    project_name: str | None = typer.Option(None, "--name", help="Project display name."),
    json_output: bool = typer.Option(False, "--json", help="Emit one JSON object."),
    dry_run: bool = typer.Option(False, "--dry-run", help="Describe changes without writing."),
) -> None:
    """Initialize an idempotent local research project."""

    if dry_run:
        root = project_dir.expanduser().resolve()
        payload = {
            "ok": True,
            "dry_run": True,
            "project": str(root),
            "would_create": ["distiller.yaml", ".distiller-state.json", "raw/", "normalized/"],
        }
        _emit(payload, json_output=json_output, human=f"Would initialize {root}")
        return

    layout, already_initialized = _execute(
        lambda: ProjectLayout.initialize(project_dir, project_name=project_name),
        json_output=json_output,
    )
    payload = {
        "ok": True,
        "project": str(layout.root),
        "already_initialized": already_initialized,
    }
    _emit(
        payload,
        json_output=json_output,
        human=("Project already initialized" if already_initialized else "Project initialized")
        + f": {layout.root}",
    )


def _import_command(
    *,
    entity: str,
    project: Path,
    file: Path,
    platform: Platform,
    mapping: Path | None,
    json_output: bool,
    dry_run: bool,
) -> None:
    def operation() -> tuple[Any, Any, bool]:
        layout = ProjectLayout.open(project)
        return ImportService(layout).import_file(
            entity=entity,  # type: ignore[arg-type]
            source=file,
            platform=platform,
            mapping_path=mapping,
            dry_run=dry_run,
        )

    receipt, report, already_imported = _execute(operation, json_output=json_output)
    fatal_quality_failure = (
        report.stats["input_rows"] > 0
        and report.stats["accepted_rows"] == 0
        and report.error_count > 0
    )
    payload = {
        "ok": not fatal_quality_failure,
        "dry_run": dry_run,
        "already_imported": already_imported,
        "receipt": receipt.model_dump(mode="json") if receipt else None,
        "quality": report.as_dict(),
    }
    _emit(
        payload,
        json_output=json_output,
        human=(
            f"{entity}: {report.stats['accepted_rows']} accepted, "
            f"{report.stats['rejected_rows']} rejected, "
            f"{report.stats['duplicate_rows']} duplicates"
        ),
    )
    if fatal_quality_failure:
        raise typer.Exit(EXIT_CODES[ErrorCode.SCHEMA_INVALID])


@import_app.command("accounts")
def import_accounts(
    project: Path = typer.Option(..., "--project"),
    file: Path = typer.Option(..., "--file"),
    platform: Platform = typer.Option(..., "--platform"),
    mapping: Path | None = typer.Option(None, "--mapping"),
    json_output: bool = typer.Option(False, "--json"),
    dry_run: bool = typer.Option(False, "--dry-run"),
) -> None:
    """Import account exports."""

    _import_command(
        entity="accounts",
        project=project,
        file=file,
        platform=platform,
        mapping=mapping,
        json_output=json_output,
        dry_run=dry_run,
    )


@import_app.command("videos")
def import_videos(
    project: Path = typer.Option(..., "--project"),
    file: Path = typer.Option(..., "--file"),
    platform: Platform = typer.Option(..., "--platform"),
    mapping: Path | None = typer.Option(None, "--mapping"),
    json_output: bool = typer.Option(False, "--json"),
    dry_run: bool = typer.Option(False, "--dry-run"),
) -> None:
    """Import video exports."""

    _import_command(
        entity="videos",
        project=project,
        file=file,
        platform=platform,
        mapping=mapping,
        json_output=json_output,
        dry_run=dry_run,
    )


@import_app.command("metrics")
def import_metrics(
    project: Path = typer.Option(..., "--project"),
    file: Path = typer.Option(..., "--file"),
    platform: Platform = typer.Option(..., "--platform"),
    mapping: Path | None = typer.Option(None, "--mapping"),
    json_output: bool = typer.Option(False, "--json"),
    dry_run: bool = typer.Option(False, "--dry-run"),
) -> None:
    """Import metric snapshots."""

    _import_command(
        entity="metrics",
        project=project,
        file=file,
        platform=platform,
        mapping=mapping,
        json_output=json_output,
        dry_run=dry_run,
    )


@import_app.command("comments")
def import_comments(
    project: Path = typer.Option(..., "--project"),
    file: Path = typer.Option(..., "--file"),
    platform: Platform = typer.Option(..., "--platform"),
    mapping: Path | None = typer.Option(None, "--mapping"),
    json_output: bool = typer.Option(False, "--json"),
    dry_run: bool = typer.Option(False, "--dry-run"),
) -> None:
    """Import comment exports with author hashing."""

    _import_command(
        entity="comments",
        project=project,
        file=file,
        platform=platform,
        mapping=mapping,
        json_output=json_output,
        dry_run=dry_run,
    )


@import_app.command("transcripts")
def import_transcripts(
    project: Path = typer.Option(..., "--project"),
    file: Path = typer.Option(..., "--file"),
    video: str = typer.Option(..., "--video"),
    language: str | None = typer.Option(None, "--language"),
    source_name: str = typer.Option("user_subtitle", "--source-name"),
    json_output: bool = typer.Option(False, "--json"),
    dry_run: bool = typer.Option(False, "--dry-run"),
) -> None:
    """Import SRT, VTT, TXT, JSON, or JSONL transcript segments."""

    receipt, report, already_imported = _execute(
        lambda: TranscriptImportService(ProjectLayout.open(project)).import_file(
            video_id=video,
            source=file,
            language=language,
            source_name=source_name,
            dry_run=dry_run,
        ),
        json_output=json_output,
    )
    payload = {
        "ok": report.error_count == 0,
        "dry_run": dry_run,
        "already_imported": already_imported,
        "receipt": receipt.model_dump(mode="json") if receipt else None,
        "quality": report.as_dict(),
    }
    _emit(
        payload,
        json_output=json_output,
        human=(
            f"transcripts: {report.stats['accepted_rows']} accepted, "
            f"{report.stats['duplicate_rows']} duplicates for {video}"
        ),
    )


@app.command("validate")
def validate_command(
    project: Path = typer.Option(..., "--project"),
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    """Validate raw integrity and staging contracts."""

    report = _execute(
        lambda: validate_project(ProjectLayout.open(project)),
        json_output=json_output,
    )
    payload = {"ok": report.error_count == 0, "quality": report.as_dict()}
    _emit(
        payload,
        json_output=json_output,
        human=f"Validation completed with {report.error_count} errors",
    )
    if report.error_count:
        raise typer.Exit(EXIT_CODES[ErrorCode.SCHEMA_INVALID])


@app.command("normalize")
def normalize_command(
    project: Path = typer.Option(..., "--project"),
    json_output: bool = typer.Option(False, "--json"),
    dry_run: bool = typer.Option(False, "--dry-run"),
) -> None:
    """Rebuild deduplicated Parquet tables from staging."""

    result = _execute(
        lambda: NormalizationService(ProjectLayout.open(project)).normalize(dry_run=dry_run),
        json_output=json_output,
    )
    _emit(
        result,
        json_output=json_output,
        human=f"Normalized: {result['counts']}",
    )


@app.command("metrics")
def metrics_command(
    project: Path = typer.Option(..., "--project"),
    account: str = typer.Option(..., "--account"),
    json_output: bool = typer.Option(False, "--json"),
    dry_run: bool = typer.Option(False, "--dry-run"),
) -> None:
    """Calculate account-local derived and robust metrics."""

    result = _execute(
        lambda: MetricsService(ProjectLayout.open(project)).calculate(
            account_id=account, dry_run=dry_run
        ),
        json_output=json_output,
    )
    _emit(
        result,
        json_output=json_output,
        human=f"Calculated {result['records']} metric records for {account}",
    )


@app.command("sample")
def sample_command(
    project: Path = typer.Option(..., "--project"),
    account: str = typer.Option(..., "--account"),
    size: int | None = typer.Option(None, "--size", min=1),
    json_output: bool = typer.Option(False, "--json"),
    dry_run: bool = typer.Option(False, "--dry-run"),
) -> None:
    """Select a deterministic stratified account sample."""

    result = _execute(
        lambda: SamplingService(ProjectLayout.open(project)).select(
            account_id=account,
            size=size,
            dry_run=dry_run,
        ),
        json_output=json_output,
    )
    manifest = result["manifest"]
    _emit(
        result,
        json_output=json_output,
        human=(
            f"Selected {manifest['selected_size']} of {manifest['population_size']} videos "
            f"for {account}: {result['output']}"
        ),
    )


@app.command("report")
def report_command(
    project: Path = typer.Option(..., "--project"),
    account: str = typer.Option(..., "--account"),
    sample_size: int | None = typer.Option(None, "--sample-size", min=1),
    json_output: bool = typer.Option(False, "--json"),
    dry_run: bool = typer.Option(False, "--dry-run"),
) -> None:
    """Generate a traceable JSON/Markdown account-health report."""

    result = _execute(
        lambda: ReportService(ProjectLayout.open(project)).generate_account_health(
            account_id=account,
            sample_size=sample_size,
            dry_run=dry_run,
        ),
        json_output=json_output,
    )
    _emit(
        result,
        json_output=json_output,
        human=f"Generated account-health report for {account}: {result['outputs'][0]}",
    )


@analyze_app.command("video")
def analyze_video_command(
    project: Path = typer.Option(..., "--project"),
    video: str = typer.Option(..., "--video"),
    model_output: Path | None = typer.Option(
        None,
        "--model-output",
        help="Offline JSON containing schema-targeted model responses.",
    ),
    max_attempts: int | None = typer.Option(None, "--max-attempts", min=1, max=5),
    strict_model: bool = typer.Option(
        False,
        "--strict-model",
        help="Fail instead of using deterministic low-confidence fallback.",
    ),
    json_output: bool = typer.Option(False, "--json"),
    dry_run: bool = typer.Option(False, "--dry-run"),
) -> None:
    """Analyze one transcript blindly, then attach account-local performance context."""

    result = _execute(
        lambda: VideoAnalysisService(ProjectLayout.open(project)).analyze(
            video_id=video,
            model_output=model_output,
            max_attempts=max_attempts,
            strict_model=strict_model,
            dry_run=dry_run,
        ),
        json_output=json_output,
    )
    analysis = result["analysis"]
    _emit(
        result,
        json_output=json_output,
        human=(f"Analyzed {video} with status={analysis['status']}: {result['outputs'][0]}"),
    )


@analyze_app.command("comments")
def analyze_comments_command(
    project: Path = typer.Option(..., "--project"),
    account: str = typer.Option(..., "--account"),
    model_output: Path | None = typer.Option(
        None,
        "--model-output",
        help="Offline JSON containing one comment_intent candidate per model attempt.",
    ),
    max_attempts: int | None = typer.Option(None, "--max-attempts", min=1, max=5),
    strict_model: bool = typer.Option(False, "--strict-model"),
    json_output: bool = typer.Option(False, "--json"),
    dry_run: bool = typer.Option(False, "--dry-run"),
) -> None:
    """Analyze redacted comments and cluster user needs."""

    result = _execute(
        lambda: CommentAnalysisService(ProjectLayout.open(project)).analyze(
            account_id=account,
            model_output=model_output,
            max_attempts=max_attempts,
            strict_model=strict_model,
            dry_run=dry_run,
        ),
        json_output=json_output,
    )
    analysis = result["analysis"]
    _emit(
        result,
        json_output=json_output,
        human=(
            f"Analyzed {analysis['comment_count']} comments into "
            f"{len(analysis['need_clusters'])} need clusters"
        ),
    )


@app.command("distill")
def distill_command(
    project: Path = typer.Option(..., "--project"),
    account: str = typer.Option(..., "--account"),
    json_output: bool = typer.Option(False, "--json"),
    dry_run: bool = typer.Option(False, "--dry-run"),
) -> None:
    """Distill account clusters, patterns, counterexamples, and actions."""

    result = _execute(
        lambda: AccountDistillationService(ProjectLayout.open(project)).distill(
            account_id=account,
            dry_run=dry_run,
        ),
        json_output=json_output,
    )
    distillation = result["distillation"]
    _emit(
        result,
        json_output=json_output,
        human=(
            f"Distilled {account}: {len(distillation['patterns'])} patterns; {result['outputs'][0]}"
        ),
    )


@app.command("compare")
def compare_command(
    project: Path = typer.Option(..., "--project"),
    target: str = typer.Option(..., "--target"),
    benchmarks: str = typer.Option(
        ..., "--benchmarks", help="Comma-separated benchmark account IDs."
    ),
    json_output: bool = typer.Option(False, "--json"),
    dry_run: bool = typer.Option(False, "--dry-run"),
) -> None:
    """Generate a conservative benchmark transfer matrix."""

    benchmark_ids = [item.strip() for item in benchmarks.split(",") if item.strip()]
    result = _execute(
        lambda: BenchmarkComparisonService(ProjectLayout.open(project)).compare(
            target_account_id=target,
            benchmark_account_ids=benchmark_ids,
            dry_run=dry_run,
        ),
        json_output=json_output,
    )
    comparison = result["comparison"]
    _emit(
        result,
        json_output=json_output,
        human=(
            f"Compared {len(comparison['benchmark_account_ids'])} benchmarks: "
            f"{len(comparison['transfer_matrix'])} transfer items"
        ),
    )


@app.command("status")
def status_command(
    project: Path = typer.Option(..., "--project"),
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    """Show project imports, tables, and last run."""

    result = _execute(
        lambda: project_status(ProjectLayout.open(project)),
        json_output=json_output,
    )
    _emit(
        result,
        json_output=json_output,
        human=(
            f"Project {result['project']['name']}: {result['imports']['count']} imports; "
            f"normalized={result['normalized']}"
        ),
    )


if __name__ == "__main__":
    app()
