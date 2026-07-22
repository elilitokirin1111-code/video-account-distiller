"""Read-only DuckDB query layer over normalized Parquet tables."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from typing import Any

import duckdb

from video_account_distiller.errors import DistillerError, ErrorCode

TABLES = (
    "accounts",
    "account_snapshots",
    "videos",
    "metric_snapshots",
    "comments",
    "transcripts",
    "derived_metrics",
    "media_features",
)


class DuckDBStore:
    """Create in-memory SQL views without copying Parquet data."""

    def __init__(self, normalized_dir: Path) -> None:
        self.normalized_dir = normalized_dir.resolve()
        self.connection = duckdb.connect(":memory:")
        self._register_views()

    def _register_views(self) -> None:
        for table in TABLES:
            path = self.normalized_dir / f"{table}.parquet"
            if not path.is_file():
                continue
            escaped = str(path).replace("'", "''")
            self.connection.execute(
                f"CREATE OR REPLACE VIEW \"{table}\" AS SELECT * FROM read_parquet('{escaped}')"
            )

    def available_tables(self) -> list[str]:
        """List normalized views currently available."""

        rows = self.connection.execute("SHOW TABLES").fetchall()
        return sorted(str(row[0]) for row in rows)

    def count(self, table: str) -> int:
        """Count rows in a registered, allow-listed table."""

        if table not in TABLES or table not in self.available_tables():
            return 0
        row = self.connection.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()
        return int(row[0]) if row is not None else 0

    def query(self, sql: str, parameters: list[Any] | None = None) -> list[dict[str, Any]]:
        """Execute a read-only SELECT/WITH query and return dictionaries."""

        normalized = sql.lstrip().casefold()
        if not (normalized.startswith("select") or normalized.startswith("with")):
            raise DistillerError(ErrorCode.QUERY_FAILED, "Only SELECT/WITH queries are allowed")
        try:
            result = self.connection.execute(sql, parameters or [])
            columns = [item[0] for item in result.description]
            return [dict(zip(columns, row, strict=True)) for row in result.fetchall()]
        except duckdb.Error as exc:
            raise DistillerError(
                ErrorCode.QUERY_FAILED,
                "DuckDB query failed",
                details={"reason": str(exc)},
            ) from exc

    def close(self) -> None:
        """Close the in-memory connection."""

        self.connection.close()

    def __enter__(self) -> DuckDBStore:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def iter_counts(self) -> Iterator[tuple[str, int]]:
        """Yield table counts in stable order."""

        for table in TABLES:
            yield table, self.count(table)
