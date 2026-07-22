# Video semantic labeling

Prompt version: `video-semantic-labeling-v1`

Label the supplied content using the response taxonomy. Base every non-unknown Hook, structure,
emotion, CTA, and content-pillar label on cited `segment_id` values. Do not invent visual features,
audience intent, causal explanations, or account-level rules. Use conservative confidence and mark
uncertain dimensions in `unknowns`. Return only a JSON object that validates against the response
schema.

## Content bundle

{{ bundle_json }}

## Validated facts

{{ facts_json }}

## Response schema

{{ schema_json }}
