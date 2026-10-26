import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import subprocess

from tools.appliance.boot_preflight import PreflightError, run_preflight
from tools.appliance.enroll import EnrollmentError, enroll
from services.appliance_dashboard import tunnel_relay


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

    def test_enrollment_provisions_distinct_provider_control_endpoint(self) -> None:
        class Response:
            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            def read(self, _limit: int) -> bytes:
                return b'{"status":"ok","node_id":"local-enrollment-node"}'

        with tempfile.TemporaryDirectory() as root:
            root_path = Path(root)
            ca_file = root_path / "enrollment-ca.pem"
            ca_file.write_text("local-test-ca", encoding="utf-8")
            bundle = root_path / "enrollment.json"
            provider_env = root_path / "provider.env"
            key_path = root_path / "persistent" / "node-ed25519.pem"
            token_path = root_path / "persistent" / "node_auth_token.txt"
            bundle.write_text(
                json.dumps(
                    {
                        "control_url": "https://enrollment.local:443",
                        "control_ca_file": str(ca_file),
                        "node_id": "local-enrollment-node",
                        "auth_token": "cm_tunnel_" + "a" * 48,
                        "enrollment_token": "local-enrollment-token",
                        "private_key_path": str(key_path),
                        "provider_env_path": str(provider_env),
                        "node_auth_token_path": str(token_path),
                        "provider_control": {
                            "host": "provider.local",
                            "port": 17443,
                            "server_hostname": "provider.local",
                            "ca_file": str(ca_file),
                        },
                    }
                ),
                encoding="utf-8",
            )
            with patch("tools.appliance.enroll.urlopen", return_value=Response()), patch(
                "tools.appliance.enroll.ssl.create_default_context",
                return_value=object(),
            ):
                enroll(bundle, allow_insecure_localhost=True)
            values = {
                line.split("=", 1)[0]: line.split("=", 1)[1]
                for line in provider_env.read_text(encoding="utf-8").splitlines()
                if "=" in line and not line.startswith("#")
            }
            self.assertEqual(values["COMPUTEMESH_CONTROL_HOST"], "provider.local")
            self.assertEqual(values["COMPUTEMESH_CONTROL_PORT"], "17443")
            self.assertEqual(values["COMPUTEMESH_CONTROL_SERVER_HOSTNAME"], "provider.local")
            self.assertEqual(values["COMPUTEMESH_CONTROL_CA_FILE"], str(ca_file))

    def test_nodeos_without_preflight_marker_does_not_report_provider_ready(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            marker = Path(root) / "node-preflight.ok"
            with patch.dict(
                os.environ,
                {
                    "COMPUTEMESH_NODEOS": "1",
                    "COMPUTEMESH_NODEOS_PREFLIGHT_MARKER": str(marker),
                },
                clear=False,
            ):
                self.assertFalse(tunnel_relay.nodeos_provider_ready())

    def test_nodeos_without_preflight_cannot_start_relay_or_generate_identity(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            marker = Path(root) / "node-preflight.ok"
            with patch.dict(
                os.environ,
                {
                    "COMPUTEMESH_NODEOS": "1",
                    "COMPUTEMESH_NODEOS_PREFLIGHT_MARKER": str(marker),
                },
                clear=False,
            ), patch(
                "tools.security.node_key_storage.get_or_create_node_private_key"
            ) as get_key:
                with self.assertRaises(tunnel_relay.NodeAuthTokenStorageError):
                    tunnel_relay.start_cloud_tunnel_relay(
                        node_id="local-test-node",
                        auth_token="cm_tunnel_" + "c" * 48,
                    )
                get_key.assert_not_called()

    def test_enrollment_rejects_implicit_http_control_endpoint_fallback(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            root_path = Path(root)
            ca_file = root_path / "ca.pem"
            ca_file.write_text("local-test-ca", encoding="utf-8")
            bundle = root_path / "enrollment.json"
            bundle.write_text(
                json.dumps(
                    {
                        "control_url": "https://enrollment.local:443",
                        "control_ca_file": str(ca_file),
                        "node_id": "local-node",
                        "auth_token": "cm_tunnel_" + "b" * 48,
                        "enrollment_token": "local-enrollment-token",
                    }
                ),
                encoding="utf-8",
            )
            with self.assertRaisesRegex(EnrollmentError, "separate provider_control"):
                enroll(bundle)

    def test_preflight_writes_ready_marker_only_after_all_local_checks(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            root_path = Path(root)
            persist = root_path / "persist"
            persist.mkdir()
            key = root_path / "node.pem"
            ca = root_path / "provider-ca.pem"
            token = root_path / "node_auth_token.txt"
            key.write_text("test-key", encoding="utf-8")
            ca.write_text("test-ca", encoding="utf-8")
            token.write_text("cm_tunnel_" + "d" * 48, encoding="utf-8")
            profile = root_path / "profile.json"
            prefill = root_path / "prefill.json"
            decode = root_path / "decode.json"
            for evidence in (profile, prefill, decode):
                evidence.write_text("{}", encoding="utf-8")
            env_path = root_path / "provider.env"
            env_path.write_text(
                "\n".join(
                    (
                        "COMPUTEMESH_NODE_ID=local-node",
                        "COMPUTEMESH_CONTROL_HOST=provider.local",
                        "COMPUTEMESH_CONTROL_PORT=17443",
                        "COMPUTEMESH_CONTROL_SERVER_HOSTNAME=provider.local",
                        f"COMPUTEMESH_CONTROL_CA_FILE={ca}",
                        f"COMPUTEMESH_NODE_PRIVATE_KEY={key}",
                        f"COMPUTEMESH_NODE_AUTH_TOKEN_PATH={token}",
                        f"COMPUTEMESH_NODE_PROFILE={profile}",
                        f"COMPUTEMESH_NODE_PREFILL={prefill}",
                        f"COMPUTEMESH_NODE_DECODE={decode}",
                    )
                ),
                encoding="utf-8",
            )
            marker = root_path / "run" / "node-preflight.ok"

            def fake_run(command, **kwargs):
                if command[0] == "findmnt":
                    return subprocess.CompletedProcess(command, 0, f"persistence {persist}\n", "")
                return subprocess.CompletedProcess(command, 0, "runtime ok\n", "")

            with patch.dict(os.environ, {"COMPUTEMESH_PERSISTENCE_MOUNT": str(persist)}, clear=False), patch(
                "tools.appliance.boot_preflight.load_node_private_key"
            ), patch(
                "tools.appliance.boot_preflight.shutil.which",
                return_value="/usr/bin/runtime",
            ), patch(
                "tools.appliance.boot_preflight.subprocess.run",
                side_effect=fake_run,
            ):
                run_preflight(env_path=env_path, require_hardware=True, ready_file=marker)
            self.assertEqual(marker.read_text(encoding="ascii"), "ready\n")


if __name__ == "__main__":
    unittest.main()
