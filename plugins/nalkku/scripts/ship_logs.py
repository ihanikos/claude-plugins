#!/usr/bin/env python3
"""Ship Claude Code session JSONL logs to the nalkku rsync endpoint.

Reads NALKKU_RSYNC_HOST, NALKKU_ORG_SLUG, NALKKU_USER_SLUG from the environment.
Exits silently if any of these are unset (plugin not yet configured).
"""

import os
import subprocess
import sys


def main() -> int:
    host = os.environ.get("NALKKU_RSYNC_HOST")
    org = os.environ.get("NALKKU_ORG_SLUG")
    user = os.environ.get("NALKKU_USER_SLUG")

    if not (host and org and user):
        return 0

    session_id = os.environ.get("CLAUDE_SESSION_ID")
    config_dir = os.environ.get("CLAUDE_CONFIG_DIR", os.path.expanduser("~/.claude"))

    if not session_id:
        return 0

    projects_dir = os.path.join(config_dir, "projects")
    jsonl_path = None
    for root, _, files in os.walk(projects_dir):
        for fname in files:
            if fname == f"{session_id}.jsonl":
                jsonl_path = os.path.join(root, fname)
                break
        if jsonl_path:
            break

    if not jsonl_path or not os.path.exists(jsonl_path):
        return 0

    remote = f"{host}/{org}/{user}/sessions/{session_id}.jsonl"
    result = subprocess.run(
        ["rsync", "-az", jsonl_path, remote],
        capture_output=True,
        text=True,
        timeout=55,
    )
    if result.returncode != 0:
        print(f"nalkku: rsync failed: {result.stderr.strip()}", file=sys.stderr)

    return 0


if __name__ == "__main__":
    sys.exit(main())
