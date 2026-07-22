# AGENTS.md

## Repository purpose

This repository implements `video-account-distiller`, an Agent Skill and Python toolkit for evidence-based video account analysis, benchmarking, content pattern distillation, scoring, prediction, and post-publication retrospectives.

## Sources of truth

Read these before changing architecture or data contracts:

1. `docs/planning/01_PRODUCT_SPEC.md`
2. `docs/planning/02_ANALYSIS_FRAMEWORK.md`
3. `docs/planning/03_TECHNICAL_DESIGN.md`
4. `docs/planning/04_DATA_SCHEMA.md`
5. `docs/planning/05_SKILL_BLUEPRINT.md`
6. `docs/planning/06_TEST_AND_ACCEPTANCE.md`
7. `docs/planning/07_MILESTONE_PLAN.md`

Keep this file short. Put durable details in `docs/`.

## Development commands

Use the repository's declared Python and `uv`.

```bash
uv sync
uv run ruff check .
uv run ruff format --check .
uv run mypy src
uv run pytest
```

Run all checks after code changes.

## Engineering rules

- Python 3.11+.
- Add type annotations to public functions.
- Validate external and model data with Pydantic.
- Preserve raw inputs; never mutate them.
- Treat unknown values as `None`, not zero.
- Keep platform-specific mappings behind adapters.
- Do not compare raw cross-platform metrics without explicit normalization.
- Keep deterministic calculations outside prompts.
- Make model calls mockable.
- Write machine-readable command results to stdout and logs to stderr.
- Never log secrets.
- Tests must not require internet access.
- Add or update tests for every behavior change.
- Record implementation tradeoffs in `docs/implementation-decisions.md`.

## Skill rules

- The skill name and folder must be `video-account-distiller`.
- Keep the main `SKILL.md` below 500 lines.
- Put detailed guidance in directly linked `references/` files.
- Avoid duplicated business logic in skill scripts.
- Ensure all relative references resolve.
- Validate the skill format before completion.

## Git rules

- Inspect the existing repository before editing.
- Make focused commits.
- Do not rewrite existing commits.
- Do not commit credentials, generated caches, raw user data, or local project state.
- Finish with a clean worktree.

## Safety and compliance

Do not implement mechanisms to bypass authentication, CAPTCHA, platform controls, rate limits, or terms of service. Online collection must use authorized APIs, user-provided exports, or explicitly permitted adapters.
