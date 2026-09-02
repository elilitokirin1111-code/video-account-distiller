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
cloud-analysis workflow described below is the only bundled remote text-model path.

Phase 5 scoring, prediction, publication, and Retro do not use this provider. Their formulas,
intervals, version linkage, and approval boundary are deterministic. A future model may suggest
language improvements only behind a separately validated Schema; it must not overwrite scores,
predictions, actual snapshots, Rule status, or approval metadata.

## Phase 6 visual/OCR provider

`VisionModelProvider.analyze(MediaVisionBundle)` is a separate mockable boundary. The bundled
`StructuredVisionFileProvider` replays local JSON with `model_name` and a `media_vision` object or
retry array. It performs no network operation. Every returned annotation must cite an existing
`shot_id`; every OCR observation must cite an existing `keyframe_id` and timestamp interval.

The bundle contains local keyframe paths and, during live analysis, the retained source-video path.
The bundled `OllamaVisionProvider` accepts only
`http://127.0.0.1:11434` or `http://localhost:11434`, defaults to `qwen3-vl:8b`, batches one to
eight keyframes, requests JSON Schema output, and maps frame indexes back to exact shot/keyframe
evidence. It extracts scene labels, colors, composition, camera, lighting, artistic text,
motion-graphic traces, branding, and OCR. Qwen3-VL may return valid structured JSON in Ollama's
local `message.thinking` field when `message.content` is empty; both are validated by the same
strict Pydantic contract.

Local providers still reject remote hosts, embedded credentials, paths, queries, and fragments.
Cloud visual providers require an explicit `vision_provider=cloud` selection and a credential from
the operating-system keyring. `QwenNativeVideoProvider` sends a local video to Model Studio as a
Base64 data URL when `qwen3.7-plus` is selected, samples at 2 FPS for clips up to three minutes,
and sends the mixed opening/ending, scene-change, and uniform keyframes in the same request as
evidence anchors. Files over 64 MiB, unsupported containers, unavailable sources, or rejected native
requests fall back to keyframe-only cloud analysis and record the fallback in `unknowns`. Qwen's
video path is visual-only; Whisper remains the speech/audio evidence source.

## Account-level cloud analysis providers

The workbench can optionally send the bounded `AnalysisContextService` payload to either OpenAI or
Alibaba Cloud Model Studio (Bailian). Both remain disabled until all three gates are satisfied:

1. the project has `privacy.allow_cloud_model_upload: true`;
2. the user confirms the bounded data upload for the current run;
3. the user confirms that the request may incur API charges.

The Web workbench accepts a password-masked API Key, verifies it against the selected provider's
online model-list endpoint, and stores it in the current operating-system user's secure keyring.
The credential remains available until the user updates or deletes it in the Web UI. Environment
variables `OPENAI_API_KEY` and `DASHSCOPE_API_KEY` remain optional fallbacks. Bailian uses
`https://dashscope.aliyuncs.com/compatible-mode/v1` unless `DASHSCOPE_BASE_URL` selects another
Alibaba Cloud HTTPS `compatible-mode/v1` endpoint. Credential values are never serialized into the
SQLite queue, project files, audit artifacts, or Git. Cloud-analysis tasks remain intentionally
non-durable and non-retryable so a restart or retry cannot silently repeat a chargeable call without
fresh scope and cost confirmation.

The provider uses `POST https://api.openai.com/v1/responses`, `store: false`, explicit reasoning
effort, and `text.format.type: json_schema` with `strict: true`. The returned JSON is validated
again with Pydantic. Every finding, action, and experiment must cite an exact reference from the
submitted evidence allowlist; invented references fail with `E_MODEL_SCHEMA_INVALID`.

The Bailian provider uses its OpenAI-compatible Chat Completions endpoint with `qwen3.7-plus`, JSON
Mode, and explicit thinking control. The system message carries the same JSON Schema and evidence
allowlist, and the response passes the same local Pydantic and evidence-reference validation as the
OpenAI path. The provider records the Alibaba response ID, returned model, normalized token usage,
and a frozen CNY rate snapshot without persisting the raw response.

### Qwen (Bailian) across the full chain

Alibaba Cloud Model Studio works everywhere a cloud provider is selectable:

- **Account-level knowledge analysis**: choose「阿里云百炼」in the GPT analysis page (or the task
  form's 知识分析服务商 picker) and pick a Qwen model — `qwen3.7-plus`, `qwen-max-latest`,
  `qwen-plus-latest`, `qwen-turbo-latest`, or `qwen-long`. Save the `sk-` key for the **bailian**
  slot in the OS credential store; a key saved under the wrong provider (e.g. a Bailian key in the
  DeepSeek slot) returns `E_ADAPTER_AUTH` (401) against the other provider's endpoint.
- **Text blind analysis and single-video deep distillation**: set `text_provider=cloud` and either
  use `https://dashscope.aliyuncs.com/compatible-mode/v1` or paste your Model Studio MaaS gateway
  (`ws-<workspace>.cn-beijing.maas.aliyuncs.com`) — a missing `https://` scheme is completed
  automatically. Use a Qwen text model such as `qwen-max-latest`.
- **Visual analysis**: selecting `qwen3.7-plus` uses the retained original video plus mixed
  keyframe anchors. Other cloud vision models continue to use bounded keyframe batches.
- **CLI deep distillation**: `--deep-provider cloud --deep-model qwen-max-latest
  --deep-base-url <dashscope-or-maas>`.

Environment fallbacks are `DASHSCOPE_API_KEY`/`DASHSCOPE_BASE_URL` for Bailian and
`DEEPSEEK_API_KEY`/`DEEPSEEK_BASE_URL` for DeepSeek. A `401` on a task almost always means the key
does not match the selected provider/endpoint: verify in the「云端模型权限」tab which provider slot
holds the key and that the task selected the same provider.

### Recommended Qwen-video + DeepSeek-distillation route

The desktop preset uses one Bailian endpoint and credential:

- cloud endpoint: `https://dashscope.aliyuncs.com/compatible-mode/v1`;
- visual model: `qwen3.7-plus` (native video plus keyframe evidence anchors);
- knowledge model: `deepseek-v4-flash` supplied through Model Studio, with thinking enabled,
  high reasoning effort, JSON mode, and a 65,536-token completion budget.

This split lets Qwen inspect temporal visual information while DeepSeek receives the transcript,
OCR, shot annotations, and source references for validated knowledge extraction. Direct
`deepseek-v4-flash-vision-exp` remains available as an experimental keyframe provider, but is not
the recommended native-video route.

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

The picker exposes `gpt-5.6-sol`, `gpt-5.6-terra`, `gpt-5.6-luna`, and `qwen3.7-plus` under their
respective providers. Before submission, the Web page displays the provider, selected model,
bounded data scope, request fingerprints, the versioned per-token rate card, and a conservative
maximum estimate in USD or CNY. After completion, actual response usage is combined with the
provider-specific immutable price snapshot to produce an auditable estimate; the provider invoice
remains authoritative. Update each snapshot and its tests when published pricing changes.
