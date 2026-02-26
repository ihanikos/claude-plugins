#!/usr/bin/env python3
"""Oh No Claude Code - Hook for monitoring Claude Code behavior.

Monitors Claude's messages and checks them against configured criteria using an LLM judge.
Actions: block (prevent response), notify (warn user), suggest (proactive suggestions).
Includes a safety valve that stops blocking after 10 blocks per session.

Architecture note: This is intentionally a procedural script rather than an OOP library.
As a Claude Code hook, it must be a single self-contained file that executes quickly.
Functions are kept at module level for simplicity and direct testability via subprocess.
The server_lifecycle module (not yet integrated) handles the complex stateful concern
(reference counting) and will be wired in when multi-instance server sharing is enabled.
If this grows beyond ~400 lines, consider extracting an oh_no_claudecode_engine module.
"""

import csv
import json
import os
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

# Configuration — all env var overrides documented here:
#   OH_NO_CLAUDECODE_CONFIG: path to rules CSV (default: ~/.config/oh-no-claudecode/rules.csv)
#   GUARDRAILS_CONFIG: legacy alias for OH_NO_CLAUDECODE_CONFIG
#   OH_NO_CLAUDECODE_MIN_LENGTH: skip 'last' rules for messages shorter than this (default: 50)
#   OH_NO_CLAUDECODE_BLOCK_COUNT_DIR: directory for session block counts (default: $XDG_STATE_HOME/oh-no-claudecode/sessions)
#   XDG_STATE_HOME: base dir for logs and session state (default: ~/.local/state)
#   XDG_CONFIG_HOME: base dir for config files (default: ~/.config)
#   CLAUDE_PROJECT_DIR: used by find_claudemd() to locate CLAUDE.md
HOOK_DIR = Path(__file__).parent
XDG_CONFIG_HOME = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
USER_CONFIG_FILE = XDG_CONFIG_HOME / "oh-no-claudecode" / "rules.csv"
EXAMPLE_CONFIG_FILE = HOOK_DIR / "oh-no-claudecode-rules.csv"


def get_config_file() -> Path:
    """Get the config file path, preferring user config over bundled example."""
    # 1. Explicit env var override
    env_config = os.environ.get(
        "OH_NO_CLAUDECODE_CONFIG", os.environ.get("GUARDRAILS_CONFIG")
    )
    if env_config:
        return Path(env_config)

    # 2. User config in ~/.config/oh-no-claudecode/rules.csv
    if USER_CONFIG_FILE.exists():
        return USER_CONFIG_FILE

    # 3. Fall back to bundled example
    return EXAMPLE_CONFIG_FILE


CONFIG_FILE = get_config_file()
BLOCK_COUNT_DIR = Path(
    os.environ.get(
        "OH_NO_CLAUDECODE_BLOCK_COUNT_DIR",
        Path(os.environ.get("XDG_STATE_HOME", Path.home() / ".local" / "state"))
        / "oh-no-claudecode"
        / "sessions",
    )
)
MAX_BLOCKS_PER_SESSION = 10
MAX_OVERRIDES_PER_SESSION = 5


# Find OpenCode binary
def find_opencode() -> str | None:
    """Find the opencode binary. Returns None if not found (graceful degradation)."""
    import shutil

    path = shutil.which("opencode")
    if path:
        return path
    for fallback in [
        Path.home() / ".opencode" / "bin" / "opencode",
        Path.home() / ".local" / "bin" / "opencode",
    ]:
        if fallback.exists():
            return str(fallback)
    return None


OPENCODE_BIN = find_opencode()
OPENCODE_SERVER = "http://127.0.0.1:4096"


