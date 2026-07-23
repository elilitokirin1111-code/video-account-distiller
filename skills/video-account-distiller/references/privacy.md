# Privacy and compliance

- Work from user-provided exports, explicitly authorized official tables, or a user-approved Douyin
  homepage through the documented fixed-host Provider only.
- Do not start browsers, login flows, CAPTCHA/risk-control bypass, direct platform-page scraping, or
  unapproved network collection.
- Preserve source bytes locally and never commit user raw/normalized data.
- Hash comment author identifiers before normalized storage; do not echo raw author IDs.
- Never print credentials to stdout, stderr, quality reports, or manifests.
- Keep `TIKHUB_API_KEY` in the local environment, preview paid calls, and require explicit cost
  confirmation before collection.
- Phase 3/4 ships no network model provider. Do not upload comments, transcripts, or media unless the
  user explicitly authorizes it and project policy allows cloud-model upload.
- Local media, extracted frames, audio measurements, OCR, and reports may expose guests, room
  numbers, screens, or booking data. Keep them local by default and never log their contents.
- Phase 4 redacts direct identifiers only in comment analysis copies; preserve raw comments and
  never expose author hashes. Treat comment clusters as biased opportunity signals, not the whole
  audience or proof of demand.
- Treat hashes as pseudonymous identifiers, not proof of anonymization.
- Warn that cross-platform raw metrics are not directly comparable.
