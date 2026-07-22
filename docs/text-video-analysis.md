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