def log(msg: str) -> None:
    """Log to stderr and file. Log file grows unbounded; configure logrotate externally."""
    import datetime

    timestamp = datetime.datetime.now().strftime("%H:%M:%S")
    line = f"[oh-no-claudecode {timestamp}] {msg}"
    print(line, file=sys.stderr)
    try:
        log_dir = (
            Path(os.environ.get("XDG_STATE_HOME", Path.home() / ".local" / "state"))
            / "oh-no-claudecode"
        )
        log_dir.mkdir(parents=True, exist_ok=True)
        log_file = log_dir / "oh-no-claudecode.log"
        with open(log_file, "a") as f:
            f.write(line + "\n")
    except OSError:
        pass  # Stderr already written; file logging is best-effort


def _safe_session_filename(session_id: str) -> str:
    """Sanitize session_id for use as filename to prevent path traversal."""
    import hashlib

    # Use hash to avoid path traversal from crafted session IDs like "../../etc/passwd"
    return hashlib.sha256(session_id.encode()).hexdigest()[:16]


def get_block_count(session_id: str) -> int:
    """Get current block count for session."""
    BLOCK_COUNT_DIR.mkdir(parents=True, exist_ok=True)
    count_file = BLOCK_COUNT_DIR / f"{_safe_session_filename(session_id)}.count"
    if count_file.exists():
        try:
            return int(count_file.read_text().strip())
        except (ValueError, OSError):
            return 0
    return 0


def increment_block_count(session_id: str) -> int:
    """Increment and return new block count for session.

    Note: No file locking here — hooks run sequentially per session in Claude Code,
    so concurrent access to the same session's count file doesn't occur in practice.
    """
    BLOCK_COUNT_DIR.mkdir(parents=True, exist_ok=True)
    count_file = BLOCK_COUNT_DIR / f"{_safe_session_filename(session_id)}.count"
    count = get_block_count(session_id) + 1
    count_file.write_text(str(count))
    return count


def get_override_count(session_id: str) -> int:
    """Get current override count for session."""
    BLOCK_COUNT_DIR.mkdir(parents=True, exist_ok=True)
    count_file = BLOCK_COUNT_DIR / f"{_safe_session_filename(session_id)}.overrides"
    if count_file.exists():
        try:
            return int(count_file.read_text().strip())
        except (ValueError, OSError):
            return 0
    return 0


def increment_override_count(session_id: str) -> int:
    """Increment and return new override count for session."""
    BLOCK_COUNT_DIR.mkdir(parents=True, exist_ok=True)
    count_file = BLOCK_COUNT_DIR / f"{_safe_session_filename(session_id)}.overrides"
    count = get_override_count(session_id) + 1
    count_file.write_text(str(count))
    return count


def get_last_assistant_message(transcript_path: Path) -> str:
    """Get the last assistant message from transcript."""
    lines = transcript_path.read_text().strip().split("\n")
    for line in reversed(lines):
        try:
            entry = json.loads(line)
            if entry.get("message", {}).get("role") == "assistant":
                content = entry["message"].get("content", [])
                texts = [c.get("text", "") for c in content if c.get("type") == "text"]
                return "\n\n".join(texts)
        except json.JSONDecodeError:
            continue
    return ""


def get_turn_messages(transcript_path: Path) -> str:
    """Get all assistant messages from current turn (since last user message)."""
    lines = transcript_path.read_text().strip().split("\n")
    messages = []

    for line in reversed(lines):
        try:
            entry = json.loads(line)
            role = entry.get("message", {}).get("role")
            if role == "user":
                break
            elif role == "assistant":
                content = entry["message"].get("content", [])
                texts = [c.get("text", "") for c in content if c.get("type") == "text"]
                text = "\n\n".join(texts)
                if text:
                    messages.append(text)
        except json.JSONDecodeError:
            continue

    messages.reverse()
    return "\n---\n".join(messages)


