import unittest
from types import SimpleNamespace

from tools.appliance.fan_control import apply_fan_policy, fan_status


class TestFanControl(unittest.TestCase):
    def test_empty_inventory_can_keep_driver_auto(self) -> None:
        result = apply_fan_policy(SimpleNamespace(gpus=[]), "auto", 60)
        self.assertTrue(result["applied"])
        self.assertEqual(result["applied_count"], 0)

    def test_invalid_mode_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            apply_fan_policy(SimpleNamespace(gpus=[]), "turbo", 100)

    def test_status_has_no_synthetic_capability(self) -> None:
        status = fan_status(SimpleNamespace(gpus=[]), SimpleNamespace())
        self.assertFalse(status["control_available"])
        self.assertEqual(status["supported_modes"], ["safe_auto", "auto"])
        self.assertEqual(status["target_percent"], 60)


if __name__ == "__main__":
    unittest.main()
