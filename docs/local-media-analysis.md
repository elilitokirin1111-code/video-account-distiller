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
shot scale, best-effort camera motion, camera angle, composition, lighting, text styles,
branding, and OCR; they cannot prove motion, edit causality, or performance impact.

### Shooting-technique and expression-form fields

The vision contract (prompt `1.4.0`) adds three dedicated craft fields per frame on top of the
existing composition/camera/lighting labels:

- `shot_scale`: visible shot scale such as 特写/近景/中景/全景/远景.
- `camera_movement`: best-effort camera motion such as 固定机位/手持/推镜/摇镜/移镜/跟拍.
- `camera` (legacy field kept): viewpoint/angle such as 平视/俯视/仰视/斜角; it is mirrored into
  `ShotVisualAnnotation.camera_angle`.

Field-name echoes and “无/未知/未确认” tokens are filtered out. Each `MediaFeatureRecord` row
aggregates the per-shot labels into `shot_scale_tags`, `camera_movement_tags`, `camera_angle_tags`,
`composition_tags`, `lighting_tags` (old rows keep the merged `visual_style_tags`), plus two
deterministic derived lists:

- `opening_technique_tags`: readable opening tags from the first shot, e.g.
  特写开场 / 固定机位开场 / 开场大字标题 / 开场即出字幕.
- `pacing_tags`: 快节奏剪辑 (<1.5 s average shot) / 中等节奏剪辑 (≤3.5 s) / 慢节奏剪辑.

The account-level distillation aggregates these into a `craft_profile`; see
`comment-and-account-distillation.md`. The per-video craft summary also feeds the optional
single-video deep distillation (`distiller analyze video --deep`), which merges the blind text
analysis with these media features into one 选材/表现形式/拍摄手法/可复制清单 reference card; see
`text-video-analysis.md`.

## Privacy boundary

Keyframes may contain faces, room numbers, booking details, screens, license plates, or guests.
Treat the raw media, frames, OCR, and report as sensitive. The shipped Providers either read a
local structured JSON file or send bounded frames to a same-computer loopback Ollama process. Any
future cloud implementation requires explicit user authorization,
`privacy.allow_cloud_model_upload: true`, redaction/logging review, retention documentation, and
mocked contract tests.
