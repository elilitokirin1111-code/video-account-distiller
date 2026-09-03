"""Fetch one bounded account context from a running Distiller API."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any
from urllib.parse import quote

import requests


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--api-url", default="http://127.0.0.1:8000")
    parser.add_argument("--project", type=Path, required=True)
    parser.add_argument("--account", required=True)
    parser.add_argument("--max-video-analyses", type=int, default=10)
    args = parser.parse_args()

    project = quote(args.project.expanduser().resolve().as_posix(), safe="")
    account = quote(args.account, safe="")
    url = f"{args.api_url.rstrip('/')}/api/projects/{project}/accounts/{account}/analysis-context"
    response = requests.get(
        url,
        params={"max_video_analyses": args.max_video_analyses},
        timeout=60,
    )
    response.raise_for_status()
    payload: Any = response.json()
    print(json.dumps(payload, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
