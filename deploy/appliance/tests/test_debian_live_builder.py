"""Unit tests for Debian Live NodeOS Image Builder."""
from pathlib import Path
import tempfile
import unittest

from deploy.appliance.debian_live_builder import (
    ApplianceBuildConfig,
    DebianLiveBuilder,
    REQUIRED_PACKAGES,
)


class TestDebianLiveBuilder(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.build_path = Path(self.temp_dir.name)
        self.builder = DebianLiveBuilder(build_dir=self.build_path)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_generate_build_manifest(self) -> None:
        manifest = self.builder.generate_build_manifest()
        self.assertEqual(manifest["distribution"], "trixie")
        self.assertEqual(manifest["binary_format"], "img.xz")
        self.assertIn("mesa-vulkan-drivers", manifest["packages"])
        self.assertIn("firmware-amd-graphics", manifest["packages"])
        self.assertIn("computemesh-appliance.service", manifest["systemd_services"])

    def test_create_build_tree(self) -> None:
        tree = self.builder.create_build_tree()
        self.assertTrue(tree.exists())

        pkg_list = tree / "config" / "package-lists" / "computemesh.list.chroot"
        self.assertTrue(pkg_list.exists())
        pkg_content = pkg_list.read_text(encoding="utf-8")
        for pkg in REQUIRED_PACKAGES[:5]:
            self.assertIn(pkg, pkg_content)

        env_file = tree / "config" / "includes.binary" / "computemesh.env"
        self.assertTrue(env_file.exists())
        self.assertIn("WALLET_PAYOUT_ADDRESS", env_file.read_text(encoding="utf-8"))

        service_file = tree / "config" / "includes.chroot" / "etc" / "systemd" / "system" / "computemesh-appliance.service"
        self.assertTrue(service_file.exists())


if __name__ == "__main__":
    unittest.main()
