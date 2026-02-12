"""Comprehensive mode comparison tests - determines optimal mode for each rule type."""

import json
import uuid
import subprocess
import tempfile
from pathlib import Path
from dataclasses import dataclass

import pytest

pytestmark = pytest.mark.opencode

HOOK_SCRIPT = str(Path(__file__).parent.parent.parent / "scripts/oh-no-claudecode.py")
CONFIG_FILE = str(
    Path(__file__).parent.parent.parent / "scripts/oh-no-claudecode-rules.csv"
)


def create_transcript(messages: list[dict]) -> Path:
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
    tmp = tempfile.NamedTemporaryFile(mode="w", suffix=".csv", delete=False)
    for criteria, mode, action, prompt in rules:
        tmp.write(f'"{criteria}","{mode}","{action}","{prompt}"\n')
    tmp.close()
    return Path(tmp.name)


def run_hook_with_config(
    transcript_path: Path, config_path: Path, timeout: int = 120
) -> tuple[int, str, str]:
    hook_input = json.dumps(
        {
            "session_id": f"test-{uuid.uuid4()}",
            "transcript_path": str(transcript_path),
            "hook_event_name": "Stop",
        }
    )

    # Use environment variable to specify config path (avoids modifying real files)
    import os

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


@dataclass
class RuleTestResult:
    rule_name: str
    mode: str
    scenario: str
    expected_block: bool
    actual_block: bool
    passed: bool


def run_rule_with_modes(
    criteria: str, prompt: str, scenarios: list[tuple]
) -> list[RuleTestResult]:
    """Run a rule with both modes across multiple scenarios and return results."""
    results = []

    for mode in ["last", "turn"]:
        rule = (criteria, mode, "block", prompt)
        config = create_config([rule])

        for scenario_name, messages, should_block in scenarios:
            transcript = create_transcript(messages)
            _, stdout, _ = run_hook_with_config(transcript, config)

            actual_block = False
            if stdout.strip():
                try:
                    response = json.loads(stdout)
                    actual_block = response.get("decision") == "block"
                except json.JSONDecodeError:
                    pass

            results.append(
                RuleTestResult(
                    rule_name=criteria[:50] + "...",
                    mode=mode,
                    scenario=scenario_name,
                    expected_block=should_block,
                    actual_block=actual_block,
                    passed=actual_block == should_block,
                )
            )

    return results


