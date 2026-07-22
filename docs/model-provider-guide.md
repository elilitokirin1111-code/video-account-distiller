# Text model provider guide

## Current provider

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

No current command contacts OpenAI or any other model service.

Phase 5 scoring, prediction, publication, and Retro do not use this provider. Their formulas,
intervals, version linkage, and approval boundary are deterministic. A future model may suggest
language improvements only behind a separately validated Schema; it must not overwrite scores,
predictions, actual snapshots, Rule status, or approval metadata.
