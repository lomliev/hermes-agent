# Discord Thread Rename Tooling Implementation Report

Task ID: SKY-NEXT-DISCORD-THREAD-TOOLS-001-BOUNDED-RENAME-THREAD-BY-ID-TOOLING-FIX  
Timestamp: 2026-05-22 08:34:23 EEST

## Verdict

Implemented locally in Hermes tooling. No live Discord thread rename was performed.

## Scope

Added a bounded `send_message` action:

- `rename_thread_by_id`

Required parameters exposed in schema:

- `thread_id`
- `parent_channel_id`
- `new_title`

## Implementation

Updated `tools/send_message_tool.py`:

- Added `rename_thread_by_id` to the existing `send_message` action enum.
- Routed `rename_thread_by_id` through the existing bounded Discord thread action handler.
- Added a fixed initial parent allowlist for thread rename:
  - `1504852444407140402` (`#frontend`)
- Added local validators for:
  - numeric Discord snowflake IDs;
  - exact approved parent channel ID;
  - non-empty Discord thread title;
  - no newlines in title;
  - no suspicious control characters in title;
  - max thread title length of 100 characters;
  - thread type is a Discord thread (`10`, `11`, or `12`);
  - `thread.parent_id == parent_channel_id`;
  - thread is not archived and not locked.
- Mutation is limited to one Discord REST PATCH:
  - `PATCH /channels/{thread_id}` with JSON body `{ "name": new_title }`

## Safety boundaries

The implementation does **not** add or expose:

- thread delete;
- thread move;
- thread archive;
- thread lock;
- message send/edit/delete in the rename path;
- permission/role/member mutation;
- webhook mutation;
- broad Discord admin operations.

## Return payload

Happy path returns:

- `success`
- `platform`
- `action`
- `thread_id`
- `parent_channel_id`
- `old_title`
- `new_title`

## Files changed

- `tools/send_message_tool.py`
- `tests/tools/test_send_message_tool.py`

## Live Discord mutation

Not performed. This task was local-write and tests-only for the new bounded tooling.
