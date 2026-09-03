"""Safety-critical validation tests for USB->SSD disk cloning.

These tests do not touch real block devices; they cover start_clone()'s
guard rails, which are the last line of defense before a destructive dd.
"""
from __future__ import annotations

import sys
from pathlib import Path
import unittest
from unittest.mock import patch

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tools.appliance import disk_clone


class TestDiskCloneSafety(unittest.TestCase):
    def setUp(self) -> None:
        disk_clone._status = disk_clone.CloneStatus()

    def test_wrong_confirm_phrase_is_rejected(self) -> None:
        accepted, message = disk_clone.start_clone("/dev/sdb", "yes please")
        self.assertFalse(accepted)
        self.assertIn("Confirmation phrase", message)

    @patch("tools.appliance.disk_clone.get_boot_source_info")
    def test_refuses_when_not_booted_from_usb(self, mock_info) -> None:
        mock_info.return_value = {
            "booted_from_usb": False,
            "source_disk": "/dev/sda",
            "source_size_bytes": 16_000_000_000,
            "source_model": "Some SSD",
        }
        accepted, message = disk_clone.start_clone("/dev/sdb", disk_clone.CONFIRM_PHRASE)
        self.assertFalse(accepted)
        self.assertIn("not currently booted from a removable", message)

    @patch("tools.appliance.disk_clone.list_clone_targets")
    @patch("tools.appliance.disk_clone.get_boot_source_info")
    def test_refuses_target_not_in_fresh_allowlist(self, mock_info, mock_targets) -> None:
        mock_info.return_value = {
            "booted_from_usb": True,
            "source_disk": "/dev/sda",
            "source_size_bytes": 16_000_000_000,
            "source_model": "USB Stick",
        }
        # Attacker/stale client asks for a device the fresh scan does not offer.
        mock_targets.return_value = [{"device": "/dev/sdc", "name": "sdc", "size_bytes": 500_000_000_000, "model": "Real SSD"}]
        accepted, message = disk_clone.start_clone("/dev/sdb", disk_clone.CONFIRM_PHRASE)
        self.assertFalse(accepted)
        self.assertIn("not a currently valid clone target", message)

    @patch("tools.appliance.disk_clone.threading.Thread")
    @patch("tools.appliance.disk_clone.list_clone_targets")
    @patch("tools.appliance.disk_clone.get_boot_source_info")
    def test_accepts_valid_target_and_starts_background_thread(self, mock_info, mock_targets, mock_thread) -> None:
        mock_info.return_value = {
            "booted_from_usb": True,
            "source_disk": "/dev/sda",
            "source_size_bytes": 16_000_000_000,
            "source_model": "USB Stick",
        }
        mock_targets.return_value = [{"device": "/dev/sdc", "name": "sdc", "size_bytes": 500_000_000_000, "model": "Real SSD"}]
        accepted, message = disk_clone.start_clone("/dev/sdc", disk_clone.CONFIRM_PHRASE)
        self.assertTrue(accepted)
        mock_thread.return_value.start.assert_called_once()
        status = disk_clone.get_clone_status()
        self.assertTrue(status["running"])
        self.assertEqual(status["target"], "/dev/sdc")
        self.assertEqual(status["total_bytes"], 16_000_000_000)

    @patch("tools.appliance.disk_clone.list_clone_targets")
    @patch("tools.appliance.disk_clone.get_boot_source_info")
    def test_refuses_concurrent_clone(self, mock_info, mock_targets) -> None:
        mock_info.return_value = {
            "booted_from_usb": True,
            "source_disk": "/dev/sda",
            "source_size_bytes": 16_000_000_000,
            "source_model": "USB Stick",
        }
        mock_targets.return_value = [{"device": "/dev/sdc", "name": "sdc", "size_bytes": 500_000_000_000, "model": "Real SSD"}]
        disk_clone._status.running = True
        accepted, message = disk_clone.start_clone("/dev/sdc", disk_clone.CONFIRM_PHRASE)
        self.assertFalse(accepted)
        self.assertIn("already in progress", message)


if __name__ == "__main__":
    unittest.main()
