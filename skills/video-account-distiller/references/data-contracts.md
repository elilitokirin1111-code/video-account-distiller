# Data contracts

Core normalized schema version is `0.1.0`; Phase 2 analysis artifacts use `0.2.0`. Executable
Pydantic models reject unknown fields.

Normalized tables are `accounts`, `account_snapshots`, `videos`, `metric_snapshots`, `comments`,
and `derived_metrics`. Every core row includes source platform/type/URI/record ID, collected and
ingested timestamps, run ID, raw hash, schema version, and quality flags.

Treat these cases differently:

- Unknown: `null`.
- Known zero: `0` or `0.0`.
- Invalid negative count/duration/spend: rejected row.
- Zero or unknown denominator: derived rate is `null`.

Stable internal IDs derive from platform plus platform record IDs. Keep current account followers
separate from `follower_count_at_publish`. Do not substitute the current count silently.

For full field definitions, read the repository `docs/data-contracts.md` and
`docs/planning/04_DATA_SCHEMA.md`.
