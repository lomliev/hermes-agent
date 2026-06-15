import json
from pathlib import Path

from gateway.runtime_guard import GuardContext, RuntimeGuardConfig, get_runtime_guard_manager


EXAMPLE_PATH = (
    Path(__file__).resolve().parents[2]
    / "docs"
    / "runtime_guard"
    / "examples"
    / "dry-run-activation.json"
)


def _iter_keys(value):
    if isinstance(value, dict):
        for key, item in value.items():
            yield str(key)
            yield from _iter_keys(item)
    elif isinstance(value, list):
        for item in value:
            yield from _iter_keys(item)


def test_downstream_dry_run_activation_example_matches_runtime_guard_config():
    example = json.loads(EXAMPLE_PATH.read_text(encoding="utf-8"))

    assert set(example) == {"platforms"}
    platform_config = example["platforms"]["discord"]
    assert platform_config["enabled"] is True
    assert "runtime_guard" not in platform_config
    assert "extra" in platform_config
    assert "runtime_guard" in platform_config["extra"]

    runtime_guard = platform_config["extra"]["runtime_guard"]
    cfg = RuntimeGuardConfig.from_mapping(platform_config["extra"])

    assert cfg.enabled is True
    assert cfg.dry_run is True
    assert cfg.fail_closed is True
    assert cfg.provider == "noop"
    assert cfg.streaming.policy == "guard_first_visible"

    scope = runtime_guard["scope"]
    assert set(scope) == {"platforms", "chat_ids", "thread_ids"}
    assert scope["platforms"] == ["discord"]
    assert scope["chat_ids"] == ["example-discord-channel-001"]
    assert scope["thread_ids"] == ["example-discord-thread-001"]
    assert all(value.startswith("example-") for value in scope["chat_ids"])
    assert all(value.startswith("example-") for value in scope["thread_ids"])
    assert cfg.scope.platforms == ("discord",)
    assert cfg.scope.chat_ids == ("example-discord-channel-001",)
    assert cfg.scope.thread_ids == ("example-discord-thread-001",)
    assert cfg.scope.parent_chat_ids == ()
    assert cfg.scope.session_keys == ()
    assert cfg.scope.guild_ids == ()
    assert not ({"user_id", "user_ids"} & set(_iter_keys(example)))

    policies = runtime_guard["delivery_surfaces"]
    assert policies == {
        "assistant_final": "guard",
        "assistant_stream": "disable",
        "tool_progress": "disable",
        "send_message_tool": "block",
    }
    assert cfg.delivery_surfaces.assistant_final == "guard"
    assert cfg.delivery_surfaces.assistant_stream == "disable"
    assert cfg.delivery_surfaces.tool_progress == "disable"
    assert cfg.delivery_surfaces.send_message_tool == "block"

    manager = get_runtime_guard_manager(platform_config["extra"])
    scoped_context_without_user = GuardContext(
        surface="assistant_final",
        platform="discord",
        chat_id="example-discord-channel-001",
        thread_id="example-discord-thread-001",
    )
    assert manager.is_scoped(scoped_context_without_user) is True
    assert manager.surface_action(scoped_context_without_user) == "guard"

    send_tool_context = scoped_context_without_user.with_surface("send_message_tool")
    assert manager.should_block_surface(send_tool_context) is True
    send_tool_decision = manager.check_surface_policy(send_tool_context)
    assert send_tool_decision.allowed is True
    assert send_tool_decision.dry_run is True
    assert send_tool_decision.status == "dry_run_allowed"
    assert send_tool_decision.audit["would_block"] is True

    stream_context = scoped_context_without_user.with_surface("assistant_stream")
    assert manager.should_disable_surface(stream_context) is True
