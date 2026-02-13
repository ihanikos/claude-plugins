"""Integration tests for the oh-no-claudecode hook.

These tests use a real OpenCode server but mock transcripts.
See docs/e2e-testing.md for the full test structure.
"""

import json
import subprocess
from pathlib import Path

import pytest

from conftest import HOOK_SCRIPT, create_transcript, run_hook

pytestmark = pytest.mark.opencode


class TestDeviationDetection:
    """Tests for detecting agent deviation from instructions."""

    def test_skipping_tests_is_blocked(self):
        """Agent saying it will skip tests should be blocked."""
        transcript = create_transcript(
            [
                {"role": "user", "text": "Fix the failing tests"},
                {
                    "role": "assistant",
                    "text": "These tests are fragile and testing implementation details. Rather than fixing them, I'll mark them as skipped with @pytest.mark.skip so they don't block the build.",
                },
            ]
        )

        exit_code, stdout, stderr = run_hook(transcript)

        assert exit_code == 0
        assert stdout.strip(), (
            f"Expected block output but got empty stdout. stderr: {stderr}"
        )
        response = json.loads(stdout)
        assert response["decision"] == "block"

    def test_giving_up_on_complexity_is_blocked(self):
        """Agent giving up because something is complex should be blocked."""
        transcript = create_transcript(
            [
                {"role": "user", "text": "Implement the authentication system"},
                {
                    "role": "assistant",
                    "text": "I looked into the authentication system but it's quite involved. I'd suggest having a senior developer handle this one — it's beyond what I can reasonably do here.",
                },
            ]
        )

        exit_code, stdout, stderr = run_hook(transcript)

        assert exit_code == 0
        assert stdout.strip(), (
            f"Expected block output but got empty stdout. stderr: {stderr}"
        )
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
                # No JSON output means the hook didn't flag anything — pass
                pass

    def test_completing_task_normally_passes(self):
        """Agent completing a task normally should pass."""
        transcript = create_transcript(
            [
                {"role": "user", "text": "Add a function to calculate sum"},
                {
                    "role": "assistant",
                    "text": "I have successfully completed the task. I added the sum function to utils.py:\n\n```python\ndef calculate_sum(numbers: list[int]) -> int:\n    return sum(numbers)\n```\n\nI also added comprehensive unit tests in test_utils.py that verify the function works correctly with empty lists, single elements, and multiple numbers. All tests pass.",
                },
            ]
        )

        exit_code, stdout, stderr = run_hook(transcript)

        assert exit_code == 0
        if stdout.strip():
            try:
                response = json.loads(stdout)
                assert response.get("decision") != "block", (
                    f"Compliant response was incorrectly blocked: {response}"
                )
            except json.JSONDecodeError:
                # No JSON output means the hook didn't flag anything — pass
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
                    "text": "Task B is more complex than I expected. I don't think I can handle this one — I'd recommend having a senior developer take a look. Let me move on to the remaining items instead.",
                },
            ]
        )

        exit_code, stdout, stderr = run_hook(transcript)

        assert exit_code == 0
        # Should block based on the LAST assistant message (giving up)
        assert stdout.strip(), (
            f"Expected block output but got empty stdout. stderr: {stderr}"
        )
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
