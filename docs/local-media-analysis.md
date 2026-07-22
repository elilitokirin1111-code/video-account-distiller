# Local media analysis

Phase 6 analyzes a user-provided local media file without contacting a platform or uploading the
file. `distiller analyze media` resolves an existing normalized video, hashes and preserves the
media, then uses a mockable local backend.

## Pipeline

1. Resolve `--file` or the normalized video's `media_path` and calculate SHA-256.
2. Read container, duration, rotation, codecs, frame rate, dimensions, and audio-stream metadata
   through FFprobe.
3. Detect scene boundaries with FFmpeg's scene score and create stable `shot_*` intervals.
4. Select at most the configured number of evenly distributed shots and extract one middle
   keyframe from each selected shot.
5. Decode a bounded mono PCM stream and calculate RMS/peak dBFS, dynamic range, windowed loudness
   variance, silence/activity ratios, and timestamped silence intervals.
6. Optionally pass a `MediaVisionBundle` to an injected provider or replay `--vision-output` JSON.
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

## Privacy boundary

Keyframes may contain faces, room numbers, booking details, screens, license plates, or guests.
Treat the raw media, frames, OCR, and report as sensitive. The shipped provider reads only a local
structured JSON file. Any future cloud implementation requires explicit user authorization,
`privacy.allow_cloud_model_upload: true`, redaction/logging review, retention documentation, and
mocked contract tests.
