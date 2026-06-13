# Slash Commands

`hermes_cli/commands.py` is the source of truth for slash command metadata.

- Add/rename commands in `COMMAND_REGISTRY` with a `CommandDef`.
- Add aliases only on the existing `CommandDef`; downstream help, autocomplete, Telegram, Slack, and gateway routing derive from the registry.
- Add CLI dispatch in `HermesCLI.process_command()` when the command is supported in the interactive CLI.
- Add gateway dispatch in `gateway/run.py` when the command is supported on messaging platforms.
- Use `cli_only`, `gateway_only`, and `gateway_config_gate` instead of ad hoc filtering.
- For persistent CLI settings, use `save_config_value()`.

Evidence: AGENTS slash-command section and `hermes_cli/commands.py` module contract.
