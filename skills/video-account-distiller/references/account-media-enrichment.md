# Retained account media enrichment

Use this only after a user-approved Douyin homepage has a valid retained MediaCrawler batch and the
user explicitly wants actual public videos processed locally.

## Preview

```bash
uv run distiller account enrich-media --project <dir> --account <acc_id> \
  --limit 3 --whisper-model base --dry-run --json
```

Dry-run reads project evidence only. Confirm:

- the account and retained batch path/hash match;
- selected videos are bounded from 1 through 10;
- candidate hosts are only Douyin or Douyin VOD domains;
- local Whisper is available;
- `would_write` remains inside the project.

Do not request, display, retain separately, or log signed candidate URLs.

## Execute

```bash
uv run distiller account enrich-media --project <dir> --account <acc_id> \
  --limit 3 --whisper-model base --vision-provider ollama \
  --vision-model qwen3-vl:8b --json
uv run distiller validate --project <dir> --json
```

The default selection prioritizes Provider-order videos without a usable evidence-linked semantic
result, so repeated bounded runs can expand coverage. Use `--strict` only when the user wants the
whole run to stop on the first download, decoder, transcription, or analysis failure. Without
strict mode, report per-video `complete`, `degraded`, or `failed` media-chain status. Report
`text_analysis_status` separately because a complete local media/transcription chain may use a
degraded bounded semantic heuristic.

The adapter:

1. reads candidates from immutable MediaCrawler `aweme/detail` evidence;
2. allows HTTPS `douyin.com`/`douyinvod.com` request and redirect hosts only;
3. limits a file to 512 MiB and writes only to a service-owned temporary directory;
4. calls the existing local media pipeline, which copies media to `raw/media/<sha256>.mp4` and
   adds bounded uniform keyframes when a long clip has too few detected cuts;
5. invokes local OpenAI Whisper without a shell or cloud API;
6. optionally sends bounded keyframes only to loopback Ollama for strict local visual/OCR labels;
7. imports transcript JSON through normal raw/staging/Parquet contracts;
8. runs blind single-video analysis, account re-distillation, and benchmark-profile rebuild;
9. writes `analyses/accounts/<account>/media-enrichments/<ame_*>/`.

Set `DISTILLER_WHISPER_COMMAND` or pass `--whisper-command` when the executable is not on `PATH`.
Never use credentials, Cookie contents, browser automation, CAPTCHA handling, proxy/stealth
features, or platform-control evasion for this route.

## Interpret

Return media-analysis, transcript, text-analysis, enrichment, and distillation paths. A local
keyword fallback may identify explicit hotel operations, service, housekeeping, job-search/career,
and accommodation language but stays degraded with confidence no greater than `0.45`.

`visual_and_audio_identity` may contain measured portrait orientation, median shot duration,
signal-level silence activity, or schema-backed visual annotations. It does not prove who or what
appears, music meaning, editing causality, or performance impact. Without a visual Provider, keep
visual semantic identity and OCR unknown. Public-view gaps can still prevent performance Patterns
even when semantic coverage improves.

Treat media, frames, voices, and transcripts as sensitive. Keep them local and out of Git. The
pinned `third_party/claude-video` MIT source is a workflow reference; do not invoke upstream
`watch.py` in the account pipeline.
