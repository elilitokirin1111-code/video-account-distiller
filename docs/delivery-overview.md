# 1.0 production delivery overview

## What this delivery provides

Version `1.0.0` establishes a stable, offline-first data and reporting kernel plus a standard
Agent Skill for video-account research. It imports user exports, preserves originals, maps and
validates fields, deduplicates records, writes Parquet, exposes DuckDB views, calculates
account-local robust metrics, reports project status through a stable Typer CLI, selects
representative samples, and generates traceable account-health reports.
It also imports subtitles, performs blind Schema-validated text analysis, and produces traceable
single-video reports before attaching account-local performance context.
It now analyzes redacted comments, clusters audience needs, produces account-local Patterns with
support and counterexamples, writes account distillation/knowledge artifacts, and builds
conservative benchmark transfer matrices.
It now scores scripts against a versioned nine-dimension Rubric, records immutable account-local
prediction intervals, links predictions to normalized publications, and turns actual snapshots into
prediction errors, retained counterexamples, pending-only change proposals, and next experiments.
It now also analyzes local media through FFmpeg/FFprobe, builds a timestamped shot/keyframe/audio
timeline, accepts optional schema-validated visual/OCR evidence, and exposes aggregate media
features through Parquet and DuckDB without uploading the file.
It now verifies authorized platform exports, synchronizes explicitly approved Feishu Bitable and
Google Sheets resources through official APIs, preserves provider pages, protects identical pushes,
isolates Batch task results, exposes scheduled snapshot work, and validates credential-free team
policy without coupling the analysis kernel to either provider.

After the `1.0.0` release, the main development line adds a Phase 8 pre-release route that accepts
a user-approved Douyin homepage URL. Its default personal non-commercial research path uses a
pinned MediaCrawler source and controlled visible-Chrome sidecar; TikHub remains an optional paid
API. Both preserve complete responses and send canonical account/video/metric/comment rows through
the same import, Parquet, robust-metric, comment-analysis, report, and distillation kernel.
The same main line now adds opt-in retained-video enrichment: an allowlisted public media download,
local Whisper Chinese transcript, existing scene/keyframe/audio analysis, blind single-video
semantics, and account re-distillation with strict hash and evidence links.

## Key user outcomes

- Start a repeatable research project from offline exports or a user-approved homepage.
- Trace every normalized record back to its source hash and run.
- Keep unknown metrics as `null` and reject impossible negatives.
- Avoid direct raw comparisons across platforms.
- Query normalized data locally with DuckDB.
- Rank the latest video snapshots relative to the same account using Median, MAD, Robust Z-score,
  configurable weights, and S/A/B/C/D bands.
- Select a deterministic sample covering performance, recency, content type, duration, promotion,
  and outliers.
- Compare high, middle, and low account-local cohorts without claiming causality.
- Resolve every reported statistic and finding through a machine-readable evidence index.
- Import SRT/VTT/TXT/JSON subtitles without inventing missing timing.
- Extract Hook, structure, CTA, emotion, and content-pillar labels without seeing performance data.
- Retry invalid model output or degrade visibly to conservative low-confidence local analysis.
- Trace every cited subtitle segment and performance value to normalized and raw evidence.
- Redact common direct identifiers from comment analysis copies without altering raw comments.
- Turn comment intent, pain, objections, and purchase questions into traceable content opportunities.
- Preserve support samples, counterexamples, paid/outlier confounders, maturity, and confidence for
  every Pattern.
- Produce actionable account experiments without claiming causality or a validated rule.
- Keep benchmark and platform baselines separate while reviewing what can be tested or adapted.
- Score new scripts with visible dimensions, missing items, risks, and bounded low-maturity Rule
  influence.
- Save P25/P50/P75 predictions with assumptions, confidence, input hashes, and Rule/Rubric versions.
- Preserve prediction and publication records as append-only, content-addressed artifacts.
- Compare a real normalized snapshot with the prediction while retaining out-of-range results.
- Produce pending Rule/Rubric proposals and next experiments without silently changing policy.
- Preserve local media by SHA-256 and extract reproducible metadata, shots, keyframes, and bounded
  audio signal features.
- Keep visual/OCR unknown by default or attach only provider output that cites exact shot/keyframe
  timestamps.
- Degrade visibly when FFmpeg is unavailable, with an optional stable strict failure mode.
- Require explicit read/write grants and environment-only credentials for collaboration adapters.
- Preserve official provider pages before mapping and route pulled rows through the same strict
  import/quality pipeline as offline exports.
