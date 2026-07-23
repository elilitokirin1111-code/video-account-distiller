# Account homepage collection

Use this workflow only for a user-approved public Douyin homepage.

## Guardrails

1. Accept only an HTTPS `douyin.com` URL.
2. Use `distiller account analyze --dry-run --json` first.
3. Show the maximum Provider calls and confirm that TikHub may charge for them.
4. Keep `TIKHUB_API_KEY` in the local environment. Never print, persist, or request it in chat.
5. Add `--confirm-provider-cost` only after approval.
6. Never use browser state, Cookie, login automation, CAPTCHA handling, direct page scraping, or
   risk-control evasion.

The fixed allowed API bases are `https://api.tikhub.dev` for mainland China and
`https://api.tikhub.io` elsewhere. Do not add an arbitrary base URL.

## Run

```bash
uv run distiller account analyze --project <dir> --url <url> \
  --count 10 --sort latest --dry-run --json

uv run distiller account analyze --project <dir> --url <url> \
  --count 10 --sort latest --confirm-provider-cost --json

uv run distiller validate --project <dir> --json
```

Use `--sort popular` only when the user requests a popularity-oriented sample. Counts are 1–100;
the default 10 matches a quick benchmark scan.

Comment text is disabled by default. When the user needs pain-point, objection, or demand analysis,
preview a bounded sample first:

```bash
uv run distiller account analyze --project <dir> --url <url> \
  --count 20 --comments-per-video 20 --comment-video-limit 3 --dry-run --json
```

This adds at most one comment call for each sampled video. The Provider selects already-collected
videos by visible comment count and reads only the first top-level comment page. After cost and
retention approval, replace `--dry-run` with `--confirm-provider-cost`.

## Interpret

The command returns:

- public account profile and internal `acc_*` ID;
- public videos and visible interaction snapshots;
- optional public top-level comments from a bounded high-comment-video sample;
- immutable Provider response and per-entity import quality;
- normalized Parquet and account-local robust metrics;
- account-health and distillation artifacts.

Public homepage data usually lacks completion rate, average watch time, follower count at
publication, full comment coverage/reply trees, traffic source, audience composition, and
promotion truth. Preserve these as unknown. Do not substitute current followers for
publication-time followers.

Expect `comment_analysis_missing` when comment sampling is disabled or yields no usable rows, and
expect low semantic-coverage warnings until the user adds subtitles or local video analysis.
Describe the initial output as quantitative homepage distillation, not full creative-semantic
learning. Raw comment pages may contain public identifiers; canonical rows retain only author
hashes and analysis uses the existing direct-identifier redaction pipeline.

## Failure handling

- `E_PROFILE_URL_INVALID`: request a valid public Douyin homepage URL.
- `E_PROVIDER_COST_CONFIRMATION_REQUIRED`: return to dry-run and obtain approval.
- `E_ADAPTER_AUTH`: inspect only the presence of `TIKHUB_API_KEY`; never expose its value.
- `E_RATE_LIMIT`: preserve bounded retry behavior and retry later.
- `E_ADAPTER_RESPONSE`: retain no invented data; update only the Provider mapping when a documented
  payload changes.

If only the optional comment endpoint fails, expect
`comment_collection_degraded:<E_* code>` in collection warnings. Stop further comment calls, keep
the valid account/video/metric batch, and describe the result as quantitative-only rather than
discarding the successful core collection.

For first live acceptance, use 10 videos, validate the project, manually compare three public posts,
and verify that outputs and Git contain no credential or authorization header.
