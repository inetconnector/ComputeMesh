from pathlib import Path
import os
import subprocess
import sys
import unittest
import tempfile
from unittest.mock import patch

from deploy.appliance import build_real_live_appliance as builder
from deploy.appliance.build_real_live_appliance import (
    DEFAULT_PERSISTENCE_SIZE_MIB,
    LLAMA_CPP_COMMIT,
    LLAMA_CPP_VERSION,
    _copy_source_snapshot,
    _resolve_source_repo,
    _render_heartbeat_unit,
    _render_module_launcher,
    _render_preflight_unit,
)


class TestRealLiveApplianceContract(unittest.TestCase):
    @staticmethod
    def _source() -> str:
        source = Path(__file__).resolve().parents[1] / "build_real_live_appliance.py"
        return source.read_text(encoding="utf-8")

    def test_runtime_is_pinned_and_model_storage_is_large_enough(self) -> None:
        self.assertEqual(LLAMA_CPP_VERSION, "v0.4.1")
        self.assertRegex(LLAMA_CPP_COMMIT, r"^[0-9a-f]{40}$")
        self.assertGreaterEqual(DEFAULT_PERSISTENCE_SIZE_MIB, 64 * 1024)

    def test_image_has_no_shared_root_password(self) -> None:
        source = Path(__file__).resolve().parents[1] / "build_real_live_appliance.py"
        text = source.read_text(encoding="utf-8")
        self.assertNotIn("root:computemesh", text)
        self.assertNotIn("PasswordAuthentication yes", text)
        self.assertIn("PasswordAuthentication no", text)
        self.assertIn("COMPUTEMESH_LLAMA_SERVER=/usr/local/bin/llama-server", text)

    def test_builder_declares_and_validates_debian_mirror(self) -> None:
        self.assertRegex(self._source(), r"DEBIAN_MIRROR\s*=")

    def test_vulkan_builder_declares_spirv_headers(self) -> None:
        self.assertIn("spirv-headers", self._source())

    def test_builder_has_no_server_specific_source_checkout_fallbacks(self) -> None:
        source = self._source()
        self.assertNotIn("/root/ComputeMesh", source)
        self.assertNotIn("/var/www/vhosts/inetconnector.com/site2", source)

    def test_builder_resolves_a_clean_explicit_git_checkout_and_exact_commit(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            checkout = Path(root) / "checkout"
            checkout.mkdir()
            for directory in ("apps", "services", "tools", "runtime", "deploy", "protocol", "portal"):
                (checkout / directory).mkdir()
            (checkout / "config.py").write_text("CONFIG = object()\n", encoding="utf-8")
            (checkout / "requirements.txt").write_text("cryptography\n", encoding="utf-8")
            subprocess.run(["git", "init", "-q"], cwd=checkout, check=True)
            subprocess.run(["git", "config", "user.email", "test@example.invalid"], cwd=checkout, check=True)
            subprocess.run(["git", "config", "user.name", "NodeOS Test"], cwd=checkout, check=True)
            subprocess.run(["git", "add", "."], cwd=checkout, check=True)
            subprocess.run(["git", "commit", "-qm", "test source"], cwd=checkout, check=True)
            expected = subprocess.run(
                ["git", "rev-parse", "HEAD"],
                cwd=checkout,
                check=True,
                capture_output=True,
                text=True,
            ).stdout.strip()

            resolved, commit = _resolve_source_repo(checkout, expected_commit=expected)

            self.assertEqual(resolved, checkout.resolve())
            self.assertEqual(commit, expected)

    def test_builder_rejects_dirty_source_checkout(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            checkout = Path(root) / "checkout"
            checkout.mkdir()
            for directory in ("apps", "services", "tools", "runtime", "deploy", "protocol", "portal"):
                (checkout / directory).mkdir()
            (checkout / "config.py").write_text("CONFIG = object()\n", encoding="utf-8")
            (checkout / "requirements.txt").write_text("cryptography\n", encoding="utf-8")
            subprocess.run(["git", "init", "-q"], cwd=checkout, check=True)
            subprocess.run(["git", "config", "user.email", "test@example.invalid"], cwd=checkout, check=True)
            subprocess.run(["git", "config", "user.name", "NodeOS Test"], cwd=checkout, check=True)
            subprocess.run(["git", "add", "."], cwd=checkout, check=True)
            subprocess.run(["git", "commit", "-qm", "test source"], cwd=checkout, check=True)
            (checkout / "requirements.txt").write_text("changed\n", encoding="utf-8")

            with self.assertRaisesRegex(RuntimeError, "clean"):
                _resolve_source_repo(checkout)

    def test_builder_exports_only_the_attested_commit_snapshot(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            root_path = Path(root)
            checkout = root_path / "checkout"
            checkout.mkdir()
            for directory in ("apps", "services", "tools", "runtime", "deploy", "protocol", "portal"):
                (checkout / directory).mkdir()
                (checkout / directory / ".keep").write_text("\n", encoding="utf-8")
            (checkout / "apps" / "attested.txt").write_text("committed\n", encoding="utf-8")
            (checkout / "config.py").write_text("CONFIG = object()\n", encoding="utf-8")
            (checkout / "requirements.txt").write_text("cryptography\n", encoding="utf-8")
            subprocess.run(["git", "init", "-q"], cwd=checkout, check=True)
            subprocess.run(["git", "config", "user.email", "test@example.invalid"], cwd=checkout, check=True)
            subprocess.run(["git", "config", "user.name", "NodeOS Test"], cwd=checkout, check=True)
            subprocess.run(["git", "add", "."], cwd=checkout, check=True)
            subprocess.run(["git", "commit", "-qm", "test source"], cwd=checkout, check=True)
            commit = subprocess.run(
                ["git", "rev-parse", "HEAD"],
                cwd=checkout,
                check=True,
                capture_output=True,
                text=True,
            ).stdout.strip()
            (checkout / "apps" / "attested.txt").write_text("mutable working tree\n", encoding="utf-8")
            (checkout / "apps" / "untracked.txt").write_text("must not enter image\n", encoding="utf-8")
            destination = root_path / "snapshot"
            (root_path / "build").mkdir()

            with patch.object(builder, "BUILD_DIR", root_path / "build"):
                _copy_source_snapshot(checkout, commit, destination)

            self.assertEqual((destination / "apps" / "attested.txt").read_text(encoding="utf-8"), "committed\n")
            self.assertFalse((destination / "apps" / "untracked.txt").exists())

    def test_service_enablement_is_fail_closed(self) -> None:
        self.assertNotIn("systemctl enable computemesh-node.service || true", self._source())

    def test_console_monitor_is_a_real_embedded_runtime(self) -> None:
        monitor = Path(__file__).resolve().parents[3] / "tools" / "appliance" / "console_monitor.py"
        self.assertTrue(monitor.is_file())

    def test_boot_has_preflight_and_explicit_enrollment_contract(self) -> None:
        text = self._source()
        self.assertIn("computemesh-node-preflight.service", text)
        self.assertIn("computemesh-enroll", text)
        self.assertIn("persistence.conf", text)
        self.assertIn("persistence-label=persistence", text)
        self.assertIn('"portal"', text)
        self.assertIn("requirements.txt", text)

    def test_generated_module_launchers_are_importable_from_an_arbitrary_cwd(self) -> None:
        text = self._source()
        self.assertIn("cd /opt/computemesh", text)
        self.assertIn("Environment=PYTHONPATH=/opt/computemesh", text)
        repo_root = Path(__file__).resolve().parents[3]
        env = os.environ.copy()
        env["PYTHONPATH"] = str(repo_root)
        with tempfile.TemporaryDirectory() as cwd:
            for module in ("tools.appliance.boot_preflight", "tools.appliance.enroll"):
                result = subprocess.run(
                    [sys.executable, "-m", module, "--help"],
                    cwd=cwd,
                    env=env,
                    capture_output=True,
                    text=True,
                    check=False,
                )
                self.assertEqual(result.returncode, 0, result.stderr)

    def test_rendered_systemd_contract_has_mounts_environment_and_preflight_order(self) -> None:
        preflight = _render_preflight_unit()
        heartbeat = _render_heartbeat_unit()
        self.assertIn("WorkingDirectory=/opt/computemesh", preflight)
        self.assertIn("Environment=PYTHONPATH=/opt/computemesh", preflight)
        self.assertIn("--ready-file /run/computemesh/node-preflight.ok", preflight)
        self.assertIn("RequiresMountsFor=/opt/computemesh /etc/computemesh /var/lib/computemesh", preflight)
        self.assertIn("Requires=computemesh-node-preflight.service", heartbeat)
        self.assertIn("EnvironmentFile=-/etc/computemesh/provider.env", heartbeat)
        self.assertIn("User=computemesh", heartbeat)
        self.assertIn("ConditionPathExists=/run/computemesh/node-preflight.ok", heartbeat)
        self.assertTrue(_render_module_launcher("tools.appliance.enroll").startswith("#!/bin/sh\nset -eu\ncd /opt/computemesh\n"))


if __name__ == "__main__":
    unittest.main()
