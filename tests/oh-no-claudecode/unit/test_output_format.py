"""Unit tests for oh-no-claudecode output format.

Tests the hook's JSON output by mocking query_opencode at the function level.
Covers fixes: rule criteria in output, verdict stripping from suggest,
suggest requires YES verdict, notify+suggest combined into single JSON.
"""

import importlib.util
import io
import json
import tempfile
import uuid
from pathlib import Path
from unittest.mock import patch

import pytest

# Import the hook script as a module (hyphenated filename requires importlib)
PLUGIN_DIR = (
    Path(__file__).resolve().parent.parent.parent.parent / "plugins/oh-no-claudecode"
)
_spec = importlib.util.spec_from_file_location(
    "oh_no_claudecode",
    PLUGIN_DIR / "scripts/oh-no-claudecode.py",
)
hook = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(hook)


def _make_transcript(messages: list[dict]) -> Path:
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


def _make_config(rules: list[tuple]) -> Path:
    """Create a temp rules CSV (columns: criteria, mode, action, response_prompt)."""
    tmp = tempfile.NamedTemporaryFile(mode="w", suffix=".csv", delete=False)
    for criteria, mode, action, response_prompt in rules:
        tmp.write(f'"{criteria}","{mode}","{action}","{response_prompt}"\n')
    tmp.close()
    return Path(tmp.name)


