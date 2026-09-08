from __future__ import annotations

import pytest

from services.identity.machine_identity import (
    MachineIdentityError,
    attach_governance_identity,
    collect_machine_identity,
)


def test_machine_identity_is_stable_under_order_case_and_whitespace() -> None:
    first = collect_machine_identity(signal_provider=lambda: {
        "system_uuid": " ABC-123 ",
        "processor_model": " Example CPU ",
        "mac": "AABBCCDDEEFF",
    })
    second = collect_machine_identity(signal_provider=lambda: {
        "mac": "aabbccddeeff",
        "processor_model": "example cpu",
        "system_uuid": "abc-123",
    })
    assert first == second
    assert first.sources == ("system_uuid",)
    assert first.machine_id.startswith("hw1:")
    assert len(first.machine_id) == len("hw1:") + 64


def test_nic_change_does_not_change_identity_when_firmware_uuid_exists() -> None:
    first = collect_machine_identity(signal_provider=lambda: {
        "system_uuid": "host-a",
        "mac": "001122334455",
    })
    second = collect_machine_identity(signal_provider=lambda: {
        "system_uuid": "host-a",
        "mac": "aabbccddeeff",
    })
    assert first == second


def test_machine_identity_changes_when_firmware_identity_changes() -> None:
    first = collect_machine_identity(signal_provider=lambda: {
        "system_uuid": "host-a",
        "processor_model": "same cpu",
    })
    second = collect_machine_identity(signal_provider=lambda: {
        "system_uuid": "host-b",
        "processor_model": "same cpu",
    })
    assert first.machine_id != second.machine_id


def test_public_machine_identity_never_contains_raw_hardware_values() -> None:
    raw_serial = "secret-board-serial-123"
    identity = collect_machine_identity(signal_provider=lambda: {
        "dmi_board_serial": raw_serial,
        "mac": "001122334455",
    })
    public = identity.to_public_dict()
    assert raw_serial not in repr(public)
    assert "001122334455" not in repr(public)
    assert public["sources"] == ["dmi_board_serial"]


def test_machine_id_precedes_processor_and_mac_fallbacks() -> None:
    identity = collect_machine_identity(signal_provider=lambda: {
        "machine_id": "installation-a",
        "processor_id": "cpu-a",
        "mac": "001122334455",
    })
    assert identity.sources == ("machine_id",)


def test_processor_id_is_used_before_mac_when_stronger_sources_are_missing() -> None:
    identity = collect_machine_identity(signal_provider=lambda: {
        "processor_id": "cpu-a",
        "mac": "001122334455",
    })
    assert identity.sources == ("processor_id",)


def test_processor_model_and_architecture_alone_are_not_unique_enough() -> None:
    with pytest.raises(MachineIdentityError, match="host-specific"):
        collect_machine_identity(signal_provider=lambda: {
            "processor_model": "common cpu",
            "architecture": "x86_64",
        })


def test_attach_governance_identity_is_additive_and_validates_fleet() -> None:
    source = {"node_id": "node-a", "profile_revision": 1}
    identity = collect_machine_identity(signal_provider=lambda: {"system_uuid": "host-a"})
    governed = attach_governance_identity(source, fleet_id="fleet-east", identity=identity)
    assert source == {"node_id": "node-a", "profile_revision": 1}
    assert governed["fleet_id"] == "fleet-east"
    assert governed["machine_identity"] == identity.to_public_dict()

    with pytest.raises(MachineIdentityError, match="fleet_id"):
        attach_governance_identity(source, fleet_id="bad fleet id", identity=identity)
