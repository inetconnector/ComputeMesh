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
                "WALLET_PAYOUT_ADDRESS=0x9876543210987654321098765432109876543210\n"
                "COORDINATOR_URL=https://node.computemesh.net\n"
                "NETWORK_MODE=static\n"
                "STATIC_IP=192.168.1.100/24\n"
                "DASHBOARD_PORT=9090\n"
                "DISABLED_GPUS=1,3\n"
                "POWER_MODE=eco\n"
                "MAX_TEMP_C=75\n",
                encoding="utf-8",
            )
            cfg = load_appliance_config(boot_path=boot_file, system_path=tmp_path / "none.json")
            self.assertEqual(cfg.rig_name, "miner-alpha")
            self.assertEqual(cfg.provider_account_id, "cm_0x123456789")
            self.assertEqual(cfg.payout_address, "0x9876543210987654321098765432109876543210")
            self.assertEqual(cfg.coordinator_url, "https://node.computemesh.net")
            self.assertEqual(cfg.network_mode, "static")
            self.assertEqual(cfg.static_ip, "192.168.1.100/24")
            self.assertEqual(cfg.dashboard_port, 9090)
            self.assertEqual(cfg.disabled_gpus, [1, 3])
            self.assertEqual(cfg.power_mode, "eco")
            self.assertEqual(cfg.max_temp_c, 75)

    def test_save_and_reload_system_config(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            sys_file = tmp_path / "config.json"
            cfg = ApplianceConfig(
                rig_name="test-node-custom",
                provider_account_id="cm_prov_test",
                payout_address="0xABCDEF1234567890ABCDEF1234567890ABCDEF12",
                coordinator_url="https://test.computemesh.net",
                network_mode="dhcp",
                static_ip=None,
                gateway=None,
                dns=None,
                enable_web_dashboard=True,
                dashboard_port=8080,
                allow_ssh=True,
                ssh_authorized_keys=None,
                disabled_gpus=[0],
                vram_reserve_mb=1024,
                power_mode="max",
                max_temp_c=85,
                enable_kiosk=True,
            )
            save_system_config(cfg, path=sys_file)
            reloaded = load_appliance_config(boot_path=tmp_path / "none.env", system_path=sys_file)
            self.assertEqual(reloaded.rig_name, "test-node-custom")
            self.assertEqual(reloaded.payout_address, "0xABCDEF1234567890ABCDEF1234567890ABCDEF12")
            self.assertEqual(reloaded.disabled_gpus, [0])
            self.assertEqual(reloaded.vram_reserve_mb, 1024)
            self.assertEqual(reloaded.power_mode, "max")
            self.assertEqual(reloaded.max_temp_c, 85)


if __name__ == "__main__":
    unittest.main()
