# Local media analysis

Phase 6 analyzes a user-provided local media file without contacting a platform or uploading the
file. `distiller analyze media` resolves an existing normalized video, hashes and preserves the
media, then uses a mockable local backend.

For a user-approved Douyin account already collected through MediaCrawler,
`distiller account enrich-media` can resolve the corresponding public media automatically from the
retained Provider batch. It still calls this same local service after download, so raw media,
scene/keyframe/audio artifacts, hashes, and validation behavior are identical. The account workflow
adds local Whisper transcription, single-video semantics, and re-distillation; see
`account-media-enrichment.md`.

## Pipeline

1. Resolve `--file` or the normalized video's `media_path` and calculate SHA-256.
2. Read container, duration, rotation, codecs, frame rate, dimensions, and audio-stream metadata
   through FFprobe.
3. Detect scene boundaries with FFmpeg's scene score and create stable `shot_*` intervals.
4. Extract a bounded set of middle-of-shot keyframes. Clips longer than ten seconds receive
   uniform fallback coverage when scene detection yields too few cuts, while `max_keyframes`
   remains a hard cap.
5. Decode a bounded mono PCM stream and calculate RMS/peak dBFS, dynamic range, windowed loudness
   variance, silence/activity ratios, and timestamped silence intervals.
6. Optionally pass a `MediaVisionBundle` to loopback Ollama/injected Provider or replay
   `--vision-output` JSON.
7. Write content-addressed artifacts and an aggregate `media_features.parquet` row.

The built-in `FFmpegMediaBackend` invokes executable argument arrays without a shell. It does not
install codecs, open a browser, or send data over a network.

## Outputs

```text
raw/media/<sha256>.<ext>
raw/vision-outputs/<sha256>.json
analyses/media/<video>/<mda_*>/
├── media-analysis.json
├── timeline.json
├── report.md
├── evidence-index.json
├── warnings.json
└── keyframes/<key_*>.jpg
normalized/media_features.parquet
```

Every shot has a non-overlapping millisecond interval. Every keyframe includes shot ID, timestamp,
path, and SHA-256. OCR observations must cite an existing shot and keyframe and remain inside the
shot interval. `distiller validate` checks all identities, paths, hashes, timeline copies, evidence,
and Parquet links.

## Degradation and strict modes

If FFmpeg is missing, the default writes a degraded artifact with the raw hash and unknown media
fields. `--strict-media` instead returns `E_MEDIA_DECODE`. A scene-detection failure falls back to a
single shot; keyframe or audio failures remain explicit warnings. No audio stream is `skipped`, not
fabricated as silence.

Without a visual provider, visual and OCR fields remain unknown and a skipped provider trace is
stored. Invalid visual output is retried up to `models.max_schema_attempts`; `--strict-vision`
returns `E_MODEL_SCHEMA_INVALID`, while the default preserves the deterministic media result and
marks visual analysis degraded.

Run local Qwen vision with:

```bash
distiller analyze media --project <dir> --video <video-id> --file <video.mp4> \
  --vision-provider ollama --vision-model qwen3-vl:8b \
  --vision-batch-size 4 --strict-vision --json
```

Only loopback port 11434 is accepted. Still frames can establish visible objects, scenes, color,
composition, lighting, text styles, branding, and OCR; they cannot prove motion, edit causality, or
performance impact.

## Privacy boundary

Keyframes may contain faces, room numbers, booking details, screens, license plates, or guests.
Treat the raw media, frames, OCR, and report as sensitive. The shipped Providers either read a
local structured JSON file or send bounded frames to a same-computer loopback Ollama process. Any
future cloud implementation requires explicit user authorization,
`privacy.allow_cloud_model_upload: true`, redaction/logging review, retention documentation, and
mocked contract tests.
