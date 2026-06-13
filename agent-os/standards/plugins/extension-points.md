# Plugins

Use plugins for local/custom extensions instead of editing Hermes core when possible.

- Local plugins live in `~/.hermes/plugins/<name>/`; bundled plugins live under `plugins/`.
- Include a compact `plugin.yaml` with `name`, `version`, `description`, `author`, `kind`, and any `provides_*` / env metadata the loader expects.
- Expose `register(ctx)` in `__init__.py` and register capabilities through the context (`ctx.register_tool`, `ctx.register_web_search_provider`, `ctx.register_platform`, etc.).
- Keep provider/platform-specific dependencies out of core; use extras or lazy dependency hooks.
- For model-provider plugins, register a `ProviderProfile` with aliases, display name, env vars, base URL, auth type, and fallback/default models as needed.

Evidence: AGENTS plugin guidance, `plugins/web/brave_free/`, `plugins/model-providers/novita/`, gateway platform plugin guide.
