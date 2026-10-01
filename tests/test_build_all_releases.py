import unittest
from tools.build_all_releases import _exclude_linux_release_path


class TestBuildAllReleases(unittest.TestCase):
    def test_linux_release_excludes_generated_and_local_runtime_paths(self) -> None:
        excluded = (
            "apps/android/.gradle/8.9/cache.bin",
            "apps/android/app/build/outputs/app.apk",
            "runtime/sd_cpp/bin/sd-server.exe",
            "runtime/sd_cpp/build_ninja/stable-diffusion.lib",
            "runtime/sd_cpp/build_nmake/ggml/src/ggml-base.lib",
            "runtime/sd_cpp_src/src/tokenizers/vocab/umt5.hpp",
            "services/__pycache__/server.pyc",
        )
        self.assertTrue(all(_exclude_linux_release_path(path) for path in excluded))

    def test_linux_release_keeps_real_source_paths_containing_build_text(self) -> None:
        self.assertFalse(_exclude_linux_release_path("services/mcp/builtin/webapp_deployer.py"))
        self.assertFalse(_exclude_linux_release_path("deploy/windows/build_installer.py"))
        self.assertFalse(_exclude_linux_release_path("runtime/sd_cpp/image_engine_service.py"))


if __name__ == "__main__":
    unittest.main()
