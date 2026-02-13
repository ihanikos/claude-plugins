"""Shared utilities for oh-no-claudecode eval tests."""

import json
import os
import uuid
import subprocess
import tempfile
from pathlib import Path

PLUGIN_DIR = Path(__file__).resolve().parent.parent.parent.parent / "plugins/oh-no-claudecode"
HOOK_SCRIPT = str(PLUGIN_DIR / "scripts/oh-no-claudecode.py")
CONFIG_FILE = str(PLUGIN_DIR / "scripts/oh-no-claudecode-rules.csv")


def create_transcript(messages: list[dict]) -> Path:
    """Create a temporary JSONL transcript file."""
    tmp = tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False)
    for i, msg in enumerate(messages):
        line = {
            "message": {
                "role": msg["role"],
                "content": [{"type": "text", "text": msg["text"]}],
            },
            "uuid": str(i),
            "timestamp": f"2026-01-22T10:00:0{i}Z",
        }
        tmp.write(json.dumps(line) + "\n")
    tmp.close()
    return Path(tmp.name)


def create_config(rules: list[tuple]) -> Path:
    """Create a temporary config file with specified rules."""
    tmp = tempfile.NamedTemporaryFile(mode="w", suffix=".csv", delete=False)
    for criteria, mode, action, prompt in rules:
        tmp.write(f'"{criteria}","{mode}","{action}","{prompt}"\n')
    tmp.close()
    return Path(tmp.name)


def run_hook_with_config(
    transcript_path: Path, config_path: Path, timeout: int = 120
) -> tuple[int, str, str]:
    """Run hook with custom config."""
    hook_input = json.dumps(
        {
            "session_id": f"test-{uuid.uuid4()}",
            "transcript_path": str(transcript_path),
            "hook_event_name": "Stop",
        }
    )

    env = os.environ.copy()
    env["OH_NO_CLAUDECODE_CONFIG"] = str(config_path)

    result = subprocess.run(
        ["python3", HOOK_SCRIPT],
        input=hook_input,
        capture_output=True,
        text=True,
        timeout=timeout,
        env=env,
    )
    return result.returncode, result.stdout, result.stderr


def run_hook(transcript_path: Path, timeout: int = 300) -> tuple[int, str, str]:
    """Run the hook script with default config and return exit code, stdout, stderr."""
    hook_input = json.dumps(
        {
            "session_id": f"test-{uuid.uuid4()}",
            "transcript_path": str(transcript_path),
            "hook_event_name": "Stop",
        }
    )

    result = subprocess.run(
        ["python3", HOOK_SCRIPT],
        input=hook_input,
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    return result.returncode, result.stdout, result.stderr
