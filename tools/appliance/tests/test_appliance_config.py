"""Unit tests for Appliance Configuration Loader."""
from pathlib import Path
import tempfile
import unittest

from tools.appliance.appliance_config import (
    ApplianceConfig,
    load_appliance_config,
    save_system_config,
)


class TestApplianceConfig(unittest.TestCase):
    def test_load_from_boot_env(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            boot_file = tmp_path / "computemesh.env"
            boot_file.write_text(
                "RIG_NAME=miner-alpha\n"
                "PROVIDER_ACCOUNT_ID=cm_0x123456789\n"
                "COORDINATOR_URL=https://node.computemesh.net\n"
                "NETWORK_MODE=static\n"
                "STATIC_IP=192.168.1.100/24\n"
                "DASHBOARD_PORT=9090\n",
                encoding="utf-8",
            )
            cfg = load_appliance_config(boot_path=boot_file, system_path=tmp_path / "none.json")
            self.assertEqual(cfg.rig_name, "miner-alpha")
            self.assertEqual(cfg.provider_account_id, "cm_0x123456789")
            self.assertEqual(cfg.coordinator_url, "https://node.computemesh.net")
            self.assertEqual(cfg.network_mode, "static")
            self.assertEqual(cfg.static_ip, "192.168.1.100/24")
            self.assertEqual(cfg.dashboard_port, 9090)


if __name__ == "__main__":
    unittest.main()
