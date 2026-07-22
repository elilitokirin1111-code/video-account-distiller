"""Typer command-line interface for the offline data and report workflow."""

from __future__ import annotations

import json
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any, TypeVar

import typer

from video_account_distiller.adapters import build_collaboration_adapter
from video_account_distiller.closed_loop import (
    PredictionService,
    PublicationService,
    RetroService,
    ScoringService,
)
from video_account_distiller.collaboration import (
    BatchService,
    CollaborationService,
    SnapshotScheduleService,
    TeamConfigService,
    load_connector_config,
)
from video_account_distiller.comments import CommentAnalysisService
from video_account_distiller.distillation import (
    AccountDistillationService,
    BenchmarkComparisonService,
)
from video_account_distiller.errors import EXIT_CODES, DistillerError, ErrorCode
from video_account_distiller.features import VideoAnalysisService
from video_account_distiller.ingestion import ImportService
from video_account_distiller.media import LocalMediaAnalysisService
from video_account_distiller.metrics import MetricsService
from video_account_distiller.models import Platform
from video_account_distiller.normalization import NormalizationService
from video_account_distiller.reports import ReportService
from video_account_distiller.sampling import SamplingService
from video_account_distiller.status import project_status
from video_account_distiller.storage.project import ProjectLayout
from video_account_distiller.transcripts import TranscriptImportService
from video_account_distiller.utils.time import parse_datetime
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
sync_app = typer.Typer(
    help="Sync through explicitly authorized official table APIs.", no_args_is_help=True
)
batch_app = typer.Typer(help="Run validated Phase 7 batch manifests.", no_args_is_help=True)
snapshot_app = typer.Typer(
    help="Plan due metric snapshots for external schedulers.", no_args_is_help=True
)
team_app = typer.Typer(
    help="Create and validate credential-free team policy.", no_args_is_help=True
)
app.add_typer(import_app, name="import")
app.add_typer(analyze_app, name="analyze")
app.add_typer(sync_app, name="sync")
app.add_typer(batch_app, name="batch")
app.add_typer(snapshot_app, name="snapshot")
app.add_typer(team_app, name="team")

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


@analyze_app.command("media")
def analyze_media_command(
    project: Path = typer.Option(..., "--project"),
    video: str = typer.Option(..., "--video"),
    file: Path | None = typer.Option(
        None, "--file", help="Local MP4/MOV/MKV or other FFmpeg-readable media."
    ),
    vision_output: Path | None = typer.Option(
        None,
        "--vision-output",
        help="Offline JSON containing schema-targeted visual/OCR annotations.",
    ),
    strict_media: bool = typer.Option(
        False, "--strict-media", help="Return E_MEDIA_DECODE instead of a degraded artifact."
    ),
    strict_vision: bool = typer.Option(
        False, "--strict-vision", help="Fail when visual/OCR output remains invalid."
    ),
    scene_threshold: float | None = typer.Option(None, "--scene-threshold", min=0.001, max=0.999),
    max_keyframes: int | None = typer.Option(None, "--max-keyframes", min=1, max=100),
    json_output: bool = typer.Option(False, "--json"),
    dry_run: bool = typer.Option(False, "--dry-run"),
) -> None:
    """Analyze a local video into timestamped shots, frames, audio, and optional OCR."""

    result = _execute(
        lambda: LocalMediaAnalysisService(ProjectLayout.open(project)).analyze(
            video_id=video,
            file=file,
            vision_output=vision_output,
            strict_media=strict_media,
            strict_vision=strict_vision,
            scene_threshold=scene_threshold,
            max_keyframes=max_keyframes,
            dry_run=dry_run,
        ),
        json_output=json_output,
    )
    if dry_run:
        human = f"Would analyze local media for {result['video_id']} with {result['backend']}"
    else:
        analysis = result["analysis"]
        human = (
            f"Analyzed local media for {analysis['video_id']} with "
            f"status={analysis['status']}: {result['outputs'][0]}"
        )
    _emit(result, json_output=json_output, human=human)


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


@app.command("score")
def score_command(
    project: Path = typer.Option(..., "--project"),
    account: str = typer.Option(..., "--account"),
    script: Path = typer.Option(..., "--script"),
    title: str | None = typer.Option(None, "--title"),
    topic: str | None = typer.Option(None, "--topic"),
    target_pillar: str | None = typer.Option(None, "--target-pillar"),
    target_metric: str = typer.Option("performance_score", "--target-metric"),
    planned_publish_hour: int | None = typer.Option(None, "--planned-publish-hour", min=0, max=23),
    json_output: bool = typer.Option(False, "--json"),
    dry_run: bool = typer.Option(False, "--dry-run"),
) -> None:
    """Score one script with an explainable account-local Rubric."""

    result = _execute(
        lambda: ScoringService(ProjectLayout.open(project)).score(
            account_id=account,
            script=script,
            title=title,
            topic=topic,
            target_pillar=target_pillar,
            target_metric=target_metric,
            planned_publish_hour=planned_publish_hour,
            dry_run=dry_run,
        ),
        json_output=json_output,
    )
    score = result["score"]
    _emit(
        result,
        json_output=json_output,
        human=f"Scored {score['candidate_id']}: {score['total_score']}/100",
    )


