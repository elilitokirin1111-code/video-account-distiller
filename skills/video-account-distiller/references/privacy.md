# Privacy and compliance

- Work from user-provided exports only.
- Do not start network collection, browsers, login flows, CAPTCHA/risk-control bypass, or scraping.
- Preserve source bytes locally and never commit user raw/normalized data.
- Hash comment author identifiers before normalized storage; do not echo raw author IDs.
- Never print credentials to stdout, stderr, quality reports, or manifests.
- Phase 3 ships no network model provider. Do not upload comments, transcripts, or media unless the
  user explicitly authorizes it and project policy allows cloud-model upload.
- Treat hashes as pseudonymous identifiers, not proof of anonymization.
- Warn that cross-platform raw metrics are not directly comparable.
