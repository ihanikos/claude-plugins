---
name: hermes-tweet
description: Use when installing, enabling, or operating Hermes Tweet, the native Hermes Agent X/Twitter plugin, or when deciding its read and action gates in Hermes sessions.
---

# Hermes Tweet

Hermes Tweet is a native Hermes Agent plugin for X/Twitter research, tweet reading, trend checks, and approval-gated social actions through Xquik.

## Install

Use the source repository when installing the runtime plugin:

```bash
hermes plugins install Xquik-dev/hermes-tweet --enable
```

If Hermes already installed the plugin without enabling it, run:

```bash
hermes plugins enable hermes-tweet
```

Confirm the plugin is enabled:

```bash
hermes plugins list
```

## Credentials

Keep credentials in the host that executes Hermes plugin tools.

- `tweet_explore` stays available without `XQUIK_API_KEY`.
- `tweet_read` tools require `XQUIK_API_KEY`.
- `tweet_action` tools require `XQUIK_API_KEY` and `HERMES_TWEET_ENABLE_ACTIONS=true`.
- Never pass credentials through tool arguments.

If Hermes is already running after changing environment values, reload the session or restart the runtime so the plugin sees the new values.

## Workflow

Use read-first workflows:

1. Start with `tweet_explore` for catalog discovery and safe planning.
2. Use read tools for search, tweet reads, replies, profiles, and trend context.
3. Summarize the evidence before any account-changing action.
4. Use action tools only when the operator explicitly approves the intended social action.

Source: https://github.com/Xquik-dev/hermes-tweet
