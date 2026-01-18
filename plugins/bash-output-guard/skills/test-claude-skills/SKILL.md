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
  "initializeCommand": "mkdir -p ${localWorkspaceFolder}/.devcontainer/claude-auth && cp ${localEnv:HOME}/.claude/.credentials.json ${localWorkspaceFolder}/.devcontainer/claude-auth/ && cp ${localEnv:HOME}/.claude.json ${localWorkspaceFolder}/.devcontainer/claude-auth/",
  "postCreateCommand": "mkdir -p /home/vscode/.claude && cp /workspaces/${localWorkspaceFolderBasename}/.devcontainer/claude-auth/.credentials.json /home/vscode/.claude/ && cp /workspaces/${localWorkspaceFolderBasename}/.devcontainer/claude-auth/.claude.json /home/vscode/"
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

### Start tmux session

```bash
devcontainer exec --workspace-folder . tmux new-session -d -s claude-test
```

### Start Claude

```bash
devcontainer exec --workspace-folder . tmux send-keys -t claude-test 'cd /workspaces/your-repo && claude --dangerously-skip-permissions' Enter
sleep 5
```

### Capture output

```bash
# Capture last 50 lines
devcontainer exec --workspace-folder . tmux capture-pane -t claude-test -p -S -50
```

### Send text to Claude

```bash
devcontainer exec --workspace-folder . tmux send-keys -t claude-test 'your message here' Enter
sleep 10  # Wait for response
devcontainer exec --workspace-folder . tmux capture-pane -t claude-test -p -S -50
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

5. **Debug hooks**: Add logging to your hook script:
   ```bash
   echo "HOOK TRIGGERED" >> /tmp/hook-debug.log
   ```
   Then check: `devcontainer exec --workspace-folder . cat /tmp/hook-debug.log`
