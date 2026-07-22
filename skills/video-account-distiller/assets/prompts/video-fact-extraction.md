# Video fact extraction

Prompt version: `video-fact-extraction-v1`

Extract only facts explicitly observable in the supplied title, description, and transcript.
Do not add external knowledge or unstated visual/audio details. Use `null` or `unknowns` for missing
information. Every extracted fact must cite one or more supplied `segment_id` values. Return only a
JSON object that validates against the response schema.

## Content bundle

{{ bundle_json }}

## Response schema

{{ schema_json }}
