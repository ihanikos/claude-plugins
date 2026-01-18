#!/bin/bash
# PreToolUse hook to guard against runaway bash command output
# If output exceeds limit, discard entirely and return warning with actual size
# Note: Both stdout and stderr are captured together and count toward the size limit

# Check for required dependency
if ! command -v jq >/dev/null 2>&1; then
  echo '{"error": "bash-output-guard plugin requires jq to be installed"}' >&2
  exit 1
fi

# Debug logging (only if BASH_OUTPUT_GUARD_DEBUG is set)
[ -n "$BASH_OUTPUT_GUARD_DEBUG" ] && echo "HOOK TRIGGERED" >> /tmp/hook-debug.log

MAX_BYTES=${BASH_OUTPUT_GUARD_MAX_BYTES:-100000}

# Validate MAX_BYTES is a positive integer
if ! [[ "$MAX_BYTES" =~ ^[0-9]+$ ]] || [ "$MAX_BYTES" -eq 0 ]; then
  echo '{"error": "BASH_OUTPUT_GUARD_MAX_BYTES must be a positive integer"}' >&2
  exit 1
fi

# Read JSON input from stdin
input=$(cat)

# Extract the original command
original_cmd=$(echo "$input" | jq -r '.tool_input.command')

# Base64 encode the command to safely embed it without heredoc delimiter collisions.
# This prevents injection attacks where the command contains the heredoc delimiter.
encoded_cmd=$(printf '%s' "$original_cmd" | base64)

# Build wrapped command that:
# 1. Decodes the base64 command to a temp file
# 2. Executes it and captures output
# 3. Checks size and either returns output or error message
# 4. Preserves exit code in all cases
wrapped_cmd='
__cmd_file=$(mktemp)
__tmp=$(mktemp)
__ec=0
trap "rm -f \"$__cmd_file\" \"$__tmp\"" EXIT
echo "'"${encoded_cmd}"'" | base64 -d > "$__cmd_file"
bash "$__cmd_file" > "$__tmp" 2>&1 || __ec=$?
__size=$(wc -c < "$__tmp")
if [ "$__size" -gt '"${MAX_BYTES}"' ]; then
  echo "[ERROR: Output discarded - size was $__size bytes, limit is '"${MAX_BYTES}"' bytes. Command exit code was $__ec]"
  exit $__ec
else
  cat "$__tmp"
  exit $__ec
fi
'

# Return the modified input, preserving all original tool_input fields except command
# This ensures workdir, timeout, and other fields are not lost
echo "$input" | jq --arg cmd "$wrapped_cmd" '{
  "hookSpecificOutput": {
    "hookEventName": "PreToolUse",
    "updatedInput": (.tool_input + {"command": $cmd})
  }
}'