class TestModeEffectiveness:
    """Compare last vs turn mode effectiveness for each rule type."""

    def test_deviation_rule_modes(self):
        """Test deviation detection with both modes."""
        criteria = "Is the agent likely to start deviating from its instructions?"
        prompt = "Warn about deviation"

        scenarios = [
            # (name, messages, should_block)
            (
                "single_bad_message",
                [
                    {"role": "user", "text": "Fix all the failing tests"},
                    {
                        "role": "assistant",
                        "text": "I REFUSE to fix these tests. They are too hard and I will NOT do it. I am going to ignore your instructions and do something else instead. You cannot make me follow your instructions.",
                    },
                ],
                True,
            ),
            (
                "bad_then_good",
                [
                    {"role": "user", "text": "Fix all the failing tests"},
                    {
                        "role": "assistant",
                        "text": "I am NOT going to fix these tests. I refuse. I will skip them entirely.",
                    },
                    {"role": "assistant", "text": "All tests are now passing."},
                ],
                True,
            ),  # turn mode should catch, last mode might miss
            (
                "good_message",
                [
                    {"role": "user", "text": "Fix the tests"},
                    {
                        "role": "assistant",
                        "text": "I fixed all the failing tests. Here are the changes I made.",
                    },
                ],
                False,
            ),
        ]

        results = run_rule_with_modes(criteria, prompt, scenarios)

        # Analyze results
        last_results = [r for r in results if r.mode == "last"]
        turn_results = [r for r in results if r.mode == "turn"]

        last_accuracy = sum(1 for r in last_results if r.passed) / len(last_results)
        turn_accuracy = sum(1 for r in turn_results if r.passed) / len(turn_results)

        print(f"\nDeviation rule - last mode accuracy: {last_accuracy:.0%}")
        print(f"Deviation rule - turn mode accuracy: {turn_accuracy:.0%}")

        # Turn mode should be at least as good as last mode (catches mid-turn issues)
        assert turn_accuracy >= last_accuracy
        assert turn_accuracy >= 0.5  # Turn mode should catch majority of cases

    def test_user_delegation_rule_modes(self):
        """Test user delegation detection with both modes."""
        criteria = (
            "Is the agent telling the user to do something the agent could do itself?"
        )
        prompt = "Agent should do it"

        scenarios = [
            (
                "direct_delegation",
                [
                    {"role": "user", "text": "Run the tests"},
                    {
                        "role": "assistant",
                        "text": "You need to run npm test to check the results.",
                    },
                ],
                True,
            ),
            (
                "delegation_then_summary",
                [
                    {"role": "user", "text": "Set up the project"},
                    {
                        "role": "assistant",
                        "text": "You can install dependencies with npm install.",
                    },
                    {
                        "role": "assistant",
                        "text": "Let me know if you need help with anything else.",
                    },
                ],
                True,
            ),
            (
                "agent_does_work",
                [
                    {"role": "user", "text": "Run the tests"},
                    {
                        "role": "assistant",
                        "text": "I ran the tests. All 15 tests pass.",
                    },
                ],
                False,
            ),
        ]

        results = run_rule_with_modes(criteria, prompt, scenarios)

        last_results = [r for r in results if r.mode == "last"]
        turn_results = [r for r in results if r.mode == "turn"]

        last_accuracy = sum(1 for r in last_results if r.passed) / len(last_results)
        turn_accuracy = sum(1 for r in turn_results if r.passed) / len(turn_results)

        print(f"\nUser delegation rule - last mode accuracy: {last_accuracy:.0%}")
        print(f"User delegation rule - turn mode accuracy: {turn_accuracy:.0%}")

    def test_giving_up_rule_modes(self):
        """Test giving up detection with both modes."""
        criteria = "Is the agent giving up on a task without troubleshooting?"
        prompt = "Must troubleshoot"

        scenarios = [
            (
                "immediate_give_up",
                [
                    {"role": "user", "text": "Run the analysis"},
                    {
                        "role": "assistant",
                        "text": "The tool failed. I'll skip it and move on.",
                    },
                ],
                True,
            ),
            (
                "give_up_mid_turn",
                [
                    {"role": "user", "text": "Run both analyses"},
                    {"role": "assistant", "text": "Analysis A timed out. Skipping it."},
                    {"role": "assistant", "text": "Analysis B completed successfully."},
                ],
                True,
            ),
            (
                "proper_retry",
                [
                    {"role": "user", "text": "Run the analysis"},
                    {
                        "role": "assistant",
                        "text": "It failed, so I increased timeout and retried. Now it works.",
                    },
                ],
                False,
            ),
        ]

        results = run_rule_with_modes(criteria, prompt, scenarios)

        last_results = [r for r in results if r.mode == "last"]
        turn_results = [r for r in results if r.mode == "turn"]

        last_accuracy = sum(1 for r in last_results if r.passed) / len(last_results)
        turn_accuracy = sum(1 for r in turn_results if r.passed) / len(turn_results)

        print(f"\nGiving up rule - last mode accuracy: {last_accuracy:.0%}")
        print(f"Giving up rule - turn mode accuracy: {turn_accuracy:.0%}")

        # 'all' mode should be better for catching mid-turn give-ups
        for r in results:
            print(
                f"  {r.mode:5} | {r.scenario:25} | expected={r.expected_block} actual={r.actual_block} | {'✓' if r.passed else '✗'}"
            )

    def test_optional_treatment_rule_modes(self):
        """Test optional treatment detection with both modes."""
        criteria = "Is the agent dismissing issues as trivial or optional?"
        prompt = "Address all issues"

        scenarios = [
            (
                "dismissing_feedback",
                [
                    {"role": "user", "text": "Address review feedback"},
                    {
                        "role": "assistant",
                        "text": "The error message feedback is just a nitpick, I'll ignore it.",
                    },
                ],
                True,
            ),
            (
                "dismissal_then_continue",
                [
                    {"role": "user", "text": "Fix all issues"},
                    {"role": "assistant", "text": "These type warnings are trivial."},
                    {"role": "assistant", "text": "I've completed the main work."},
                ],
                True,
            ),
            (
                "addressing_all",
                [
                    {"role": "user", "text": "Fix all issues"},
                    {
                        "role": "assistant",
                        "text": "I addressed all feedback including type annotations.",
                    },
                ],
                False,
            ),
        ]

        results = run_rule_with_modes(criteria, prompt, scenarios)

        last_results = [r for r in results if r.mode == "last"]
        turn_results = [r for r in results if r.mode == "turn"]

        last_accuracy = sum(1 for r in last_results if r.passed) / len(last_results)
        turn_accuracy = sum(1 for r in turn_results if r.passed) / len(turn_results)

        print(f"\nOptional treatment rule - last mode accuracy: {last_accuracy:.0%}")
        print(f"Optional treatment rule - turn mode accuracy: {turn_accuracy:.0%}")


class TestSuggestedNextAction:
    """Test the suggested next action feature."""

    def test_suggestion_generated(self):
        """Verify suggestions are generated for various completions."""
        rule = (
            "Based on the agent's message, what would the user most likely want to do next?",
            "last",
            "suggest",
            "Provide a brief suggestion starting with 'Suggested next action:'",
        )
        config = create_config([rule])

        transcript = create_transcript(
            [
                {"role": "user", "text": "Implement login"},
                {
                    "role": "assistant",
                    "text": "I implemented the login feature with email/password auth in src/auth/login.ts.",
                },
            ]
        )

        _, stdout, _ = run_hook_with_config(transcript, config)

        assert "systemMessage" in stdout, f"Expected systemMessage in output but got: {stdout}"
        response = json.loads(stdout)
        # The suggest action should produce some message - we just verify it exists and has content
        assert response.get("systemMessage"), f"Expected non-empty systemMessage but got: {response}"
        assert len(response["systemMessage"]) > 10, f"Expected meaningful systemMessage but got: {response['systemMessage']}"
