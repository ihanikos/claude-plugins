# hermes-tweet

A Claude Code skill companion for [Hermes Tweet](https://github.com/Xquik-dev/hermes-tweet), the native Hermes Agent X/Twitter plugin for read-first social workflows and approval-gated actions.

## What it provides

Installs the `hermes-tweet` skill, which documents how to:

- Install and enable Hermes Tweet in Hermes Agent
- Keep `tweet_explore` available without network credentials
- Configure `XQUIK_API_KEY` only in the Hermes runtime environment
- Require `HERMES_TWEET_ENABLE_ACTIONS=true` before action tools are exposed
- Use read tools before any approval-gated social action

## Installation

Install via the Claude Code plugin marketplace.

## Usage

Invoke the skill in any Claude session:

```text
/hermes-tweet
```

This loads the Hermes Tweet install and safety guide into your session context.
