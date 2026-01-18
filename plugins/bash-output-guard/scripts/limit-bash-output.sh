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

# Read JSON input from stdin
input=$(cat)

# Extract the original command
original_cmd=$(echo "$input" | jq -r '.tool_input.command')

# Escape the command for safe embedding in a shell string.
# We write the command to a temp file and source it, avoiding quoting issues.
# This approach handles all shell metacharacters safely.
wrapped_cmd='
__cmd_file=$(mktemp)
__tmp=$(mktemp)
__ec=0
cat > "$__cmd_file" <<'"'"'__HOOK_CMD_EOF__'"'"'
'"${original_cmd}"'
__HOOK_CMD_EOF__
trap "rm -f \"$__cmd_file\" \"$__tmp\"" EXIT
bash "$__cmd_file" > "$__tmp" 2>&1 || __ec=$?
__size=$(wc -c < "$__tmp")
if [ "$__size" -gt '"${MAX_BYTES}"' ]; then
  echo "[ERROR: Output discarded - size was $__size bytes, limit is '"${MAX_BYTES}"' bytes. Command exit code was $__ec]"
  exit 1
else
  cat "$__tmp"
  exit $__ec
fi
'

# Return the modified input
jq -n --arg cmd "$wrapped_cmd" '{
  "hookSpecificOutput": {
    "hookEventName": "PreToolUse",
    "updatedInput": {
      "command": $cmd
    }
  }
}'
