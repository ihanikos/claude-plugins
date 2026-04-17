"""Tests verifying the bash-output-guard / devcontainer-testing plugin split (IHA-1731)."""

import json
import os
import subprocess
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
BOG_PLUGIN = REPO_ROOT / "plugins/bash-output-guard"
DCT_PLUGIN = REPO_ROOT / "plugins/devcontainer-testing"
MARKETPLACE = REPO_ROOT / ".claude-plugin/marketplace.json"
HOOK_SCRIPT = BOG_PLUGIN / "scripts/limit-bash-output.sh"


def test_bash_output_guard_skill_removed():
    assert not (BOG_PLUGIN / "skills").exists(), "skills/ directory should not exist in bash-output-guard"


def test_bash_output_guard_version_bumped_to_2_0_0():
    plugin_json = json.loads((BOG_PLUGIN / ".claude-plugin/plugin.json").read_text())
    assert plugin_json["version"] == "2.0.0", f"Expected 2.0.0, got {plugin_json['version']}"


def test_bash_output_guard_hook_files_intact():
    assert (BOG_PLUGIN / "scripts/limit-bash-output.sh").exists(), "limit-bash-output.sh missing"
    assert (BOG_PLUGIN / "hooks/hooks.json").exists(), "hooks.json missing"


def test_devcontainer_testing_plugin_json_valid():
    plugin_json_path = DCT_PLUGIN / ".claude-plugin/plugin.json"
    assert plugin_json_path.exists(), "devcontainer-testing plugin.json missing"
    data = json.loads(plugin_json_path.read_text())
    for field in ("name", "description", "version", "author"):
        assert field in data, f"Required field '{field}' missing from plugin.json"


def test_devcontainer_testing_skill_exists():
    skill = DCT_PLUGIN / "skills/devcontainer-testing/SKILL.md"
    assert skill.exists(), "devcontainer-testing SKILL.md missing"
    assert skill.stat().st_size > 0, "SKILL.md is empty"


def test_devcontainer_testing_readme_exists():
    assert (DCT_PLUGIN / "README.md").exists(), "devcontainer-testing README.md missing"


def test_marketplace_bash_output_guard_version_2_0_0():
    marketplace = json.loads(MARKETPLACE.read_text())
    plugins = {p["name"]: p for p in marketplace["plugins"]}
    assert "bash-output-guard" in plugins, "bash-output-guard not in marketplace"
    assert plugins["bash-output-guard"]["version"] == "2.0.0", (
        f"Expected 2.0.0, got {plugins['bash-output-guard']['version']}"
    )


def test_marketplace_has_devcontainer_testing_entry():
    marketplace = json.loads(MARKETPLACE.read_text())
    plugins = {p["name"]: p for p in marketplace["plugins"]}
    assert "devcontainer-testing" in plugins, "devcontainer-testing not in marketplace"
    entry = plugins["devcontainer-testing"]
    assert "category" in entry, "devcontainer-testing entry missing 'category'"
    assert "tags" in entry, "devcontainer-testing entry missing 'tags'"


def _run_hook(command: str, max_bytes: int = 100000) -> subprocess.CompletedProcess:
    payload = json.dumps({"tool_input": {"command": command}})
    env = {"PATH": os.environ["PATH"], "BASH_OUTPUT_GUARD_MAX_BYTES": str(max_bytes)}
    return subprocess.run(
        ["bash", str(HOOK_SCRIPT)],
        input=payload,
        capture_output=True,
        text=True,
        env=env,
    )


def test_hook_behavior_preserved_large_output():
    large_cmd = "python3 -c \"print('x' * 200000)\""
    result = _run_hook(large_cmd)
    assert result.returncode == 0, f"Hook exited with {result.returncode}: {result.stderr}"
    output = json.loads(result.stdout)
    wrapped_cmd = output["hookSpecificOutput"]["updatedInput"]["command"]

    with tempfile.NamedTemporaryFile(mode="w", suffix=".sh", delete=False) as f:
        f.write(wrapped_cmd)
        tmp_path = f.name

    try:
        exec_result = subprocess.run(["bash", tmp_path], capture_output=True, text=True)
        assert "[ERROR: Output discarded" in exec_result.stdout, (
            f"Expected discard message, got: {exec_result.stdout[:200]}"
        )
    finally:
        Path(tmp_path).unlink(missing_ok=True)


def test_hook_behavior_preserved_small_output():
    small_cmd = "echo hello"
    result = _run_hook(small_cmd)
    assert result.returncode == 0, f"Hook exited with {result.returncode}: {result.stderr}"
    output = json.loads(result.stdout)
    wrapped_cmd = output["hookSpecificOutput"]["updatedInput"]["command"]

    with tempfile.NamedTemporaryFile(mode="w", suffix=".sh", delete=False) as f:
        f.write(wrapped_cmd)
        tmp_path = f.name

    try:
        exec_result = subprocess.run(["bash", tmp_path], capture_output=True, text=True)
        assert "hello" in exec_result.stdout, f"Expected 'hello' in output, got: {exec_result.stdout[:200]}"
        assert "[ERROR: Output discarded" not in exec_result.stdout
    finally:
        Path(tmp_path).unlink(missing_ok=True)
