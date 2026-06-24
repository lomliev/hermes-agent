#!/usr/bin/env python3
"""Export a bounded read-only Discord case transcript.

This is an operator wrapper around the service-gated ``discord`` tool action
``case_export``.  It never sends, edits, deletes, pins, or creates Discord
objects; it only reads messages from one exact channel/thread target.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def _ensure_repo_on_path() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    repo_str = str(repo_root)
    if repo_str not in sys.path:
        sys.path.insert(0, repo_str)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--channel-id", default="", help="Discord parent/channel ID.")
    parser.add_argument("--thread-id", default="", help="Discord thread ID; overrides channel-id as transcript target.")
    parser.add_argument("--message-id", default="", help="Optional anchor message ID; exports around this message.")
    parser.add_argument("--before", default="", help="Optional before-message pagination anchor.")
    parser.add_argument("--after", default="", help="Optional after-message pagination anchor.")
    parser.add_argument("--limit", type=int, default=50, help="Max messages to export, capped at 100.")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    _ensure_repo_on_path()
    from tools.discord_tool import discord_core

    raw = discord_core(
        action="case_export",
        channel_id=args.channel_id,
        thread_id=args.thread_id,
        message_id=args.message_id,
        before=args.before,
        after=args.after,
        limit=args.limit,
    )
    print(raw)
    try:
        payload = json.loads(raw)
    except Exception:
        return 1
    return 1 if isinstance(payload, dict) and payload.get("error") else 0


if __name__ == "__main__":
    raise SystemExit(main())
