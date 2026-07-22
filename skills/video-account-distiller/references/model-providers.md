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
