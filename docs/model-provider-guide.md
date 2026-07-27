# Text model provider guide

## Text providers

Phase 3/4 intentionally ships only an offline structured-file provider. This keeps model calls
mockable, tests network-free, and user content local. A response file contains:

```json
{
  "model_name": "model-and-version",
  "video_fact_extraction": {},
  "video_semantic_labeling": {},
  "comment_intent": []
}
```

Use an array for any task to supply retry candidates. Comment analysis consumes one valid candidate
per comment (plus invalid candidates used by retries); exhausted candidates never repeat silently.
The CLI copies the response bytes to
`raw/model-outputs/<sha256>.json`, records the hash in the run manifest, and never overwrites it.

## Provider protocol

Custom providers implement `TextModelProvider.generate_structured(prompt, response_model, ...)`.
They must return the requested Pydantic model, keep temperature deterministic by default, avoid
logging prompt content or credentials, expose provider/model names, and surface Schema failures
without silently repairing unsupported fields.

Before adding a cloud implementation:

1. Require explicit user authorization and `privacy.allow_cloud_model_upload: true`.
2. Document retention, region, model name, and content-use terms.
3. Ensure no transcript, comment text, or credential is printed to logs.
4. Keep the blind content bundle free of metrics.
5. Add mocked provider, privacy, retry, timeout, and Schema contract tests.
6. Redact comment direct identifiers before upload and preserve raw response hashes/prompt versions.

No current text-analysis command contacts OpenAI or any other model service.

Phase 5 scoring, prediction, publication, and Retro do not use this provider. Their formulas,
intervals, version linkage, and approval boundary are deterministic. A future model may suggest
language improvements only behind a separately validated Schema; it must not overwrite scores,
predictions, actual snapshots, Rule status, or approval metadata.

## Phase 6 visual/OCR provider

`VisionModelProvider.analyze(MediaVisionBundle)` is a separate mockable boundary. The bundled
`StructuredVisionFileProvider` replays local JSON with `model_name` and a `media_vision` object or
retry array. It performs no network operation. Every returned annotation must cite an existing
`shot_id`; every OCR observation must cite an existing `keyframe_id` and timestamp interval.

The bundle contains local keyframe paths so an explicitly supplied custom local Provider can read
them. The bundled `OllamaVisionProvider` accepts only
`http://127.0.0.1:11434` or `http://localhost:11434`, defaults to `qwen3-vl:8b`, batches one to
eight keyframes, requests JSON Schema output, and maps frame indexes back to exact shot/keyframe
evidence. It extracts scene labels, colors, composition, camera, lighting, artistic text,
motion-graphic traces, branding, and OCR. Qwen3-VL may return valid structured JSON in Ollama's
local `message.thinking` field when `message.content` is empty; both are validated by the same
strict Pydantic contract.

Remote hosts, HTTPS, alternate ports, embedded credentials, paths, queries, and fragments are
rejected before image bytes are read. A cloud implementation must not be bundled or activated
implicitly. It requires explicit user
authorization, `privacy.allow_cloud_model_upload: true`, documented retention and region, redacted
logging, and mocked upload/timeout/Schema tests.
