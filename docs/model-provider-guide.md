# Text model provider guide

## Current provider

Phase 3 intentionally ships only an offline structured-file provider. This keeps model calls
mockable, tests network-free, and user content local. A response file contains:

```json
{
  "model_name": "model-and-version",
  "video_fact_extraction": {},
  "video_semantic_labeling": {}
}
```

Use an array for either task to supply retry candidates. The CLI copies the response bytes to
`raw/model-outputs/<sha256>.json`, records the hash in the run manifest, and never overwrites it.

## Provider protocol

Custom providers implement `TextModelProvider.generate_structured(prompt, response_model, ...)`.
They must return the requested Pydantic model, keep temperature deterministic by default, avoid
logging prompt content or credentials, expose provider/model names, and surface Schema failures
without silently repairing unsupported fields.

Before adding a cloud implementation:

1. Require explicit user authorization and `privacy.allow_cloud_model_upload: true`.
2. Document retention, region, model name, and content-use terms.
3. Ensure no transcript or credential is printed to logs.
4. Keep the blind content bundle free of metrics.
5. Add mocked provider, privacy, retry, timeout, and Schema contract tests.
6. Preserve raw response hashes and prompt versions.

No current command contacts OpenAI or any other model service.
