# Testing

Use `scripts/run_tests.sh`; do not call `pytest` directly for normal validation.

- The wrapper activates the venv, unsets credential-shaped env vars, pins UTC/locale/hash seed, and uses 4 xdist workers.
- Run targeted tests through the wrapper during development:

```bash
scripts/run_tests.sh tests/gateway/
scripts/run_tests.sh tests/agent/test_foo.py::test_x
scripts/run_tests.sh -v --tb=long
```

- Run the full suite before pushing broad changes.
- Keep tests hermetic: temp HOME/HERMES_HOME, no real credentials, no production services.
- Do not add change-detector tests for mutable catalogs, model lists, config version literals, or enumeration counts. Prefer behavioral invariants and relationship checks.

Evidence: AGENTS testing section and `scripts/run_tests.sh`.
