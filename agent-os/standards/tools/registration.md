# Tool Registration

Register built-in tools via `tools.registry`, not parallel maps.

- Tool modules self-register with a top-level `registry.register(...)` call.
- Keep `tools/registry.py` dependency-light; tool files import it, and `model_tools.py` discovers/imports registered tool modules.
- Tool handlers return strings, usually JSON for structured results/errors.
- Put behavioral guidance in the static tool schema description when it should be prompt-cache-friendly.
- Use `check_fn` for availability; assume results may be TTL-cached briefly.
- Use `dynamic_schema_overrides` only for runtime-dependent schema text.

Minimal pattern:

```python
registry.register(
    name="tool_name",
    toolset="toolset_name",
    schema=TOOL_SCHEMA,
    handler=lambda args, **kw: tool_fn(args.get("x"), ctx=kw.get("ctx")),
    check_fn=check_tool_requirements,
    emoji="⚡",
)
```

Evidence: `tools/registry.py`, `tools/todo_tool.py`, AGENTS dependency chain.
