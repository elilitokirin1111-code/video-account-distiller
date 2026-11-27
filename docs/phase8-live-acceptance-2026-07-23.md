# Phase 8 live MediaCrawler acceptance — 2026-07-23

## Scope

This acceptance used one user-approved public Douyin account on Windows with the pinned
MediaCrawler sidecar and a visible Microsoft Edge window. Authentication and any platform
verification remained manual. The run did not enable proxy, stealth, automatic-login, CAPTCHA, or
risk-control-evasion behavior.

The repository does not contain the account session, Cookie values, credentials, comment text,
raw Provider payload, or the external acceptance project. Only non-sensitive counts, hashes, and
findings are recorded here.

## Result

- Completed the one-command homepage-to-distillation workflow.
- Collected 10 public videos, 10 metric snapshots, and 30 top-level comments from three sampled
  videos.
- Accepted 1 account, 10 videos, 10 metric snapshots, and 30 comments with zero rejected or
  duplicate rows in the acceptance batch.
- Preserved the Provider batch as an immutable raw artifact with SHA-256
  `2849b8f4c60fdc5a800d861b596566b55a473af8709f93831c9244096736eaa8`.
- Rebuilt Parquet and DuckDB, calculated derived metrics, and generated comment analysis, account
  health, evidence index, warning register, and account distillation artifacts.
- Final project validation reported zero errors and zero warnings.
- Manually compared three collected works across Provider and canonical companions: video ID,
  title, publication timestamp, snapshot timestamp, likes, comments, shares, and saves matched.
- Confirmed the repository and emitted machine output did not contain a credential, Cookie value,
  or authorization header.

## Findings and remediation

The first login navigation destroyed the active page evaluation context. The bounded manual-login
wait now treats navigation errors as transient. A separate Edge profile and a bounded configurable
login timeout were also added.

The live public payload exposed positive interaction counts while reporting `play_count = 0`.
That value is now treated as unavailable (`null`) rather than a measured zero. This prevents
invalid view-based rates and false universal `S` rankings. All-tied valid scores now degrade to
neutral band `B`. The final rerun reported all ten performance bands as unknown, generated no
unsupported performance Pattern, and kept positioning confidence low.

## Interpretation boundary

This acceptance proves the local collection, import, validation, storage, query, metric, comment,
report, and distillation chain. It does not prove causal content rules. With ten works and no local
video/transcript semantic analysis, positioning, visual identity, and creative-pattern conclusions
must remain low-confidence observations. Level 4 rule approval continues to require repeated,
controlled evidence and human review.
