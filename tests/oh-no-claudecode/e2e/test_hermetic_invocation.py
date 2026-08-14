"""Tests that e2e claude sessions are spawned hermetically (IHA-2132).

Verifies the spawned claude process's CLAUDE_CONFIG_DIR is an isolated
directory carrying no settings or hooks, so no hook from the developer's
own configuration can fire and no such hook can re-enter the test suite.
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
    # The isolated dir may carry copied credentials (auth only), but must
    # contain no settings, plugins, or hooks.
    contents = {p.name for p in config_dir.iterdir()}
    assert contents <= {".credentials.json"}, (
        f"isolated config dir must carry no settings/hooks: {contents}"
    )
    assert config_dir != home_claude
    assert not config_dir.is_relative_to(home_claude)

    plugin_dir_idx = argv.index("--plugin-dir")
    assert argv[plugin_dir_idx + 1] == str(PLUGIN_DIR)
    assert "--bare" not in argv


def _write_outer_settings(outer_dir: Path, hook_command: str) -> None:
    """Register hook_command as a SessionStart and Stop hook in outer_dir.

    Simulates a developer's user-level ~/.claude/settings.json. SessionStart
    is included because print mode (-p) fires it.
    """
    hook_entry = [{"hooks": [{"type": "command", "command": hook_command}]}]
    settings = {"hooks": {"SessionStart": hook_entry, "Stop": hook_entry}}
    (outer_dir / "settings.json").write_text(json.dumps(settings))


@pytest.fixture
def outer_claude_config(tmp_path, monkeypatch):
    """An outer CLAUDE_CONFIG_DIR exported to the test process environment.

    Set before claude_env is built (ordering enforced by hermetic_claude_env)
    so the spawned-process env construction demonstrably overrides an
    inherited CLAUDE_CONFIG_DIR rather than merely running without one.
    """
    outer_dir = tmp_path / "outer-claude-config"
    outer_dir.mkdir()
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(outer_dir))
    return outer_dir


@pytest.fixture
def hermetic_claude_env(outer_claude_config, request):
    """claude_env built while the outer CLAUDE_CONFIG_DIR is exported.

    Depends on outer_claude_config and only then instantiates claude_env, so
    build_claude_env() demonstrably copies a process environment that already
    carries the inherited CLAUDE_CONFIG_DIR and overrides it.
    """
    return request.getfixturevalue("claude_env")


def test_run_claude_does_not_execute_inherited_global_hooks(
    outer_claude_config, hermetic_claude_env, tmp_path
):
    """No hook from any config dir other than the isolated one fires."""
    sentinel_marker = tmp_path / "sentinel-hook-ran"
    _write_outer_settings(outer_claude_config, f"touch {sentinel_marker}")

    # The fixture's env must point at the isolated inner dir, not the outer one.
    assert hermetic_claude_env["CLAUDE_CONFIG_DIR"] != str(outer_claude_config)

    result, _events = run_claude("Say hello", hermetic_claude_env)

    assert result.returncode == 0, (
        f"claude exited with {result.returncode}\nstderr: {result.stderr[:500]}"
    )
    assert not sentinel_marker.exists(), (
        "sentinel hook from the outer CLAUDE_CONFIG_DIR fired: the spawned "
        "claude is not hermetic"
    )


def test_run_claude_does_not_recurse_via_global_stop_hook(
    outer_claude_config, hermetic_claude_env, tmp_path
):
    """A user-level hook that writes a marker and spawns pytest must not fire.

    Neither the marker nor any output from a nested pytest may appear,
    bounding the process tree to pytest → claude.
    """
    hook_marker = tmp_path / "recursion-hook-ran"
    nested_pytest_output = tmp_path / "nested-pytest-output"
    _write_outer_settings(
        outer_claude_config,
        f"touch {hook_marker} && pytest --version > {nested_pytest_output} 2>&1",
    )

    assert hermetic_claude_env["CLAUDE_CONFIG_DIR"] != str(outer_claude_config)

    result, _events = run_claude("Say hello", hermetic_claude_env)

    assert result.returncode == 0, (
        f"claude exited with {result.returncode}\nstderr: {result.stderr[:500]}"
    )
    assert not hook_marker.exists(), (
        "recursion-vector hook from the outer CLAUDE_CONFIG_DIR fired"
    )
    assert not nested_pytest_output.exists(), (
        "a nested pytest process was spawned by an inherited hook"
    )
