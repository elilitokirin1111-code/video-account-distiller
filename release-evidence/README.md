# Release evidence staging

Stable public releases require one verified public-beta bundle in this directory before the release
tag is pushed. The filename is version-bound:

```text
video-account-distiller-public-beta-<version>.zip
```

Create it with `distiller release beta bundle`; do not assemble or edit it by hand. The tag workflow
copies the version-matched bundle into `dist/`, verifies the frozen evidence against the package
version, includes its SHA-256 in `SHA256SUMS.txt`, and uploads it with the release artifacts.

The bundle contains hashed machine/account labels plus compatibility, drill, incident, and gate
records. It must not contain raw creator exports, credentials, cookies, browser profiles, account
names, or secrets. Review free-text notes and incident summaries before committing a bundle.
