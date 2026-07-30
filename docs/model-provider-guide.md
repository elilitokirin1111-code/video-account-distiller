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

The Phase 3/4 per-video and per-comment commands remain offline-only. The separate account-level
GPT workflow described below is the only bundled remote text-model path.

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

## Account-level OpenAI Responses provider

The workbench can optionally send the bounded `AnalysisContextService` payload to the OpenAI
Responses API. It remains disabled until all three gates are satisfied:

1. the project has `privacy.allow_cloud_model_upload: true`;
2. the user confirms the bounded data upload for the current run;
3. the user confirms that the request may incur API charges.

The API key is read only from `OPENAI_API_KEY` in the API server environment. The REST and Web
interfaces do not accept a key field, and the value is never serialized into the SQLite queue,
project files, audit artifacts, or Git. Restart the API process after changing the variable. GPT
tasks remain intentionally non-durable and non-retryable so a restart or retry cannot silently
repeat a chargeable remote call without fresh scope and cost confirmation.

The provider uses `POST https://api.openai.com/v1/responses`, `store: false`, explicit reasoning
effort, and `text.format.type: json_schema` with `strict: true`. The returned JSON is validated
again with Pydantic. Every finding, action, and experiment must cite an exact reference from the
submitted evidence allowlist; invented references fail with `E_MODEL_SCHEMA_INVALID`.

Only a redacted context is uploaded. Direct platform account IDs, handles, profile URLs, raw
hashes, and source-row metadata are removed, while raw comments, provider pages, signed media URLs,
browser state, and credentials were already excluded by the bounded context contract.

Successful calls write:

- `analysis.json`: validated result, requested/returned model, template, and used evidence refs;
- `audit.json`: request/schema/input hashes, response/output hash, model version, token usage,
  versioned price snapshot, estimated cost, confirmation flags, and privacy assertions, without
  the key or raw provider response;
- `evaluation.json`: the fixed evaluation question set covering citation completeness, evidence
  allowlist integrity, numeric hallucination review, conclusion stability, and the derived-only
  Rule/Rubric boundary;
- `report.md`: deterministic human-readable rendering of the validated JSON.

The default picker uses `gpt-5.6-terra` as the balanced option and also exposes
`gpt-5.6-sol` and `gpt-5.6-luna`. Model roles follow the current
[OpenAI model guidance](https://developers.openai.com/api/docs/models). Before submission, the Web
page displays the selected model, bounded data scope, request fingerprints, the versioned per-token
rate card, and a conservative maximum estimate. After completion, actual response usage is combined
with that immutable price snapshot to produce an auditable estimate; the OpenAI billing dashboard
or invoice remains authoritative. Update the snapshot and its tests when published pricing changes.
