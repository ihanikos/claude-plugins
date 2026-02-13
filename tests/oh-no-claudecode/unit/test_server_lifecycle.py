"""E2E tests for OpenCode server lifecycle management.

Tests the server_lifecycle.py script's CLI interface (--acquire/--release)
and reference counting logic. These tests mock the opencode binary to avoid
requiring a real OpenCode installation.
"""

import json
import os
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

PLUGIN_DIR = (
    Path(__file__).resolve().parent.parent.parent.parent / "plugins/oh-no-claudecode"
)
LIFECYCLE_SCRIPT = str(PLUGIN_DIR / "scripts/server_lifecycle.py")


def run_lifecycle(
    action: str,
    session_id: str = "test-session",
    env_extra: dict | None = None,
    timeout: int = 15,
) -> tuple[int, str, str]:
    """Run server_lifecycle.py with --acquire or --release."""
    hook_input = json.dumps({"session_id": session_id})

    env = os.environ.copy()
    if env_extra:
        env.update(env_extra)

    result = subprocess.run(
        [sys.executable, LIFECYCLE_SCRIPT, f"--{action}"],
        input=hook_input,
        capture_output=True,
        text=True,
        timeout=timeout,
        env=env,
    )
    return result.returncode, result.stdout, result.stderr


@pytest.fixture
def fake_opencode(tmp_path, monkeypatch):
    """Create a fake opencode binary that simulates server behavior.

    The fake binary:
    - `serve --port PORT`: creates a marker file and sleeps (backgroundable)
    - `run --attach URL ...`: exits 0 with "OK" if marker file exists
    - Other commands: exits 1
    """
    marker = tmp_path / "server-running"
    fake_bin = tmp_path / "opencode"
    fake_bin.write_text(
        textwrap.dedent(f"""\
        #!/usr/bin/env python3
        import sys, time, os, signal, socket, threading
        marker = "{marker}"

        def handle_term(signum, frame):
            try:
                os.unlink(marker)
            except FileNotFoundError:
                pass
            sys.exit(0)

        signal.signal(signal.SIGTERM, handle_term)

        if "serve" in sys.argv:
            # Extract port from --port arg
            port = 4096
            if "--port" in sys.argv:
                port = int(sys.argv[sys.argv.index("--port") + 1])
            # Listen on the port so TCP health checks succeed
            srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            srv.bind(("127.0.0.1", port))
            srv.listen(1)
            srv.settimeout(1.0)
            open(marker, "w").close()
            try:
                while True:
                    try:
                        conn, _ = srv.accept()
                        conn.close()
                    except socket.timeout:
                        pass
            except KeyboardInterrupt:
                pass
            finally:
                srv.close()
                try:
                    os.unlink(marker)
                except FileNotFoundError:
                    pass
        elif "--attach" in sys.argv:
            if os.path.exists(marker):
                print("OK")
                sys.exit(0)
            else:
                sys.exit(1)
        else:
            sys.exit(1)
        """)
    )
    fake_bin.chmod(0o755)

    # Put fake binary first in PATH
    monkeypatch.setenv("PATH", f"{tmp_path}:{os.environ.get('PATH', '')}")

    return {"bin": fake_bin, "marker": marker}


@pytest.fixture
def clean_refs(tmp_path, monkeypatch):
    """Use temporary files for lock/refs to avoid polluting /tmp."""
    lock_file = tmp_path / "opencode-server.lock"
    refs_file = tmp_path / "opencode-server.refs"

    # Monkeypatch the module constants when imported, but since we run as
    # subprocess, we need to inject via env. The script reads these from
    # module-level constants, so we'll patch the script's globals via a wrapper.
    wrapper = tmp_path / "lifecycle_wrapper.py"
    wrapper.write_text(
        textwrap.dedent(f"""\
        import sys
        sys.path.insert(0, "{PLUGIN_DIR / 'scripts'}")
        import server_lifecycle
        from pathlib import Path
        server_lifecycle.OPENCODE_LOCK_FILE = Path("{lock_file}")
        server_lifecycle.OPENCODE_REFS_FILE = Path("{refs_file}")
        server_lifecycle.main()
        """)
    )

    return {
        "wrapper": str(wrapper),
        "lock_file": lock_file,
        "refs_file": refs_file,
    }


def run_wrapped(
    clean_refs: dict,
    action: str,
    session_id: str = "test-session",
    env_extra: dict | None = None,
    timeout: int = 15,
) -> tuple[int, str, str]:
    """Run the lifecycle wrapper with patched paths."""
    hook_input = json.dumps({"session_id": session_id})

    env = os.environ.copy()
    if env_extra:
        env.update(env_extra)

    result = subprocess.run(
        [sys.executable, clean_refs["wrapper"], f"--{action}"],
        input=hook_input,
        capture_output=True,
        text=True,
        timeout=timeout,
        env=env,
    )
    return result.returncode, result.stdout, result.stderr


