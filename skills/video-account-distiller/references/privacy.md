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
- Phase 3/4 ships no network model provider. Do not upload comments, transcripts, or media unless
  the user explicitly authorizes it and project policy allows cloud-model upload.
- Local media, extracted frames, audio measurements, OCR, and reports may expose guests, room
  numbers, screens, or booking data. Keep them local by default.
- Phase 4 redacts direct identifiers only in comment analysis copies; preserve raw comments and
  never expose author hashes. Treat comment clusters as biased opportunity signals.
- Treat hashes as pseudonymous identifiers, not proof of anonymization.
- Warn that cross-platform raw metrics are not directly comparable.
