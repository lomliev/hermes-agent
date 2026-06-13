# Discord Admin Channel Tooling Runtime Reload Note

## Runtime Reload Needed
YES.

## Why
The callable tool schema and handler live in `tools/send_message_tool.py`. Already-running Hermes gateway/agent processes need to reload/restart before the updated `send_message` action enum and handler branches are available to Muncho.

## Required Before Real Use
Before any live Discord channel rename/create action is attempted, configure the approved SkyVision Next category ID in runtime config/env:

```yaml
discord:
  skyvision_next_category_id: "<OWNER_SUPPLIED_SKYVISION_NEXT_CATEGORY_ID>"
```

or set:

```bash
DISCORD_SKYVISION_NEXT_CATEGORY_ID=<OWNER_SUPPLIED_SKYVISION_NEXT_CATEGORY_ID>
```

The category ID must be supplied/confirmed by the owner or from safe authoritative metadata. The local cached channel directory inspected during this task did not contain parent category IDs.

## Reload Sequence
1. Configure the approved SkyVision Next category ID.
2. Restart/reload the Hermes gateway/agent runtime.
3. Use `send_message` with `action="list_category_channels"` for preflight only.
4. Do not run `rename_channel_by_id` or `create_text_channel_in_category` until a separate explicit Discord mutation approval is granted.

## Safety Reminder
This task did not authorize live Discord mutation. A separate approval is still required before channel rename/create.
