from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from services.appliance_dashboard import tunnel_relay
from tools.appliance import heartbeat_relay
from tools.appliance.node_identity import (
    NodeIdentityError,
    migrate_enrolled_node_id,
    resolve_node_id,
)


def _provider_env(path: Path, node_id: str) -> None:
    path.write_text(
        "\n".join(
            (
                f"COMPUTEMESH_NODE_ID={node_id}",
                "COMPUTEMESH_CONTROL_HOST=provider.local",
            )
        )
        + "\n",
        encoding="utf-8",
    )


def test_enrolled_provider_id_wins_over_boot_and_hostname_fallback(tmp_path: Path) -> None:
    provider_env = tmp_path / "provider.env"
    _provider_env(provider_env, "enrolled-node-01")

    with patch.dict("os.environ", {"COMPUTEMESH_PROVIDER_ENV": str(provider_env)}, clear=False), patch(
        "tools.appliance.appliance_config.load_appliance_config",
        side_effect=AssertionError("unenrolled fallback must not be consulted"),
    ):
        assert tunnel_relay.get_default_node_id() == "enrolled-node-01"
        assert heartbeat_relay.load_heartbeat_node_id() == "enrolled-node-01"


def test_invalid_persisted_provider_id_fails_closed_instead_of_using_hostname(tmp_path: Path) -> None:
    provider_env = tmp_path / "provider.env"
    _provider_env(provider_env, "cm-node-provider")
    provider_env.write_text(
        provider_env.read_text(encoding="utf-8").replace(
            "COMPUTEMESH_NODE_ID=cm-node-provider",
            "COMPUTEMESH_NODE_ID=",
        ),
        encoding="utf-8",
    )

    with patch.dict("os.environ", {"COMPUTEMESH_PROVIDER_ENV": str(provider_env)}, clear=False):
        with pytest.raises(NodeIdentityError, match="persisted provider identity"):
            resolve_node_id()


def test_explicit_id_cannot_override_enrolled_identity(tmp_path: Path) -> None:
    provider_env = tmp_path / "provider.env"
    _provider_env(provider_env, "enrolled-node-01")

    with patch.dict("os.environ", {"COMPUTEMESH_PROVIDER_ENV": str(provider_env)}, clear=False):
        with pytest.raises(NodeIdentityError, match="explicit node id does not match"):
            resolve_node_id("boot-default-node")


def test_authorized_node_id_migration_updates_provider_env_and_receipt(tmp_path: Path) -> None:
    provider_env = tmp_path / "provider.env"
    _provider_env(provider_env, "old-node-01")
    receipt = provider_env.parent / "enrollment.receipt.json"
    receipt.write_text(json.dumps({"node_id": "old-node-01", "public_key": "test"}) + "\n", encoding="utf-8")

    migrate_enrolled_node_id(
        "new-node-01",
        previous_node_id="old-node-01",
        provider_env_path=provider_env,
    )

    assert "COMPUTEMESH_NODE_ID=new-node-01" in provider_env.read_text(encoding="utf-8")
    assert json.loads(receipt.read_text(encoding="utf-8"))["node_id"] == "new-node-01"


def test_migration_rejects_wrong_previous_identity(tmp_path: Path) -> None:
    provider_env = tmp_path / "provider.env"
    _provider_env(provider_env, "old-node-01")

    with pytest.raises(NodeIdentityError, match="previous node id does not match"):
        migrate_enrolled_node_id(
            "new-node-01",
            previous_node_id="another-node",
            provider_env_path=provider_env,
        )


def test_nodeos_dashboard_does_not_start_second_heartbeat_relay() -> None:
    with patch.dict("os.environ", {"COMPUTEMESH_NODEOS": "1"}, clear=False):
        assert tunnel_relay.dashboard_must_not_start_relay() is True
