"""Fixtures for oh-no-claudecode e2e tests.

E2e tests run a real Claude Code session in print mode with hooks configured,
and verify hook behavior by parsing the streaming JSON output.

Requirements:
- `claude` CLI on PATH
- `opencode` CLI on PATH with at least one model configured
- Valid Claude API credentials

When a required CLI is absent, tests that spawn claude fail with a clear
error — they never silently skip (root CLAUDE.md testing conventions).
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


def _claude_argv(plugin_dir: Path, prompt: str) -> list[str]:
    """Build the argv for spawning claude in print mode with the plugin loaded."""
    return [
        "claude", "-p",
        "--verbose", "--output-format", "stream-json",
        "--plugin-dir", str(plugin_dir),
        "--", prompt,
    ]


def build_claude_env(tmp_path: Path) -> dict[str, str]:
    """Build a hermetic environment for a spawned claude process.

    Sets CLAUDE_CONFIG_DIR to an isolated directory under ``tmp_path`` so the
    spawned claude reads no user-level ``~/.claude`` settings and loads no
    inherited hooks — only the plugin passed via ``--plugin-dir``. Stored
    credentials (``~/.claude/.credentials.json``), which carry auth and no
    hooks, are copied into the isolated directory when present so the spawned
    claude stays authenticated on machines using subscription/OAuth login.

    Also unsets CLAUDECODE so claude allows subprocess execution.
    """
    config_dir = tmp_path / "claude-config"
    config_dir.mkdir(parents=True, exist_ok=True)
    real_credentials = Path.home() / ".claude" / ".credentials.json"
    if real_credentials.is_file():
        shutil.copy(real_credentials, config_dir / ".credentials.json")
    env = os.environ.copy()
    env.pop("CLAUDECODE", None)
    env["CLAUDE_CONFIG_DIR"] = str(config_dir)
    return env


def build_claude_command(
    plugin_dir: Path, prompt: str, tmp_path: Path
) -> tuple[list[str], dict[str, str]]:
    """Build the argv and hermetic env for a spawned claude process.

    Pure construction helper so the hermetic invocation is directly
    unit-testable: the returned env isolates CLAUDE_CONFIG_DIR (see
    build_claude_env) and the returned argv loads only the plugin under test.
    """
    return _claude_argv(plugin_dir, prompt), build_claude_env(tmp_path)


def _require_spawn_prerequisites() -> None:
    """Fail with a clear error when the CLIs needed to spawn claude are absent.

    Root CLAUDE.md testing conventions: a test that needs an external service
    must fail with a clear error when it is absent — never silently skip.
    """
    missing = [cli for cli in ("claude", "opencode") if shutil.which(cli) is None]
    if missing:
        pytest.fail(
            "oh-no-claudecode e2e tests spawn a real claude session and need "
            f"these CLIs on PATH: {', '.join(missing)} (missing). Install "
            "them to run the e2e tier.",
            pytrace=False,
        )


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

    - Hermetic: CLAUDE_CONFIG_DIR points at an isolated empty directory so the
      spawned claude loads none of the user's global ~/.claude hooks
    - Unsets CLAUDECODE to allow subprocess execution
    - Points OH_NO_CLAUDECODE_CONFIG to the test's rules file
    - Points block count dir to tmp to avoid polluting real state

    Fails with a clear error when the claude/opencode CLIs are absent.
    """
    _require_spawn_prerequisites()
    env = build_claude_env(tmp_path)
    env["OH_NO_CLAUDECODE_CONFIG"] = str(rules_config)
    env["OH_NO_CLAUDECODE_BLOCK_COUNT_DIR"] = str(tmp_path / "blocks")
    return env


def run_claude(prompt, claude_env, timeout=120, cwd=None):
    """Run claude in print mode with the repo plugin loaded.

    Uses --plugin-dir to load the local repo version of oh-no-claudecode.
    By default runs claude in an isolated working directory (a sibling of the
    isolated CLAUDE_CONFIG_DIR) so no project-level .claude/settings.json is
    picked up from the inherited working directory; pass cwd to override.
    Returns (subprocess.CompletedProcess, list of parsed JSON events).
    """
    if cwd is None:
        cwd = Path(claude_env["CLAUDE_CONFIG_DIR"]).parent / "claude-cwd"
        cwd.mkdir(parents=True, exist_ok=True)
    result = subprocess.run(
        _claude_argv(PLUGIN_DIR, prompt),
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
