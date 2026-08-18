# Transcript import and blind video analysis

## Scope

Phase 3 analyzes user-provided subtitle text. It supports SRT, VTT, TXT, JSON, and JSONL, but does
not decode media, run speech recognition, inspect frames, or access a platform. TXT segments keep
unknown timing as `null`.

## Two-stage anti-hindsight flow

1. Import and normalize transcript segments with immutable raw hashes.
2. Build `BlindVideoBundle` from title, description, duration, language, and transcript only.
3. Run fact extraction and semantic labeling against strict Pydantic Schema.
4. Validate every cited segment ID.
5. Freeze `blind-analysis.json` and prompt hashes.
6. Load the latest metric and account-local derived-metric rows.
7. Attach performance context without changing content labels.

The bundle rejects views, likes, comments, shares, saves, performance score/band, promotion,
engagement, and completion fields. This prevents “high views therefore good Hook” circular labels.

## Provider and degradation policy

The built-in `StructuredFileProvider` reads offline JSON and performs no network operation. Task
values may be arrays so invalid candidates can be followed by corrected retry candidates. The
project config controls `max_schema_attempts`.

After repeated failure, default behavior emits deterministic observable facts, limited conservative
text heuristics, low confidence, explicit unknowns, and warnings. `--strict-model` instead returns
`E_MODEL_UNAVAILABLE` or `E_MODEL_SCHEMA_INVALID`. See `docs/model-provider-guide.md`.

## Evidence and outputs

Artifacts live under `analyses/videos/<video-id>/<vta-id>/`:

- `analysis.json`: blind labels plus stage-two performance context.
- `blind-analysis.json`: content-only facts, labels, task attempts, prompt hashes, and warnings.
- `report.md`: readable Hook/structure/CTA/emotion breakdown.
- `evidence-index.json`: transcript segment and metric provenance.
- `warnings.json`: degradation, confidence, text-only, and causal-limit warnings.

`segment_to_evidence` resolves each cited segment to an `evi_*` item and then to the normalized
record ID, source record ID, raw hash, and import run.

Both transcript import and video analysis accept either the internal `vid_*` or a unique platform
video ID. Run `distiller validate` after analysis to verify artifact Schema, blind-stage isolation,
raw model-output hashes, declared paths, and evidence references in one command.

## Interpretation limits

Semantic labels are annotations, not causes. One analyzed video cannot establish an account Pattern
or validated rule. Visual Hook, shots, editing rhythm, on-screen text, music, and sound remain
unknown until Phase 6. Phase 4 will compare repeated labeled samples, counterexamples, and comments.

## Single-video deep distillation

`distiller analyze video --deep` adds an optional third stage on top of the blind text analysis
and any existing local media analysis. It builds one content-addressed `svd_*` reference card under
`analyses/videos/<video-id>/` so you can distill one interesting video from an account you do not
otherwise follow, without any account-level performance bands:

- **选材 topic**: why the video exists, its angle (痛点/清单/悬念/身份点名…), target audience,
  information increment, memory point, and a reusable topic formula.
- **表现形式 expression**: opening form, subtitle/art-text style, packaging (stickers, motion
  graphics, branding), audio expression, and editing style.
- **拍摄手法 craft**: shot-scale/camera/composition/lighting profiles, opening technique, and
  pacing, plus a deterministic per-shot `craft_summary` with counts and measured rhythm.
- **可复制清单 copy checklist**: what to copy and what to avoid when reproducing the video.

The deep stage accepts `--deep-provider ollama|llamacpp|cloud` with `--deep-model`,
`--deep-base-url`, `--deep-api-key`, or offline `--deep-output` JSON. Model output is strictly
validated, citations to `segment_id`/`shot_id` are filtered against real evidence, and invalid
output is retried up to `max_schema_attempts`. Without a provider the service degrades visibly to a
deterministic aggregation of the blind labels and measured media features (`status: degraded`,
`deep_model_unavailable_deterministic_fallback`), which still organizes topic/structure/craft into
the same report shape. `--strict-deep` fails instead of degrading. `distiller validate` checks the
`svd_*` artifacts, their evidence index, and the referenced text/media analyses.