@app.command("predict")
def predict_command(
    project: Path = typer.Option(..., "--project"),
    account: str = typer.Option(..., "--account"),
    script: Path = typer.Option(..., "--script"),
    title: str | None = typer.Option(None, "--title"),
    topic: str | None = typer.Option(None, "--topic"),
    target_pillar: str | None = typer.Option(None, "--target-pillar"),
    target_metric: str = typer.Option("performance_score", "--target-metric"),
    target_age_hours: int | None = typer.Option(None, "--target-age-hours", min=1),
    planned_publish_hour: int | None = typer.Option(None, "--planned-publish-hour", min=0, max=23),
    json_output: bool = typer.Option(False, "--json"),
    dry_run: bool = typer.Option(False, "--dry-run"),
) -> None:
    """Score a script and save an immutable account-local prediction interval."""

    result = _execute(
        lambda: PredictionService(ProjectLayout.open(project)).predict(
            account_id=account,
            script=script,
            title=title,
            topic=topic,
            target_pillar=target_pillar,
            target_metric=target_metric,
            target_age_hours=target_age_hours,
            planned_publish_hour=planned_publish_hour,
            dry_run=dry_run,
        ),
        json_output=json_output,
    )
    prediction = result["prediction"]
    _emit(
        result,
        json_output=json_output,
        human=(
            f"Predicted {prediction['prediction_id']} at "
            f"T+{prediction['target_snapshot_age_hours']}h"
        ),
    )


@app.command("publish")
def publish_command(
    project: Path = typer.Option(..., "--project"),
    prediction: str = typer.Option(..., "--prediction"),
    video: str = typer.Option(..., "--video"),
    published_at: str | None = typer.Option(None, "--published-at"),
    url: str | None = typer.Option(None, "--url"),
    notes: str | None = typer.Option(None, "--notes"),
    json_output: bool = typer.Option(False, "--json"),
    dry_run: bool = typer.Option(False, "--dry-run"),
) -> None:
    """Register a publication and its snapshot plan without changing the prediction."""

    result = _execute(
        lambda: PublicationService(ProjectLayout.open(project)).register(
            prediction_id=prediction,
            video_id=video,
            published_at=parse_datetime(published_at),
            url=url,
            notes=notes,
            dry_run=dry_run,
        ),
        json_output=json_output,
    )
    publication = result["publication"]
    _emit(
        result,
        json_output=json_output,
        human=f"Registered publication {publication['publication_id']}",
    )


@app.command("retro")
def retro_command(
    project: Path = typer.Option(..., "--project"),
    publication: str = typer.Option(..., "--publication"),
    snapshot: str = typer.Option("t3d", "--snapshot"),
    target_age_hours: int | None = typer.Option(None, "--target-age-hours", min=1),
    json_output: bool = typer.Option(False, "--json"),
    dry_run: bool = typer.Option(False, "--dry-run"),
) -> None:
    """Review prediction error and propose pending rule/rubric changes."""

    result = _execute(
        lambda: RetroService(ProjectLayout.open(project)).run(
            publication_id=publication,
            snapshot=snapshot,
            target_age_hours=target_age_hours,
            dry_run=dry_run,
        ),
        json_output=json_output,
    )
    retro = result["retro"]
    _emit(
        result,
        json_output=json_output,
        human=(
            f"Reviewed {publication}: {len(retro['prediction_errors'])} prediction errors, "
            f"{len(retro['next_experiments'])} next experiments"
        ),
    )


@import_app.command("authorized-export")
def import_authorized_export_command(
    project: Path = typer.Option(..., "--project"),
    manifest: Path = typer.Option(..., "--manifest"),
    mapping: Path | None = typer.Option(None, "--mapping"),
    json_output: bool = typer.Option(False, "--json"),
    dry_run: bool = typer.Option(False, "--dry-run"),
) -> None:
    """Import an export only after validating its explicit grant and SHA-256 manifest."""

    result = _execute(
        lambda: CollaborationService(ProjectLayout.open(project)).import_authorized_export(
            manifest_path=manifest,
            mapping_path=mapping,
            dry_run=dry_run,
        ),
        json_output=json_output,
    )
    quality = result["quality"]
    _emit(
        result,
        json_output=json_output,
        human=(
            f"Authorized export: {quality['stats']['accepted_rows']} accepted, "
            f"{quality['stats']['rejected_rows']} rejected"
        ),
    )


