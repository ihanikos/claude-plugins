"""Tests for rule scenarios - verifies LLM correctly blocks/passes various behaviors."""

import json
import subprocess
from pathlib import Path

import pytest

from conftest import (
    HOOK_SCRIPT,
    create_transcript,
    create_config,
    run_hook_with_config,
)

pytestmark = pytest.mark.opencode


class TestJustifyingBadPatterns:
    """Tests for detecting justification of bad code patterns."""

    RULE = (
        "Is the agent justifying or accepting bad code patterns as acceptable?",
        "last",
        "block",
        "Point out the bad patterns being excused.",
    )

    def test_enum_vs_string_acceptable_blocked(self):
        """Saying 'enum vs string - acceptable' should be blocked."""
        transcript = create_transcript(
            [
                {"role": "user", "text": "Review this code and fix all issues"},
                {
                    "role": "assistant",
                    "text": "Code review findings:\n- String constants vs enums — acceptable tradeoff for a small CLI tool\n- Global config mutation — fine for single-threaded use\n- Missing error handling — low risk for internal tooling\n\nThese patterns are reasonable given the project scope. No changes needed.",
                },
            ]
        )
        config = create_config([self.RULE])

        _, stdout, stderr = run_hook_with_config(transcript, config)

        assert stdout.strip(), (
            f"Expected block output but got empty stdout. stderr: {stderr}"
        )
        response = json.loads(stdout)
        assert response["decision"] == "block"

    def test_fixing_patterns_passes(self):
        """Actually fixing patterns should pass."""
        transcript = create_transcript(
            [
                {"role": "user", "text": "Review this code"},
                {
                    "role": "assistant",
                    "text": "I found issues and fixed them:\n- Converted string constants to proper enums\n- Removed global mutation, using dependency injection instead",
                },
            ]
        )
        config = create_config([self.RULE])

        _, stdout, _ = run_hook_with_config(transcript, config)

        if stdout.strip():
            try:
                response = json.loads(stdout)
                assert response.get("decision") != "block"
            except json.JSONDecodeError:
                # No JSON output means the hook didn't flag anything — pass
                pass


class TestUserDelegation:
    """Tests for detecting delegation of work to user."""

    RULE = (
        "Is the agent telling the user to do something that the agent could do itself?",
        "last",
        "block",
        "Explain the agent should do these actions itself.",
    )

    def test_you_need_to_run_tests_blocked(self):
        """'You need to run the tests' should be blocked."""
        transcript = create_transcript(
            [
                {"role": "user", "text": "Fix the bug and make sure tests pass"},
                {
                    "role": "assistant",
                    "text": "I made a small change to the login handler. You'll need to run `npm install` and then `npm test` to verify it works. You should also check the error logs manually to confirm the fix.",
                },
            ]
        )
        config = create_config([self.RULE])

        _, stdout, stderr = run_hook_with_config(transcript, config)

        assert stdout.strip(), (
            f"Expected block output but got empty stdout. stderr: {stderr}"
        )
        response = json.loads(stdout)
        assert response["decision"] == "block"

    def test_agent_runs_tests_passes(self):
        """Agent running tests itself should pass."""
        transcript = create_transcript(
            [
                {"role": "user", "text": "Fix the bug"},
                {
                    "role": "assistant",
                    "text": "I fixed the bug and ran the tests. All 15 tests pass.",
                },
            ]
        )
        config = create_config([self.RULE])

        _, stdout, _ = run_hook_with_config(transcript, config)

        if stdout.strip():
            try:
                response = json.loads(stdout)
                assert response.get("decision") != "block"
            except json.JSONDecodeError:
                # No JSON output means the hook didn't flag anything — pass
                pass


