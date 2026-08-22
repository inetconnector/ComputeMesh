import copy
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import stat
import tempfile
import unittest
import zipfile

from setup import evidence_transfer as transfer

MODEL_SIZE = 8_000_000_000
DIGEST = "sha256:" + "a" * 64
MODEL_NAME = "shared-model.gguf"


def stamp(minutes_ago: int) -> str:
    value = datetime.now(timezone.utc) - timedelta(minutes=minutes_ago)
    return value.isoformat().replace("+00:00", "Z")


def profile(node_id: str, *, revision: int = 3, gpu_memory: int = 10_000_000_000) -> dict:
    return {
        "schema_version": 1,
        "node_id": node_id,
        "profile_revision": revision,
        "captured_at": stamp(5),
        "platform": {
            "os": "TestOS",
            "release": "1",
            "architecture": "x86_64",
            "python_version": "3.11",
        },
        "cpu": {"model": "Test CPU", "logical_cores": 8},
        "memory": {"total_bytes": 16_000_000_000, "available_bytes": 14_000_000_000},
        "devices": [{
            "device_id": "gpu:0",
            "kind": "gpu",
            "vendor": "Test",
            "name": "Test GPU",
            "memory_total_bytes": gpu_memory,
            "driver_version": "1",
            "backend": "cuda",
        }],
        "runtime_capabilities": [],
        "provider_limits": {
            "draining": False,
            "max_memory_fraction": 0.90,
            "max_power_watts": None,
        },
        "benchmark_refs": [],
    }


def benchmark(
    name: str,
    run_id: str,
    *,
    revision: int = 3,
    node_id: str | None = None,
    peer_node_id: str | None = None,
    tps: float = 100.0,
) -> dict:
    conditions = {"warm_state": "warm"}
    if node_id is not None:
        conditions["local_node_id"] = node_id
    if peer_node_id is not None:
        conditions["peer_node_id"] = peer_node_id
        conditions["peer_identity_binding"] = "unauthenticated_server_report_v1"
    if name == "llama_cpp_prefill":
        metrics = {
            "model_name": MODEL_NAME,
            "model_size_bytes": MODEL_SIZE,
            "prefill_tokens_per_second_avg": tps,
            "prompt_tokens": 512,
        }
    elif name == "llama_cpp_decode":
        metrics = {
            "model_name": MODEL_NAME,
            "model_size_bytes": MODEL_SIZE,
            "decode_tokens_per_second_avg": tps,
            "generated_tokens": 128,
            "inter_token_ms_avg": 1000.0 / tps,
        }
    else:
        metrics = {
            "rtt_ms_p50": 2.0,
            "rtt_ms_p95": 3.0,
            "upload_mbps_p50": 900.0,
            "download_mbps_p50": 850.0,
        }
    return {
        "schema_version": 1,
        "run_id": run_id,
        "benchmark_name": name,
        "captured_at": stamp(4),
        "profile_revision": revision,
        "conditions": conditions,
        "metrics": metrics,
        "raw_samples": [],
    }


def model_manifest() -> dict:
    return {
        "schema_version": 1,
        "model_id": "shared-model",
        "model_version": "1",
        "architecture": "test",
        "layer_count": 32,
        "license": {"id": "test", "source": "test", "redistribution_allowed": False},
        "runtime_compatibility": [{"runtime": "llama.cpp"}],
        "quantizations": ["Q4_K_M"],
        "partitioning": {"allowed": ["contiguous_layers"]},
        "artifacts": [{
            "digest": DIGEST,
            "size_bytes": MODEL_SIZE,
            "media_type": "application/x-gguf",
        }],
    }


def write_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def write_node(root: Path, node_id: str, *, peer_node_id: str | None = None, gpu_memory: int = 10_000_000_000) -> None:
    write_json(root / "inventory" / "node_profile.json", profile(node_id, gpu_memory=gpu_memory))
    write_json(root / "llama" / "benchmark-prefill.json", benchmark("llama_cpp_prefill", f"{node_id}-p", tps=300.0))
    write_json(root / "llama" / "benchmark-decode.json", benchmark("llama_cpp_decode", f"{node_id}-d", tps=80.0))
    if peer_node_id is not None:
        write_json(
            root / "network" / "network-bound.json",
            benchmark(
                "tcp_network_path",
                f"{node_id}-to-{peer_node_id}",
                node_id=node_id,
                peer_node_id=peer_node_id,
            ),
        )


class EvidenceTransferTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.exports = self.root / "exports"
        self.imports = self.root / "imports"

    def tearDown(self):
        self.tmp.cleanup()

    def _export(self, node_id: str = "lab-worker01"):
        node_root = self.root / node_id
        write_node(node_root, node_id, gpu_memory=6_000_000_000)
        (node_root / "not-evidence.txt").write_text("do not export", encoding="utf-8")
        (node_root / "model.gguf").write_bytes(b"not model data")
        result = transfer.export_node_evidence(
            node_root=node_root,
            node_id=node_id,
            profile_revision=3,
            export_root=self.exports,
        )
        return node_root, result

    def test_export_contains_only_contract_evidence_and_path_free_manifest(self):
        node_root, result = self._export()
        self.assertTrue(result.archive.is_file())
        with zipfile.ZipFile(result.archive) as archive:
            names = set(archive.namelist())
            self.assertIn(transfer.EXPORT_MANIFEST_NAME, names)
            self.assertFalse(any("model.gguf" in name or "not-evidence" in name for name in names))
            manifest = json.loads(archive.read(transfer.EXPORT_MANIFEST_NAME))
        self.assertEqual(manifest["node_id"], "lab-worker01")
        self.assertEqual(manifest["profile_revision"], 3)
        self.assertEqual(manifest["export_id"], result.export_id)
        serialized = json.dumps(manifest)
        self.assertNotIn(str(node_root.resolve()), serialized)
        self.assertTrue(all(item["path"].endswith(".json") for item in manifest["files"]))

    def test_export_requires_config_revision_to_match_latest_profile(self):
        node_root = self.root / "lab-worker01"
        write_node(node_root, "lab-worker01")
        with self.assertRaisesRegex(transfer.EvidenceTransferError, "newest captured revision"):
            transfer.export_node_evidence(
                node_root=node_root,
                node_id="lab-worker01",
                profile_revision=2,
                export_root=self.exports,
            )

    def test_roundtrip_import_is_hash_verified_and_idempotent(self):
        _, exported = self._export()
        first = transfer.import_node_export(archive_path=exported.archive, import_root=self.imports)
        second = transfer.import_node_export(archive_path=exported.archive, import_root=self.imports)
        self.assertEqual(first, second)
        self.assertEqual(first.node_id, "lab-worker01")
        self.assertTrue((first.evidence_root / "inventory" / "node_profile.json").is_file())
        self.assertFalse((first.evidence_root / "model.gguf").exists())

    def test_import_rejects_modified_evidence_bytes(self):
        _, exported = self._export()
        tampered = self.root / "tampered.zip"
        with zipfile.ZipFile(exported.archive) as source, zipfile.ZipFile(tampered, "w") as target:
            changed = False
            for info in source.infolist():
                data = source.read(info.filename)
                if info.filename.startswith("evidence/") and not changed:
                    data = bytes([data[0] ^ 1]) + data[1:]
                    changed = True
                target.writestr(info, data)
        with self.assertRaisesRegex(transfer.EvidenceTransferError, "SHA-256 mismatch"):
            transfer.import_node_export(archive_path=tampered, import_root=self.imports)

    def test_import_rejects_symlink_entry(self):
        _, exported = self._export()
        malicious = self.root / "symlink.zip"
        with zipfile.ZipFile(exported.archive) as source, zipfile.ZipFile(malicious, "w") as target:
            changed = False
            for original in source.infolist():
                data = source.read(original.filename)
                info = copy.copy(original)
                if original.filename.startswith("evidence/") and not changed:
                    info.external_attr = (stat.S_IFLNK | 0o777) << 16
                    changed = True
                target.writestr(info, data)
        with self.assertRaisesRegex(transfer.EvidenceTransferError, "symlink"):
            transfer.import_node_export(archive_path=malicious, import_root=self.imports)

    def test_manifest_path_traversal_is_rejected_before_extraction(self):
        _, exported = self._export()
        with zipfile.ZipFile(exported.archive) as source:
            manifest = json.loads(source.read(transfer.EXPORT_MANIFEST_NAME))
        item = manifest["files"][0]
        item["path"] = "../escape.json"
        manifest["files"] = sorted(manifest["files"], key=lambda value: value["path"])
        manifest["export_id"] = transfer._export_id(
            manifest["node_id"], manifest["profile_revision"], manifest["files"]
        )
        malicious = self.root / "traversal.zip"
        with zipfile.ZipFile(malicious, "w") as archive:
            archive.writestr(transfer.EXPORT_MANIFEST_NAME, json.dumps(manifest))
            for entry in manifest["files"]:
                archive.writestr(f"evidence/{entry['path']}", b"x" * entry["size_bytes"])
        outside = self.root / "escape.json"
        with self.assertRaisesRegex(transfer.EvidenceTransferError, "unsafe archive path"):
            transfer.import_node_export(archive_path=malicious, import_root=self.imports)
        self.assertFalse(outside.exists())

    def test_existing_import_tamper_is_detected(self):
        _, exported = self._export()
        imported = transfer.import_node_export(archive_path=exported.archive, import_root=self.imports)
        victim = imported.evidence_root / "inventory" / "node_profile.json"
        victim.write_text("{}\n", encoding="utf-8")
        with self.assertRaisesRegex(transfer.EvidenceTransferError, "existing import"):
            transfer.import_node_export(archive_path=exported.archive, import_root=self.imports)

    def test_peer_export_can_build_real_shape_bundle_with_local_coordinator_tree(self):
        coordinator_id = "lab-coord001"
        worker_id = "lab-worker01"
        coordinator_root = self.root / coordinator_id
        write_node(coordinator_root, coordinator_id, peer_node_id=worker_id, gpu_memory=10_000_000_000)
        worker_root = self.root / worker_id
        write_node(worker_root, worker_id, gpu_memory=6_000_000_000)
        exported = transfer.export_node_evidence(
            node_root=worker_root,
            node_id=worker_id,
            profile_revision=3,
            export_root=self.exports,
        )
        imported = transfer.import_node_export(archive_path=exported.archive, import_root=self.imports)
        manifest_path = self.root / "model_manifest.json"
        write_json(manifest_path, model_manifest())
        output = self.root / "bundle" / "experiment_bundle.json"
        result = transfer.build_lab_bundle(
            local_node_root=coordinator_root,
            local_node_id=coordinator_id,
            peer_evidence_root=imported.evidence_root,
            model_manifest=manifest_path,
            output=output,
        )
        self.assertEqual(result, output.resolve())
        bundle = json.loads(output.read_text(encoding="utf-8"))
        self.assertEqual(bundle["sources"]["coordinator"]["profile"]["node_id"], coordinator_id)
        self.assertEqual(bundle["sources"]["worker"]["profile"]["node_id"], worker_id)
        self.assertEqual(bundle["sources"]["network"]["peer_node_id"], worker_id)
        self.assertEqual(bundle["placement_decision"]["model"]["layer_count_source"], "model_manifest_v1")
        self.assertNotIn(str(self.root.resolve()), json.dumps(bundle))


if __name__ == "__main__":
    unittest.main()
