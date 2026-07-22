# Data contracts

Core normalized schema version is `0.1.0`; Phase 2 analysis artifacts use `0.2.0`; new transcript
and text-analysis contracts use `0.3.0`. Executable Pydantic models reject unknown fields.

Normalized tables are `accounts`, `account_snapshots`, `videos`, `metric_snapshots`, `comments`,
`transcripts`, and `derived_metrics`. Every core row includes source platform/type/URI/record ID, collected and
ingested timestamps, run ID, raw hash, schema version, and quality flags.

Treat these cases differently:

- Unknown: `null`.
- Known zero: `0` or `0.0`.
- Invalid negative count/duration/spend: rejected row.
- Zero or unknown denominator: derived rate is `null`.

Stable internal IDs derive from platform plus platform record IDs. Keep current account followers
separate from `follower_count_at_publish`. Do not substitute the current count silently.

Transcript timing may be `null`; never invent timestamps for TXT. Phase 3 semantic output must cite
existing transcript segment IDs. `blind-analysis.json` must contain no performance fields.

For full field definitions, read the repository `docs/data-contracts.md` and
`docs/planning/04_DATA_SCHEMA.md`.
