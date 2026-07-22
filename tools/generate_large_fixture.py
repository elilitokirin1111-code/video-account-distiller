"""Generate a deterministic, offline large fixture without network access."""

from __future__ import annotations

import argparse
import csv
from pathlib import Path


def generate(output: Path, rows: int) -> tuple[Path, Path]:
    """Generate one account and a requested number of video rows."""

    if rows <= 0:
        raise ValueError("rows must be positive")
    output.mkdir(parents=True, exist_ok=True)
    accounts = output / "accounts.csv"
    videos = output / "videos.csv"
    with accounts.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(
            ["platform_account_id", "display_name", "follower_count_current", "snapshot_at"]
        )
        writer.writerow(["large-account", "Large Offline Fixture", 100000, "2026-07-20T00:00:00Z"])
    with videos.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(
            [
                "platform_video_id",
                "account_id",
                "title",
                "published_at",
                "duration_seconds",
                "follower_count_at_publish",
            ]
        )
        for index in range(rows):
            writer.writerow(
                [
                    f"large-video-{index:06d}",
                    "large-account",
                    f"Offline fixture video {index}",
                    "2026-07-01T00:00:00Z",
                    30 + index % 60,
                    90000 + index % 10000,
                ]
            )
    return accounts, videos


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--rows", type=int, default=100_000)
    args = parser.parse_args()
    accounts, videos = generate(args.output, args.rows)
    print(f"generated accounts={accounts} videos={videos} rows={args.rows}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
