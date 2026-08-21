import json
import shlex
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
SETUP = REPO / "setup.sh"
LINUX = REPO / "setup" / "linux.sh"
DIRECT = [
    REPO / "setup" / "NODE.sh",
    REPO / "setup" / "NETWORK-SERVER.sh",
    REPO / "setup" / "NETWORK-CLIENT.sh",
    REPO / "setup" / "LLAMA-BENCH.sh",
    REPO / "setup" / "TESTS.sh",
]
BASH = shutil.which("bash")


@unittest.skipUnless(BASH, "bash is required for Linux setup tests")
class LinuxSetupTests(unittest.TestCase):
    def run_bash(self, script: str, *, input_text: str | None = None):
        return subprocess.run(
            [BASH, "-lc", script],
            input=input_text,
            text=True,
            capture_output=True,
            cwd=REPO,
            check=True,
        )

    def test_shell_syntax(self):
        subprocess.run([BASH, "-n", str(SETUP), str(LINUX), *(str(x) for x in DIRECT)], check=True)

    def test_help_entrypoint(self):
        out = subprocess.run([BASH, str(SETUP), "--help"], text=True, capture_output=True, check=True).stdout
        self.assertIn("Usage: ./setup.sh", out)

    def test_private_ipv4_filter(self):
        py = shlex.quote(sys.executable)
        linux = shlex.quote(str(LINUX))
        script = (
            f"source {linux}; VENV_PY={py}; "
            "is_private_ipv4 10.1.2.3; is_private_ipv4 172.20.1.2; is_private_ipv4 192.168.1.2; "
            "! is_private_ipv4 8.8.8.8; ! is_private_ipv4 169.254.1.1"
        )
        self.run_bash(script)

    def test_release_asset_selection(self):
        fixture = {
            "tag_name": "b10218",
            "assets": [
                {"name": "llama-b10218-bin-ubuntu-x64.tar.gz", "browser_download_url": "https://x/cpu"},
                {"name": "llama-b10218-bin-ubuntu-vulkan-x64.tar.gz", "browser_download_url": "https://x/vk"},
                {"name": "llama-b10218-bin-ubuntu-rocm-7.2-x64.tar.gz", "browser_download_url": "https://x/rocm"},
                {"name": "llama-b10218-bin-ubuntu-arm64.tar.gz", "browser_download_url": "https://x/arm"},
            ],
        }
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "release.json"
            p.write_text(json.dumps(fixture), encoding="utf-8")
            py = shlex.quote(sys.executable)
            linux = shlex.quote(str(LINUX))
            path = shlex.quote(str(p))
            for backend, arch, expected in [
                ("vulkan", "x86_64", "vulkan-x64"),
                ("rocm", "x86_64", "rocm-7.2-x64"),
                ("cpu", "aarch64", "ubuntu-arm64"),
            ]:
                out = self.run_bash(
                    f"source {linux}; VENV_PY={py}; release_asset {path} {backend} {arch}"
                ).stdout
                self.assertIn(expected, out)

    def test_network_server_is_private_and_firewall_is_temporary(self):
        text = LINUX.read_text(encoding="utf-8")
        self.assertNotIn("--bind 0.0.0.0", text)
        self.assertIn("source address=$network", text)
        self.assertIn("destination address=$ip", text)
        self.assertIn("firewall-cmd", text)
        self.assertIn("ufw --force delete allow", text)
        self.assertIn("trap cleanup_firewall EXIT INT TERM", text)
        self.assertIn("is_private_ipv4", text)

    def test_direct_launchers_route_to_expected_modes(self):
        expected = {
            "NODE.sh": "node",
            "NETWORK-SERVER.sh": "server",
            "NETWORK-CLIENT.sh": "client",
            "LLAMA-BENCH.sh": "llama",
            "TESTS.sh": "tests",
        }
        for path in DIRECT:
            text = path.read_text(encoding="utf-8")
            self.assertIn(f'"{expected[path.name]}"', text)


if __name__ == "__main__":
    unittest.main()
