# Account homepage collection

Use this workflow only for a user-approved public Douyin homepage.

## Profiles and provider choice

`standard` is the default: TikHub, 20 homepage videos, latest order, no comments. TikHub is a paid
API, so keep `TIKHUB_API_KEY` in the environment, preview first, and require
`--confirm-provider-cost` for execution.

`comprehensive` means all Provider-exposed homepage videos up to the 1,000-page/20,000-video
emergency guards, plus at most 20 top-level comments from each of three sampled videos. It does not
mean every comment, replies, deleted content, fan profiles, private creator metrics, or unlimited
media download.

`owned` keeps public collection bounded while signaling that authorized platform exports or
official table/API connectors will be imported separately. The public Provider cannot supply
completion, watch time, conversion, revenue, traffic-source, or fan-demographic data.

Use `mediacrawler` only for the declared personal, non-commercial research workflow. It uses the
repository-pinned sidecar and a visible dedicated browser profile. The user performs login or
platform verification manually. Never invoke proxy, stealth, automatic-login, slider/CAPTCHA, or
risk-control-evasion features.

## Preview and run

Dry-run performs no network access, browser launch, or project writes:

```bash
uv run distiller account analyze --project <dir> --url <url> \
  --profile standard --max-provider-calls 10 --dry-run --json
```

Review these fields:

- `collection_scope`: requested video/comment limits and emergency termination.
- `provider_calls`: maximum endpoint calls before execution.
- `budget`: whether the explicit hard ceiling is sufficient.
- `billing`: maximum potentially chargeable calls.
- `capabilities`: available evidence and fields that are not guaranteed.

Execute TikHub only after approval:

```bash
uv run distiller account analyze --project <dir> --url <url> \
  --profile standard --max-provider-calls 10 \
  --confirm-provider-cost --json
uv run distiller validate --project <dir> --json
```

For comprehensive planning:

```bash
uv run distiller account analyze --project <dir> --url <url> \
  --profile comprehensive --dry-run --json
```

The potentially large plan must be narrowed with `--count`, `--comments-per-video`, and
`--comment-video-limit`, or explicitly bounded with `--max-provider-calls`, before execution.

For the optional local research sidecar:

```bash
uv run distiller account analyze --project <dir> --url <url> \
  --provider mediacrawler --count 20 --dry-run --json
```

The first run may prepare the sidecar and open Chrome. Keep it visible and let the user complete
login. `MEDIACRAWLER_BROWSER_CHANNEL=msedge` selects a dedicated Edge profile.
`MEDIACRAWLER_LOGIN_TIMEOUT_SECONDS` may be 30–900 and
`MEDIACRAWLER_PROCESS_TIMEOUT_SECONDS` may be 60–3,600; never use timeout changes to evade controls.

## Interpret coverage

The execution result includes `coverage`:

- Video status states whether the requested limit was reached, the Provider was exhausted, or an
  emergency guard stopped collection.
- Comment status always says `bounded_top_level_sample_not_full_comment_universe`.
- Account snapshot flags show whether follower, following, total-like, and video-count values were
  observed.
- Warnings expose degraded comment/detail calls and missing public fields.

Repeated collection preserves earlier raw batches and normalized account snapshots. Use
`distiller account growth` only after at least two time-separated snapshots. Missing metrics remain
unknown; never substitute zero.

Homepage collection is metadata-only by default. Actual media processing requires separate
approval and a bounded `--media-limit <1-10>` with MediaCrawler retained detail evidence, or a later
`distiller account enrich-media` run. Keep signed URLs inside raw evidence and all media/transcript
processing local unless the user separately approves remote processing.

## Failure handling

- `E_PROFILE_URL_INVALID`: request a valid public HTTPS Douyin homepage.
- `E_COLLECTION_BUDGET_EXCEEDED`: reduce scope or approve a higher call ceiling.
- `E_PROVIDER_COST_CONFIRMATION_REQUIRED`: review dry-run billing and obtain approval.
- `E_MEDIACRAWLER_UNAVAILABLE`: initialize the sidecar and inspect `distiller doctor --json`.
- `E_BROWSER_LOGIN_REQUIRED`: rerun and let the user complete visible login.
- `E_COLLECTION_TIMEOUT`: reduce scope or inspect the visible browser; do not evade controls.
- `E_ADAPTER_AUTH`: inspect token presence without printing its value.
- `E_RATE_LIMIT`: stop and retry later; never bypass a limit.
- `E_ADAPTER_RESPONSE`: preserve no invented data; repair only the Provider mapping.

If optional comments fail, keep the valid account/video/metric batch and report the
`comment_collection_degraded:<E_* code>` warning. For live acceptance, validate the project,
manually compare at least three public posts, and confirm Git/logs contain no credentials or
browser-session material.
