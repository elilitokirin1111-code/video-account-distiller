# Production installation and operation

## Install a release artifact

Download the wheel and `SHA256SUMS.txt` from the matching GitHub Release. Verify the checksum before
installation, then install into an isolated Python 3.11+ environment:

```powershell
uv venv .venv --python 3.11
uv pip install --python .venv\Scripts\python.exe .\video_account_distiller-1.0.0-py3-none-any.whl
.\.venv\Scripts\python.exe -m video_account_distiller --version
.\.venv\Scripts\python.exe -m video_account_distiller doctor --json
```

On macOS or Linux, replace `.venv\Scripts\python.exe` with `.venv/bin/python`.

The release also contains `video-account-distiller-skill-1.0.0.zip`. Extract its
`video-account-distiller` directory into `$CODEX_HOME/skills/` when the Codex Agent Skill is needed;
the Python wheel and Skill archive are versioned together but installed independently.

## Readiness interpretation

`distiller doctor --json` is read-only. It reports:

- installed package and dependency versions;
- Python and operating-system details;
- FFmpeg/FFprobe availability;
- pinned MediaCrawler source plus local `uv`/Node readiness for optional homepage collection;
- whether collaboration token environment variables are present, never their values;
- optional project readability, writability, and integrity-validation status.

`ok: true` means the core runtime is usable and, when `--project` is supplied, the project is
initialized and validates successfully. `capabilities.local_media` may be false without blocking
the table-analysis core. `capabilities.mediacrawler_douyin` may be false in a wheel-only install
because the third-party source is intentionally not relicensed into the wheel. Feishu and Google
capabilities remain false until their token environment variables are configured.

## Homepage collection runtime

The default TikHub workflow is available from the installed wheel. Set `TIKHUB_API_KEY` locally,
run a dry-run first, then pass `--confirm-provider-cost` for the real bounded collection. The
default scope is 20 videos and zero comments.

The optional MediaCrawler workflow requires a source checkout with its pinned Git submodule, or an
explicit compatible checkout supplied through `MEDIACRAWLER_HOME`:

```bash
git clone --recurse-submodules \
  https://github.com/elilitokirin1111-code/video-account-distiller.git
cd video-account-distiller
uv sync
uv run distiller doctor --json
```

MediaCrawler retains its own non-commercial learning license and is not included in the root wheel.
Review `THIRD_PARTY_NOTICES.md` before use. The controlled adapter may launch visible Chrome, but
login and platform verification remain manual; browser session contents are not written to the
analysis project.

## First production workflow

1. Create a dedicated project directory; do not work inside the repository.
2. Run `init`, then import one authorized export with `--dry-run` first.
3. Run the non-dry import, `validate`, `normalize`, and `status`.
4. Review rejects, duplicates, warnings, normalized counts, and account IDs.
5. Generate metrics/sample/report before running comment analysis or distillation.
6. Back up the project before adding a new data source or changing mappings.
7. Use only a dedicated test table for the first Feishu/Google write acceptance.

Raw inputs, prediction records, publications, and prior analyses are immutable. Upgrades do not
rewrite them automatically.

## Release acceptance command

Maintainers can reproduce the installed-wheel workflow with:

```powershell
python tools\release_acceptance.py `
  --fixtures tests\fixtures `
  --media C:\path\to\authorized-hotel-video.mp4 `
  --report acceptance-local.json
```

Run this script with the Python executable from the environment where the built wheel is installed.
It creates a temporary Chinese-path project, checks every JSON result, verifies expected tables and
artifacts, and removes the project unless `--keep-workspace` is supplied.

## Optional integrations

Feishu Bitable and Google Sheets are production-capable but tenant-specific. Before enabling them
for a real team, certify a dedicated table in this order: read grant, paginated read, pull dry run,
normalized count review, push dry run, one-row write, and read-back. Do not use the production table
for the first write test.
