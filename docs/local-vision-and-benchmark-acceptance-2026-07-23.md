# Local vision and reusable benchmark acceptance — 2026-07-23

## Scope

This acceptance verifies the D-drive Ollama installation, loopback Qwen3-VL Provider, immutable
visual evidence, real-account re-distillation, reusable public-interaction/comment profile, and
project validation. It does not claim access to creator-only Douyin views or validate a
multi-account rank from one account.

## Local runtime

- Ollama version: `0.32.1`
- Application: `D:\AI\Ollama\App`
- Model storage: `D:\AI\Ollama\Models`
- User environment: `OLLAMA_MODELS=D:\AI\Ollama\Models`
- Installer SHA-256:
  `2F53AFAB45547896E66B2879174EE78BB1F079F4A20B0858E0E377DA0C3631F0`
- Installer signature: valid, signer `Ollama Inc.`
- Model: `qwen3-vl:8b`
- Model digest:
  `901cae73216286ea8c5aba8b46d307ff7188f737285ec500c795a12f05225d28`
- Stored size: `6,140,415,879` bytes
- Reported capability: `vision`
- GPU: NVIDIA GeForce RTX 5060 Ti, 16,311 MiB

The project accepts only `http://127.0.0.1:11434` or `localhost:11434`. See the
[official Windows installation guide](https://github.com/ollama/ollama/blob/main/docs/windows.mdx),
[Qwen3-VL model page](https://ollama.com/library/qwen3-vl), and
[Ollama vision documentation](https://docs.ollama.com/capabilities/vision).

## Real-project result

Project:
`C:\Users\pc\Documents\门店运营\video-account-distiller-real-test`

Account:
`acc_2d45b539cc289d76f95d`

The final visual run analyzed four bounded keyframes from a 106.4-second retained public video:

- media analysis: `mda_8983f64a0315c51c021d`
- Provider/model: `ollama` / `qwen3-vl:8b`
- Provider status: `success`
- OCR observations: 3
- visible evidence included furniture/room objects, eye-level framing, indoor lighting, and
  white sans-serif subtitle styling
- all OCR boxes were normalized to 0–1 coordinates
- four raw local model responses were stored under `raw/vision-outputs/<sha256>.json`
- no image was sent to a non-loopback endpoint

The refreshed distillation is `dst_a07e7a3394349063a469`. It now includes measured portrait
format, shot-duration and audio-activity evidence plus local visual labels and subtitle styling.

The reusable profile is `abp_d909b025248212d8c649` and retains:

- 10 videos and 10 latest public metric snapshots
- 49 analyzed comments across 3 videos
- total likes/comments/shares/saves:
  `896,775 / 55,605 / 85,768 / 44,166`
- per-video medians:
  `31,260 / 1,155 / 2,229.5 / 1,718`
- median total public interactions per video: `41,739`
- interactions per 1,000 current followers: `118.841058`
- comment-like coverage: `100%`; comment-like total/median: `20,233 / 9`
- sentiment/intent counts, question/pain/objection/spam rates, need clusters, bounded top
  questions, and content opportunities
- descriptive interaction medians for each distilled content cluster
- content and visual identity plus exact input hashes and snapshot times

Public views were unavailable and are explicitly marked `view_metrics_unavailable_not_ranked`.
Content-cluster interaction differences are descriptive associations only.

## Compatibility defects found and fixed

1. Qwen3-VL returned valid structured JSON in Ollama's local `message.thinking` while
   `message.content` was empty. The Provider now accepts either field and applies the same strict
   Schema.
2. The first prompt allowed category-name echo such as “主色” inside `camera`. The prompt and Schema
   now provide concrete field guidance, and deterministic filtering removes field-name echoes.
3. Qwen may emit OCR boxes on a 0–1000 coordinate scale. The Provider now validates and normalizes
   that scale to the project contract's 0–1 coordinates.
4. Local Provider responses were not preserved previously. Every response is now stored by its
   canonical SHA-256 and included in the analysis fingerprint/run inputs.

## Final validation

`distiller validate` completed with:

- errors: `0`
- warnings: `0`
- immutable vision outputs: `4`
- raw media: `2`
- media analyses: `8`
- account media enrichments: `3`
- Phase 4 artifacts: `12`
- reusable benchmark profiles: `2`
- retained account collection batches: `3`

The two profile artifacts represent successive implementation outputs; neither overwrote the
other. A meaningful cross-account rank requires at least one more approved Douyin account profile.

## Subsequent craft extension (vision contract 1.4.0)

A later upgrade adds explicit per-frame `shot_scale` and `camera_movement` fields, mirrors the
legacy `camera` viewpoint into `camera_angle`, and distills account-level 拍摄手法与表现形式
(shot scale, camera motion, angle, composition, lighting, text styles, motion graphics, branding,
opening technique, editing rhythm) into a structured `CraftProfile` with coverage, `craft`
Patterns, report sections, and benchmark-profile `craft_identity`. See
`local-media-analysis.md` and `comment-and-account-distillation.md` for the current contract.


