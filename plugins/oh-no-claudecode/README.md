# Oh No Claude Code

LLM-as-judge behavior monitoring for Claude Code. Uses OpenCode to evaluate Claude's responses against configurable rules and can block, notify, or suggest based on the verdict.

## Problem

Claude Code sometimes deviates from instructions, skips tests, gives up on complex tasks, or delegates work to the user. These behaviors can be hard to catch in real-time during automated workflows.

## Solution

This plugin intercepts Claude's responses at the Stop event and:
- Evaluates each message against configurable rules using an LLM judge (OpenCode)
- **Blocks** responses that violate rules (Claude retries with corrected behavior)
- **Notifies** users about concerning patterns (non-blocking warnings)
- **Suggests** next actions based on the completion

## Installation

```bash
/plugin marketplace add ihanikos/claude-plugins
/plugin install oh-no-claudecode
```

### Requirements

- **OpenCode** must be installed and authenticated (`opencode auth login`)
- For best performance, run an OpenCode server (see [OpenCode Server Setup](#opencode-server-setup) below)

## Configuration

### Rules File

The rules file is loaded from (in priority order):
1. `$OH_NO_CLAUDECODE_CONFIG` environment variable (if set)
2. `~/.config/oh-no-claudecode/rules.csv` (user config, recommended)
3. Bundled example file (fallback for first-time users)

**To customize**, copy the example to your user config:

```bash
mkdir -p ~/.config/oh-no-claudecode
cp scripts/oh-no-claudecode-rules.example.csv ~/.config/oh-no-claudecode/rules.csv
```

Then edit `~/.config/oh-no-claudecode/rules.csv`:

```csv
# Format: "criteria","mode","action","response_prompt"
#
# criteria: Question to evaluate about the agent's behavior
# mode: "turn" (all messages in turn), "last" (only last message), or "claudemd" (check against CLAUDE.md)
# action: "block" (prevent response), "notify" (warn user), or "suggest" (proactive suggestion)
# response_prompt: Instructions for crafting the explanation

"Is the agent skipping or abandoning a task?",turn,block,"Warn that all tasks must be completed"
"Is the agent resorting to workarounds instead of fixing the problem?",last,notify,"Point out the workaround"
"What would the user likely want to do next?",last,suggest,"Suggest a brief next action"
```

### Modes

| Mode | What it checks |
|------|----------------|
| `turn` | All assistant messages since the last user message (catches mid-turn deviations) |
| `last` | Only the final assistant message |
| `claudemd` | Check compliance with the project's CLAUDE.md rules |

### Actions

| Action | Behavior |
|--------|----------|
| `block` | Stops Claude's response and makes it retry. Has a safety valve (10 blocks per session max). |
| `notify` | Shows a warning to the user but doesn't block |
| `suggest` | Shows a proactive suggestion (always outputs, doesn't require YES verdict) |

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `OH_NO_CLAUDECODE_CONFIG` | `~/.config/oh-no-claudecode/rules.csv` | Path to rules file |
| `OH_NO_CLAUDECODE_MIN_LENGTH` | `50` | Skip 'last' mode rules for messages shorter than this |

## How It Works

```
┌─────────────┐     Stop event      ┌──────────────────┐
│ Claude Code │ ──────────────────► │ oh-no-claudecode │
└─────────────┘                     │      .py         │
                                    └────────┬─────────┘
                                             │
                    ┌────────────────────────┼────────────────────────┐
                    │                        │                        │
                    ▼                        ▼                        ▼
           ┌───────────────┐        ┌───────────────┐        ┌───────────────┐
           │ Read session  │        │ Load config   │        │ Query OpenCode│
           │ transcript    │        │ rules (CSV)   │        │ (concurrent)  │
           └───────────────┘        └───────────────┘        └───────────────┘
                                                                      │
                                                                      ▼
                                              ┌───────────────────────┴───────────────────────┐
                                              │                       │                       │
                                              ▼                       ▼                       ▼
                                     ┌───────────────┐       ┌───────────────┐       ┌───────────────┐
                                     │ action=block  │       │ action=notify │       │ action=suggest│
                                     │ Claude retries│       │ Warning shown │       │ Tip shown     │
                                     └───────────────┘       └───────────────┘       └───────────────┘
```

## Features

- **Concurrent rule evaluation**: All rules are evaluated in parallel for faster response
- **Safety valve**: Stops blocking after 10 blocks per session to prevent infinite loops
- **Brief response bypass**: Short responses ("Done.", "OK.") skip `last` mode rules to avoid false positives
- **CLAUDE.md compliance**: Rules can check against project-specific instructions
- **Graceful degradation**: If OpenCode is unavailable, the hook exits cleanly

## Logs

Debug logs are written to `~/.local/state/oh-no-claudecode/oh-no-claudecode.log`

## Example Rules

| What it catches | Mode | Action |
|-----------------|------|--------|
| Skipping tests | turn | block |
| Giving up on complex tasks | turn | block |
| Delegating work to user | turn | block |
| Using workarounds | last | notify |
| Justifying bad patterns | turn | block |
| Suggesting next action | last | suggest |

## OpenCode Server Setup

The hook queries OpenCode for each rule evaluation. Without a server, each query spawns a new process (~10-15 seconds). With a server, queries are much faster (~2-3 seconds).

### Starting the Server

```bash
# Start server on default port 4096
opencode serve --port 4096

# Or run in background
nohup opencode serve --port 4096 > /tmp/opencode-server.log 2>&1 &
```

### Auto-start on Login (systemd)

Create `~/.config/systemd/user/opencode-server.service`:

```ini
[Unit]
Description=OpenCode Server
After=network.target

[Service]
Type=simple
ExecStart=%h/.opencode/bin/opencode serve --port 4096
Restart=on-failure
RestartSec=5

[Install]
WantedBy=default.target
```

Then enable it:

```bash
systemctl --user daemon-reload
systemctl --user enable --now opencode-server
```

### Auto-start in Devcontainer

Add to `.devcontainer/devcontainer.json`:

```json
{
  "postStartCommand": "nohup ~/.opencode/bin/opencode serve --port 4096 > /tmp/opencode-server.log 2>&1 &"
}
```

### Verifying the Server

```bash
# Check if server is responding
opencode run --attach http://127.0.0.1:4096 "respond with only: OK"
```

## Testing

### Running Unit Tests

Unit tests don't require OpenCode and run quickly:

```bash
cd plugins/oh-no-claudecode
pip install pytest
pytest tests/unit/ -v
```

### Running OpenCode Evals

OpenCode evals test the actual LLM judgment against specific scenarios. The test fixture automatically manages the OpenCode server:

```bash
# Run opencode-evals (server starts automatically if needed)
pytest tests/opencode-evals/ -v

# Or skip if OpenCode is unavailable
pytest tests/opencode-evals/ -v --skip-opencode
```

The fixture uses reference counting, so it won't kill an OpenCode server started by another session.

### Manual Testing

Use the test helper to quickly check a rule against a message:

```bash
./scripts/test_helper.sh "I'll skip the failing tests since they're too complex."
```

### Test Structure

```
tests/
├── conftest.py                              # OpenCode server lifecycle (reference counting)
├── unit/
│   └── test_oh_no_claudecode_logic.py       # Logic tests (no OpenCode needed)
└── opencode-evals/
    ├── test_oh_no_claudecode.py             # Core hook behavior evals
    ├── test_rules.py                        # Rule scenario evals
    └── test_last_and_turn_mode_comparison.py # last vs turn mode effectiveness
```
