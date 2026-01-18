# Claude Plugins

A collection of Claude Code plugins by ihanikos.

## Available Plugins

| Plugin | Description |
|--------|-------------|
| [bash-output-guard](../plugins/bash-output-guard) | Prevents runaway bash command output from hanging Claude sessions |

## Installation

Add this marketplace to Claude Code:

```bash
/plugin marketplace add ihanikos/claude-plugins
```

Then browse and install plugins:

```bash
/plugin discover
```

Or install directly:

```bash
/plugin install bash-output-guard@ihanikos/claude-plugins
```

## Contributing

1. Create a new plugin directory under `plugins/`
2. Add your plugin with the standard structure:
   ```
   plugins/your-plugin/
   ├── .claude-plugin/
   │   └── plugin.json
   ├── commands/       (optional)
   ├── hooks/          (optional)
   ├── skills/         (optional)
   └── README.md
   ```
3. Add an entry to `.claude-plugin/marketplace.json`
4. Submit a pull request

## License

MIT