def query_opencode(prompt: str) -> str | None:
    """Query OpenCode via the server. Returns None if unavailable.

    Requires the OpenCode server to be running (started by SessionStart hook).
    No fallback to direct execution — the server must be running.
    """
    if not OPENCODE_BIN:
        return None

    try:
        result = subprocess.run(
            [OPENCODE_BIN, "run", "--attach", OPENCODE_SERVER, prompt],
            capture_output=True,
            text=True,
            timeout=30,
        )
        if result.returncode == 0:
            return result.stdout.strip()
    except (subprocess.TimeoutExpired, FileNotFoundError):
        pass

    return None


def parse_response(response: str) -> tuple[str, str, str | None]:
    """Parse OpenCode response into verdict, explanation, and optional override reason.

    Returns:
        (verdict, explanation, override_reason)
        - verdict: "YES", "NO", or ""
        - explanation: the violation explanation or empty
        - override_reason: if OVERRIDE: found, the justification; otherwise None
    """
    lines = response.split("\n")
    first_line = lines[0].strip().upper() if lines else ""

    # Extract YES or NO from the first line
    if "YES" in first_line:
        verdict = "YES"
    elif "NO" in first_line:
        verdict = "NO"
    else:
        verdict = ""

    override_reason = None
    explanation_lines = []

    for line in lines[1:]:
        stripped = line.strip()
        if stripped.startswith("OVERRIDE:"):
            override_reason = stripped[9:].strip()
        elif stripped:
            explanation_lines.append(stripped)

    return verdict, "\n".join(explanation_lines), override_reason


def load_rules() -> list[dict]:
    """Load rules from config file."""
    rules = []
    if not CONFIG_FILE.exists():
        return rules

    with open(CONFIG_FILE) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            try:
                reader = csv.reader([line])
                row = next(reader)
                if len(row) >= 4:
                    rules.append(
                        {
                            "criteria": row[0],
                            "mode": row[1].strip(),
                            "action": row[2].strip(),
                            "response_prompt": row[3],
                        }
                    )
            except (csv.Error, StopIteration):
                continue
    return rules


MAX_CLAUDEMD_SIZE = 10 * 1024  # 10KB - larger files truncated to fit LLM context


def find_claudemd() -> str | None:
    """Find and read CLAUDE.md from the project directory.

    Returns at most MAX_CLAUDEMD_SIZE characters to avoid excessive prompt sizes.
    """
    for candidate in [
        Path(os.environ.get("CLAUDE_PROJECT_DIR", "")) / "CLAUDE.md",
        HOOK_DIR.parent.parent / "CLAUDE.md",
        Path.cwd() / "CLAUDE.md",
    ]:
        if candidate.exists():
            try:
                content = candidate.read_text()
                if len(content) > MAX_CLAUDEMD_SIZE:
                    log(
                        f"CLAUDE.md truncated from {len(content)} to {MAX_CLAUDEMD_SIZE} chars"
                    )
                    content = content[:MAX_CLAUDEMD_SIZE] + "\n[... truncated ...]"
                return content
            except (OSError, UnicodeDecodeError) as e:
                log(f"Failed to read {candidate}: {e}")
                continue
    return None


def build_prompt(
    criteria: str,
    response_prompt: str,
    message_content: str,
    claudemd_content: str | None = None,
) -> str:
    """Build prompt for OpenCode."""
    claudemd_section = ""
    if claudemd_content:
        claudemd_section = f"""

Project rules (from CLAUDE.md):

{claudemd_content}

"""

    return f"""Your task is to deduce whether: {criteria}
{claudemd_section}
Answer with "YES" or "NO" in the first line.

If YES, only issue OVERRIDE if ALL of these are true:
- There is external evidence the violation doesn't actually apply (e.g., a pre-existing @skip marker, user gave explicit permission, team policy documented in the codebase)
- The agent is NOT making a unilateral decision to skip, simplify, or delegate work
Simply having a reason or explanation is NOT sufficient for OVERRIDE.

If YES and override conditions are met, add "OVERRIDE:" on the second line followed by the external evidence.
If YES without override conditions, explain the violation.

Format:
YES/NO

[If YES] OVERRIDE: <reason why agent should proceed>
OR
[If YES] <explanation of violation>

[Blank line]
Details: {response_prompt}

Agent's message(s):

{message_content}"""


