#!/bin/bash
# PreToolUse hook to guard against runaway bash command output
# If output exceeds limit, discard entirely and return warning with actual size

MAX_BYTES=${BASH_OUTPUT_GUARD_MAX_BYTES:-100000}

# Read JSON input from stdin
input=$(cat)

# Extract the original command
original_cmd=$(echo "$input" | jq -r '.tool_input.command')

# Wrap command to:
# 1. Capture output to temp file
# 2. Check size
# 3. If over limit: discard and show warning with size
# 4. If under limit: output unchanged, preserve exit code
wrapped_cmd='__tmp=$(mktemp); __ec=0; ( '"${original_cmd}"' ) >$__tmp 2>&1 || __ec=$?; __size=$(wc -c < $__tmp); if [ $__size -gt '"${MAX_BYTES}"' ]; then echo "[ERROR: Output discarded - size was $__size bytes, limit is '"${MAX_BYTES}"' bytes]"; rm -f $__tmp; exit 1; else cat $__tmp; rm -f $__tmp; exit $__ec; fi'

# Return the modified input
jq -n --arg cmd "$wrapped_cmd" '{
  "hookSpecificOutput": {
    "hookEventName": "PreToolUse",
    "updatedInput": {
      "command": $cmd
    }
  }
}'
