# Discord Thread Rename Tooling Runtime Reload Note

Task ID: SKY-NEXT-DISCORD-THREAD-TOOLS-001-BOUNDED-RENAME-THREAD-BY-ID-TOOLING-FIX  
Timestamp: 2026-05-22 08:34:23 EEST

## Runtime reload needed

YES.

## Why

The local source now exposes a new tool action in `SEND_MESSAGE_SCHEMA` and the `send_message_tool` action dispatcher:

- `rename_thread_by_id`

Hermes tool schemas and gateway sessions are loaded at runtime. The active Discord/gateway session will not necessarily expose the new action until the relevant Hermes runtime/gateway process is restarted or reset.

## Recommended activation sequence

1. Keep this task as local implementation + tests only.
2. Review local diff and reports.
3. Separately approve runtime reload/restart if/when Muncho needs the action live.
4. After reload, verify active tool schema includes exactly the bounded new action and still does not expose forbidden thread/admin mutations.
5. Only after a separate live-mutation approval should any real Discord thread be renamed.

## Not done in this task

- No gateway restart.
- No runtime reload.
- No live Discord API mutation.
- No thread rename.
