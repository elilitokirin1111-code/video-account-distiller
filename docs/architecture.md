# Architecture

## Phase 0/1 data flow

```text
CSV / JSON / JSONL
        │
        ▼
FileAdapter → MappingResolver → Pydantic validation
        │               │
        │               └── platform templates or user FieldMapping
        ▼
immutable raw copy + SHA-256
        │
        ▼
validated JSONL staging
        │
        ▼
NormalizationService → deduplicated Parquet
        │                         │
        │                         └── DuckDB read-only views
        ▼
MetricsService → DerivedMetrics Parquet
```

The Agent Skill orchestrates the CLI. Deterministic behavior lives in the Python package. No prompt,
model provider, browser, or platform network access is used in Phase 0/1.

## Components

- `adapters/`: file parsing and centralized platform mapping templates.
- `ingestion/`: raw preservation, hashing, conversion, Pydantic validation, row deduplication, and
  import receipts.
- `normalization/`: deterministic cross-import deduplication and Parquet rebuilds.
- `metrics/`: null-safe ratios, Median, MAD, Robust Z-score, weighted score, and account-local
  performance bands.
- `storage/`: project state, run manifests, atomic Parquet writes, and DuckDB views.
- `quality.py`: paired JSON/Markdown reports.
- `cli.py`: Typer commands and stable error envelopes.

## Persistence and traceability

Original files are copied under `raw/imports/<entity>/` using their SHA-256 as the filename. Every
staged and normalized record includes `schema_version`, `run_id`, `raw_hash`, source identifiers,
timestamps, and data-quality flags. Every mutating operation writes `runs/<run-id>/manifest.json`.

Normalized Parquet is reproducible from staging. Project state is stored in
`.distiller-state.json`; later rule and task workflows may introduce SQLite without changing the
Phase 1 table contracts.

## Failure model

Expected failures use stable `E_*` codes. CLI JSON goes to stdout; human error text goes to stderr.
Atomic writes prevent partially replaced state and Parquet files. Validation can detect altered or
missing raw inputs by recalculating SHA-256.

## Current boundaries

Phase 2+ sampling, content analysis, comment intent, pattern evidence, reporting, scoring,
prediction, retrospective, multimodal processing, and authorized live adapters are not present.
