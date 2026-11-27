# Account media enrichment

This workflow closes the gap between public homepage metadata and actual video-content analysis.
It operates only on a retained MediaCrawler batch for a user-approved Douyin account.

## What it does

For a bounded sample of 1–20 videos, `AccountMediaEnrichmentService`:

1. Finds the latest immutable MediaCrawler batch for the internal account ID.
2. Resolves the corresponding normalized videos and prioritizes videos without a usable
   evidence-linked semantic result.
3. Extracts candidate play addresses from retained `aweme/detail` evidence without returning or
   logging signed URLs.
4. Downloads through HTTPS only from `douyin.com` or `douyinvod.com`, follows redirects only inside
   the same boundary, and enforces a 512 MiB per-file limit.
5. Runs the existing local FFmpeg pipeline for metadata, shots, bounded keyframes, and audio
   measurements. Long videos with too few detected cuts receive uniform fallback coverage instead
   of a single midpoint frame. The media is copied to `raw/media/<sha256>.mp4` before the temporary
   download is removed.
6. Optionally sends bounded keyframes to loopback Ollama/Qwen3-VL for strict scene, composition,
   color, lighting, artistic-text, branding, and OCR evidence.
7. Runs a local OpenAI Whisper CLI, imports the generated JSON transcript through
   `TranscriptImportService`, and rebuilds `transcripts.parquet`.
8. Runs blind single-video text analysis, then re-runs account distillation so content clusters,
   persona signals, measured framing/edit/audio signals, and warnings reflect the new evidence.
9. Writes one strict `AccountMediaEnrichment` artifact linking the retained Provider batch,
   media-analysis IDs, transcript hashes, text-analysis IDs, and resulting distillation.
10. Rebuilds a content-addressed account benchmark profile for later comparisons.

The implementation is adapted from the workflow shape of the pinned MIT
`bradautomates/claude-video` project. It uses the project's native media and evidence kernel rather
than executing upstream `watch.py`; the exact version and license are in
`THIRD_PARTY_NOTICES.md`.

## Commands

Preview an already collected account. This does not access the network or write:

```bash
uv run distiller account enrich-media --project <dir> --account <acc_id> \
  --limit 3 --whisper-model base --dry-run --json
```

Run the local workflow:

```bash
uv run distiller account enrich-media --project <dir> --account <acc_id> \
  --limit 3 --whisper-model base --vision-provider ollama \
  --vision-model qwen3-vl:8b --strict-vision --json
```

Use `--whisper-command <path>` or environment variable `DISTILLER_WHISPER_COMMAND` when `whisper`
is not on `PATH`. Use `--strict` to stop at the first download, decoder, transcription, or
single-video analysis failure. The default retains successful media work and reports degraded or
failed media-chain videos individually. A successfully completed local chain can still carry
`text_analysis_status: degraded` when it used the bounded local heuristic; this does not relabel
the media/transcription chain as failed.

A new homepage run can opt in directly:

```bash
uv run distiller account analyze --project <dir> --url <douyin-homepage> \
  --media-limit 3 --whisper-model base \
  --vision-provider ollama --vision-model qwen3-vl:8b --json
```

`--media-limit 0` is the default and preserves the metadata-only collection behavior.

## Artifacts

- Provider provenance:
  `raw/account-collections/mediacrawler/<collection-hash>/provider-batch.json`
- Immutable media: `raw/media/<media-sha256>.mp4`
- Immutable generated transcript:
  `raw/imports/transcripts/<transcript-sha256>.json`
- Media analysis: `analyses/media/<video>/<mda_*>/`
- Single-video analysis: `analyses/videos/<video>/<vta_*>/`
- Account enrichment:
  `analyses/accounts/<account>/media-enrichments/<ame_*>/enrichment.json`
- Rebuilt account report:
  `reports/accounts/<account>/<dst_*>/distillation.json`
- Reusable account snapshot:
  `analyses/accounts/<account>/benchmark-profiles/<abp_*>/profile.json`

The account enrichment artifact stores only the source batch hash/path and selected response host;
it never copies signed media URLs into stdout, run manifests, or reports. `distiller validate`
checks the source batch file hash, companion warning artifact, downstream analysis paths, and
distillation path.

## Interpretation and limits

The bundled local semantic fallback can classify explicit Chinese hotel operations, service,
housekeeping, job-search/career, and accommodation terms at confidence no higher than `0.45`. It
remains a degraded heuristic and is not a substitute for a reviewed structured model result.

Framing, median shot duration, and signal-level silence ratio are measured production signals.
Loopback Ollama can add visible scene/object, composition, lighting, color, text-style, branding,
and OCR labels tied to exact keyframes. It does not establish real identity, exact location, video
motion from still frames, music meaning, or causal performance effects. Without a visual Provider,
visual semantic identity and OCR remain unknown even though keyframe JPEG evidence exists locally.

Public URLs may expire. Re-run homepage collection normally when every retained candidate is
unavailable; do not obtain cookies, automate login, bypass verification, or evade platform limits.
Raw video, frames, and transcripts may contain guests, room numbers, screens, or booking details
and must not be committed or uploaded without separate explicit authorization.
