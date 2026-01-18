---
name: test-claude-skills
description: Test Claude Code plugins, hooks, and skills in an isolated devcontainer environment. Use when testing Claude Code extensions, plugins, hooks, or skills.
---

# Testing Claude Code Skills/Plugins

Claude Code plugins and hooks must be tested in an isolated environment with a real Claude Code instance. Use devcontainers for this.

## Setup

### 1. Create devcontainer configuration

Create `.devcontainer/devcontainer.json` in the plugin repository:

```json
{
  "name": "Claude Plugin Test",
  "image": "mcr.microsoft.com/devcontainers/base:ubuntu",
  "features": {
    "ghcr.io/devcontainers/features/node:1": {
      "version": "lts"
    }
  },
  "postCreateCommand": "npm install -g @anthropic-ai/claude-code && mkdir -p /home/vscode/.claude && cp /tmp/claude-creds/.credentials.json /home/vscode/.claude/",
  "mounts": [
    "source=${localEnv:HOME}/.claude/.credentials.json,target=/tmp/claude-creds/.credentials.json,type=bind,readonly"
  ]
}
```

### 2. Start the devcontainer

```bash
devcontainer up --workspace-folder .
```

If `devcontainer` CLI is not installed:
```bash
npm install -g @devcontainers/cli
```

### 3. Rebuild after config changes

```bash
devcontainer up --workspace-folder . --remove-existing-container
```

## Testing with tmux

Interactive Claude sessions require a TTY. Use tmux to control Claude inside the container:

### Start tmux session in container

```bash
devcontainer exec --workspace-folder . tmux new-session -d -s claude-test
```

### Send commands to Claude

```bash
# Start Claude with your plugin
devcontainer exec --workspace-folder . tmux send-keys -t claude-test 'claude --plugin-dir /workspaces/your-plugin --dangerously-skip-permissions' Enter

# Wait for Claude to start
sleep 5

# Send a command to test
devcontainer exec --workspace-folder . tmux send-keys -t claude-test 'Run: echo hello' Enter

# Capture output
devcontainer exec --workspace-folder . tmux capture-pane -t claude-test -p
```

### Install plugin and test

```bash
# Send /plugin install command
devcontainer exec --workspace-folder . tmux send-keys -t claude-test '/plugin install your-plugin' Enter
sleep 3

# Test the plugin
devcontainer exec --workspace-folder . tmux send-keys -t claude-test 'your test command here' Enter
sleep 5

# Capture result
devcontainer exec --workspace-folder . tmux capture-pane -t claude-test -p -S -50
```

### Clean up

```bash
devcontainer exec --workspace-folder . tmux kill-session -t claude-test
```

## Important Notes

1. **Hooks via `--plugin-dir`**: The `--plugin-dir` flag loads commands/agents/skills but may not load hooks. For hooks to work, install the plugin via `/plugin install` or place hooks in `.claude/settings.json`.

2. **Credentials**: The devcontainer mounts credentials read-only from host, then copies them so Claude can write to the directory.

3. **Non-interactive mode (`-p`)**: Slash commands like `/plugin` don't work in `-p` mode. Use tmux for interactive testing.

4. **Capturing output**: Use `tmux capture-pane -p -S -N` where N is lines of history to capture.
