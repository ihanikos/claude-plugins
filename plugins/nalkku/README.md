# nalkku

Ships Claude Code session JSONL logs to the nalkku rsync endpoint for real-time analysis.

## Setup

Set these environment variables before enabling the plugin:

| Variable | Description |
|---|---|
| `NALKKU_RSYNC_HOST` | Remote host to rsync logs to (e.g. `user@nalkku.example.com:/data`) |
| `NALKKU_ORG_SLUG` | Your organisation slug (provided by the nalkku operator) |
| `NALKKU_USER_SLUG` | Your user slug (provided by the nalkku operator) |

The plugin rsyncs `~/.claude/projects/<session_id>.jsonl` to:

```text
NALKKU_RSYNC_HOST/NALKKU_ORG_SLUG/NALKKU_USER_SLUG/sessions/<session_id>.jsonl
```


## Hooks

| Event | Action |
|---|---|
| `Stop` | rsync current session JSONL to remote |
| `SessionEnd` | rsync current session JSONL to remote (fallback) |

The plugin exits silently if environment variables are not configured.
