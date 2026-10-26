import unittest
import lzma
import os
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock

from tools.build_all_releases import (
    ReleaseBuildError,
    _exclude_linux_release_path,
    _write_nodeos_provenance_report,
    _validate_nodeos_artifacts,
    _validate_nodeos_provenance_report,
    sign_and_verify_release,
)


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

    def test_nodeos_artifacts_must_contain_current_build_provenance(self) -> None:
        expected = {
            "schema_version": 1,
            "artifact_kind": "nodeos",
            "source_commit": "a" * 40,
            "version": "1.2.189",
        }
        marker = b"COMPUTEMESH_BUILD_PROVENANCE_V1=" + (
            '{"artifact_kind":"nodeos","schema_version":1,'
            '"source_commit":"' + "a" * 40 + '","version":"1.2.189"}'
        ).encode("ascii")
        with TemporaryDirectory() as root:
            root_path = Path(root)
            iso = root_path / "node.iso"
            image = root_path / "node.img.xz"
            iso.write_bytes(b"iso bytes\n" + marker + b"\n")
            image.write_bytes(lzma.compress(b"compressed image without provenance"))

            with self.assertRaisesRegex(ValueError, "provenance"):
                _validate_nodeos_artifacts(iso, image, expected)

    def test_nodeos_artifacts_reject_a_stale_source_commit(self) -> None:
        expected = {
            "schema_version": 1,
            "artifact_kind": "nodeos",
            "source_commit": "b" * 40,
            "version": "1.2.189",
        }
        stale_marker = b"COMPUTEMESH_BUILD_PROVENANCE_V1=" + (
            '{"artifact_kind":"nodeos","schema_version":1,'
            '"source_commit":"' + "c" * 40 + '","version":"1.2.189"}'
        ).encode("ascii")
        with TemporaryDirectory() as root:
            root_path = Path(root)
            iso = root_path / "node.iso"
            image = root_path / "node.img.xz"
            iso.write_bytes(stale_marker + b"\n")
            image.write_bytes(lzma.compress(stale_marker + b"\n"))

            with self.assertRaisesRegex(ValueError, "source_commit"):
                _validate_nodeos_artifacts(iso, image, expected)

    def test_release_signing_requires_explicit_operator_approval(self) -> None:
        with mock.patch.dict("os.environ", {}, clear=False):
            os.environ.pop("COMPUTEMESH_RELEASE_SIGNING_APPROVED", None)
            with self.assertRaisesRegex(ReleaseBuildError, "explicit"):
                sign_and_verify_release()

    def test_existing_nodeos_artifacts_require_matching_digest_report(self) -> None:
        expected = {
            "schema_version": 1,
            "artifact_kind": "nodeos",
            "source_commit": "d" * 40,
            "version": "1.2.189",
        }
        marker = b"COMPUTEMESH_BUILD_PROVENANCE_V1=" + (
            '{"artifact_kind":"nodeos","schema_version":1,'
            '"source_commit":"' + "d" * 40 + '","version":"1.2.189"}'
        ).encode("ascii")
        with TemporaryDirectory() as root:
            root_path = Path(root)
            iso = root_path / "node.iso"
            image = root_path / "node.img.xz"
            report = root_path / "node.provenance.json"
            iso.write_bytes(marker + b"\niso")
            image.write_bytes(lzma.compress(marker + b"\nimage"))
            _validate_nodeos_artifacts(iso, image, expected)
            _write_nodeos_provenance_report(iso, image, expected, report)

            image.write_bytes(lzma.compress(marker + b"\ntampered"))
            with self.assertRaisesRegex(ValueError, "sha256"):
                _validate_nodeos_provenance_report(iso, image, expected, report)


if __name__ == "__main__":
    unittest.main()
