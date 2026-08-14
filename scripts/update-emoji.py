#!/usr/bin/env python3
"""Regenerate web/emoji.json from GitHub's gemoji database.

ntfy's own web client sources its short-code -> emoji table from the same
gemoji data, so re-running this keeps our tag rendering in sync with the
official client as new emoji get added upstream.
"""

import json
import sys
from pathlib import Path

import requests

GEMOJI_URL = "https://raw.githubusercontent.com/github/gemoji/master/db/emoji.json"
OUTPUT_PATH = Path(__file__).resolve().parent.parent / "web" / "emoji.json"


def build_map(gemoji_entries: list[dict]) -> dict[str, str]:
    mapping: dict[str, str] = {}
    conflicts = []
    for entry in gemoji_entries:
        emoji = entry["emoji"]
        for alias in entry["aliases"]:
            if alias in mapping and mapping[alias] != emoji:
                conflicts.append((alias, mapping[alias], emoji))
            mapping[alias] = emoji

    if conflicts:
        print(f"warning: {len(conflicts)} alias conflicts (last write wins):", file=sys.stderr)
        for alias, old, new in conflicts:
            print(f"  {alias}: {old} -> {new}", file=sys.stderr)

    return mapping


def main() -> None:
    resp = requests.get(GEMOJI_URL, timeout=30)
    resp.raise_for_status()
    entries = resp.json()

    mapping = build_map(entries)

    OUTPUT_PATH.write_text(
        json.dumps(mapping, ensure_ascii=False, sort_keys=True, separators=(",", ":")),
        encoding="utf-8",
    )
    print(f"wrote {len(mapping)} short codes ({OUTPUT_PATH.stat().st_size} bytes) to {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
