# Claude Plugins Monorepo

## Adding a new plugin

When adding a new plugin to `plugins/`, always complete these steps:

1. Create the plugin directory with required structure:
   - `.claude-plugin/plugin.json` — name, description, version, author
   - `hooks/hooks.json` — hook definitions (if applicable)
   - `README.md` — usage and configuration docs
2. **Register in `.claude-plugin/marketplace.json`** — add an entry to the `plugins` array so users can discover and install it
3. Put tests in `tests/<plugin-name>/`, not inside the plugin directory — plugins should be installable without shipping test infrastructure

## Testing

- Unit tests: `hatch run pytest tests/<plugin-name>/unit/`
- Eval tests (require OpenCode): `hatch run pytest tests/<plugin-name>/opencode-evals/ -m opencode`
- All tests: `hatch run pytest tests/ -v`
- **Never use `--ignore` flags** — the test suite has proper fixtures that auto-start OpenCode or skip tests when unavailable. Using `--ignore` bypasses this infrastructure and hides test failures.