- Preview remote writes without sending them, reuse identical completed pushes, and surface partial
  writes instead of silently treating them as complete.
- Handle authorization, rate-limit, and provider-response failures with stable machine errors.
- Run auditable batches, emit due/future/available snapshot tasks, and keep team roles free of
  credential values.
- Preview the bounded calls for one Douyin homepage and turn its public profile, 1～100 posts, and
  bounded top-level comments into a traceable distillation. Require cost confirmation only for the
  optional paid TikHub route.
- Preview and process a bounded retained-video sample without manual per-video import, signed-URL
  disclosure, browser cookies, or cloud media upload.

## Verification evidence

The repository includes unit, contract, integration, and golden tests; seven offline fixture groups;
a 100,000-row generator; Ruff, mypy, pytest, and Skill validation commands; and a GitHub Actions
workflow for Python 3.11 and 3.14.

Final production acceptance on 2026-07-23 produced the following evidence:

- Ruff passed with no findings; mypy passed across 110 source and test files.
- All 107 offline tests passed with 89.04% statement coverage.
- The official Skill quick validator accepted the Skill; wrapper smoke tests cover data, sampling,
  report, transcript, blind-analysis, local media, comment, distillation, comparison, score,
  prediction, publication, Retro, authorized sync, Batch, Snapshot, Team, and status routes.
- An independent offline Skill forward test completed authorized-export import, Team initialization,
  Batch snapshot planning, validation, and status with network proxies blocked; its feedback added
  the explicit normalize step and direct Batch `artifact_path` output.
- The built `1.0.0` wheel was installed into a clean Python 3.11 environment on Windows, then ran
  18 operator subprocess commands from a Chinese path using 30 videos, 30 metric snapshots, 18
  comments, and a user-supplied hotel MP4. Final validation reported zero errors and warnings.
- `distiller doctor --json` is read-only, and Windows machine JSON is ASCII-safe through pipes while
  preserving decoded Chinese text.
- A deterministic 100,000-video fixture imported all 100,000 rows in about 4.4 seconds and rebuilt
  the normalized Parquet tables in about 4.4 seconds on the delivery workstation, with zero rejected
  rows and zero data-quality warnings. Timings are indicative, not a cross-machine performance SLA.

The current Phase 8 main-line increment is accepted with 141 tests and 88.35% statement coverage.
Provider contracts cover URL allowlisting, MediaCrawler sidecar pagination and manual
login errors, public-field mapping, pinned-runtime absence, TikHub credentials and HTTP
authorization/rate-limit errors, paid-call confirmation, secret non-disclosure, immutable response
validation, and the complete URL-to-distillation integration path. The first live MediaCrawler Edge
acceptance passed on 2026-07-23 with 10 videos, 10 metric snapshots, and 30 comments accepted,
zero row rejections, and zero final project validation findings. The live payload's unavailable
public view counts remain explicit instead of being converted into fabricated performance ranks.

## Not delivered yet

The repository does not include credential/CAPTCHA automation, proxy or stealth evasion, comment
reply trees, arbitrary video downloading, a cloud visual-model client, an installed background
scheduler, or a Web console. Opt-in video download is limited to retained approved MediaCrawler
evidence and allowlisted Douyin/CDN hosts. Phase 7 online behavior is limited to explicitly authorized Feishu Bitable and
Google Sheets official APIs. Phase 8's default MediaCrawler adapter is limited to personal
non-commercial learning/research; TikHub is an optional paid route. Public view counts may be
unavailable, and semantic video/transcript analysis still requires local media or transcripts.
Level 4 approval remains intentionally human-governed and requires repeated controlled evidence;
Phase 5 produces only pending proposals.

## Handoff

Read `README.md` for Quick Start, `docs/data-contracts.md` for machine contracts,
`docs/comment-and-account-distillation.md` for Phase 4 interpretation,
`docs/scoring-prediction-retro.md` for the Phase 5 learning loop,
`docs/local-media-analysis.md` for Phase 6 media evidence,
`docs/account-media-enrichment.md` for the retained public-video workflow,
`docs/authorized-collaboration-adapters.md` for Phase 7 authorization and synchronization,
`docs/phase8-account-url-analysis.md` for Phase 8 homepage collection and live acceptance,
`docs/adapter-guide.md` for field mappings, `docs/privacy-and-compliance.md` for boundaries, and
`docs/release-notes.md` for current and future updates.
