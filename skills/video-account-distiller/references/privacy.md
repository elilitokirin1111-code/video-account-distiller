# Privacy and compliance

- Work only from user-provided exports, explicitly authorized official tables, or a
  user-approved public Douyin homepage.
- The approved MediaCrawler path may open a dedicated visible Chrome profile. Login and platform
  verification remain manual user actions. Never automate credentials, CAPTCHA/slider handling,
  proxy rotation, stealth scripts, rate-limit bypass, or risk-control evasion.
- Preserve source bytes locally and never commit user raw/normalized data or browser profiles.
- Treat the MediaCrawler submodule as third-party, non-commercial learning/research software;
  preserve its license and `THIRD_PARTY_NOTICES.md`, and review licensing before commercial use.
- Hash comment author identifiers before normalized storage; do not echo raw author IDs.
- Never print credentials, Cookie contents, authorization headers, or browser-session data.
- For TikHub, keep `TIKHUB_API_KEY` in the local environment, preview paid calls, and require
  explicit cost confirmation.
- Phase 3/4 ships no network model provider. Phase 6 Ollama vision is loopback-only and keeps
  keyframes on the same computer. Do not upload comments, transcripts, or media unless
  the user explicitly authorizes it and project policy allows cloud-model upload.
- Local media, extracted frames, audio measurements, OCR, and reports may expose guests, room
  numbers, screens, or booking data. Keep them local by default.
- Retained account media enrichment accepts only explicit bounded runs, never logs signed play
  URLs, never supplies browser Cookies, and uses local Whisper. Keep downloaded media, frames,
  voices, and transcripts out of Git and cloud services by default.
- Preserve the pinned `claude-video` MIT license and attribution. Treat it as a workflow reference;
  the controlled account path must not execute upstream `/watch`.
- Phase 4 redacts direct identifiers only in comment analysis copies; preserve raw comments and
  never expose author hashes. Treat comment clusters as biased opportunity signals.
- Treat hashes as pseudonymous identifiers, not proof of anonymization.
- Warn that cross-platform raw metrics are not directly comparable.
