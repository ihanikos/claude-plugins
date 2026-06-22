#!/usr/bin/env python3
"""Ship Claude Code session JSONL logs to the nalkku rsync endpoint.

Reads NALKKU_RSYNC_HOST, NALKKU_ORG_SLUG, NALKKU_USER_SLUG from the environment.
Exits silently if any of these are unset (plugin not yet configured).
Hook context (session_id, transcript_path) is read from stdin as JSON.
"""

import json
import os
import subprocess
import sys


def main() -> int:
    host = os.environ.get("NALKKU_RSYNC_HOST")
    org = os.environ.get("NALKKU_ORG_SLUG")
    user = os.environ.get("NALKKU_USER_SLUG")

    if not (host and org and user):
        return 0

    try:
        hook_input = json.load(sys.stdin)
    except (json.JSONDecodeError, OSError):
        return 0

    session_id = hook_input.get("session_id", "")
    transcript_path = hook_input.get("transcript_path", "")

    if not session_id or not transcript_path:
        return 0

    if not os.path.exists(transcript_path):
        return 0

    remote = f"{host}/{org}/{user}/sessions/{session_id}.jsonl"
    try:
        result = subprocess.run(
            ["rsync", "-az", transcript_path, remote],
            capture_output=True,
            text=True,
            timeout=55,
        )
    except (subprocess.TimeoutExpired, OSError) as exc:
        print(f"nalkku: rsync invocation failed: {exc}", file=sys.stderr)
        return 1

    if result.returncode != 0:
        print(f"nalkku: rsync failed: {result.stderr.strip()}", file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
