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
        accounts = (
            store.query(
                "SELECT account_id, platform, display_name FROM accounts ORDER BY account_id"
            )
            if "accounts" in store.available_tables()
            else []
        )
    last_manifest = None
    if state.last_run_id:
        manifest_path = project.runs_dir / state.last_run_id / "manifest.json"
        if manifest_path.is_file():
            last_manifest = read_json(manifest_path)
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
                for entity in ("accounts", "videos", "metrics", "comments")
            },
        },
        "normalized": table_counts,
        "accounts": accounts,
        "last_run": last_manifest,
        "last_normalized_at": (
            state.last_normalized_at.isoformat() if state.last_normalized_at else None
        ),
        "last_metrics_at": state.last_metrics_at.isoformat() if state.last_metrics_at else None,
    }
