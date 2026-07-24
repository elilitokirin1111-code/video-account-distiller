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

# DuckDB constructs that are not allowed in read-only queries against Parquet views.
# These either mutate state, expose filesystem access beyond the registered views,
# or bypass the Parquet read path entirely.
_FORBIDDEN_SQL_TOKENS = (
    "attach",
    "detach",
    "alter",
    "create",
    "drop",
    "insert",
    "update",
    "delete",
    "truncate",
    "copy",
    "export",
    "import",
    "pragma",
    "checkpoint",
    "read_csv",
    "read_csv_auto",
    "read_json",
    "read_parquet",  # Allow only through our registered views, not ad-hoc
    "read_text",
    "sql_auto",
    "call",
    "set ",
    "reset ",
    "load ",
    "install ",
)


def _validate_path_for_sql(raw: str) -> str:
    """Reject paths with characters unsafe inside a SQL string literal.

    Because DuckDB DDL statements (CREATE VIEW) do not accept prepared
    parameters, we must interpolate the path into the SQL string.  This
    validator rejects any path that contains a single-quote or a control
    character so that only safe paths are embedded.
    """
    for idx, ch in enumerate(raw):
        if ch == "'":
            raise DistillerError(
                ErrorCode.QUERY_FAILED,
                "Parquet path contains a single-quote character",
                details={"path": raw, "offset": idx},
            )
        if ord(ch) < 0x20 or ch in ("\x7f",):
            raise DistillerError(
                ErrorCode.QUERY_FAILED,
                "Parquet path contains an unsafe control character",
                details={"path": raw},
            )
    return raw


class DuckDBStore:
    """Create in-memory SQL views without copying Parquet data."""

    def __init__(self, normalized_dir: Path) -> None:
        self.normalized_dir = normalized_dir.resolve()
        self.connection = duckdb.connect(":memory:")
        self._closed = False
        self._register_views()

    def _register_views(self) -> None:
        for table in TABLES:
            path = self.normalized_dir / f"{table}.parquet"
            if not path.is_file():
                continue
            # Table name comes from the hardcoded TABLES allowlist — safe for
            # interpolation.  The path is validated by _validate_path_for_sql
            # before embedding because DuckDB DDL does not accept parameters.
            safe = _validate_path_for_sql(str(path))
            self.connection.execute(
                f"CREATE OR REPLACE VIEW \"{table}\" AS SELECT * FROM read_parquet('{safe}')"
            )

    def available_tables(self) -> list[str]:
        """List normalized views currently available."""

        rows = self.connection.execute("SHOW TABLES").fetchall()
        return sorted(str(row[0]) for row in rows)

    def count(self, table: str) -> int:
        """Count rows in a registered, allow-listed table."""

        if table not in TABLES or table not in self.available_tables():
            return 0
        # Table name comes from the hardcoded TABLES allowlist — safe for interpolation.
        row = self.connection.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()
        return int(row[0]) if row is not None else 0

    def query(self, sql: str, parameters: list[Any] | None = None) -> list[dict[str, Any]]:
        """Execute a read-only SELECT/WITH query and return dictionaries."""

        if self._closed:
            raise DistillerError(
                ErrorCode.QUERY_FAILED,
                "Cannot execute query on a closed DuckDBStore",
            )
        normalized = sql.lstrip().casefold()
        if not (normalized.startswith("select") or normalized.startswith("with")):
            raise DistillerError(ErrorCode.QUERY_FAILED, "Only SELECT/WITH queries are allowed")
        for token in _FORBIDDEN_SQL_TOKENS:
            if token in normalized:
                raise DistillerError(
                    ErrorCode.QUERY_FAILED,
                    f"Forbidden SQL construct detected: {token}",
                )
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

        if not self._closed:
            self.connection.close()
            self._closed = True

    def __enter__(self) -> DuckDBStore:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def iter_counts(self) -> Iterator[tuple[str, int]]:
        """Yield table counts in stable order."""

        for table in TABLES:
            yield table, self.count(table)
