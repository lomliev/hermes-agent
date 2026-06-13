# Hermes Home and Profile Isolation

Tests and code that touch Hermes user state must respect profile-aware paths.

- Use `get_hermes_home()` / profile helpers instead of hardcoded `~/.hermes` for runtime state.
- In tests, isolate `Path.home()` and `HERMES_HOME` with `tmp_path` + `monkeypatch`.
- Do not read or mutate the developer's real config, sessions, logs, skills, or `.env` in tests.

Canonical test fixture shape:

```python
home = tmp_path / ".hermes"
home.mkdir()
monkeypatch.setattr(Path, "home", lambda: tmp_path)
monkeypatch.setenv("HERMES_HOME", str(home))
```

Evidence: `AGENTS.md` and `tests/hermes_cli/test_profiles.py` use this pattern.
