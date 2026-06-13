# Discord Thread Rename Capability Status

Task ID: SKY-NEXT-DISCORD-THREAD-TOOLS-001-BOUNDED-RENAME-THREAD-BY-ID-TOOLING-FIX  
Timestamp: 2026-05-22 08:34:23 EEST

## Capability status

Local source capability: IMPLEMENTED  
Local tests: PASSING  
Active runtime capability: RELOAD NEEDED  
Live Discord mutation approval: NOT GRANTED IN THIS TASK  
Live Discord thread rename performed: NO

## Bounded action exposed locally

`send_message(action="rename_thread_by_id", thread_id=..., parent_channel_id=..., new_title=...)`

## Current allowlist

Initial approved parent channel only:

- `#frontend`
- `1504852444407140402`

Any other `parent_channel_id` fails before Discord API mutation.

## Runtime safety model

Before PATCH, the tool must:

1. Validate `thread_id` is numeric.
2. Validate `parent_channel_id` is numeric.
3. Validate `parent_channel_id == 1504852444407140402`.
4. Fetch thread metadata via `GET /channels/{thread_id}`.
5. Validate target is a Discord thread.
6. Validate `thread.parent_id == parent_channel_id`.
7. Validate thread is not archived and not locked.
8. Validate title is safe and within limits.

Only then may it call:

```text
PATCH /channels/{thread_id}
body: {"name": new_title}
```

## Explicit non-capabilities

The action does not provide:

- title matching rename;
- cross-parent rename;
- move/archive/delete/lock/unlock thread;
- message edit/delete/send;
- channel create/delete;
- permission/role/member/webhook operations;
- broad Discord admin API access.

## Next gate

To use this in production runtime, a separate approval is needed for runtime reload. A separate approval is also needed for each live Discord mutation batch.
