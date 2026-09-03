from pathlib import Path

import pytest

from services.gateway import confidential_live_bootstrap as bootstrap


class FakeOwnerStore:
    def owner_for_provider_node(self, node_id):
        return "owner-provider" if node_id == "node-a" else None


class FakeHandler:
    ledger = object()
    owner_account_store = FakeOwnerStore()
    confidential_coordinator = "stale"
    confidential_replay_store = "stale"
    confidential_data_plane = "stale"
    confidential_stream_data_plane = "stale"


class FakeRegistry:
    pass


def test_disabled_confidential_mode_clears_handler_components(monkeypatch):
    monkeypatch.delenv("COMPUTEMESH_CONFIDENTIAL_ENABLED", raising=False)
    runtime = bootstrap.install_live_confidential_gateway(
        handler_cls=FakeHandler,
        registry=FakeRegistry(),
    )
    assert runtime is None
    assert FakeHandler.confidential_coordinator is None
    assert FakeHandler.confidential_replay_store is None
    assert FakeHandler.confidential_data_plane is None
    assert FakeHandler.confidential_stream_data_plane is None


def test_enabled_confidential_mode_installs_complete_runtime_atomically(monkeypatch, tmp_path: Path):
    fake_broker = object()
    monkeypatch.setenv("COMPUTEMESH_CONFIDENTIAL_ENABLED", "1")
    monkeypatch.setenv("COMPUTEMESH_CONFIDENTIAL_STATE_DIR", str(tmp_path))
    monkeypatch.setattr(
        bootstrap,
        "build_remote_confidential_broker_from_env",
        lambda *, registry: fake_broker,
    )
    runtime = bootstrap.install_live_confidential_gateway(
        handler_cls=FakeHandler,
        registry=FakeRegistry(),
    )
    assert runtime is not None
    assert runtime.broker is fake_broker
    assert FakeHandler.confidential_coordinator is runtime.coordinator
    assert FakeHandler.confidential_replay_store is runtime.replay_store
    assert FakeHandler.confidential_data_plane is runtime.data_plane
    assert FakeHandler.confidential_stream_data_plane is runtime.stream_data_plane
    assert (tmp_path / "gateway_sessions.sqlite3").is_file()
    assert (tmp_path / "gateway_replay.sqlite3").is_file()


def test_enabled_mode_without_state_dir_fails_instead_of_partial_install(monkeypatch):
    monkeypatch.setenv("COMPUTEMESH_CONFIDENTIAL_ENABLED", "1")
    monkeypatch.delenv("COMPUTEMESH_CONFIDENTIAL_STATE_DIR", raising=False)
    FakeHandler.confidential_coordinator = "unchanged"
    with pytest.raises(bootstrap.LiveConfidentialBootstrapError, match="STATE_DIR"):
        bootstrap.install_live_confidential_gateway(
            handler_cls=FakeHandler,
            registry=FakeRegistry(),
        )
    assert FakeHandler.confidential_coordinator == "unchanged"
