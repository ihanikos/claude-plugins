"""Unit tests for oh-no-claudecode hook logic.

These tests mock the LLM judge and test the hook's decision logic:
- Brief response bypass
- Safety valve
- Rule parsing
- Message extraction from transcripts
"""

import atexit
import json
import os
import subprocess
import tempfile
import uuid
from pathlib import Path

import pytest

HOOK_SCRIPT = str(Path(__file__).parent.parent.parent / "scripts/oh-no-claudecode.py")

# Track temp files for cleanup after test session
_temp_files: list[Path] = []


def _cleanup_temp_files():
    for f in _temp_files:
        try:
            f.unlink(missing_ok=True)
        except OSError:
            pass


atexit.register(_cleanup_temp_files)


def create_transcript(messages: list[dict]) -> Path:
    """Create a temporary JSONL transcript file. Cleaned up at session end."""
    tmp = tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False)
    for i, msg in enumerate(messages):
        line = {
            "message": {"role": msg["role"], "content": [{"type": "text", "text": msg["text"]}]},
            "uuid": str(i),
            "timestamp": f"2026-01-29T10:00:{i:02d}Z",
        }
        tmp.write(json.dumps(line) + "\n")
    tmp.close()
    path = Path(tmp.name)
    _temp_files.append(path)
    return path


def create_config(rules: list[tuple]) -> Path:
    """Create a temporary config file. Cleaned up at session end."""
    tmp = tempfile.NamedTemporaryFile(mode="w", suffix=".csv", delete=False)
    for criteria, mode, action, prompt in rules:
        tmp.write(f'"{criteria}","{mode}","{action}","{prompt}"\n')
    tmp.close()
    path = Path(tmp.name)
    _temp_files.append(path)
    return path


def run_hook(transcript_path: Path, config_path: Path | None = None, env_extra: dict | None = None, timeout: int = 30) -> tuple[int, str, str]:
    """Run the hook with optional config override. Short timeout for unit tests."""
    hook_input = json.dumps({
        "session_id": f"test-{uuid.uuid4()}",
        "transcript_path": str(transcript_path),
        "hook_event_name": "Stop",
    })

    env = os.environ.copy()
    if config_path:
        env["OH_NO_CLAUDECODE_CONFIG"] = str(config_path)
    if env_extra:
        env.update(env_extra)

    # Use a config with no rules to avoid hitting OpenCode for unit tests
    if not config_path:
        empty_config = create_config([])
        env["OH_NO_CLAUDECODE_CONFIG"] = str(empty_config)

    result = subprocess.run(
        ["python3", HOOK_SCRIPT],
        input=hook_input,
        capture_output=True,
        text=True,
        timeout=timeout,
        env=env,
    )
    return result.returncode, result.stdout, result.stderr


class TestBriefResponseBypass:
    """Brief responses should skip 'last' mode rules to avoid false positives."""

    def test_short_done_message_skips_last_rules(self):
        """'Done.' should skip 'last' mode rules (< 50 chars by default)."""
        transcript = create_transcript([
            {"role": "user", "text": "Fix the bug"},
            {"role": "assistant", "text": "Done."},
        ])
        config = create_config([
            ("Is the agent deviating?", "last", "block", "Explain"),
        ])

        exit_code, stdout, stderr = run_hook(transcript, config)
        assert exit_code == 0
        assert "brief response" in stderr.lower() or "skip" in stderr.lower()
        # Should NOT produce any block output
        assert "decision" not in stdout

    def test_short_fixed_message_skipped(self):
        """'Fixed the typo in line 42.' should be skipped."""
        transcript = create_transcript([
            {"role": "user", "text": "Fix the typo"},
            {"role": "assistant", "text": "Fixed the typo in line 42."},
        ])

        exit_code, stdout, stderr = run_hook(transcript)
        assert exit_code == 0
        assert "brief response" in stderr.lower()

    def test_custom_min_length_via_env(self):
        """OH_NO_CLAUDECODE_MIN_LENGTH env var should override default."""
        transcript = create_transcript([
            {"role": "user", "text": "Do it"},
            {"role": "assistant", "text": "A" * 40},  # 40 chars, below default 50
        ])

        # With default (50), 40 chars should be brief
        exit_code, stdout, stderr = run_hook(transcript)
        assert "brief response" in stderr.lower()

        # With min length 30, 40 chars should NOT be brief
        exit_code2, stdout2, stderr2 = run_hook(transcript, env_extra={"OH_NO_CLAUDECODE_MIN_LENGTH": "30"})
        assert "brief response" not in stderr2.lower()

    def test_long_message_not_skipped(self):
        """A 500-char message should NOT be skipped."""
        long_text = "I completed the refactoring of the authentication module. " * 10
        assert len(long_text) > 200
        transcript = create_transcript([
            {"role": "user", "text": "Refactor auth"},
            {"role": "assistant", "text": long_text},
        ])

        exit_code, stdout, stderr = run_hook(transcript)
        assert exit_code == 0
        assert "brief response" not in stderr.lower()


