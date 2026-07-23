# Local media analysis

Resolve an existing normalized video and a user-provided local media path. The default command is:

```bash
uv run distiller analyze media --project <dir> --video <video-id> \
  --file <video.mp4> --json
```

The local pipeline hashes and preserves the media, reads FFprobe metadata, detects FFmpeg scene
boundaries, extracts bounded middle-of-shot keyframes, adds uniform coverage when long clips have
too few detected cuts, decodes a bounded mono PCM stream,
and writes timestamped evidence. It never opens a browser or uploads the file.

Outputs live under `analyses/media/<video>/<mda_*>/` and include `media-analysis.json`,
`timeline.json`, `report.md`, `evidence-index.json`, `warnings.json`, and `keyframes/`. Aggregate
features are queryable from `normalized/media_features.parquet` and the DuckDB `media_features`
view. Raw media and replayed visual output are stored by SHA-256.

Interpret audio fields as signal measurements, not speech meaning. `has_audio: false` means no
decodable stream; `null` means decoding was unavailable. Silence is a configured dBFS threshold,
not proof that nobody spoke. Scene boundaries are detector output, not semantic story beats.

Use `--max-keyframes <1-100>` for a bounded, evenly distributed sample and
`--scene-threshold <0-1>` to tune scene sensitivity. Different effective settings or Provider
results may create separate immutable `mda_*` analyses for the same media hash. Status reports the
count; the returned artifact paths identify the exact result.

Without a visual provider, OCR and visual labels remain unknown. To replay a local result, pass
`--vision-output <json>` with `model_name` and a `media_vision` object or retry array. Every visual
annotation must cite an existing shot; every OCR observation must cite an existing keyframe and a
millisecond interval inside its shot.

Use `--strict-media` to stop with `E_MEDIA_DECODE` when FFmpeg/FFprobe is unavailable or metadata
cannot be decoded. The default degrades visibly. Use `--strict-vision` to stop on invalid visual
Schema; otherwise deterministic media results are retained with warnings.

Run `distiller validate` after generation. Verify raw media hash, keyframe hashes, timeline copies,
evidence identity, OCR timing, and `media_features.parquet` links. Treat raw media, frames, OCR, and
reports as sensitive; do not upload them unless the user separately authorizes that exact action
and project privacy policy allows it.

Do not confuse analysis warnings with validator warnings. An expected limitation such as “visual
Provider not supplied” belongs in the analysis warning file. Project validation can still report
zero warnings when the limitation is explicit and every Schema, path, hash, and evidence link is
valid.

For an approved account already collected with MediaCrawler, use `account enrich-media` rather
than manually locating each file. That route downloads only allowlisted candidates from retained
Provider evidence and then calls this same media service before local transcription and account
re-distillation. Read `account-media-enrichment.md`.
