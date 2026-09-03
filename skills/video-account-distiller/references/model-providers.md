# Structured model providers

Phase 3/4 ships no network model client. Use `--model-output <json>` for an offline response file with
these top-level keys:

```json
{
  "model_name": "provider-model-version",
  "video_fact_extraction": {},
  "video_semantic_labeling": {},
  "comment_intent": []
}
```

Task values may be arrays of candidates to exercise retry behavior. Comment analysis consumes one
valid candidate per comment, and exhausted candidates fail rather than repeating. Every candidate is
validated with strict Pydantic output Schema and transcript evidence references. Invalid responses
are retried up to `models.max_schema_attempts`.

Without `--strict-model`, unavailable or repeatedly invalid output degrades to conservative local
facts, limited heuristics, `unknown` semantic fields, low confidence, and explicit warnings. With
`--strict-model`, stop with `E_MODEL_UNAVAILABLE` or `E_MODEL_SCHEMA_INVALID`.

Model-output bytes are copied to content-addressed local raw storage and hashed. Do not pass cloud
content unless the user explicitly authorizes it and `privacy.allow_cloud_model_upload` is true;
no bundled Phase 3/4 command uploads data. Redact comment identifiers before any authorized future
provider receives them.

Phase 6 separately defines `VisionModelProvider.analyze(MediaVisionBundle)`.
`StructuredVisionFileProvider` replays local JSON under `media_vision` and preserves its SHA-256.
`OllamaVisionProvider` calls only `http://127.0.0.1:11434` or `localhost` and defaults to
`qwen3-vl:8b`; it rejects remote hosts, TLS URLs, alternate ports, credentials, paths, queries, and
fragments. It sends bounded base64 keyframes, requests a JSON Schema response, maps frame indexes
back to immutable shot/keyframe evidence, and validates normal content or Qwen's local `thinking`
field. A custom provider must return strict `MediaVisionAnnotation`, cite existing IDs, expose
provider/model names, and remain mockable. No bundled command sends frames to a cloud vision
service. Any future cloud implementation requires explicit authorization and
`privacy.allow_cloud_model_upload: true`.
