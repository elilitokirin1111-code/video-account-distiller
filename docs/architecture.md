# Architecture

## Phase 0/1/2/3 data flow

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
        │
        ▼
SamplingService → content-addressed sample manifest
        │
        ▼
ReportService → report.json + report.md + evidence index + warnings
        │
        ├── SRT / VTT / TXT / JSON
        │            │
        │            ▼
        │    TranscriptImportService → transcripts.parquet
        │            │
        │            ▼
        └── VideoAnalysisService
                    ├── blind fact extraction + semantic labels
                    └── post-label performance context + video report
```

The Agent Skill orchestrates the CLI. Deterministic behavior lives in the Python package. Phase 3
uses versioned prompts and a mockable text-provider boundary, but ships no network provider,
browser control, or platform access.

## Components

- `adapters/`: file parsing and centralized platform mapping templates.
- `ingestion/`: raw preservation, hashing, conversion, Pydantic validation, row deduplication, and
  import receipts.
- `normalization/`: deterministic cross-import deduplication and Parquet rebuilds.
- `metrics/`: null-safe ratios, Median, MAD, Robust Z-score, weighted score, and account-local
  performance bands.
- `sampling/`: normalized account dataset joins and deterministic stratified selection.
- `transcripts/`: SRT/VTT/TXT/JSON parsing, immutable raw storage, and normalized segments.
- `features/`: blind content bundle, versioned prompts, structured provider validation, retry,
  conservative degradation, and post-label performance merge.
- `reports/`: null-safe account statistics, high/middle/low comparisons, evidence collection, and
  Jinja2 Markdown rendering.
- `storage/`: project state, run manifests, atomic Parquet writes, and DuckDB views.
- `quality.py`: paired JSON/Markdown reports.
- `cli.py`: Typer commands and stable error envelopes.

## Persistence and traceability

Original files are copied under `raw/imports/<entity>/` using their SHA-256 as the filename. Every
staged and normalized record includes `schema_version`, `run_id`, `raw_hash`, source identifiers,
timestamps, and data-quality flags. Every mutating operation writes `runs/<run-id>/manifest.json`.

Phase 2 samples and reports use stable content-addressed `smp_*` and `rpt_*` identifiers. Repeating
the same input/configuration reuses the artifact. Report evidence resolves `evi_*` identifiers to
normalized record IDs, source record IDs, raw hashes, and source run IDs.

Phase 3 transcript imports are keyed by video plus raw hash. Single-video analyses use stable
content-addressed `vta_*` IDs. `blind-analysis.json` is frozen before metric lookup; cited transcript
segment IDs resolve through the video evidence index to normalized records and raw source hashes.

Normalized Parquet is reproducible from staging. Project state is stored in
`.distiller-state.json`; later rule and task workflows may introduce SQLite without changing the
Phase 1 table contracts.

## Failure model

Expected failures use stable `E_*` codes. CLI JSON goes to stdout; human error text goes to stderr.
Atomic writes prevent partially replaced state and Parquet files. Validation can detect altered or
missing raw inputs by recalculating SHA-256.

## Current boundaries

Phase 4+ comment intent, full account distillation, pattern evidence, scoring, prediction,
retrospective, visual/audio multimodal processing, and authorized live adapters are not present.
Phase 3 analyzes transcript text only and cannot infer camera, image, music, or sound features.
