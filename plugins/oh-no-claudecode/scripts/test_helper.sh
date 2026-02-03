#!/bin/bash
# Helper script to quickly test monitor rules
# Usage: ./test_helper.sh "assistant message"

SCRIPT_DIR="$(dirname "$(readlink -f "$0")")"
HOOK_SCRIPT="$SCRIPT_DIR/oh-no-claudecode.py"
MESSAGE="$1"

# Create transcript
cat > /tmp/test-transcript.jsonl << EOF
{"message":{"role":"user","content":[{"type":"text","text":"Do the task"}]},"uuid":"1","timestamp":"2026-01-22T10:00:00Z"}
{"message":{"role":"assistant","content":[{"type":"text","text":"$MESSAGE"}]},"uuid":"2","timestamp":"2026-01-22T10:00:01Z"}
EOF

echo "=== Testing message ==="
echo "$MESSAGE"
echo ""
echo "=== Hook output ==="
echo '{"session_id":"test","transcript_path":"/tmp/test-transcript.jsonl","hook_event_name":"Stop"}' | python3 "$HOOK_SCRIPT" 2>&1
