# API and GPT analysis workflow

Use this route when another application or GPT-compatible workflow needs a stable evidence payload.

## Start and inspect

```bash
distiller-api
```

The default address is `http://127.0.0.1:8000`. Override only with `DISTILLER_API_HOST` and
`DISTILLER_API_PORT`. API task records persist in SQLite at
`~/.video-account-distiller/api/tasks.sqlite3`; `DISTILLER_TASK_DB` may point to another local file.

Check:

```text
GET /api/health
GET /api/tasks?limit=50
GET /api/tasks/{task_id}
```

After a restart, abandoned `pending` or `running` work becomes `failed` with
`E_TASK_INTERRUPTED` and `retryable: true`. It is not silently resumed because Provider calls and
filesystem writes may already have partially completed.

## Read account evidence

URL-encode the absolute project path as one path segment:

```text
GET /api/projects/{project_path}/accounts/{account_id}/growth
GET /api/projects/{project_path}/accounts/{account_id}/analysis-context
```

Or run:

```bash
python skills/video-account-distiller/scripts/get-analysis-context.py \
  --project <dir> --account <account-id>
```

`analysis-context` includes:

- normalized account/video/metric/comment availability;
- observed account-snapshot growth;
- latest account-health report and account distillation;
- aggregate comment needs without raw per-comment text;
- latest benchmark and retained-media enrichment summaries;
- bounded latest per-video semantic analyses;
- evidence paths, private-field availability, limitations, and an analysis contract.

It excludes Provider raw pages, credentials, cookies, browser state, signed media URLs, and raw
comment text. The endpoint does not call a model and does not imply permission to upload data.

## GPT workflow

1. Obtain user approval for the specific project/account and whether remote processing is allowed.
2. Retrieve the context JSON.
3. Give the model the complete `analysis_contract`, `limitations`, and `source_paths`.
4. Ask for four separately labeled layers: observed facts, statistical associations, hypotheses,
   and recommended tests/actions.
5. Require important claims to cite an artifact path or evidence identifier.
6. Reject conclusions that require missing private fields, fan demographics, complete comments,
   or causal inference.
7. Save model output separately; never overwrite deterministic evidence artifacts.

Suggested analysis request:

```text
Analyze this account context. First state the data scope and unavailable fields. Then separate
observed facts, account-local associations, hypotheses, and prioritized experiments. Cite a source
path or evidence ID for each important claim. Do not infer missing values or represent sampled
comments as the whole audience.
```

For a direct local CLI export without running the API:

```bash
uv run distiller account context --project <dir> --account <account-id> --json
```

## Optional OpenAI handoff

The repository currently stops at the context boundary and does not call a cloud model. OpenAI
recommends the Responses API for new integrations:
<https://developers.openai.com/api/docs/guides/migrate-to-responses>.

Add a direct Provider only after all of these are true:

1. The user has explicitly approved remote processing for this project/account.
2. `OPENAI_API_KEY` is present in the process environment; never persist or display it.
3. The model is an explicit configuration value rather than a silently changing hard-coded
   default.
4. The request uses the Responses API with storage disabled unless separate retention approval
   exists.
5. The uploaded payload is the bounded context, never Provider raw pages, signed URLs, cookies, or
   credentials.
6. The response is written as a new traced artifact with model, prompt version, source paths,
   timestamp, and limitations; deterministic evidence is never overwritten.

Current model guidance is published at
<https://developers.openai.com/api/docs/guides/latest-model>. Re-evaluate quality, cost, reasoning
effort, and data-retention settings on representative account contexts before choosing a default.
