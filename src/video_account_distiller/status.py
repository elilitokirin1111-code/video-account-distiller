"""Project status aggregation."""

from __future__ import annotations

from typing import Any

from video_account_distiller.storage.duckdb_store import DuckDBStore
from video_account_distiller.storage.project import ProjectLayout
from video_account_distiller.utils.io import read_json


def project_status(project: ProjectLayout) -> dict[str, Any]:
    """Return a machine-readable snapshot without mutating project state."""

    state = project.load_state()
    with DuckDBStore(project.normalized_dir) as store:
        table_counts = dict(store.iter_counts())
        available_tables = store.available_tables()
        accounts = (
            store.query(
                "SELECT account_id, platform, display_name FROM accounts ORDER BY account_id"
            )
            if "accounts" in available_tables
            else []
        )
        recent_videos = (
            store.query(
                "SELECT video_id, account_id, platform_video_id, title, "
                "CAST(published_at AS VARCHAR) AS published_at "
                "FROM videos "
                "ORDER BY published_at DESC NULLS LAST, video_id "
                "LIMIT 20"
            )
            if "videos" in available_tables
            else []
        )
    last_manifest = None
    if state.last_run_id:
        manifest_path = project.runs_dir / state.last_run_id / "manifest.json"
        if manifest_path.is_file():
            last_manifest = read_json(manifest_path)
    sample_manifests = list(
        (project.root / "analyses" / "accounts").glob("*/samples/*/sample-manifest.json")
    )
    account_reports = list((project.root / "reports" / "accounts").glob("*/*/report.json"))
    comment_analyses = list((project.root / "analyses" / "comments").glob("*/*/analysis.json"))
    media_analyses = list((project.root / "analyses" / "media").glob("*/*/media-analysis.json"))
    media_enrichments = list(
        (project.root / "analyses" / "accounts").glob("*/media-enrichments/*/enrichment.json")
    )
    distillations = list((project.root / "reports" / "accounts").glob("*/*/distillation.json"))
    comparisons = list((project.root / "reports" / "comparisons").glob("*/comparison.json"))
    scores = list((project.root / "reports" / "scoring").glob("*/*/score.json"))
    predictions = list((project.root / "predictions").glob("*/prediction.json"))
    publications = list((project.root / "publications").glob("*/publication.json"))
    retros = list((project.root / "reports" / "retros").glob("*/*/retro.json"))
    sync_receipts = list((project.root / "collaboration" / "syncs").glob("*/sync.json"))
    batch_results = list((project.root / "collaboration" / "batches").glob("*/batch-result.json"))
    account_collections = list(
        (project.root / "raw" / "account-collections").glob("*/*/provider-batch.json")
    )
    pending_rule_changes = 0
    pending_rubric_changes = 0
    for path in retros:
        payload = read_json(path)
        pending_rule_changes += len(payload.get("rule_change_proposals", []))
        pending_rubric_changes += len(payload.get("rubric_change_proposals", []))
    return {
        "ok": True,
        "schema_version": state.schema_version,
        "project": {
            "id": state.project_id,
            "name": state.project_name,
            "root": str(project.root),
            "created_at": state.created_at.isoformat(),
            "updated_at": state.updated_at.isoformat(),
        },
        "imports": {
            "count": len(state.imports),
            "raw_hashes": sorted({receipt.raw_hash for receipt in state.imports}),
            "by_entity": {
                entity: sum(receipt.entity == entity for receipt in state.imports)
                for entity in ("accounts", "videos", "metrics", "comments", "transcripts")
            },
        },
        "normalized": table_counts,
        "accounts": accounts,
        "videos": {
            "total": table_counts.get("videos", 0),
            "recent": recent_videos,
            "truncated": table_counts.get("videos", 0) > len(recent_videos),
        },
        "last_run": last_manifest,
        "last_normalized_at": (
            state.last_normalized_at.isoformat() if state.last_normalized_at else None
        ),
        "last_metrics_at": state.last_metrics_at.isoformat() if state.last_metrics_at else None,
        "last_sample_at": state.last_sample_at.isoformat() if state.last_sample_at else None,
        "last_report_at": state.last_report_at.isoformat() if state.last_report_at else None,
        "last_transcript_at": (
            state.last_transcript_at.isoformat() if state.last_transcript_at else None
        ),
        "last_video_analysis_at": (
            state.last_video_analysis_at.isoformat() if state.last_video_analysis_at else None
        ),
        "last_media_analysis_at": (
            state.last_media_analysis_at.isoformat() if state.last_media_analysis_at else None
        ),
        "last_comment_analysis_at": (
            state.last_comment_analysis_at.isoformat() if state.last_comment_analysis_at else None
        ),
        "last_distillation_at": (
            state.last_distillation_at.isoformat() if state.last_distillation_at else None
        ),
        "last_comparison_at": (
            state.last_comparison_at.isoformat() if state.last_comparison_at else None
        ),
        "last_scoring_at": state.last_scoring_at.isoformat() if state.last_scoring_at else None,
        "last_prediction_at": (
            state.last_prediction_at.isoformat() if state.last_prediction_at else None
        ),
        "last_publication_at": (
            state.last_publication_at.isoformat() if state.last_publication_at else None
        ),
        "last_retro_at": state.last_retro_at.isoformat() if state.last_retro_at else None,
        "last_collaboration_at": (
            state.last_collaboration_at.isoformat() if state.last_collaboration_at else None
        ),
        "last_batch_at": state.last_batch_at.isoformat() if state.last_batch_at else None,
        "collaboration": {
            "sync_receipts": len(sync_receipts),
            "batch_results": len(batch_results),
            "team_configured": (project.root / "team.yaml").is_file(),
            "snapshot_plan_available": (
                project.root / "collaboration" / "schedules" / "snapshot-plan.json"
            ).is_file(),
        },
        "collection": {
            "account_batches": len(account_collections),
            "providers": sorted({path.parent.parent.name for path in account_collections}),
        },
        "artifacts": {
            "sample_manifests": len(sample_manifests),
            "account_health_reports": len(account_reports),
            "video_analyses": len(
                list((project.root / "analyses" / "videos").glob("*/*/analysis.json"))
            ),
            "media_analyses": len(media_analyses),
            "media_enrichments": len(media_enrichments),
            "comment_analyses": len(comment_analyses),
            "account_distillations": len(distillations),
            "benchmark_comparisons": len(comparisons),
            "content_scores": len(scores),
            "predictions": len(predictions),
            "publications": len(publications),
            "retros": len(retros),
            "pending_rule_changes": pending_rule_changes,
            "pending_rubric_changes": pending_rubric_changes,
        },
    }
