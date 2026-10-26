import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import call, patch
import subprocess
import sys

from tools.appliance.boot_preflight import PreflightError, run_preflight
from tools.appliance.enroll import EnrollmentError, _activate_nodeos_services, enroll
from services.appliance_dashboard import tunnel_relay


def _write_valid_evidence(root: Path, node_id: str) -> tuple[Path, Path, Path]:
    evidence_dir = root / "evidence"
    evidence_dir.mkdir(parents=True, exist_ok=True)
    profile = evidence_dir / "node_profile.json"
    prefill = evidence_dir / "prefill.json"
    decode = evidence_dir / "decode.json"
    profile.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "node_id": node_id,
                "profile_revision": 1,
                "captured_at": "2026-10-26T12:00:00Z",
                "platform": {"os": "Linux", "release": "test", "architecture": "x86_64"},
                "cpu": {"logical_cores": 8},
                "memory": {"total_bytes": 16 * 1024**3, "available_bytes": 8 * 1024**3},
                "devices": [],
                "runtime_capabilities": [{"runtime": "llama.cpp", "version": "v0.4.1"}],
                "provider_limits": {"draining": False},
                "benchmark_refs": ["inventory-run-1"],
            }
        ),
        encoding="utf-8",
    )
    for path, name, metric, count_key in (
        (prefill, "llama_cpp_prefill", "prefill_tokens_per_second_avg", "prompt_tokens"),
        (decode, "llama_cpp_decode", "decode_tokens_per_second_avg", "generated_tokens"),
    ):
        path.write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "run_id": f"{name}-run-1",
                    "benchmark_name": name,
                    "captured_at": "2026-10-26T12:00:01Z",
                    "profile_revision": 1,
                    "conditions": {"warm_state": "warm"},
                    "metrics": {
                        "llama_build_number": 1,
                        "llama_build_commit": "a" * 40,
                        "model_name": "test.gguf",
                        metric: 10.0,
                        count_key: 32,
                    },
                    "raw_samples": [],
                }
            ),
            encoding="utf-8",
        )
    return profile, prefill, decode


