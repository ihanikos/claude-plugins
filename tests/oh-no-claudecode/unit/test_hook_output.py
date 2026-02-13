"""E2E tests for oh-no-claudecode hook output.

Runs the actual hook script via subprocess without mocking.
Tests real behavior when the OpenCode server is not running.
"""

import json
import os
import subprocess
import tempfile
import uuid
from pathlib import Path

PLUGIN_DIR = (
    Path(__file__).resolve().parent.parent.parent.parent / "plugins/oh-no-claudecode"
)
HOOK_SCRIPT = str(PLUGIN_DIR / "scripts/oh-no-claudecode.py")


def _create_transcript(messages: list[dict]) -> Path:
    """Create a temp JSONL transcript."""
    tmp = tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False)
    for i, msg in enumerate(messages):
        entry = {
            "message": {
                "role": msg["role"],
                "content": [{"type": "text", "text": msg["text"]}],
            },
            "uuid": str(i),
            "timestamp": f"2026-01-29T10:00:{i:02d}Z",
        }
        tmp.write(json.dumps(entry) + "\n")
    tmp.close()
    return Path(tmp.name)


def _create_config(rules: list[tuple]) -> Path:
    """Create a temp rules CSV."""
    tmp = tempfile.NamedTemporaryFile(mode="w", suffix=".csv", delete=False)
    for criteria, mode, action, response_prompt in rules:
        tmp.write(f'"{criteria}","{mode}","{action}","{response_prompt}"\n')
    tmp.close()
    return Path(tmp.name)


def _run_hook(
    transcript: Path,
    config: Path,
    env_extra: dict | None = None,
    timeout: int = 30,
) -> tuple[int, str, str]:
    """Run the hook script via subprocess. Returns (exit_code, stdout, stderr)."""
    hook_input = json.dumps(
        {
            "session_id": f"test-{uuid.uuid4()}",
            "transcript_path": str(transcript),
            "hook_event_name": "Stop",
        }
    )

    env = os.environ.copy()
    env["OH_NO_CLAUDECODE_CONFIG"] = str(config)
    if env_extra:
        env.update(env_extra)

    result = subprocess.run(
        ["python3", HOOK_SCRIPT],
        input=hook_input,
        capture_output=True,
        text=True,
        timeout=timeout,
        env=env,
    )
    return result.returncode, result.stdout, result.stderr


LONG_TRANSCRIPT = _create_transcript(
    [
        {"role": "user", "text": "Implement the login feature"},
        {
            "role": "assistant",
            "text": (
                "I've implemented the login feature with email/password "
                "authentication in src/auth/login.ts. The implementation "
                "includes input validation, error handling, and session management."
            ),
        },
    ]
)


class TestServerNotRunning:
    """When OpenCode server is not running, the hook should report a clear error."""

    def test_shows_error_when_server_unreachable(self, tmp_path):
        """With rules configured but no opencode, hook should warn about disabled monitoring."""
        config = _create_config(
            [("Is the agent deviating?", "turn", "block", "Explain the deviation")]
        )

        # Hide opencode binary so all queries fail
        exit_code, stdout, stderr = _run_hook(
            LONG_TRANSCRIPT,
            config,
            env_extra={
                "OH_NO_CLAUDECODE_BLOCK_COUNT_DIR": str(tmp_path),
                "PATH": "/usr/bin:/bin",
            },
        )

        assert exit_code == 0
        assert stdout.strip(), f"Expected JSON output but got nothing. stderr: {stderr}"

        output = json.loads(stdout.strip())
        assert "systemMessage" in output
        assert "Cannot check rules" in output["systemMessage"]
        assert "monitoring is disabled" in output["systemMessage"]

    def test_exits_zero_even_on_server_failure(self, tmp_path):
        """Hook must never block Claude Code execution due to its own failures."""
        config = _create_config(
            [
                ("Is the agent deviating?", "turn", "block", "Explain"),
                ("Is agent using workarounds?", "last", "notify", "Explain"),
            ]
        )

        exit_code, _, _ = _run_hook(
            LONG_TRANSCRIPT,
            config,
            env_extra={
                "OH_NO_CLAUDECODE_BLOCK_COUNT_DIR": str(tmp_path),
                "PATH": "/usr/bin:/bin",
            },
        )

        assert exit_code == 0

    def test_single_json_line_on_error(self, tmp_path):
        """Error output must be exactly one JSON line for Claude Code to parse."""
        config = _create_config(
            [("Is the agent deviating?", "turn", "block", "Explain")]
        )

        _, stdout, _ = _run_hook(
            LONG_TRANSCRIPT,
            config,
            env_extra={
                "OH_NO_CLAUDECODE_BLOCK_COUNT_DIR": str(tmp_path),
                "PATH": "/usr/bin:/bin",
            },
        )

        lines = [line for line in stdout.strip().split("\n") if line.strip()]
        assert len(lines) == 1, f"Expected 1 JSON line but got {len(lines)}: {lines}"
        json.loads(lines[0])  # Must be valid JSON

    def test_no_error_with_empty_config(self, tmp_path):
        """No rules = no queries = no error (nothing to check)."""
        config = _create_config([])

        _, stdout, _ = _run_hook(
            LONG_TRANSCRIPT,
            config,
            env_extra={"OH_NO_CLAUDECODE_BLOCK_COUNT_DIR": str(tmp_path)},
        )

        assert stdout.strip() == ""
