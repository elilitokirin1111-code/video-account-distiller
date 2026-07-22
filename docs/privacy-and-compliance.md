# Privacy and compliance

## Offline-first defaults

Phase 0/1 performs no model calls and no live platform requests. Files remain local to the project.
No credentials are required.

## Raw data

- Original exports are preserved byte-for-byte and indexed by SHA-256.
- Raw files are not modified by validation, normalization, metrics, or reports.
- Project raw data, local state, secrets, caches, and generated analysis projects are excluded from
  Git by default.
- Validation recalculates hashes and reports integrity failures.

## Comment privacy

Raw author identifiers are never placed in normalized `Comment` records. When provided, they are
hashed with SHA-256. Reports should avoid exposing usernames or full identifiers. Hashing is
pseudonymization, not anonymization; access to raw exports must still be controlled.

## Secrets and logging

`.distiller-secrets*` is ignored except for the empty example file. Machine results go to stdout;
logs and human errors go to stderr. Credentials must never appear in either channel or in run
manifests.

## Platform compliance

This repository does not implement scraping, login automation, CAPTCHA handling, anti-bot bypass,
rate-limit bypass, or other platform-control evasion. Future collection must use authorized APIs,
explicitly permitted adapters, or user-provided exports and must document platform-specific terms.

## User responsibilities

Confirm that exported data may be processed, minimize personal data, restrict project access, honor
deletion and retention requirements, and avoid committing raw or normalized user data to GitHub.
