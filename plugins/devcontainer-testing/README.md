# devcontainer-testing

A Claude Code skill for testing plugins, hooks, and skills in an isolated devcontainer environment.

## What it provides

Installs the `test-claude-skills` skill, which documents how to:

- Set up a devcontainer with Claude Code, tmux, and jq
- Use tmux to control interactive Claude sessions
- Install plugins via the `/plugin` UI (required for hooks)
- Wait for Claude responses reliably
- Debug hook execution

## Installation

Install via the Claude Code plugin marketplace.

## Usage

Invoke the skill in any Claude session:

```
/test-claude-skills
```

This loads the full testing guide into your session context.
