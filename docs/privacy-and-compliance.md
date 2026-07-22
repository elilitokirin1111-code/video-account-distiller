# Privacy and compliance

## Offline-first defaults

Phase 0/1/2/5 performs no model calls. Phase 3/4 accepts local structured model-output files or uses a
deterministic fallback; it ships no network model client and makes no live platform request. No
credentials are required.

## Raw data

- Original exports are preserved byte-for-byte and indexed by SHA-256.
- Raw files are not modified by validation, normalization, metrics, or reports.
- Project raw data, local state, secrets, caches, and generated analysis projects are excluded from
  Git by default.
- Validation recalculates hashes and reports integrity failures.
- Subtitle and structured model-output bytes are also preserved under content-addressed raw paths.
- Phase 5 script candidates are copied byte-for-byte under `raw/candidates/`; they may contain
  confidential campaign, price, product, employee, or customer information and require the same
  access controls as raw exports.

## Comment privacy

Raw author identifiers are never placed in normalized `Comment` records. When provided, they are
hashed with SHA-256. Reports should avoid exposing usernames or full identifiers. Hashing is
pseudonymization, not anonymization; access to raw exports must still be controlled.

Phase 2 evidence indexes contain normalized/source record IDs, hashes, and run IDs, not raw comment
author identifiers or raw comment text. Account-health reports aggregate video-level metrics and
do not publish raw exports.

Phase 4 comment analysis creates a separate cleaned copy and redacts common phone numbers, email
addresses, URLs, social handles, and contact IDs before prompting or reporting. The immutable raw
comment and normalized comment are not rewritten. Reports use comment IDs and redacted excerpts,
never raw author IDs or `author_hash` values. Redaction is best-effort and does not replace human
review before sharing.

Comment clusters are biased samples, not population estimates. Reports explicitly retain warnings
for platform ranking, pinning, deletion, export limits, controversy amplification, and the gap
between commenters and all viewers. Purchase-intent labels are annotations, not conversion claims.

Phase 3 reports may contain transcript excerpts because they are required content evidence. Treat
transcripts as potentially sensitive. Evidence indexes store cited text, timing, normalized/source
IDs, hashes, and source runs. Do not publish reports without reviewing personal or confidential
content.

## Secrets and logging

`.distiller-secrets*` is ignored except for the empty example file. Machine results go to stdout;
logs and human errors go to stderr. Credentials must never appear in either channel or in run
manifests.

`privacy.allow_cloud_model_upload` defaults to false. The shipped Phase 3/4 provider reads local JSON
only; adding any cloud provider requires explicit user authorization, policy checks, a documented
retention boundary, redacted logging, and independent contract tests.

Phase 5 scoring, prediction, publication, and Retro are deterministic and local. Prediction files
record versions and hashes, not credentials. Publication URLs and notes may still be sensitive;
reports should be reviewed before sharing. Retro keeps actual metric evidence and counterexamples
instead of hiding unfavorable results. Rule/Rubric proposals remain pending so a single publication
cannot silently alter decision policy.

## Platform compliance

This repository does not implement scraping, login automation, CAPTCHA handling, anti-bot bypass,
rate-limit bypass, or other platform-control evasion. Future collection must use authorized APIs,
explicitly permitted adapters, or user-provided exports and must document platform-specific terms.

## User responsibilities

Confirm that exported data may be processed, minimize personal data, restrict project access, honor
deletion and retention requirements, and avoid committing raw or normalized user data to GitHub.
