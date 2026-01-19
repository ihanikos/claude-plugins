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
    },
    "ghcr.io/anthropics/devcontainer-features/claude-code:1": {},
    "ghcr.io/devcontainers-extra/features/apt-packages:1": {
      "packages": "tmux,jq"
    }
  },
  "initializeCommand": "mkdir -p ${localWorkspaceFolder}/.devcontainer/claude-auth && ([ -f ${localEnv:HOME}/.claude/.credentials.json ] && cp ${localEnv:HOME}/.claude/.credentials.json ${localWorkspaceFolder}/.devcontainer/claude-auth/ || echo 'Warning: .credentials.json not found') && ([ -f ${localEnv:HOME}/.claude.json ] && cp ${localEnv:HOME}/.claude.json ${localWorkspaceFolder}/.devcontainer/claude-auth/ || echo 'Warning: .claude.json not found')",
  "postCreateCommand": "mkdir -p /home/vscode/.claude && ([ -f .devcontainer/claude-auth/.credentials.json ] && cp .devcontainer/claude-auth/.credentials.json /home/vscode/.claude/ || true) && ([ -f .devcontainer/claude-auth/.claude.json ] && cp .devcontainer/claude-auth/.claude.json /home/vscode/ || true)"
}
```

**Key points:**
- Uses devcontainer features for Claude Code, Node.js, tmux, and jq
- Copies both `.credentials.json` (OAuth tokens) AND `.claude.json` (onboarding state) - both are required
- `initializeCommand` runs on host before container starts
- `postCreateCommand` runs inside container after creation
- Add `.devcontainer/claude-auth/` to `.gitignore` to avoid committing credentials

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

Interactive Claude sessions require a TTY. Use tmux to control Claude inside the container.

**Important**: Always use `--dangerously-skip-permissions` inside the container for testing. This bypasses permission prompts and lets you see hook-transformed commands directly.

### API Response Times

Claude API response times are unpredictable - sometimes fast (5-10s), sometimes slow (60s+), especially:
- First request after starting Claude
- When using Opus models
- During high API load

The sleep times in examples below are minimums. Use the polling helper function for reliable waiting.

### Helper Function for Waiting

Use this function to wait for Claude responses with a timeout:

```bash
# Wait for Claude output to stabilize (with timeout)
wait_for_claude() {
  local timeout=${1:-60}
  local prev_output=""
  local stable_count=0
  local elapsed=0

  while [ $elapsed -lt $timeout ]; do
    output=$(devcontainer exec --workspace-folder . tmux capture-pane -t claude-test -p -S -30 2>/dev/null)
    if [ "$output" = "$prev_output" ]; then
      stable_count=$((stable_count + 1))
      # Output stable for 3 checks (6 seconds) = likely done
      if [ $stable_count -ge 3 ]; then
        echo "$output"
        return 0
      fi
    else
      stable_count=0
      prev_output="$output"
    fi
    sleep 2
    elapsed=$((elapsed + 2))
  done

  echo "Timeout after ${timeout}s waiting for response"
  echo "$output"
  return 1
}
```

### Start tmux session

```bash
devcontainer exec --workspace-folder . tmux new-session -d -s claude-test
```

### Start Claude

```bash
devcontainer exec --workspace-folder . tmux send-keys -t claude-test 'cd /workspaces/your-repo && claude --dangerously-skip-permissions' Enter
sleep 5  # Initial startup is usually fast
```

### Capture output

```bash
# Capture last 50 lines
devcontainer exec --workspace-folder . tmux capture-pane -t claude-test -p -S -50
```

### Send text to Claude

```bash
devcontainer exec --workspace-folder . tmux send-keys -t claude-test 'your message here' Enter
wait_for_claude 120  # Wait up to 120 seconds
```

### Clean up

```bash
devcontainer exec --workspace-folder . tmux kill-session -t claude-test
```

## Installing Plugins from Local Marketplace

To test plugins with hooks, you must install via the `/plugin` UI (not `--plugin-dir`).

### 1. Add local marketplace

```bash
# Open plugin menu
devcontainer exec --workspace-folder . tmux send-keys -t claude-test '/plugin' Enter
sleep 2

# Navigate to Marketplaces tab (press Right twice)
devcontainer exec --workspace-folder . tmux send-keys -t claude-test Right Right
sleep 1

# Select "Add Marketplace"
devcontainer exec --workspace-folder . tmux send-keys -t claude-test Enter
sleep 1

# Type the local path (repo root containing .claude-plugin/marketplace.json)
devcontainer exec --workspace-folder . tmux send-keys -t claude-test '/workspaces/your-repo' Enter
sleep 2
```

### 2. Install plugin

```bash
# Go to Discover tab
devcontainer exec --workspace-folder . tmux send-keys -t claude-test Left Left
sleep 1

# Select your plugin and press Enter for details
devcontainer exec --workspace-folder . tmux send-keys -t claude-test Enter
sleep 1

# Press Enter to install (user scope)
devcontainer exec --workspace-folder . tmux send-keys -t claude-test Enter
sleep 3
```

### 3. Verify installation

```bash
# Check Installed tab
devcontainer exec --workspace-folder . tmux send-keys -t claude-test '/plugin' Enter
sleep 2
devcontainer exec --workspace-folder . tmux send-keys -t claude-test Right  # Go to Installed
sleep 1
devcontainer exec --workspace-folder . tmux capture-pane -t claude-test -p -S -30
```

Look for `✔ enabled` status. If you see `✘ error`, press Enter on the plugin to see details.

### 4. Restart Claude after plugin changes

Plugins load at startup. After installing or updating:

```bash
devcontainer exec --workspace-folder . tmux send-keys -t claude-test C-d  # Exit Claude
sleep 2
devcontainer exec --workspace-folder . tmux send-keys -t claude-test 'claude --dangerously-skip-permissions' Enter
sleep 5
```

## Plugin Schema Requirements

Common issues with plugin.json:

1. **Don't specify `hooks` field** - Claude auto-loads `hooks/hooks.json` from plugin root. Specifying it causes "duplicate hooks file" error.

2. **`repository` must be a string**, not an object:
   ```json
   "repository": "https://github.com/user/repo"
   ```
   Not:
   ```json
   "repository": { "type": "git", "url": "..." }
   ```

3. **Bump version** when making changes - Claude caches plugins by version.

## Important Notes

1. **Hooks require proper installation**: The `--plugin-dir` flag loads skills/commands but NOT hooks. For hooks to work, install via `/plugin` UI.

2. **Both credential files required**:
   - `~/.claude/.credentials.json` - OAuth tokens
   - `~/.claude.json` - Onboarding state (skips first-run setup)

3. **Non-interactive mode (`-p`)**: Slash commands don't work in `-p` mode. Use tmux.

4. **Plugin UI navigation**:
   - `Left`/`Right` or `Tab` - Switch tabs (Discover/Installed/Marketplaces)
   - `Up`/`Down` - Navigate items
   - `Enter` - Select/confirm
   - `Escape` - Go back
   - `Space` - Toggle selection
   - `u` - Update (in Marketplaces tab)

5. **Debug hooks**: Use environment variables for conditional logging:
   ```bash
   [ -n "$MY_HOOK_DEBUG" ] && echo "HOOK TRIGGERED" >> /tmp/hook-debug.log
   ```
   Then run with debugging: `MY_HOOK_DEBUG=1 claude --dangerously-skip-permissions`
   Check logs: `devcontainer exec --workspace-folder . cat /tmp/hook-debug.log`
