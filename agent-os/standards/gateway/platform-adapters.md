# Gateway Platform Adapters

Prefer platform plugins for community/third-party integrations; edit core gateway only for built-in platforms.

Plugin path:
- Create `plugin.yaml` + `adapter.py` under `~/.hermes/plugins/<name>/` or bundled `plugins/platforms/<name>/`.
- Adapter inherits `BasePlatformAdapter` and registers with `ctx.register_platform()` in `register(ctx)`.
- Use plugin hooks for env enablement, YAML config mapping, cron delivery, standalone sending, and setup wizard env metadata.

Built-in path requires coordinated changes:
- `gateway/platforms/<platform>.py`: required adapter methods, `check_<platform>_requirements()`.
- `gateway/config.py`, `gateway/run.py`, `gateway/session.py` if identity fields change.
- Prompt hints, toolsets, cron delivery, `send_message_tool`, channel directory, status/setup UI, redaction, docs, tests.

Adapter rules:
- Build `SessionSource` with `self.build_source(...)`.
- Dispatch inbound messages via `self.handle_message(event)`.
- Filter self/echo messages and redact sensitive identifiers in logs.
- Respect platform message/media limits; e.g. Telegram length uses UTF-16 code units.

Evidence: `gateway/platforms/ADDING_A_PLATFORM.md`, `gateway/platforms/base.py`, `gateway/platforms/telegram.py`.
