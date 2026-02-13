"""E2e tests for oh-no-claudecode hooks.

Runs real Claude Code sessions in print mode and verifies hook behavior
by parsing the streaming JSON output.

Note: In -p (print) mode, only SessionStart hooks fire.
Stop and SessionEnd hooks require an interactive session.
"""

import json

from conftest import run_claude


class TestPluginLoads:
    """Verify the plugin loads and its hooks fire via --plugin-dir."""

    def test_session_start_hook_fires(self, claude_env):
        """SessionStart hook from the plugin should fire and acquire the server."""
        result, events = run_claude("Say hello", claude_env)

        assert result.returncode == 0, (
            f"claude exited with {result.returncode}\n"
            f"stderr: {result.stderr[:500]}"
        )

        # Find hook events from our plugin (server_lifecycle)
        lifecycle_events = [
            e for e in events
            if e.get("type") == "system"
            and e.get("subtype") == "hook_response"
            and "server_lifecycle" in (e.get("stderr") or "")
        ]

        assert lifecycle_events, (
            f"Expected server_lifecycle hook response but found none.\n"
            f"Hook events: {[e for e in events if 'hook' in e.get('subtype', '')]}\n"
            f"stderr: {result.stderr[:500]}"
        )

        # Verify it acquired successfully
        hook_stderr = lifecycle_events[0].get("stderr", "")
        assert "acquired successfully" in hook_stderr.lower(), (
            f"Expected successful acquire but got: {hook_stderr}"
        )

    def test_plugin_listed_in_init(self, claude_env):
        """The plugin should appear in the init event's plugins list."""
        result, events = run_claude("Say hello", claude_env)

        init_events = [e for e in events if e.get("subtype") == "init"]
        assert init_events, "No init event found in stream"

        plugins = init_events[0].get("plugins", [])
        plugin_names = [p.get("name") for p in plugins]
        assert "oh-no-claudecode" in plugin_names, (
            f"oh-no-claudecode not in plugins: {plugin_names}"
        )
