from pathlib import Path
import tempfile
import unittest

from tools.appliance.boot_preflight import PreflightError, run_preflight
from tools.appliance.enroll import EnrollmentError, enroll


class TestNodeOSRuntimeTools(unittest.TestCase):
    def test_preflight_rejects_unprovisioned_provider_environment(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            with self.assertRaisesRegex(PreflightError, "provider.env"):
                run_preflight(env_path=Path(root) / "provider.env", require_hardware=False)

    def test_enrollment_rejects_template_bundle_without_network_or_credentials(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            bundle = Path(root) / "enrollment.json"
            bundle.write_text(
                '{"control_url":"https://control.example.invalid",'
                '"control_ca_file":"/missing/ca.pem",'
                '"node_id":"node_replace_me",'
                '"auth_token":"<operator-issued-cm_tunnel_token>",'
                '"enrollment_token":"<one-time-token>"}',
                encoding="utf-8",
            )
            with self.assertRaisesRegex(EnrollmentError, "auth_token"):
                enroll(bundle)


if __name__ == "__main__":
    unittest.main()
