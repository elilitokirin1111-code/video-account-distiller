# Privacy and compliance

## Offline-first defaults

Phase 0/1/2/5 performs no model calls. Phase 3/4 accepts local structured model-output files or uses a
deterministic fallback; it ships no network model client. Phase 7 may contact only a user-configured,
explicitly authorized Feishu Bitable or Google Sheets official API. Offline analysis needs no
credentials. Phase 8 may use the controlled, pinned MediaCrawler adapter for a user-approved public
Douyin homepage in the declared personal non-commercial research scope, or the optional fixed-host
TikHub API after explicit cost confirmation.

## Raw data

- Original exports are preserved byte-for-byte and indexed by SHA-256.
- Raw files are not modified by validation, normalization, metrics, or reports.
- Project raw data, local state, secrets, caches, and generated analysis projects are excluded from
  Git by default.
- Validation recalculates hashes and reports integrity failures.
- Subtitle and structured model-output bytes are also preserved under content-addressed raw paths.
- Phase 6 local media is copied under `raw/media/`; keyframes, OCR, and timelines remain inside the
  project. They may reveal guests, room numbers, screens, booking data, faces, or license plates.
- Phase 5 script candidates are copied byte-for-byte under `raw/candidates/`; they may contain
  confidential campaign, price, product, employee, or customer information and require the same
  access controls as raw exports.
- Phase 7 provider pages are copied under `raw/collaboration/` before mapping. They may include
  collaboration-only fields or personal data and require the same access controls as raw exports.
- Phase 8 public account batches are copied under `raw/account-collections/` before mapping. When
  comment sampling is enabled, raw pages may include public usernames and identifiers.
  Public availability does not make them unrestricted; apply the user's retention and sharing
  policy.

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

The shipped Phase 6 visual Providers either read local structured JSON or call same-computer
loopback Ollama on port 11434. Remote hosts, credentials, alternate ports, and URL paths are
rejected. FFmpeg/FFprobe are local processes and do not upload media. Treat extracted keyframes and
OCR as sensitive raw-derived evidence; review and redact them before sharing outside the project.

Phase 5 scoring, prediction, publication, and Retro are deterministic and local. Prediction files
record versions and hashes, not credentials. Publication URLs and notes may still be sensitive;
reports should be reviewed before sharing. Retro keeps actual metric evidence and counterexamples
instead of hiding unfavorable results. Rule/Rubric proposals remain pending so a single publication
cannot silently alter decision policy.

Phase 7 connector YAML/JSON and `team.yaml` store only token environment-variable names, grants,
roles, and resource identifiers. Actual tokens must come from the process environment or an external
secret manager. Errors expose an HTTP/provider code when useful but never response headers, request
authorization headers, or token values. Sync and Batch outputs record counts, hashes, IDs, and paths,
not credentials.

Phase 8 MediaCrawler collection may open a dedicated visible Chrome profile under the user's home
directory. The user completes login and platform verification manually. The project does not copy
Cookie values, local storage, passwords, or session material into analysis artifacts, logs, or Git.
The CLI comment defaults remain bounded and can be disabled with `--comments-per-video 0`.

The optional TikHub route reads `TIKHUB_API_KEY` only from the process environment and allows only
`api.tikhub.dev`/`api.tikhub.io`. Dry-run makes no request. Real TikHub calls require explicit cost
confirmation, and outputs never contain the token or authorization header.

Opt-in account media enrichment reads signed public-video candidates only from the immutable
MediaCrawler batch for the approved account. It permits HTTPS Douyin/CDN hosts only, validates the
redirect host, enforces a file-size limit, and never returns or logs the signed URL. Downloaded
bytes are copied into content-addressed `raw/media/` before the service-owned temporary directory
is removed. No Cookie or browser session is supplied to the downloader.

Whisper transcription runs through a local executable and generated subtitles pass through the
same immutable import/normalization path as user-provided subtitles. Media, extracted audio,
frames, and transcripts are not uploaded. They may still expose guests, staff, room numbers,
screens, voices, or booking information; restrict project access and review/redact them before
sharing. The pinned `claude-video` source retains its MIT license and is used as an attributed
workflow reference, not as a network service.

## Platform compliance

The controlled MediaCrawler path reads public pages only for a user-approved URL and bounded sample.
It does not invoke upstream proxy, stealth, automatic-login, slider/CAPTCHA, or risk-control-evasion
features. Platform challenges remain manual user actions; unresolved challenges stop with a stable
error. Other collection is limited to authorized official APIs, the optional fixed-host TikHub
Provider, or user-provided exports. HTTP 429 responses receive bounded backoff and then fail; the
software never attempts to evade a provider limit.

MediaCrawler keeps its upstream non-commercial learning license. Preserve
`THIRD_PARTY_NOTICES.md` and the submodule license, and complete a separate licensing review before
commercial use, hosted service, or paid delivery.

## User responsibilities

Confirm that exported data may be processed, minimize personal data, restrict project access, honor
deletion and retention requirements, and avoid committing raw or normalized user data to GitHub.