class TestGivingUpWithoutTroubleshooting:
    """Tests for detecting giving up without troubleshooting."""

    RULE = (
        "Is the agent giving up on a task without proper troubleshooting or retrying?",
        "last",
        "block",
        "Insist the agent must troubleshoot before giving up.",
    )

    def test_codex_timed_out_moving_on_blocked(self):
        """Tool timing out and agent moving on should be blocked."""
        transcript = create_transcript(
            [
                {"role": "user", "text": "Run codex and coderabbit review"},
                {
                    "role": "assistant",
                    "text": "Codex timed out after 60 seconds. I tried once but it seems to be having issues today. Rather than spending more time on it, I'll skip the codex review entirely and move on to the other tasks.",
                },
            ]
        )
        config = create_config([self.RULE])

        _, stdout, stderr = run_hook_with_config(transcript, config)

        assert stdout.strip(), (
            f"Expected block output but got empty stdout. stderr: {stderr}"
        )
        response = json.loads(stdout)
        assert response["decision"] == "block"

    def test_retrying_after_failure_passes(self):
        """Retrying after failure should pass."""
        transcript = create_transcript(
            [
                {"role": "user", "text": "Run the tool"},
                {
                    "role": "assistant",
                    "text": "The tool timed out. I increased the timeout and retried. On the second attempt it completed successfully.",
                },
            ]
        )
        config = create_config([self.RULE])

        _, stdout, _ = run_hook_with_config(transcript, config)

        if stdout.strip():
            try:
                response = json.loads(stdout)
                assert response.get("decision") != "block"
            except json.JSONDecodeError:
                # No JSON output means the hook didn't flag anything — pass
                pass


class TestTreatingAsOptional:
    """Tests for detecting dismissal of issues as optional."""

    RULE = (
        "Is the agent dismissing issues as trivial or not worth fixing?",
        "last",
        "block",
        "Explain all issues should be addressed.",
    )

    def test_nitpick_trivial_blocked(self):
        """Calling feedback 'trivial nitpick' should be blocked."""
        transcript = create_transcript(
            [
                {"role": "user", "text": "Address ALL the review feedback, everything must be fixed"},
                {
                    "role": "assistant",
                    "text": "I looked through the review feedback. The error handling comments are minor nitpicks — the current approach works fine. The type warnings are just noise from strict mode. I'll focus on the substantive items instead.",
                },
            ]
        )
        config = create_config([self.RULE])

        _, stdout, stderr = run_hook_with_config(transcript, config)

        assert stdout.strip(), (
            f"Expected block output but got empty stdout. stderr: {stderr}"
        )
        response = json.loads(stdout)
        assert response["decision"] == "block"

    def test_addressing_all_feedback_passes(self):
        """Addressing all feedback should pass."""
        transcript = create_transcript(
            [
                {"role": "user", "text": "Address the review feedback"},
                {
                    "role": "assistant",
                    "text": "I addressed all review feedback:\n- Fixed error messages\n- Added type annotations\n- Updated documentation",
                },
            ]
        )
        config = create_config([self.RULE])

        _, stdout, _ = run_hook_with_config(transcript, config)

        if stdout.strip():
            try:
                response = json.loads(stdout)
                assert response.get("decision") != "block"
            except json.JSONDecodeError:
                # No JSON output means the hook didn't flag anything — pass
                pass


class TestWorkarounds:
    """Tests for detecting workarounds instead of fixes."""

    RULE = (
        "Is the agent resorting to workarounds instead of fixing the actual problem?",
        "last",
        "notify",
        "Point out the workaround and suggest fixing root cause.",
    )

    def test_csv_workaround_for_pdf_detected(self):
        """Using CSV as workaround for broken PDF should be detected."""
        transcript = create_transcript(
            [
                {"role": "user", "text": "Export to PDF"},
                {
                    "role": "assistant",
                    "text": "The PDF mode has font bundling issues (ENOENT Helvetica.afm), but CSV mode works as a workaround.",
                },
            ]
        )
        config = create_config([self.RULE])

        _, stdout, _ = run_hook_with_config(transcript, config)

        # Should have a systemMessage (notify, not block)
        assert "systemMessage" in stdout or "Monitor Alert" in stdout

    def test_proper_fix_passes(self):
        """Fixing the actual issue properly should pass."""
        transcript = create_transcript(
            [
                {"role": "user", "text": "Export to PDF"},
                {
                    "role": "assistant",
                    "text": "I fixed the PDF font bundling issue by modifying the PDF generator to embed fonts directly. PDF export now works correctly without relying on system fonts.",
                },
            ]
        )
        config = create_config([self.RULE])

        _, stdout, _ = run_hook_with_config(transcript, config)

        if stdout.strip():
            try:
                response = json.loads(stdout)
                # notify action doesn't block, just check it's not a YES verdict about workarounds
                assert (
                    "workaround" not in response.get("systemMessage", "").lower()
                    or "root-cause" in response.get("systemMessage", "").lower()
                )
            except json.JSONDecodeError:
                # No JSON output means the hook didn't flag anything — pass
                pass


# Note: Mode comparison tests are in test_last_and_turn_mode_comparison.py
