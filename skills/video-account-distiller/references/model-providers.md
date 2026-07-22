# Structured model providers

Phase 3 ships no network model client. Use `--model-output <json>` for an offline response file with
these top-level keys:

```json
{
  "model_name": "provider-model-version",
  "video_fact_extraction": {},
  "video_semantic_labeling": {}
}
```

Either task value may be an array of candidates to exercise retry behavior. Every candidate is
validated with strict Pydantic output Schema and transcript evidence references. Invalid responses
are retried up to `models.max_schema_attempts`.

Without `--strict-model`, unavailable or repeatedly invalid output degrades to conservative local
facts, limited heuristics, `unknown` semantic fields, low confidence, and explicit warnings. With
`--strict-model`, stop with `E_MODEL_UNAVAILABLE` or `E_MODEL_SCHEMA_INVALID`.

Model-output bytes are copied to content-addressed local raw storage and hashed. Do not pass cloud
content unless the user explicitly authorizes it and `privacy.allow_cloud_model_upload` is true;
no bundled Phase 3 command uploads data.