@sync_app.command("pull")
def sync_pull_command(
    project: Path = typer.Option(..., "--project"),
    connector_config: Path = typer.Option(..., "--connector-config"),
    entity: str = typer.Option(..., "--entity"),
    platform: Platform = typer.Option(..., "--platform"),
    mapping: Path | None = typer.Option(None, "--mapping"),
    json_output: bool = typer.Option(False, "--json"),
    dry_run: bool = typer.Option(False, "--dry-run"),
) -> None:
    """Pull rows from an explicitly authorized Feishu or Google table."""

    def operation() -> dict[str, Any]:
        config = load_connector_config(connector_config)
        adapter = build_collaboration_adapter(config)
        return CollaborationService(ProjectLayout.open(project)).pull(
            adapter=adapter,
            entity=entity,
            platform=platform,
            mapping_path=mapping,
            dry_run=dry_run,
        )

    result = _execute(operation, json_output=json_output)
    _emit(
        result,
        json_output=json_output,
        human=f"Pulled {result['sync']['row_count']} {entity} rows",
    )


@sync_app.command("push")
def sync_push_command(
    project: Path = typer.Option(..., "--project"),
    connector_config: Path = typer.Option(..., "--connector-config"),
    entity: str = typer.Option(..., "--entity"),
    json_output: bool = typer.Option(False, "--json"),
    dry_run: bool = typer.Option(False, "--dry-run"),
) -> None:
    """Append normalized rows to an explicitly authorized Feishu or Google table."""

    def operation() -> dict[str, Any]:
        config = load_connector_config(connector_config)
        adapter = build_collaboration_adapter(config)
        return CollaborationService(ProjectLayout.open(project)).push(
            adapter=adapter,
            entity=entity,
            dry_run=dry_run,
        )

    result = _execute(operation, json_output=json_output)
    _emit(
        result,
        json_output=json_output,
        human=f"Pushed {result['sync']['row_count']} {entity} rows",
    )


@snapshot_app.command("plan")
def snapshot_plan_command(
    project: Path = typer.Option(..., "--project"),
    at: str | None = typer.Option(None, "--at", help="Optional ISO-8601 planning time."),
    json_output: bool = typer.Option(False, "--json"),
    dry_run: bool = typer.Option(False, "--dry-run"),
) -> None:
    """Emit due/future/available snapshot tasks without collecting platform data."""

    planning_time = parse_datetime(at) if at else None
    result = _execute(
        lambda: SnapshotScheduleService(ProjectLayout.open(project)).plan(
            now=planning_time, dry_run=dry_run
        ),
        json_output=json_output,
    )
    payload = result.model_dump(mode="json")
    due = sum(task["status"] == "due" for task in payload["tasks"])
    _emit(payload, json_output=json_output, human=f"Snapshot plan: {due} due tasks")


@batch_app.command("run")
def batch_run_command(
    project: Path = typer.Option(..., "--project"),
    file: Path = typer.Option(..., "--file"),
    json_output: bool = typer.Option(False, "--json"),
    dry_run: bool = typer.Option(False, "--dry-run"),
) -> None:
    """Run a strict batch manifest and isolate each task result."""

    result = _execute(
        lambda: BatchService(ProjectLayout.open(project)).run(manifest_path=file, dry_run=dry_run),
        json_output=json_output,
    )
    payload = result.model_dump(mode="json")
    failures = sum(task["status"] == "failed" for task in payload["tasks"])
    _emit(
        payload,
        json_output=json_output,
        human=(
            f"Batch {result.batch_id}: {len(result.tasks) - failures} succeeded, {failures} failed"
        ),
    )


@team_app.command("init")
def team_init_command(
    project: Path = typer.Option(..., "--project"),
    owner: str = typer.Option(..., "--owner"),
    owner_name: str | None = typer.Option(None, "--owner-name"),
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    """Create a credential-free team policy without overwriting an existing file."""

    config, already_initialized = _execute(
        lambda: TeamConfigService(ProjectLayout.open(project)).initialize(
            owner_id=owner, owner_name=owner_name
        ),
        json_output=json_output,
    )
    payload = {
        "ok": True,
        "already_initialized": already_initialized,
        "path": str(ProjectLayout.open(project).root / "team.yaml"),
        "team": config.model_dump(mode="json"),
    }
    _emit(payload, json_output=json_output, human=f"Team config ready: {config.name}")


@team_app.command("validate")
def team_validate_command(
    project: Path = typer.Option(..., "--project"),
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    """Validate team roles and connector references without reading credential values."""

    config = _execute(
        lambda: TeamConfigService(ProjectLayout.open(project)).load(),
        json_output=json_output,
    )
    payload = {
        "ok": True,
        "team_id": config.team_id,
        "members": len(config.members),
        "connectors": len(config.connectors),
    }
    _emit(payload, json_output=json_output, human=f"Team config valid: {config.name}")


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
