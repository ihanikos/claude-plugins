#!/usr/bin/env python3
"""Ship Claude Code session JSONL logs to the nalkku rsync endpoint.

Reads NALKKU_RSYNC_HOST, NALKKU_ORG_SLUG, NALKKU_USER_SLUG from the environment.
Exits silently if any of these are unset (plugin not yet configured).
Hook context (session_id, transcript_path) is read from stdin as JSON.
"""

import json
import os
import pathlib
import re
import subprocess
import sys

_SESSION_ID_RE = re.compile(r"^[A-Za-z0-9._-]+$")


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

    if not _SESSION_ID_RE.fullmatch(session_id):
        print("nalkku: invalid session_id, aborting", file=sys.stderr)
        return 1

    config_dir = os.environ.get("CLAUDE_CONFIG_DIR")
    expected_root = pathlib.Path(config_dir).resolve() if config_dir else (pathlib.Path.home() / ".claude").resolve()
    try:
        resolved = pathlib.Path(transcript_path).resolve()
        resolved.relative_to(expected_root)
    except ValueError:
        print("nalkku: transcript_path outside ~/.claude, aborting", file=sys.stderr)
        return 1

    if not resolved.exists():
        return 0

    remote = f"{host}/{org}/{user}/sessions/{session_id}.jsonl"
    try:
        result = subprocess.run(
            ["rsync", "-az", str(resolved), remote],
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
