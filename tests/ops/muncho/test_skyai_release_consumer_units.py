from __future__ import annotations

import pytest

from ops.muncho.runtime.skyai_release_consumer_units import (
    SERVICE_UNIT,
    TIMER_UNIT,
    SkyAIConsumerUnitError,
    render_skyai_consumer_units,
)


def test_consumer_units_are_release_pinned_hardened_and_periodic() -> None:
    revision = "a" * 40
    bundle = render_skyai_consumer_units(
        revision=revision,
        signing_public_key_id="b" * 64,
    )
    service = bundle.units[SERVICE_UNIT].decode()
    timer = bundle.units[TIMER_UNIT].decode()

    assert str(bundle.release_root).endswith(revision)
    assert f"WorkingDirectory={bundle.release_root}\n" in service
    assert (
        f" -I -B {bundle.release_root}/ops/muncho/runtime/"
        "skyai_release_consumer.py run-once\n"
    ) in service
    assert "ProtectSystem=strict\n" in service
    assert "NoNewPrivileges=yes\n" in service
    assert "EnvironmentFile=" not in service
    assert "PassEnvironment=" not in service
    assert "OnUnitActiveSec=5min\n" in timer
    assert "Persistent=true\n" in timer
    assert bundle.manifest["personal_mac_required_for_routine_releases"] is False
    assert bundle.manifest["maximum_queue_to_deploy_seconds"] == 86_400


def test_consumer_unit_renderer_rejects_unknown_exact_identities() -> None:
    with pytest.raises(SkyAIConsumerUnitError):
        render_skyai_consumer_units(
            revision="short",
            signing_public_key_id="b" * 64,
        )