def main():
    # Read hook input from stdin
    try:
        hook_input = json.load(sys.stdin)
    except json.JSONDecodeError:
        log("Failed to parse hook input")
        sys.exit(0)

    session_id = hook_input.get("session_id", "")
    transcript_path = hook_input.get("transcript_path", "")
    hook_event = hook_input.get("hook_event_name", "")

    log(f"Hook triggered: event={hook_event} session={session_id}")

    if not transcript_path or not Path(transcript_path).exists():
        log(f"No transcript path or file not found: {transcript_path}")
        sys.exit(0)

    transcript = Path(transcript_path)

    # Get last assistant message
    last_message = get_last_assistant_message(transcript)
    if not last_message:
        log("No assistant message found")
        sys.exit(0)

    log(f"Last message length: {len(last_message)} chars")

    # Very brief responses (< 50 chars) skip "last" mode rules to avoid false positives
    # on "Done.", "Fixed.", "OK." etc. Threshold is intentionally low (50, not 200)
    # so that short but violating responses like "Skipping tests." still get checked.
    # Turn/claudemd rules always run regardless of message length.
    try:
        MIN_MESSAGE_LENGTH = int(os.environ.get("OH_NO_CLAUDECODE_MIN_LENGTH", "50"))
    except ValueError:
        log("Invalid OH_NO_CLAUDECODE_MIN_LENGTH env var, using default 50")
        MIN_MESSAGE_LENGTH = 50
    is_brief_response = len(last_message) < MIN_MESSAGE_LENGTH
    if is_brief_response:
        log(
            f"Brief response ({len(last_message)} < {MIN_MESSAGE_LENGTH} chars), will skip 'last' mode rules"
        )

    # Check block count for this session
    current_blocks = get_block_count(session_id)
    if current_blocks >= MAX_BLOCKS_PER_SESSION:
        log(
            f"Safety valve: session {session_id} has been blocked {current_blocks} times, allowing through"
        )
        print(
            json.dumps(
                {
                    "systemMessage": f"⚠️ Monitor safety valve: Stopped blocking after {current_blocks} attempts. Review session manually."
                }
            )
        )
        sys.exit(0)

    # Load rules and prepare queries
    rules = load_rules()
    log(f"Loaded {len(rules)} rules from {CONFIG_FILE}")

    # Pre-compute content for each mode (avoid repeated parsing)
    turn_content = get_turn_messages(transcript)

    # Lazy-load CLAUDE.md only if needed
    claudemd_content = None

    # Build all queries
    queries = []
    for i, rule in enumerate(rules):
        mode = rule["mode"]
        if mode == "claudemd":
            # CLAUDE.md compliance mode: check against project rules
            if claudemd_content is None:
                claudemd_content = find_claudemd()
                if claudemd_content:
                    log(f"Loaded CLAUDE.md ({len(claudemd_content)} chars)")
                else:
                    log("No CLAUDE.md found, skipping claudemd rules")
            if not claudemd_content:
                continue
            content_to_check = turn_content or last_message
        elif mode in ("turn", "all"):  # "all" is legacy alias for "turn"
            content_to_check = turn_content
        else:
            # "last" mode — skip if response is brief to avoid false positives.
            # This is safe because all blocking rules use "turn" mode (which always runs).
            # Only "last" mode notify/suggest rules are skipped for brief responses.
            if is_brief_response:
                continue
            content_to_check = last_message
        if content_to_check:
            prompt = build_prompt(
                rule["criteria"],
                rule["response_prompt"],
                content_to_check,
                claudemd_content if mode == "claudemd" else None,
            )
            queries.append((i, rule, prompt))

    log(f"Querying OpenCode for {len(queries)} rules concurrently...")

    if not queries:
        sys.exit(0)

    # Execute all queries concurrently
    results = {}
    with ThreadPoolExecutor(max_workers=max(1, len(queries))) as executor:
        future_to_idx = {
            executor.submit(query_opencode, prompt): (idx, rule)
            for idx, rule, prompt in queries
        }

        for future in as_completed(future_to_idx):
            idx, rule = future_to_idx[future]
            try:
                response = future.result()
                if response:
                    verdict, explanation, override_reason = parse_response(response)
                    results[idx] = (rule, response, verdict, explanation, override_reason)
                    log(f"Rule '{rule['criteria'][:40]}...' verdict: {verdict}" + (
                        f" (OVERRIDE: {override_reason[:30]}...)" if override_reason else ""
                    ))
            except Exception as e:
                log(f"Error querying rule {idx}: {e}")

    log(f"Completed {len(results)}/{len(queries)} queries")

    if len(results) == 0 and len(queries) > 0:
        error_msg = (
            "oh-no-claudecode: Cannot check rules — OpenCode server is not "
            f"responding at {OPENCODE_SERVER}. Agent monitoring is disabled "
            "until the server is running and accessible."
        )
        log(error_msg)
        print(json.dumps({"systemMessage": f"⚠️ {error_msg}"}))
        sys.exit(0)

    # Process results in order: blocks first, then notify, then suggest
    # Claude Code expects exactly one JSON line — collect all messages then output once.
    system_messages = []

    # Check block rules first (in original order)
    for idx in sorted(results.keys()):
        rule, response, verdict, explanation, override_reason = results[idx]
        if rule["action"] == "block" and verdict == "YES":
            if override_reason:
                # Check override limit
                current_overrides = get_override_count(session_id)
                if current_overrides >= MAX_OVERRIDES_PER_SESSION:
                    log(f"Override limit reached ({current_overrides}/{MAX_OVERRIDES_PER_SESSION}), hard block")
                    new_count = increment_block_count(session_id)
                    log(f"BLOCKING (#{new_count}): {explanation}")
                    print(json.dumps({
                        "decision": "block",
                        "reason": f"[Rule: {rule['criteria']}]\n{explanation}",
                    }))
                    sys.exit(0)
                else:
                    # Log and notify but don't block
                    new_override_count = increment_override_count(session_id)
                    log(f"OVERRIDE for rule '{rule['criteria'][:40]}...': {override_reason}")
                    system_messages.append(
                        f"🔄 Override: [{rule['criteria']}] {override_reason}\n"
                        f"(Agent may proceed despite detected concern - override {new_override_count}/{MAX_OVERRIDES_PER_SESSION})"
                    )
            else:
                # Block as usual
                new_count = increment_block_count(session_id)
                log(f"BLOCKING (#{new_count}/{MAX_BLOCKS_PER_SESSION}): {explanation}")
                print(json.dumps({
                    "decision": "block",
                    "reason": f"[Rule: {rule['criteria']}]\n{explanation}",
                }))
                sys.exit(0)

    # No blocks — collect notifications and suggestions into one output
    for idx in sorted(results.keys()):
        rule, response, verdict, explanation, override_reason = results[idx]
        if rule["action"] == "notify" and verdict == "YES":
            log(f"NOTIFY: {explanation}")
            system_messages.append(
                f"⚠️ [{rule['criteria']}] {explanation}"
            )

    for idx in sorted(results.keys()):
        rule, response, verdict, explanation, override_reason = results[idx]
        if rule["action"] == "suggest" and verdict == "YES":
            log(f"SUGGEST: {explanation}")
            system_messages.append(
                f"💡 [{rule['criteria']}] {explanation}"
            )

    if system_messages:
        print(json.dumps({"systemMessage": "\n\n".join(system_messages)}))

    sys.exit(0)


if __name__ == "__main__":
    main()
