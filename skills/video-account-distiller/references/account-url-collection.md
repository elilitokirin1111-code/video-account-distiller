# Account homepage collection

Use this workflow only for a user-approved public Douyin homepage.

## Provider choice

Use `mediacrawler` by default for the declared personal, non-commercial research workflow. It uses
the repository-pinned submodule and a visible dedicated Chrome profile. The user performs login or
platform verification manually. Never invoke MediaCrawler proxy, stealth, automatic-login,
slider/CAPTCHA, or risk-control-evasion features.

Use `tikhub` only when the user explicitly wants the API route and accepts its current billing.
Keep `TIKHUB_API_KEY` in the local environment, always preview, and require
`--confirm-provider-cost` for real TikHub calls.

## Run

Preview first. Dry-run performs no network access, browser launch, or project writes:

```bash
uv run distiller account analyze --project <dir> --url <url> \
  --sort latest --dry-run --json
```

Run the default complete workflow:

```bash
uv run distiller account analyze --project <dir> --url <url> \
  --sort latest --json

uv run distiller validate --project <dir> --json
```

The first run may prepare the pinned sidecar environment and open Chrome. Keep the browser visible;
the user must complete login or verification. The dedicated profile is outside the analysis
project and repository.

When the user requests local Microsoft Edge, set
`MEDIACRAWLER_BROWSER_CHANNEL=msedge`; it uses a separate dedicated Edge profile and preserves the
same manual-authentication boundary.
For a slower first login, set `MEDIACRAWLER_LOGIN_TIMEOUT_SECONDS` to an integer from 30 through
900. Page navigation during manual authentication is transient until that bounded timeout expires.
Full-homepage collection allows up to 3,600 seconds by default. Set
`MEDIACRAWLER_PROCESS_TIMEOUT_SECONDS` from 60 through 3,600 only to tighten that local process
deadline; never use timeout changes to evade platform verification or limits.

The CLI defaults to every Provider-exposed homepage video and stops when `has_more` is false.
`--count <1-20000>` is an optional explicit limit. Full-homepage mode also detects repeated
cursors and has a 1,000-page/20,000-video emergency guard; disclose a safety-limit warning as
incomplete collection. Comments remain bounded at 10 comments per video from at most three
high-comment collected videos. Use `--comments-per-video 0` when the user wants a smaller
personal-data scope; allowed maxima are 20 comments for each of at most 10 sampled videos.

For the optional paid API route:

```bash
uv run distiller account analyze --project <dir> --url <url> \
  --provider tikhub --dry-run --json

uv run distiller account analyze --project <dir> --url <url> \
  --provider tikhub --confirm-provider-cost --json
```

## Interpret

The command returns public account/profile rows, videos, visible interaction snapshots, bounded
top-level comments, immutable Provider evidence, normalized Parquet, robust metrics, account-health
artifacts, comment-demand analysis, account distillation, and a reusable `abp_*` benchmark profile.
Later runs retain earlier raw batches and profiles, so new accounts or newer snapshots can be
compared without re-entering old data.

Public homepage data usually lacks completion rate, average watch time, follower count at
publication, full comment coverage/reply trees, traffic source, audience composition, and
promotion truth. Preserve these as unknown. Describe the first output as quantitative homepage
distillation until transcripts or local media analysis add semantic evidence.

Popular sort covers the complete Provider-exposed homepage set in default full mode. When an
explicit `--count` is supplied, popular sort is only within the bounded pool read for that request.
Comments are biased samples, not the whole audience. Raw pages may contain public identifiers;
canonical comments retain only author hashes and analysis uses direct-identifier redaction.

Homepage collection defaults to metadata-only. When the user separately approves actual public
video processing, pass `--media-limit <1-10>` or use the existing account ID with
`distiller account enrich-media`. Read `account-media-enrichment.md`; keep signed URLs inside the
raw batch and all media/transcription local.

## Failure handling

- `E_PROFILE_URL_INVALID`: request a valid public HTTPS Douyin homepage.
- `E_MEDIACRAWLER_UNAVAILABLE`: initialize the submodule and inspect `distiller doctor --json`.
- `E_BROWSER_LOGIN_REQUIRED`: rerun and let the user complete login in visible Chrome.
- `E_COLLECTION_TIMEOUT`: reduce scope or inspect the visible browser; do not evade controls.
- `E_PROVIDER_COST_CONFIRMATION_REQUIRED`: TikHub only; preview and obtain cost approval.
- `E_ADAPTER_AUTH`: TikHub only; inspect key presence without exposing its value.
- `E_RATE_LIMIT`: stop and retry later; never bypass a limit.
- `E_ADAPTER_RESPONSE`: preserve no invented data; repair only the Provider mapping.

If optional comments fail, keep the valid account/video/metric batch and report the
`comment_collection_degraded:<E_* code>` warning. For live acceptance, validate the project,
manually compare at least three public posts, and confirm Git/logs contain no credentials or
browser-session material.
