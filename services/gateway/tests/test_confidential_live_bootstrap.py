import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

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


class TestConfidentialLiveBootstrap(unittest.TestCase):
    def setUp(self) -> None:
        self.orig_env = dict(os.environ)

    def tearDown(self) -> None:
        os.environ.clear()
        os.environ.update(self.orig_env)

    def test_disabled_confidential_mode_clears_handler_components(self):
        os.environ.pop("COMPUTEMESH_CONFIDENTIAL_ENABLED", None)
        runtime = bootstrap.install_live_confidential_gateway(
            handler_cls=FakeHandler,
            registry=FakeRegistry(),
        )
        self.assertIsNone(runtime)
        self.assertIsNone(FakeHandler.confidential_coordinator)
        self.assertIsNone(FakeHandler.confidential_replay_store)
        self.assertIsNone(FakeHandler.confidential_data_plane)
        self.assertIsNone(FakeHandler.confidential_stream_data_plane)

    def test_enabled_confidential_mode_installs_complete_runtime_atomically(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            fake_broker = object()
            os.environ["COMPUTEMESH_CONFIDENTIAL_ENABLED"] = "1"
            os.environ["COMPUTEMESH_CONFIDENTIAL_STATE_DIR"] = str(tmp_path)
            with patch.object(
                bootstrap,
                "build_remote_confidential_broker_from_env",
                return_value=fake_broker,
            ):
                runtime = bootstrap.install_live_confidential_gateway(
                    handler_cls=FakeHandler,
                    registry=FakeRegistry(),
                )
                self.assertIsNotNone(runtime)
                self.assertIs(runtime.broker, fake_broker)
                self.assertIs(FakeHandler.confidential_coordinator, runtime.coordinator)
                self.assertIs(FakeHandler.confidential_replay_store, runtime.replay_store)
                self.assertIs(FakeHandler.confidential_data_plane, runtime.data_plane)
                self.assertIs(FakeHandler.confidential_stream_data_plane, runtime.stream_data_plane)
                self.assertTrue((tmp_path / "gateway_sessions.sqlite3").is_file())
                self.assertTrue((tmp_path / "gateway_replay.sqlite3").is_file())

    def test_enabled_mode_without_state_dir_fails_instead_of_partial_install(self):
        os.environ["COMPUTEMESH_CONFIDENTIAL_ENABLED"] = "1"
        os.environ.pop("COMPUTEMESH_CONFIDENTIAL_STATE_DIR", None)
        FakeHandler.confidential_coordinator = "unchanged"
        with self.assertRaisesRegex(bootstrap.LiveConfidentialBootstrapError, "STATE_DIR"):
            bootstrap.install_live_confidential_gateway(
                handler_cls=FakeHandler,
                registry=FakeRegistry(),
            )
        self.assertEqual(FakeHandler.confidential_coordinator, "unchanged")


if __name__ == "__main__":
    unittest.main()

