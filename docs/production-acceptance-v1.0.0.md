# Production acceptance — 1.0.0

Date: 2026-07-23

## Release decision

`1.0.0` is accepted for the offline-first hotel video-account workflow on Windows and Python
3.11+. Optional live table connectors require a separate tenant-specific authorization acceptance
before their first production write.

## Environment

- Windows 11 workstation with a Chinese repository and temporary project path.
- Clean Python 3.11.15 virtual environment.
- Package installed from `video_account_distiller-1.0.0-py3-none-any.whl`, not editable source.
- FFmpeg and FFprobe available locally.
- No cloud model, browser automation, platform scraping, or live collaboration credential used.

## Operator workflow exercised

The acceptance runner completed 18 subprocess commands through the installed package:

1. installation doctor;
2. project initialization;
3. account, video, metric, and comment imports;
4. import integrity validation;
5. normalization and status discovery;
6. robust metric calculation;
7. deterministic sample and account-health report;
8. redacted comment analysis and account distillation;
9. local analysis of a user-supplied hotel MP4 with at most two keyframes;
10. final validation, project doctor, and status.

## Results

| Check | Result |
|---|---:|
| Commands completed | 18/18 |
| Accounts | 1 |
| Videos | 30 |
| Metric snapshots | 30 |
| Comments | 18 |
| Derived metrics | 30 |
| Media feature records | 1 |
| Account-health reports | 1 |
| Comment analyses | 1 |
| Account distillations | 1 |
| Media analyses | 1, complete |
| Final validation errors | 0 |
| Final validation warnings | 0 |

The temporary project was removed after the run. The source MP4 and all generated raw/project data
remain outside Git and the release artifacts.

## Defect found and closed

The first subprocess run exposed locale-dependent JSON encoding on Windows when paths contained
Chinese text. Machine JSON now uses ASCII-safe JSON escaping, preserving decoded Chinese values
while remaining portable through Windows pipes. A contract regression test covers this behavior.

## Remaining controlled acceptance

- Certify Feishu Bitable against a dedicated tenant test table.
- Certify Google Sheets against a dedicated test spreadsheet.
- Validate a user-provided real account export when one becomes available; no such export was
  present in the release workspace.
