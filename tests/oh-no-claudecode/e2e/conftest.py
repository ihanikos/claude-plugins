"""Fixtures for oh-no-claudecode e2e tests.

E2e tests run a real Claude Code session in print mode with hooks configured,
and verify hook behavior by parsing the streaming JSON output.

Requirements:
- `claude` CLI on PATH
- `opencode` CLI on PATH with at least one model configured
- Valid Claude OAuth session (run `claude auth login` if expired)
"""

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

PLUGIN_DIR = (
    Path(__file__).resolve().parent.parent.parent.parent / "plugins/oh-no-claudecode"
)


def _claude_available() -> bool:
    """Check if claude CLI is available."""
    return shutil.which("claude") is not None


def _opencode_available() -> bool:
    """Check if opencode CLI is available."""
    return shutil.which("opencode") is not None


E2E_DIR = Path(__file__).resolve().parent


def pytest_collection_modifyitems(config, items):
    """Skip e2e tests only when CLIs are not installed.
    
    Auth failures should cause test failures, not skips - it's up to the caller
    to decide whether to run these tests.
    """
    skip_reasons = []
    if not _claude_available():
        skip_reasons.append("claude CLI not available")
    if not _opencode_available():
        skip_reasons.append("opencode CLI not available")

    if skip_reasons:
        reason = "; ".join(skip_reasons)
        skip_marker = pytest.mark.skip(reason=reason)
        for item in items:
            if Path(item.fspath).resolve().is_relative_to(E2E_DIR):
                item.add_marker(skip_marker)


@pytest.fixture
def rules_config(tmp_path):
    """Create a temporary rules CSV. Returns the path.

    Tests should write their rules to this file before running claude.
    The path is passed to the hook via OH_NO_CLAUDECODE_CONFIG env var.
    """
    config_file = tmp_path / "rules.csv"
    config_file.write_text("# Empty — override in test\n")
    return config_file


@pytest.fixture
def claude_env(rules_config, tmp_path):
    """Environment variables for running claude in e2e tests.

    - Unsets CLAUDECODE to allow subprocess execution
    - Points OH_NO_CLAUDECODE_CONFIG to the test's rules file
    - Points block count dir to tmp to avoid polluting real state
    """
    env = os.environ.copy()
    env.pop("CLAUDECODE", None)
    env["OH_NO_CLAUDECODE_CONFIG"] = str(rules_config)
    env["OH_NO_CLAUDECODE_BLOCK_COUNT_DIR"] = str(tmp_path / "blocks")
    return env


def run_claude(prompt, claude_env, timeout=120, cwd=None):
    """Run claude in print mode with the repo plugin loaded.

    Uses --plugin-dir to load the local repo version of oh-no-claudecode.
    Returns (subprocess.CompletedProcess, list of parsed JSON events).
    """
    import subprocess

    result = subprocess.run(
        [
            "claude", "-p",
            "--verbose", "--output-format", "stream-json",
            "--plugin-dir", str(PLUGIN_DIR),
            "--", prompt,
        ],
        capture_output=True,
        text=True,
        timeout=timeout,
        cwd=cwd,
        env=claude_env,
    )

    events = []
    for line in result.stdout.strip().split("\n"):
        line = line.strip()
        if not line:
            continue
        try:
            events.append(json.loads(line))
        except json.JSONDecodeError:
            pass

    return result, events
