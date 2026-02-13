#!/usr/bin/env python3
"""OpenCode server lifecycle management with reference counting.

Used by SessionStart/SessionEnd hooks to start/stop the OpenCode server.
Multiple Claude Code sessions share one server via reference counting.

CLI usage (called from hooks):
    echo '{"session_id": "..."}' | python3 server_lifecycle.py --acquire
    echo '{"session_id": "..."}' | python3 server_lifecycle.py --release
"""

import fcntl
import json
import os
import shutil
import signal
import subprocess
import sys
import time
from pathlib import Path

OPENCODE_LOCK_FILE = Path("/tmp/opencode-server.lock")
OPENCODE_REFS_FILE = Path("/tmp/opencode-server.refs")
OPENCODE_SERVER_PORT = 4096


def log(msg: str) -> None:
    """Log to stderr."""
    print(f"[server_lifecycle] {msg}", file=sys.stderr)


def find_opencode() -> str | None:
    """Find the opencode binary."""
    path = shutil.which("opencode")
    if path:
        return path
    for fallback in [
        Path.home() / ".opencode" / "bin" / "opencode",
        Path.home() / ".local" / "bin" / "opencode",
    ]:
        if fallback.exists():
            return str(fallback)
    return None


def is_server_running(pid: int | None) -> bool:
    """Check if server process is still running."""
    if pid is None:
        return False
    if pid == -1:
        return is_server_available()
    try:
        os.kill(pid, 0)
        return True
    except (OSError, ProcessLookupError):
        return False


def is_server_available() -> bool:
    """Check if OpenCode server is listening on the port.

    Uses a TCP connection check rather than an LLM query — fast and reliable
    for determining if the server process is up and accepting connections.
    """
    import socket

    try:
        with socket.create_connection(("127.0.0.1", OPENCODE_SERVER_PORT), timeout=2):
            return True
    except (ConnectionRefusedError, OSError, TimeoutError):
        return False


def start_opencode_server() -> int | None:
    """Start OpenCode server and return PID. Returns -1 if server already exists."""
    opencode_bin = find_opencode()
    if not opencode_bin:
        return None

    if is_server_available():
        return -1

    proc = subprocess.Popen(
        [opencode_bin, "serve", "--port", str(OPENCODE_SERVER_PORT)],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )

    for _ in range(30):
        if is_server_available():
            return proc.pid
        time.sleep(0.5)

    # Server started but never became available — kill it and report failure
    log(f"Server process {proc.pid} started but never responded, killing it")
    try:
        proc.terminate()
        proc.wait(timeout=5)
    except (OSError, subprocess.TimeoutExpired):
        proc.kill()
    return None


def stop_opencode_server(pid: int) -> None:
    """Stop OpenCode server by PID. Does nothing if pid is -1 (external server)."""
    if pid == -1:
        return
    try:
        os.kill(pid, signal.SIGTERM)
        for _ in range(10):
            if not is_server_running(pid):
                return
            time.sleep(0.2)
        os.kill(pid, signal.SIGKILL)
    except (OSError, ProcessLookupError):
        pass


def load_refs() -> dict:
    """Load reference count data."""
    if OPENCODE_REFS_FILE.exists():
        try:
            return json.loads(OPENCODE_REFS_FILE.read_text())
        except (json.JSONDecodeError, OSError):
            pass
    return {"count": 0, "pid": None}


def save_refs(refs: dict) -> None:
    """Save reference count data."""
    OPENCODE_REFS_FILE.write_text(json.dumps(refs))


def opencode_acquire() -> bool:
    """Acquire OpenCode server (start if needed). Returns True if available."""
    opencode_bin = find_opencode()
    if not opencode_bin:
        return False

    OPENCODE_LOCK_FILE.touch(exist_ok=True)

    with open(OPENCODE_LOCK_FILE, "r+") as lock_file:
        fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
        try:
            refs = load_refs()

            if refs["pid"] and not is_server_running(refs["pid"]):
                refs["count"] = 0
                refs["pid"] = None

            if refs["count"] == 0:
                pid = start_opencode_server()
                if pid is None:
                    return False
                refs["pid"] = pid

            refs["count"] += 1
            save_refs(refs)
            return True
        finally:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)


def opencode_release() -> None:
    """Release OpenCode server (stop if last user)."""
    if not OPENCODE_LOCK_FILE.exists():
        return

    with open(OPENCODE_LOCK_FILE, "r+") as lock_file:
        fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
        try:
            refs = load_refs()
            refs["count"] = max(0, refs["count"] - 1)

            if refs["count"] == 0 and refs["pid"]:
                stop_opencode_server(refs["pid"])
                refs["pid"] = None

            save_refs(refs)
        finally:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)


def main() -> None:
    """CLI entrypoint for hook invocation."""
    import argparse

    parser = argparse.ArgumentParser(description="OpenCode server lifecycle management")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--acquire", action="store_true", help="Start/attach to server")
    group.add_argument("--release", action="store_true", help="Release server reference")
    args = parser.parse_args()

    # Read hook JSON from stdin (Claude Code passes hook context)
    try:
        hook_input = json.load(sys.stdin)
    except (json.JSONDecodeError, EOFError):
        hook_input = {}

    session_id = hook_input.get("session_id", "unknown")

    if args.acquire:
        log(f"Acquiring server for session {session_id}")
        ok = opencode_acquire()
        if ok:
            log("Server acquired successfully")
        else:
            error_msg = (
                "oh-no-claudecode: Could not start OpenCode server. "
                "Is the 'opencode' binary installed and on PATH?"
            )
            log(error_msg)
            print(json.dumps({"systemMessage": f"⚠️ {error_msg}"}))
        sys.exit(0)

    if args.release:
        log(f"Releasing server for session {session_id}")
        opencode_release()
        log("Server released")
        sys.exit(0)


if __name__ == "__main__":
    main()
