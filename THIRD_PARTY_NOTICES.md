# Third-party notices

The root `video-account-distiller` project is distributed under its own `LICENSE`. Components
listed below keep their original copyright and license terms; the root license does not relicense
them.

## MediaCrawler

- Project: `NanmiCoder/MediaCrawler`
- Source: <https://github.com/NanmiCoder/MediaCrawler>
- Bundled location: `third_party/MediaCrawler`
- Pinned commit: `0625e01a6bc717a3fc9c96d3dac7fb8957043838`
- Upstream license: `third_party/MediaCrawler/LICENSE`

MediaCrawler is included as a Git submodule for this project's declared personal,
non-commercial learning and research workflow. Its upstream license is not an OSI-approved
open-source license and contains non-commercial and attribution conditions. Keep the submodule's
license, copyright notices, repository link, and this notice with redistributed source copies.

Before any commercial use, hosted service, paid delivery, internal production deployment for
commercial benefit, or redistribution beyond the upstream terms, obtain appropriate permission
from the MediaCrawler copyright holder or replace this provider with a suitably licensed data
source. The `--provider tikhub` adapter remains an independent API-based alternative.

`video-account-distiller` invokes a limited MediaCrawler Douyin client bridge. It does not invoke
the upstream proxy, stealth, automatic login, slider/CAPTCHA, or risk-control-evasion workflows.
Authentication, when required, is completed manually by the user in a visible dedicated Chrome
profile.

## claude-video

- Project: `bradautomates/claude-video`
- Source: <https://github.com/bradautomates/claude-video>
- Bundled location: `third_party/claude-video`
- Pinned commit: `83da59fa78c3eee9e20f515fe75c438bb5166efd`
- Upstream version: `0.2.0`
- License: MIT
- Upstream license: `third_party/claude-video/LICENSE`

Copyright (c) 2026 Bradley Bonanno.

The upstream project is retained as an auditable design and attribution boundary for video
download, caption, scene-aware frame, and transcription workflows. `video-account-distiller`
does not execute the upstream `/watch` command in its production account workflow. The internal
adapter keeps the useful pipeline shape while adding Chinese-local transcription, strict
Pydantic artifacts, immutable source hashes, bounded Douyin CDN allowlisting, and project-native
evidence links. This avoids the upstream English-only caption default, cloud-only Whisper
fallback, Markdown-only output, and source/output-directory deletion risk while preserving the
MIT notice.
