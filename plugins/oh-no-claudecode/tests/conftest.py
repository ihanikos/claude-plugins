"""Pytest configuration for oh-no-claudecode tests."""

import fcntl
import json
import os
import shutil
import signal
import subprocess
import time
from pathlib import Path

import pytest


# Reference counting files for OpenCode lifecycle
OPENCODE_LOCK_FILE = Path("/tmp/opencode-server.lock")
OPENCODE_REFS_FILE = Path("/tmp/opencode-server.refs")
OPENCODE_SERVER_PORT = 4096


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
        return is_server_available()  # Check external server
    try:
        os.kill(pid, 0)
        return True
    except (OSError, ProcessLookupError):
        return False


def is_server_available() -> bool:
    """Check if OpenCode server is responding on the port."""
    opencode_bin = find_opencode()
    if not opencode_bin:
        return False
    try:
        result = subprocess.run(
            [
                opencode_bin,
                "run",
                "--attach",
                f"http://127.0.0.1:{OPENCODE_SERVER_PORT}",
                "-m",
                "opencode/gpt-5-nano",
                "respond with only: OK",
            ],
            capture_output=True,
            text=True,
            timeout=10,
        )
        return result.returncode == 0 and "OK" in result.stdout
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return False


def start_opencode_server() -> int | None:
    """Start OpenCode server and return PID. Returns -1 if server already exists."""
    opencode_bin = find_opencode()
    if not opencode_bin:
        return None

    # Check if server is already running
    if is_server_available():
        return -1  # Signal that we're using existing server

    proc = subprocess.Popen(
        [opencode_bin, "serve", "--port", str(OPENCODE_SERVER_PORT)],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )

    # Wait for server to be ready
    for _ in range(30):
        if is_server_available():
            return proc.pid
        time.sleep(0.5)

    return proc.pid


def stop_opencode_server(pid: int) -> None:
    """Stop OpenCode server by PID. Does nothing if pid is -1 (external server)."""
    if pid == -1:
        return  # Don't stop external server
    try:
        os.kill(pid, signal.SIGTERM)
        # Wait for graceful shutdown
        for _ in range(10):
            if not is_server_running(pid):
                return
            time.sleep(0.2)
        # Force kill if still running
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

            # Check if existing server is still running
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


# Pytest hooks and fixtures


def pytest_addoption(parser):
    parser.addoption(
        "--skip-opencode",
        action="store_true",
        default=False,
        help="Skip tests that require OpenCode service",
    )


def pytest_configure(config):
    config.addinivalue_line(
        "markers", "opencode: marks tests as requiring OpenCode service"
    )


def pytest_collection_modifyitems(config, items):
    if config.getoption("--skip-opencode"):
        skip_opencode = pytest.mark.skip(reason="--skip-opencode flag provided")
        for item in items:
            if "opencode" in item.keywords:
                item.add_marker(skip_opencode)
    else:
        # Auto-wire opencode_server fixture for opencode-marked tests so they
        # get server lifecycle management and skip when OpenCode is unavailable.
        for item in items:
            if "opencode" in item.keywords:
                item.add_marker(pytest.mark.usefixtures("opencode_server"))


@pytest.fixture(scope="session")
def opencode_server():
    """Session-scoped fixture that ensures OpenCode server is running.

    Uses reference counting so multiple test sessions can share one server.
    NOT autouse — only tests that request this fixture or use the opencode mark need it.
    Unit tests run without OpenCode.
    """
    available = opencode_acquire()
    if not available:
        pytest.skip("OpenCode not available")

    yield f"http://127.0.0.1:{OPENCODE_SERVER_PORT}"

    opencode_release()


@pytest.fixture
def opencode_available(opencode_server):
    """Fixture that provides OpenCode server URL. Marks test as requiring OpenCode."""
    return opencode_server
