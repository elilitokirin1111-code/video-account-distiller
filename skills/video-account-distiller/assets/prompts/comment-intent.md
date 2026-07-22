# Comment intent extraction — v1

You label one already-redacted user comment. Use only the supplied text and metadata. Do not infer
the author's real identity, demographics, income, health, or other sensitive traits. Treat likes as
sampling context, not proof that the opinion is representative.

Return exactly one JSON object matching the supplied Schema. Use `unknown` and empty arrays when
evidence is absent. Keep pain points, questions, objections, and content opportunities concise and
grounded in the comment. Purchase intent is a probability-like annotation, not a sale prediction.

Comment input:

{{ comment_json }}

Required output Schema:

{{ schema_json }}
