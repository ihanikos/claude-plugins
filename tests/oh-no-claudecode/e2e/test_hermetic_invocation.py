"""Tests that e2e claude sessions are spawned hermetically (IHA-2132).

The spawned claude must not inherit the developer's global ~/.claude
configuration: global Stop hooks registered there re-enter the test suite
(hook → pytest → e2e test → claude → hook → …), recursing without bound.
These tests verify the spawned process's CLAUDE_CONFIG_DIR is an isolated
empty directory, so no inherited hook can fire and no recursion can start.
"""

import json
from pathlib import Path

import pytest

from conftest import PLUGIN_DIR, build_claude_command, run_claude


def test_build_claude_command_sets_isolated_claude_config_dir(tmp_path):
    """The constructed subprocess input is hermetic by construction."""
    argv, env = build_claude_command(PLUGIN_DIR, "Say hello", tmp_path)

    config_dir = Path(env["CLAUDE_CONFIG_DIR"])
    home_claude = Path.home() / ".claude"
    assert config_dir.is_dir()
    assert not any(config_dir.iterdir()), "isolated config dir must be empty"
    assert config_dir != home_claude
    assert not config_dir.is_relative_to(home_claude)

    plugin_dir_idx = argv.index("--plugin-dir")
    assert argv[plugin_dir_idx + 1] == str(PLUGIN_DIR)
    assert "--bare" not in argv


def _write_outer_settings(outer_dir: Path, hook_command: str) -> None:
    """Register hook_command as a SessionStart and Stop hook in outer_dir.

    Simulates a developer's global ~/.claude/settings.json. SessionStart is
    included because print mode (-p) fires it; Stop reproduces the original
    recursion vector.
    """
    hook_entry = [{"hooks": [{"type": "command", "command": hook_command}]}]
    settings = {"hooks": {"SessionStart": hook_entry, "Stop": hook_entry}}
    (outer_dir / "settings.json").write_text(json.dumps(settings))


@pytest.fixture
def outer_claude_config(tmp_path, monkeypatch):
    """An outer CLAUDE_CONFIG_DIR exported to the test process environment.

    Set before claude_env is built so the spawned-process env construction
    demonstrably overrides an inherited CLAUDE_CONFIG_DIR rather than merely
    running without one.
    """
    outer_dir = tmp_path / "outer-claude-config"
    outer_dir.mkdir()
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(outer_dir))
    return outer_dir


def test_run_claude_does_not_execute_inherited_global_hooks(
    outer_claude_config, claude_env, tmp_path
):
    """No hook from any config dir other than the isolated one fires."""
    sentinel_marker = tmp_path / "sentinel-hook-ran"
    _write_outer_settings(outer_claude_config, f"touch {sentinel_marker}")

    # The fixture's env must point at the isolated inner dir, not the outer one.
    assert claude_env["CLAUDE_CONFIG_DIR"] != str(outer_claude_config)

    result, _events = run_claude("Say hello", claude_env)

    assert result.returncode == 0, (
        f"claude exited with {result.returncode}\nstderr: {result.stderr[:500]}"
    )
    assert not sentinel_marker.exists(), (
        "sentinel hook from the outer CLAUDE_CONFIG_DIR fired: the spawned "
        "claude is not hermetic"
    )


def test_run_claude_does_not_recurse_via_global_stop_hook(
    outer_claude_config, claude_env, tmp_path
):
    """The original recursion vector (a global hook spawning pytest) is dead.

    Reproduces the python-pytest-passes.sh vector: a hook that writes a marker
    and spawns pytest. Neither the marker nor any output from a nested pytest
    may appear, bounding the process tree to pytest → claude.
    """
    hook_marker = tmp_path / "recursion-hook-ran"
    nested_pytest_output = tmp_path / "nested-pytest-output"
    _write_outer_settings(
        outer_claude_config,
        f"touch {hook_marker} && pytest --version > {nested_pytest_output} 2>&1",
    )

    assert claude_env["CLAUDE_CONFIG_DIR"] != str(outer_claude_config)

    result, _events = run_claude("Say hello", claude_env)

    assert result.returncode == 0, (
        f"claude exited with {result.returncode}\nstderr: {result.stderr[:500]}"
    )
    assert not hook_marker.exists(), (
        "recursion-vector hook from the outer CLAUDE_CONFIG_DIR fired"
    )
    assert not nested_pytest_output.exists(), (
        "a nested pytest process was spawned by an inherited hook"
    )
