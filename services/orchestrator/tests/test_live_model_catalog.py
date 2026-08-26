from __future__ import annotations

import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from services.orchestrator.live_model_catalog import (
    LiveModelCatalogError,
    discover_verified_live_models,
)


class LiveModelCatalogTests(unittest.TestCase):
    def _fixture(self, root: Path, *, tamper: bool = False) -> tuple[Path, Path]:
        artifact = root / "tiny.gguf"
        artifact.write_bytes(b"GGUF" + b"\x00" * 28)
        digest = hashlib.sha256(artifact.read_bytes()).hexdigest()
        manifest = {
            "schema_version": 1,
            "model_id": "test/tiny",
            "model_version": "v1",
            "architecture": "test",
            "layer_count": 4,
            "license": {"id": "test", "source": "local", "redistribution_allowed": False},
            "runtime_compatibility": [{"runtime": "llama.cpp"}],
            "quantizations": ["Q4"],
            "partitioning": {"allowed": ["contiguous_layers"]},
            "artifacts": [{
                "digest": "sha256:" + ("0" * 64 if tamper else digest),
                "size_bytes": artifact.stat().st_size,
                "media_type": "application/x-gguf",
            }],
        }
        manifest_path = root / "tiny.computemesh-model-manifest.json"
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
        catalog_path = root / "catalog.json"
        catalog_path.write_text(json.dumps({
            "schema_version": 1,
            "models": [{"manifest": manifest_path.name, "artifact": artifact.name}],
        }), encoding="utf-8")
        return catalog_path, artifact

    def test_catalog_binds_manifest_to_actual_artifact(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            catalog, artifact = self._fixture(root)
            states = discover_verified_live_models(catalog_path=catalog, catalog_root=root)
            self.assertEqual(len(states), 1)
            self.assertEqual(states[0].model_id, "test/tiny")
            self.assertEqual(states[0].model_path, artifact.resolve())

    def test_digest_mismatch_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            catalog, _ = self._fixture(root, tamper=True)
            with self.assertRaisesRegex(LiveModelCatalogError, "SHA-256"):
                discover_verified_live_models(catalog_path=catalog, catalog_root=root)

    def test_non_gguf_file_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            catalog, artifact = self._fixture(root)
            artifact.write_bytes(b"NOPE" + artifact.read_bytes()[4:])
            manifest = json.loads((root / "tiny.computemesh-model-manifest.json").read_text())
            manifest["artifacts"][0]["size_bytes"] = artifact.stat().st_size
            manifest["artifacts"][0]["digest"] = "sha256:" + hashlib.sha256(artifact.read_bytes()).hexdigest()
            (root / "tiny.computemesh-model-manifest.json").write_text(json.dumps(manifest))
            with self.assertRaisesRegex(LiveModelCatalogError, "GGUF magic"):
                discover_verified_live_models(catalog_path=catalog, catalog_root=root)


if __name__ == "__main__":
    unittest.main()