class TestNodeOSRuntimeTools(unittest.TestCase):
    def test_enrollment_import_does_not_load_dashboard_relay_or_mint_token(self) -> None:
        repo_root = Path(__file__).resolve().parents[3]
        env = os.environ.copy()
        env["PYTHONPATH"] = str(repo_root)
        env["COMPUTEMESH_NODEOS"] = ""
        with tempfile.TemporaryDirectory() as home:
            env["HOME"] = home
            result = subprocess.run(
                [
                    sys.executable,
                    "-c",
                    (
                        "import sys; import tools.appliance.enroll; "
                        "print('services.appliance_dashboard.tunnel_relay' in sys.modules)"
                    ),
                ],
                cwd=repo_root,
                env=env,
                capture_output=True,
                text=True,
                check=False,
            )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "False")

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
            profile_path, prefill_path, decode_path = _write_valid_evidence(
                root_path / "persistent", "local-enrollment-node"
            )
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
                        "profile_path": str(profile_path),
                        "prefill_path": str(prefill_path),
                        "decode_path": str(decode_path),
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
            profile, prefill, decode = _write_valid_evidence(root_path, "local-node")
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

    def test_preflight_rejects_empty_evidence_documents(self) -> None:
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
            with patch("tools.appliance.boot_preflight.load_node_private_key"), patch(
                "tools.appliance.boot_preflight.shutil.which", return_value="/usr/bin/runtime"
            ), patch(
                "tools.appliance.boot_preflight.subprocess.run",
                return_value=subprocess.CompletedProcess(["findmnt"], 0, "", ""),
            ):
                with self.assertRaisesRegex(PreflightError, "evidence"):
                    run_preflight(env_path=env_path, require_hardware=False)

    def test_enrollment_rejects_missing_runtime_evidence_before_gateway_acceptance(self) -> None:
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
            bundle.write_text(
                json.dumps(
                    {
                        "control_url": "https://enrollment.local:443",
                        "control_ca_file": str(ca_file),
                        "node_id": "local-enrollment-node",
                        "auth_token": "cm_tunnel_" + "a" * 48,
                        "enrollment_token": "local-enrollment-token",
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
            with patch("tools.appliance.enroll.urlopen", return_value=Response()) as request:
                with self.assertRaisesRegex(EnrollmentError, "measured runtime evidence"):
                    enroll(bundle, allow_insecure_localhost=True)
            request.assert_not_called()
            self.assertTrue(bundle.exists())

    def test_enrollment_storage_failure_is_retryable_without_replacing_accepted_token(self) -> None:
        class Response:
            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            def read(self, _limit: int) -> bytes:
                return b'{"status":"ok","node_id":"retry-node"}'

        with tempfile.TemporaryDirectory() as root:
            root_path = Path(root)
            ca_file = root_path / "enrollment-ca.pem"
            ca_file.write_text("local-test-ca", encoding="utf-8")
            profile, prefill, decode = _write_valid_evidence(root_path, "retry-node")
            provider_env = root_path / "provider.env"
            token_path = root_path / "node_auth_token.txt"
            key_path = root_path / "node.pem"
            bundle = root_path / "enrollment.json"
            bundle.write_text(
                json.dumps(
                    {
                        "control_url": "https://enrollment.local:443",
                        "control_ca_file": str(ca_file),
                        "node_id": "retry-node",
                        "auth_token": "cm_tunnel_" + "c" * 48,
                        "enrollment_token": "local-enrollment-token",
                        "private_key_path": str(key_path),
                        "provider_env_path": str(provider_env),
                        "node_auth_token_path": str(token_path),
                        "profile_path": str(profile),
                        "prefill_path": str(prefill),
                        "decode_path": str(decode),
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
                "tools.appliance.enroll.ssl.create_default_context", return_value=object()
            ), patch(
                "tools.appliance.enroll.persist_node_auth_token",
                side_effect=OSError("identity mount unavailable"),
            ):
                with self.assertRaisesRegex(EnrollmentError, "token cannot be persisted"):
                    enroll(bundle, allow_insecure_localhost=True)
            self.assertTrue(bundle.exists())
            self.assertFalse(provider_env.exists())
            self.assertFalse(token_path.exists())

            with patch("tools.appliance.enroll.urlopen", return_value=Response()), patch(
                "tools.appliance.enroll.ssl.create_default_context", return_value=object()
            ):
                enroll(bundle, allow_insecure_localhost=True)
            self.assertFalse(bundle.exists())
            self.assertIn("COMPUTEMESH_NODE_ID=retry-node", provider_env.read_text(encoding="utf-8"))
            self.assertEqual(token_path.read_text(encoding="utf-8").strip(), "cm_tunnel_" + "c" * 48)

    def test_enrollment_activation_runs_preflight_and_restarts_managed_units(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            root_path = Path(root)
            provider_env = root_path / "provider.env"
            marker = root_path / "node-preflight.ok"
            with patch.dict(
                os.environ,
                {
                    "COMPUTEMESH_NODEOS": "1",
                    "COMPUTEMESH_NODEOS_PREFLIGHT_MARKER": str(marker),
                },
                clear=False,
            ), patch("tools.appliance.boot_preflight.run_preflight") as run_preflight, patch(
                "tools.appliance.enroll.subprocess.run",
                return_value=subprocess.CompletedProcess(["systemctl"], 0, "", ""),
            ) as systemctl_run:
                _activate_nodeos_services(provider_env)

            run_preflight.assert_called_once_with(env_path=provider_env, ready_file=marker)
            self.assertEqual(
                [call.args[0] for call in systemctl_run.call_args_list],
                [
                    ["systemctl", "restart", "computemesh-node-preflight.service"],
                    ["systemctl", "restart", "computemesh-node.service"],
                    ["systemctl", "restart", "computemesh-node-heartbeat.service"],
                ],
            )


if __name__ == "__main__":
    unittest.main()