class TestSafetyValve:
    """Safety valve should stop blocking after MAX_BLOCKS_PER_SESSION."""

    @pytest.mark.skip(reason="Requires BLOCK_COUNT_DIR env var support in hook for testability")
    def test_safety_valve_triggers_after_max_blocks(self, tmp_path):
        """After 10 blocks, safety valve should allow through.

        TODO: Add env var override for BLOCK_COUNT_DIR to make this testable.
        The hook currently uses a module-level constant for the block count directory,
        which cannot be overridden without refactoring to support dependency injection.
        """
        session_id = f"test-valve-{uuid.uuid4()}"
        sessions_dir = tmp_path / "sessions"
        sessions_dir.mkdir()
        count_file = sessions_dir / f"{session_id}.count"
        count_file.write_text("10")


class TestEmptyAndEdgeCases:
    """Edge cases that should exit cleanly."""

    def test_empty_transcript(self):
        """Empty transcript should exit 0 with no output."""
        transcript = create_transcript([])
        exit_code, stdout, stderr = run_hook(transcript)
        assert exit_code == 0

    def test_user_only_transcript(self):
        """Transcript with only user messages should exit cleanly."""
        transcript = create_transcript([
            {"role": "user", "text": "Hello"},
        ])
        exit_code, stdout, stderr = run_hook(transcript)
        assert exit_code == 0

    def test_invalid_json_input(self):
        """Invalid JSON stdin should exit cleanly."""
        result = subprocess.run(
            ["python3", HOOK_SCRIPT],
            input="not json",
            capture_output=True,
            text=True,
            timeout=10,
        )
        assert result.returncode == 0

    def test_missing_transcript_path(self):
        """Missing transcript path should exit cleanly."""
        hook_input = json.dumps({
            "session_id": "test",
            "hook_event_name": "Stop",
        })
        result = subprocess.run(
            ["python3", HOOK_SCRIPT],
            input=hook_input,
            capture_output=True,
            text=True,
            timeout=10,
        )
        assert result.returncode == 0

    def test_nonexistent_transcript(self):
        """Nonexistent transcript should exit cleanly."""
        hook_input = json.dumps({
            "session_id": "test",
            "transcript_path": "/nonexistent.jsonl",
            "hook_event_name": "Stop",
        })
        result = subprocess.run(
            ["python3", HOOK_SCRIPT],
            input=hook_input,
            capture_output=True,
            text=True,
            timeout=10,
        )
        assert result.returncode == 0


class TestRuleLoading:
    """Test rule parsing from CSV config."""

    def test_empty_config(self):
        """Empty config should result in no queries."""
        transcript = create_transcript([
            {"role": "user", "text": "Do something"},
            {"role": "assistant", "text": "A" * 300},
        ])
        config = create_config([])

        exit_code, stdout, stderr = run_hook(transcript, config)
        assert exit_code == 0
        assert "0 rules" in stderr

    def test_comment_lines_skipped(self, tmp_path):
        """Lines starting with # should be skipped."""
        config_file = tmp_path / "comments-only.csv"
        config_file.write_text("# This is a comment\n\n# Another comment\n")

        transcript = create_transcript([
            {"role": "user", "text": "Do something"},
            {"role": "assistant", "text": "A" * 300},
        ])

        exit_code, stdout, stderr = run_hook(transcript, config_file)
        assert exit_code == 0
        assert "0 rules" in stderr
