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
