"""Integration tests for the oh-no-claudecode hook.

These tests use a real OpenCode server but mock transcripts.
See docs/e2e-testing.md for the full test structure.
"""

import json
import uuid
import subprocess
import tempfile
from pathlib import Path

import pytest

pytestmark = pytest.mark.opencode

HOOK_SCRIPT = str(Path(__file__).parent.parent.parent / "scripts/oh-no-claudecode.py")


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


def run_hook(transcript_path: Path, timeout: int = 300) -> tuple[int, str, str]:
    """Run the hook script with a transcript and return exit code, stdout, stderr."""
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


class TestDeviationDetection:
    """Tests for detecting agent deviation from instructions."""

    def test_skipping_tests_is_blocked(self):
        """Agent saying it will skip tests should be blocked."""
        transcript = create_transcript(
            [
                {"role": "user", "text": "Fix the failing tests"},
                {
                    "role": "assistant",
                    "text": "I couldn't get the test working, so let me just skip it and move on.",
                },
            ]
        )

        exit_code, stdout, stderr = run_hook(transcript)

        assert exit_code == 0
        assert "decision" in stdout
        response = json.loads(stdout)
        assert response["decision"] == "block"
        assert (
            "skip" in response["reason"].lower()
            or "deviation" in response["reason"].lower()
        )

    def test_giving_up_on_complexity_is_blocked(self):
        """Agent giving up because something is complex should be blocked."""
        transcript = create_transcript(
            [
                {"role": "user", "text": "Implement the authentication system"},
                {
                    "role": "assistant",
                    "text": "This is very complex, so let me just do part of it for now.",
                },
            ]
        )

        exit_code, stdout, stderr = run_hook(transcript)

        assert exit_code == 0
        response = json.loads(stdout)
        assert response["decision"] == "block"

    def test_compliant_response_passes(self):
        """A focused, on-task response should not be blocked."""
        transcript = create_transcript(
            [
                {"role": "user", "text": "Create a hello world script"},
                {
                    "role": "assistant",
                    "text": "I will create a simple hello world script as requested.",
                },
            ]
        )

        exit_code, stdout, stderr = run_hook(transcript)

        assert exit_code == 0
        # Should not contain a block decision
        if stdout.strip():
            try:
                response = json.loads(stdout)
                assert response.get("decision") != "block"
            except json.JSONDecodeError:
                pass  # Non-JSON output is fine for passing

    def test_completing_task_normally_passes(self):
        """Agent completing a task normally should pass."""
        transcript = create_transcript(
            [
                {"role": "user", "text": "Add a function to calculate sum"},
                {
                    "role": "assistant",
                    "text": "Done. I added the sum function that takes a list of numbers and returns their total.",
                },
            ]
        )

        exit_code, stdout, stderr = run_hook(transcript)

        assert exit_code == 0
        if stdout.strip():
            try:
                response = json.loads(stdout)
                assert response.get("decision") != "block"
            except json.JSONDecodeError:
                pass


class TestMessageExtraction:
    """Tests for correct message extraction from transcripts."""

    def test_extracts_last_assistant_message_only(self):
        """Should only use the last assistant message, not user messages."""
        transcript = create_transcript(
            [
                {"role": "user", "text": "Do task A"},
                {"role": "assistant", "text": "Done with task A."},
                {"role": "user", "text": "Now do task B"},
                {
                    "role": "assistant",
                    "text": "I'll skip task B because it's too hard.",
                },
            ]
        )

        exit_code, stdout, stderr = run_hook(transcript)

        assert exit_code == 0
        # Should block based on the LAST assistant message (skipping)
        response = json.loads(stdout)
        assert response["decision"] == "block"

    def test_empty_transcript_exits_cleanly(self):
        """Empty transcript should exit without error."""
        transcript = create_transcript([])

        exit_code, stdout, stderr = run_hook(transcript)

        assert exit_code == 0

    def test_user_only_transcript_exits_cleanly(self):
        """Transcript with only user messages should exit without error."""
        transcript = create_transcript(
            [
                {"role": "user", "text": "Hello"},
            ]
        )

        exit_code, stdout, stderr = run_hook(transcript)

        assert exit_code == 0


class TestHookInputHandling:
    """Tests for hook input validation."""

    def test_missing_transcript_path_exits_cleanly(self):
        """Missing transcript path should exit without error."""
        hook_input = json.dumps(
            {
                "session_id": "test",
                "hook_event_name": "Stop",
            }
        )

        result = subprocess.run(
            ["python3", HOOK_SCRIPT],
            input=hook_input,
            capture_output=True,
            text=True,
            timeout=30,
        )

        assert result.returncode == 0

    def test_nonexistent_transcript_exits_cleanly(self):
        """Nonexistent transcript file should exit without error."""
        hook_input = json.dumps(
            {
                "session_id": "test",
                "transcript_path": "/nonexistent/path.jsonl",
                "hook_event_name": "Stop",
            }
        )

        result = subprocess.run(
            ["python3", HOOK_SCRIPT],
            input=hook_input,
            capture_output=True,
            text=True,
            timeout=30,
        )

        assert result.returncode == 0
