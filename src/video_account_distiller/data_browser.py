"""Read-only browsing of normalized rows with auditable source-tier filters."""

from __future__ import annotations

import json
from collections import Counter
from typing import Any, Literal

from video_account_distiller.models import DataSourceTier, ImportReceipt
from video_account_distiller.storage.duckdb_store import DuckDBStore
from video_account_distiller.storage.project import ProjectLayout

BrowsableTable = Literal[
    "accounts",
    "account_snapshots",
    "videos",
    "metric_snapshots",
    "comments",
    "transcripts",
    "audience_profiles",
]

BROWSABLE_TABLES: tuple[BrowsableTable, ...] = (
    "accounts",
    "account_snapshots",
    "videos",
    "metric_snapshots",
    "comments",
    "transcripts",
    "audience_profiles",
)

_ENTITY_BY_TABLE: dict[BrowsableTable, str] = {
    "accounts": "accounts",
    "account_snapshots": "accounts",
    "videos": "videos",
    "metric_snapshots": "metrics",
    "comments": "comments",
    "transcripts": "transcripts",
    "audience_profiles": "audience_profiles",
}


def _tier(receipt: ImportReceipt) -> DataSourceTier:
    return DataSourceTier(receipt.data_source_tier)


class NormalizedDataBrowser:
    """Browse normalized records without exposing arbitrary SQL."""

    def __init__(self, project: ProjectLayout) -> None:
        self.project = project

    def list_imports(
        self,
        *,
        entity: str | None = None,
        source_tier: DataSourceTier | None = None,
    ) -> list[dict[str, Any]]:
        receipts = self.project.load_state().imports
        selected = [
            receipt
            for receipt in receipts
            if (entity is None or receipt.entity == entity)
            and (source_tier is None or _tier(receipt) == source_tier)
        ]
        selected.sort(key=lambda receipt: receipt.imported_at, reverse=True)
        return [receipt.model_dump(mode="json") for receipt in selected]

    def browse(
        self,
        *,
        table: BrowsableTable,
        source_tier: DataSourceTier | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> dict[str, Any]:
        state = self.project.load_state()
        entity = _ENTITY_BY_TABLE[table]
        relevant_receipts = [receipt for receipt in state.imports if receipt.entity == entity]
        tier_by_hash = {receipt.raw_hash: _tier(receipt) for receipt in relevant_receipts}

        where = ""
        parameters: list[Any] = []
        if source_tier is not None:
            hashes = sorted(
                raw_hash for raw_hash, tier in tier_by_hash.items() if tier == source_tier
            )
            if not hashes:
                return {
                    "table": table,
                    "source_tier": source_tier.value,
                    "total": 0,
                    "limit": limit,
                    "offset": offset,
                    "rows": [],
                    "source_tier_counts": {},
                }
            placeholders = ", ".join("?" for _ in hashes)
            where = f" WHERE raw_hash IN ({placeholders})"
            parameters.extend(hashes)

        with DuckDBStore(self.project.normalized_dir) as store:
            if table not in store.available_tables():
                return {
                    "table": table,
                    "source_tier": source_tier.value if source_tier else None,
                    "total": 0,
                    "limit": limit,
                    "offset": offset,
                    "rows": [],
                    "source_tier_counts": {},
                }
            count_rows = store.query(
                f'SELECT COUNT(*) AS total FROM "{table}"{where}',
                parameters,
            )
            total = int(count_rows[0]["total"])
            serialized_rows = store.query(
                "SELECT to_json(browser_row) AS row_json FROM ("
                "SELECT *, ROW_NUMBER() OVER (ORDER BY record_id) AS _browser_row_number "
                f'FROM "{table}"{where}'
                ") AS browser_row WHERE _browser_row_number > ? AND _browser_row_number <= ? "
                "ORDER BY _browser_row_number",
                [*parameters, offset, offset + limit],
            )
        rows = [json.loads(str(item["row_json"])) for item in serialized_rows]
        for row in rows:
            row.pop("_browser_row_number", None)

        tier_counts: Counter[str] = Counter()
        for row in rows:
            tier = tier_by_hash.get(str(row.get("raw_hash")), DataSourceTier.UNKNOWN)
            row["data_source_tier"] = tier.value
            tier_counts[tier.value] += 1
        return {
            "table": table,
            "source_tier": source_tier.value if source_tier else None,
            "total": total,
            "limit": limit,
            "offset": offset,
            "rows": rows,
            "source_tier_counts": dict(sorted(tier_counts.items())),
        }
