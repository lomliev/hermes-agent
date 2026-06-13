# Dependency Scope and Pins

Use exact pins in `pyproject.toml` dependencies and extras.

- Core `[project].dependencies`: only packages used by every Hermes session.
- Provider/platform/tool-specific packages: put in extras or lazy dependencies, not core.
- When bumping a pin, regenerate `uv.lock` with `uv lock`.
- Do not reintroduce version ranges without a written security/compatibility rationale.

Evidence: `pyproject.toml` documents exact-pin supply-chain rationale and keeps backend-specific packages in optional extras.
Assumption: this remains policy unless maintainers explicitly relax it.
