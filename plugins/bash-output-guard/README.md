# Bash Output Guard

Prevents runaway bash command output from hanging Claude Code sessions.

## Problem

When Claude runs a bash command that produces massive output (e.g., `grep` on large log files, `seq 1 1000000`), the session can become unresponsive as it tries to process megabytes of text.

## Solution

This plugin intercepts all Bash tool calls and:
- Captures command output to a temporary file
- Checks the output size before returning it
- If output exceeds the limit: discards it entirely and returns a warning with the actual size
- If output is under the limit: returns it unchanged, preserving the exit code

## Installation

```bash
/plugin marketplace add ihanikos/claude-plugins
/plugin install bash-output-guard
```

## Configuration

Set the `BASH_OUTPUT_GUARD_MAX_BYTES` environment variable to customize the limit (default: 100000 bytes / ~100KB):

```bash
export BASH_OUTPUT_GUARD_MAX_BYTES=200000
```

## Behavior

### Output under limit
```
$ echo "hello"
hello
```
Command runs normally, exit code preserved.

### Output over limit
```
$ seq 1 1000000
[ERROR: Output discarded - size was 6888896 bytes, limit is 100000 bytes]
```
Output is discarded entirely, warning shows actual size.

## Technical Details

- Uses a PreToolUse hook to wrap bash commands
- Does not impose any timeout (Claude's timeout controls apply)
- Preserves exit codes for commands under the limit
- Works with pipes, redirects, and subshells
