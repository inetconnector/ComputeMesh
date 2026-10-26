from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from services.appliance_dashboard import tunnel_relay
from tools.appliance import heartbeat_relay
from tools.appliance.node_identity import (
    NodeIdentityError,
    migrate_enrolled_node_id,
    resolve_node_id,
)
from tools.security.node_key_storage import save_node_private_key


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


def test_nodeos_heartbeat_and_provider_use_the_enrollment_key_across_restart(tmp_path: Path) -> None:
    provider_env = tmp_path / "provider.env"
    key_path = tmp_path / "persistent" / "node-ed25519.pem"
    key_path.parent.mkdir()
    key = Ed25519PrivateKey.generate()
    save_node_private_key(key, key_path, protect_os=False)
    _provider_env(provider_env, "enrolled-node-01")
    provider_env.write_text(
        provider_env.read_text(encoding="utf-8")
        + f"COMPUTEMESH_NODE_PRIVATE_KEY={key_path}\n",
        encoding="utf-8",
    )
    marker = tmp_path / "node-preflight.ok"
    marker.write_text("ready\n", encoding="ascii")
    auth_token = "cm_tunnel_" + "a" * 48

    with patch.dict(
        "os.environ",
        {
            "COMPUTEMESH_NODEOS": "1",
            "COMPUTEMESH_PROVIDER_ENV": str(provider_env),
            "COMPUTEMESH_NODEOS_PREFLIGHT_MARKER": str(marker),
        },
        clear=False,
    ), patch("tools.appliance.lan_discovery_responder.start_lan_discovery_responder"):
        first = tunnel_relay.CloudTunnelRelay(node_id="enrolled-node-01", auth_token=auth_token, autostart=False)
        second = tunnel_relay.CloudTunnelRelay(node_id="enrolled-node-01", auth_token=auth_token, autostart=False)
        expected = key.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw).hex()
        assert first._key_path == key_path
        assert second._key_path == key_path
        assert first.public_key_hex == expected
        assert second.public_key_hex == expected
        first.stop()
        second.stop()


def test_nodeos_rejects_missing_or_switched_enrollment_key(tmp_path: Path) -> None:
    provider_env = tmp_path / "provider.env"
    enrolled_key = tmp_path / "enrolled.pem"
    switched_key = tmp_path / "switched.pem"
    save_node_private_key(Ed25519PrivateKey.generate(), enrolled_key, protect_os=False)
    save_node_private_key(Ed25519PrivateKey.generate(), switched_key, protect_os=False)
    _provider_env(provider_env, "enrolled-node-01")
    provider_env.write_text(
        provider_env.read_text(encoding="utf-8")
        + f"COMPUTEMESH_NODE_PRIVATE_KEY={enrolled_key}\n",
        encoding="utf-8",
    )
    marker = tmp_path / "node-preflight.ok"
    marker.write_text("ready\n", encoding="ascii")

    with patch.dict(
        "os.environ",
        {
            "COMPUTEMESH_NODEOS": "1",
            "COMPUTEMESH_PROVIDER_ENV": str(provider_env),
            "COMPUTEMESH_NODEOS_PREFLIGHT_MARKER": str(marker),
            "COMPUTEMESH_NODE_PRIVATE_KEY": str(switched_key),
        },
        clear=False,
    ), patch("tools.appliance.lan_discovery_responder.start_lan_discovery_responder"):
        with pytest.raises(tunnel_relay.NodeAuthTokenStorageError, match="does not match"):
            tunnel_relay.CloudTunnelRelay(
                node_id="enrolled-node-01",
                auth_token="cm_tunnel_" + "b" * 48,
                autostart=False,
            )

    provider_env.write_text(
        provider_env.read_text(encoding="utf-8").replace(str(enrolled_key), str(tmp_path / "missing.pem")),
        encoding="utf-8",
    )
    with patch.dict(
        "os.environ",
        {
            "COMPUTEMESH_NODEOS": "1",
            "COMPUTEMESH_PROVIDER_ENV": str(provider_env),
            "COMPUTEMESH_NODEOS_PREFLIGHT_MARKER": str(marker),
        },
        clear=False,
    ), patch("tools.appliance.lan_discovery_responder.start_lan_discovery_responder"):
        with pytest.raises(tunnel_relay.NodeAuthTokenStorageError, match="private key"):
            tunnel_relay.CloudTunnelRelay(
                node_id="enrolled-node-01",
                auth_token="cm_tunnel_" + "b" * 48,
                autostart=False,
            )
