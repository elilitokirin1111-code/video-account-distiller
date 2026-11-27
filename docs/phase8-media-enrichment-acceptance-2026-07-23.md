# Phase 8 retained-media acceptance — 2026-07-23

## Scope

This acceptance used one separately approved Douyin homepage collection already retained by the
project. It exercised the project-native `claude-video`-adapted route without invoking upstream
`watch.py`, Computer Use, a cloud transcription API, CAPTCHA automation, proxy/stealth features, or
a paid data endpoint.

The run was deliberately bounded to two public videos. Raw media, extracted frames, transcripts,
signed source addresses, browser state, and account-identifying values remain outside Git.

## Result

| Check | Accepted result |
|---|---|
| Retained account sample | 10 normalized videos |
| Locally enriched videos | 2 |
| Durations | 106.4 seconds; 318.8 seconds |
| Local transcript segments | 53; 208 |
| Media analysis version | 1.1.1 |
| Single-shot fallback | 1 detected shot; 12 uniformly covered keyframes |
| Edited-video analysis | 151 detected shots; 16 bounded keyframes |
| Semantic coverage | 2/10 videos |
| Observed content directions | Job search/career; hotel service and complaints |
| Measured production coverage | 2/2 portrait; shot-duration and silence summaries present |
| Final validation | 0 errors; 0 warnings |
| Signed-address scan outside retained raw evidence | 0 findings |

The resulting positioning statement was evidence-bounded: it described only the two semantically
analyzed videos and kept the other eight videos outside the semantic claim. The report also exposed
portrait orientation, median shot duration, and signal-level audio activity from the newest media
artifacts.

## Expected limitations

- Public view counts were unavailable in the retained platform payload, so no performance Pattern
  was promoted. Content understanding does not substitute for a valid performance denominator.
- Local keyword semantics are explicitly `degraded`, confidence-capped at `0.45`, and require
  human or structured-model review for publication-grade conclusions.
- Visual objects, people, locations, on-screen text, and music meaning remain unknown because this
  acceptance did not supply an authorized visual/OCR Provider. Local keyframes are evidence ready
  for a later opt-in Provider.
- Public play addresses can expire. A normal bounded homepage recollection is the supported refresh
  path; credentials, Cookie extraction, verification bypass, and risk-control evasion remain out of
  scope.

## Reproduction gates

Run the following only against an explicitly approved retained account:

```bash
uv run distiller account enrich-media --project <dir> --account <acc_id> \
  --limit 1 --whisper-model base --dry-run --json
uv run distiller account enrich-media --project <dir> --account <acc_id> \
  --limit 1 --whisper-model base --strict --json
uv run distiller validate --project <dir> --json
```

Before release, repeat the offline suite, Ruff, mypy, build, Skill validation, secret/signed-address
scan, and Git cleanliness check. Expanding beyond the bounded sample is an explicit follow-up, not
an implication that all ten videos were visually or semantically reviewed.
