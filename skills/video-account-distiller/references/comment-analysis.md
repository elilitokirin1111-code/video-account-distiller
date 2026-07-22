# Comment analysis

Use only normalized comments from user-provided exports. Author identifiers are already hashed;
never expose them. Analyze a redacted copy of comment text so phone numbers, email addresses, URLs,
handles, and obvious contact IDs do not enter prompts or reports. Preserve source bytes unchanged.

Label sentiment, intent, pain points, questions, objections, purchase intent, identity signals,
content opportunities, spam probability, confidence, and unknowns through strict Schema. Retry
invalid provider output; otherwise mark deterministic fallback labels as degraded.

Group comments by a stable primary-intent priority, not by opaque cluster numbers. For every need
cluster return frequency, intensity, covered videos, representative comment IDs, opportunities,
and an `evi_*` item resolving to normalized comments and raw hashes.

Always warn that visible/exported commenters are not all viewers. Pinning, platform ranking,
deletions, export limits, and controversy can bias the sample. A frequent comment is an opportunity
signal, not proof of market size or purchase conversion.
