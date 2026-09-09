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

    def test_out_of_range_block_size_is_rejected(self) -> None:
        accepted, message = disk_clone.start_clone("/dev/sdb", disk_clone.CONFIRM_PHRASE, block_size_mb=999)
        self.assertFalse(accepted)
        self.assertIn("block_size_mb", message)

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
            "clone_bytes": 16_000_000_000,
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
            "clone_bytes": 16_000_000_000,
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
            "clone_bytes": 16_000_000_000,
            "source_model": "USB Stick",
        }
        mock_targets.return_value = [{"device": "/dev/sdc", "name": "sdc", "size_bytes": 500_000_000_000, "model": "Real SSD"}]
        disk_clone._status.running = True
        accepted, message = disk_clone.start_clone("/dev/sdc", disk_clone.CONFIRM_PHRASE)
        self.assertFalse(accepted)
        self.assertIn("already in progress", message)

    @patch("tools.appliance.disk_clone.subprocess.run")
    def test_post_clone_fixup_runs_safely(self, mock_subproc) -> None:
        mock_subproc.return_value.returncode = 0
        disk_clone._post_clone_fixup("/dev/sda")
        self.assertTrue(mock_subproc.called)

    @patch("tools.appliance.disk_clone._is_removable")
    @patch("tools.appliance.disk_clone.Path.exists")
    @patch("tools.appliance.disk_clone.Path.iterdir")
    @patch("tools.appliance.disk_clone._block_disk_size_bytes")
    def test_list_clone_targets_includes_existing_os_flag(self, mock_size, mock_iter, mock_exists, mock_removable) -> None:
        mock_exists.return_value = True
        mock_removable.return_value = False
        mock_size.return_value = 128_000_000_000

        entry = Path("/sys/block/sda")
        mock_iter.return_value = [entry]

        targets = disk_clone.list_clone_targets("sdb", min_bytes=10_000_000)
        self.assertEqual(len(targets), 1)
        self.assertEqual(targets[0]["device"], "/dev/sda")
        self.assertIn("size_formatted", targets[0])
        self.assertIn("has_existing_os", targets[0])


if __name__ == "__main__":
    unittest.main()