# Shared transcript — long enough to not be skipped by brief-response check
STANDARD_TRANSCRIPT = _make_transcript(
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


def _run_hook(
    config: Path,
    tmp_path: Path,
    query_mock=None,
    transcript: Path | None = None,
) -> tuple[int, str, str]:
    """Run hook main() with mocked query_opencode. Returns (exit_code, stdout, stderr)."""
    if transcript is None:
        transcript = STANDARD_TRANSCRIPT
    if query_mock is None:
        query_mock = lambda prompt: "NO\n\nNo issues found."

    hook_input = {
        "session_id": f"test-{uuid.uuid4()}",
        "transcript_path": str(transcript),
        "hook_event_name": "Stop",
    }

    stdout_buf = io.StringIO()
    stderr_buf = io.StringIO()
    exit_code = 0

    with (
        patch.object(hook, "CONFIG_FILE", config),
        patch.object(hook, "BLOCK_COUNT_DIR", tmp_path / "blocks"),
        patch.object(hook, "query_opencode", side_effect=query_mock),
        patch("sys.stdin", io.StringIO(json.dumps(hook_input))),
        patch("sys.stdout", stdout_buf),
        patch("sys.stderr", stderr_buf),
    ):
        try:
            hook.main()
        except SystemExit as e:
            exit_code = e.code if e.code is not None else 0

    return exit_code, stdout_buf.getvalue(), stderr_buf.getvalue()


class TestBlockOutputFormat:
    """Block output should include rule criteria in reason."""

    def test_block_includes_rule_criteria(self, tmp_path):
        config = _make_config(
            [
                (
                    "Is the agent deviating from instructions?",
                    "turn",
                    "block",
                    "Explain the deviation",
                ),
            ]
        )

        _, stdout, _ = _run_hook(
            config,
            tmp_path,
            query_mock=lambda p: "YES\n\nThe agent started ignoring the requirements.",
        )

        output = json.loads(stdout.strip())
        assert output["decision"] == "block"
        assert "Is the agent deviating from instructions?" in output["reason"]
        assert "The agent started ignoring the requirements." in output["reason"]

    def test_block_reason_does_not_start_with_verdict(self, tmp_path):
        config = _make_config(
            [("Is the agent deviating?", "turn", "block", "Explain")]
        )

        _, stdout, _ = _run_hook(
            config,
            tmp_path,
            query_mock=lambda p: "YES\n\nAgent is deviating.",
        )

        output = json.loads(stdout.strip())
        assert not output["reason"].startswith("YES")


class TestSuggestOutputFormat:
    """Suggest should use explanation (stripped of verdict) and require YES."""

    def test_suggest_strips_verdict(self, tmp_path):
        config = _make_config(
            [
                (
                    "What should the user do next?",
                    "last",
                    "suggest",
                    "Provide suggestion",
                ),
            ]
        )

        _, stdout, _ = _run_hook(
            config,
            tmp_path,
            query_mock=lambda p: "YES\n\nSuggested next action: run the test suite.",
        )

        output = json.loads(stdout.strip())
        msg = output["systemMessage"]
        assert "YES" not in msg
        assert "Suggested next action: run the test suite." in msg

    def test_suggest_requires_yes_verdict(self, tmp_path):
        config = _make_config(
            [
                (
                    "What should the user do next?",
                    "last",
                    "suggest",
                    "Provide suggestion",
                ),
            ]
        )

        _, stdout, _ = _run_hook(
            config,
            tmp_path,
            query_mock=lambda p: "NO\n\nNo suggestion needed.",
        )

        assert stdout.strip() == ""

    def test_suggest_includes_rule_criteria(self, tmp_path):
        config = _make_config(
            [
                (
                    "What should the user do next?",
                    "last",
                    "suggest",
                    "Provide suggestion",
                ),
            ]
        )

        _, stdout, _ = _run_hook(
            config,
            tmp_path,
            query_mock=lambda p: "YES\n\nRun the tests.",
        )

        output = json.loads(stdout.strip())
        assert "What should the user do next?" in output["systemMessage"]


class TestNotifyOutputFormat:
    """Notify should include rule criteria."""

    def test_notify_includes_rule_criteria(self, tmp_path):
        config = _make_config(
            [
                (
                    "Is the agent using workarounds?",
                    "last",
                    "notify",
                    "Point out the workaround",
                ),
            ]
        )

        _, stdout, _ = _run_hook(
            config,
            tmp_path,
            query_mock=lambda p: "YES\n\nThe agent is using a workaround for auth.",
        )

        output = json.loads(stdout.strip())
        assert "Is the agent using workarounds?" in output["systemMessage"]
        assert "The agent is using a workaround" in output["systemMessage"]


class TestCombinedOutput:
    """Multiple non-block messages must be combined into a single JSON line."""

    def test_notify_and_suggest_single_json(self, tmp_path):
        config = _make_config(
            [
                ("Is the agent using workarounds?", "last", "notify", "Explain"),
                ("What should user do next?", "last", "suggest", "Suggest"),
            ]
        )

        _, stdout, _ = _run_hook(
            config,
            tmp_path,
            query_mock=lambda p: "YES\n\nSome explanation.",
        )

        lines = [line for line in stdout.strip().split("\n") if line.strip()]
        assert len(lines) == 1, f"Expected 1 JSON line but got {len(lines)}: {lines}"

        output = json.loads(lines[0])
        assert "systemMessage" in output
        assert "Is the agent using workarounds?" in output["systemMessage"]
        assert "What should user do next?" in output["systemMessage"]

    def test_block_takes_priority_over_notify_suggest(self, tmp_path):
        """Block should exit immediately without notify/suggest output."""
        config = _make_config(
            [
                ("Is agent deviating?", "turn", "block", "Explain"),
                ("Is agent using workarounds?", "last", "notify", "Explain"),
                ("What next?", "last", "suggest", "Suggest"),
            ]
        )

        _, stdout, _ = _run_hook(
            config,
            tmp_path,
            query_mock=lambda p: "YES\n\nIssue found.",
        )

        output = json.loads(stdout.strip())
        assert output["decision"] == "block"
        assert "systemMessage" not in output


class TestServerNotRunning:
    """When all queries fail (server not running), show a clear error."""

    def test_all_queries_fail_shows_error(self, tmp_path):
        config = _make_config(
            [("Is the agent deviating?", "turn", "block", "Explain")]
        )

        _, stdout, stderr = _run_hook(
            config,
            tmp_path,
            query_mock=lambda p: None,  # Server not responding
        )

        output = json.loads(stdout.strip())
        assert "systemMessage" in output
        assert "Cannot check rules" in output["systemMessage"]
        assert "monitoring is disabled" in output["systemMessage"]

    def test_partial_failure_no_error(self, tmp_path):
        """If some queries succeed, don't show server error."""
        config = _make_config(
            [
                ("Is the agent deviating?", "turn", "block", "Explain"),
                ("Is agent using workarounds?", "last", "notify", "Explain"),
            ]
        )

        call_count = 0

        def partial_mock(prompt):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return "NO\n\nNo issues."
            return None

        _, stdout, _ = _run_hook(config, tmp_path, query_mock=partial_mock)

        # Should NOT show server error since one query succeeded
        if stdout.strip():
            output = json.loads(stdout.strip())
            assert "Cannot check rules" not in output.get("systemMessage", "")


class TestDisabledRules:
    """Commented-out rules in production CSV should not be loaded."""

    def test_production_csv_rule7_disabled(self):
        """Rule 7 (suggest 'what would user want to do next') should be commented out."""
        production_csv = PLUGIN_DIR / "scripts/oh-no-claudecode-rules.csv"
        assert production_csv.exists()

        with patch.object(hook, "CONFIG_FILE", production_csv):
            rules = hook.load_rules()

        criteria_list = [r["criteria"] for r in rules]
        assert not any(
            "what would the user most likely want to do next" in c.lower()
            for c in criteria_list
        ), f"Rule 7 should be commented out but found in: {criteria_list}"

    def test_production_csv_active_rule_count(self):
        """Production CSV should have 7 active rules (8 minus disabled rule 7)."""
        production_csv = PLUGIN_DIR / "scripts/oh-no-claudecode-rules.csv"

        with patch.object(hook, "CONFIG_FILE", production_csv):
            rules = hook.load_rules()

        assert len(rules) == 7, f"Expected 7 active rules but got {len(rules)}: {[r['criteria'][:40] for r in rules]}"