class TestAcquireStartsServer:
    """--acquire should start the server when none is running."""

    def test_acquire_starts_server(self, fake_opencode, clean_refs):
        """First acquire should start the server and set refcount to 1."""
        exit_code, stdout, stderr = run_wrapped(clean_refs, "acquire")
        assert exit_code == 0
        assert "acquired successfully" in stderr.lower()

        # Check refs file
        refs = json.loads(clean_refs["refs_file"].read_text())
        assert refs["count"] == 1
        assert refs["pid"] is not None

    def test_acquire_exits_zero_on_success(self, fake_opencode, clean_refs):
        """--acquire should always exit 0 (hooks must not fail the session)."""
        exit_code, _, _ = run_wrapped(clean_refs, "acquire")
        assert exit_code == 0


class TestReleaseStopsServer:
    """--release after last acquire should stop the server."""

    def test_release_after_single_acquire(self, fake_opencode, clean_refs):
        """Single acquire then release should stop server and reset refs."""
        run_wrapped(clean_refs, "acquire")
        exit_code, stdout, stderr = run_wrapped(clean_refs, "release")
        assert exit_code == 0
        assert "released" in stderr.lower()

        refs = json.loads(clean_refs["refs_file"].read_text())
        assert refs["count"] == 0
        assert refs["pid"] is None

    def test_release_without_acquire(self, fake_opencode, clean_refs):
        """Release without prior acquire should exit cleanly."""
        exit_code, _, _ = run_wrapped(clean_refs, "release")
        assert exit_code == 0


class TestReferenceCounting:
    """Multiple acquires should keep server alive until last release."""

    def test_multiple_acquires_increment_count(self, fake_opencode, clean_refs):
        """Two acquires should set refcount to 2."""
        run_wrapped(clean_refs, "acquire", session_id="session-1")
        run_wrapped(clean_refs, "acquire", session_id="session-2")

        refs = json.loads(clean_refs["refs_file"].read_text())
        assert refs["count"] == 2
        assert refs["pid"] is not None

    def test_partial_release_keeps_server(self, fake_opencode, clean_refs):
        """Releasing one of two acquires should keep server running."""
        run_wrapped(clean_refs, "acquire", session_id="session-1")
        run_wrapped(clean_refs, "acquire", session_id="session-2")
        run_wrapped(clean_refs, "release", session_id="session-1")

        refs = json.loads(clean_refs["refs_file"].read_text())
        assert refs["count"] == 1
        assert refs["pid"] is not None

    def test_last_release_stops_server(self, fake_opencode, clean_refs):
        """Releasing all acquires should stop the server."""
        run_wrapped(clean_refs, "acquire", session_id="session-1")
        run_wrapped(clean_refs, "acquire", session_id="session-2")
        run_wrapped(clean_refs, "release", session_id="session-1")
        run_wrapped(clean_refs, "release", session_id="session-2")

        refs = json.loads(clean_refs["refs_file"].read_text())
        assert refs["count"] == 0
        assert refs["pid"] is None


class TestMissingOpencode:
    """Graceful handling when opencode binary is not found."""

    def test_acquire_without_opencode(self, clean_refs, monkeypatch):
        """--acquire with no opencode binary should exit 0 but show error."""
        # Set PATH to empty dir so opencode won't be found
        monkeypatch.setenv("PATH", "/nonexistent")
        # Also ensure no fallback paths exist
        monkeypatch.setenv("HOME", "/nonexistent")

        exit_code, stdout, stderr = run_wrapped(clean_refs, "acquire")
        assert exit_code == 0
        assert "could not start" in stderr.lower()
        # Should output a systemMessage so user sees the error in Claude Code
        assert "systemMessage" in stdout
        assert "opencode" in stdout.lower()

    def test_release_without_opencode(self, clean_refs, monkeypatch):
        """--release with no opencode binary should exit 0 gracefully."""
        monkeypatch.setenv("PATH", "/nonexistent")
        monkeypatch.setenv("HOME", "/nonexistent")

        exit_code, _, _ = run_wrapped(clean_refs, "release")
        assert exit_code == 0


class TestCliInterface:
    """Test the CLI argument parsing."""

    def test_no_args_fails(self):
        """Running without --acquire or --release should fail."""
        result = subprocess.run(
            [sys.executable, LIFECYCLE_SCRIPT],
            input="{}",
            capture_output=True,
            text=True,
            timeout=5,
        )
        assert result.returncode != 0

    def test_empty_stdin(self, fake_opencode, clean_refs):
        """Empty stdin should be handled gracefully."""
        env = os.environ.copy()
        env["PATH"] = f"{fake_opencode['bin'].parent}:{env.get('PATH', '')}"

        result = subprocess.run(
            [sys.executable, clean_refs["wrapper"], "--acquire"],
            input="",
            capture_output=True,
            text=True,
            timeout=15,
            env=env,
        )
        assert result.returncode == 0

    def test_invalid_json_stdin(self, fake_opencode, clean_refs):
        """Invalid JSON on stdin should be handled gracefully."""
        env = os.environ.copy()
        env["PATH"] = f"{fake_opencode['bin'].parent}:{env.get('PATH', '')}"

        result = subprocess.run(
            [sys.executable, clean_refs["wrapper"], "--acquire"],
            input="not json",
            capture_output=True,
            text=True,
            timeout=15,
            env=env,
        )
        assert result.returncode == 0
