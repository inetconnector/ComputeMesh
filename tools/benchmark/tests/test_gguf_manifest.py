import hashlib
import json
from pathlib import Path
import struct
import tempfile
import unittest

from jsonschema import Draft202012Validator, FormatChecker

from tools.benchmark import gguf_manifest as gm


def gguf_string(value: str) -> bytes:
    raw = value.encode("utf-8")
    return struct.pack("<Q", len(raw)) + raw


def gguf_value(value_type: int, value) -> bytes:
    if value_type == gm.TYPE_STRING:
        return gguf_string(value)
    if value_type == gm.TYPE_ARRAY:
        element_type, items = value
        return (
            struct.pack("<I", element_type)
            + struct.pack("<Q", len(items))
            + b"".join(gguf_value(element_type, item) for item in items)
        )
    fmt = gm.FIXED_TYPES[value_type][0]
    return struct.pack("<" + fmt, value)


def write_gguf(path: Path, entries, *, version=3, tensor_count=0):
    payload = bytearray()
    payload.extend(b"GGUF")
    payload.extend(struct.pack("<I", version))
    payload.extend(struct.pack("<Q", tensor_count))
    payload.extend(struct.pack("<Q", len(entries)))
    for key, value_type, value in entries:
        payload.extend(gguf_string(key))
        payload.extend(struct.pack("<I", value_type))
        payload.extend(gguf_value(value_type, value))
    path.write_bytes(bytes(payload))


def standard_entries(*, include_version=True, include_license=True, file_type=15):
    entries = [
        ("general.name", gm.TYPE_STRING, "Qwen Test"),
        ("general.architecture", gm.TYPE_STRING, "qwen2"),
        ("qwen2.block_count", gm.TYPE_UINT32, 28),
        ("general.file_type", gm.TYPE_UINT32, file_type),
        ("tokenizer.ggml.tokens", gm.TYPE_ARRAY, (gm.TYPE_STRING, ["a", "bb", "ccc"])),
        ("unrelated.nested", gm.TYPE_ARRAY, (gm.TYPE_ARRAY, [
            (gm.TYPE_UINT32, [1, 2]),
            (gm.TYPE_UINT32, [3]),
        ])),
    ]
    if include_version:
        entries.append(("general.version", gm.TYPE_STRING, "2.5"))
    if include_license:
        entries.extend([
            ("general.license", gm.TYPE_STRING, "Apache-2.0"),
            ("general.license.link", gm.TYPE_STRING, "https://example.invalid/license"),
        ])
    return entries


def split_entries(split_no: int, split_count: int, tensors_count: int):
    return [
        ("split.no", gm.TYPE_UINT16, split_no),
        ("split.count", gm.TYPE_UINT16, split_count),
        ("split.tensors.count", gm.TYPE_INT32, tensors_count),
    ]


class GgufManifestTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.gguf = self.root / "model.gguf"

    def tearDown(self):
        self.tmp.cleanup()

    def test_inspect_extracts_architecture_block_count_and_metadata(self):
        write_gguf(self.gguf, standard_entries())
        info = gm.inspect_gguf(self.gguf)
        self.assertEqual(info.version, 3)
        self.assertEqual(info.architecture, "qwen2")
        self.assertEqual(info.block_count, 28)
        self.assertEqual(info.name, "Qwen Test")
        self.assertEqual(info.model_version, "2.5")
        self.assertEqual(info.license_id, "Apache-2.0")
        self.assertEqual(info.file_type, 15)
        self.assertEqual(info.summary()["quantization"], "Q4_K_M")
        self.assertIsNone(info.split_count)

    def test_arrays_are_skipped_without_becoming_manifest_content(self):
        write_gguf(self.gguf, standard_entries())
        info = gm.inspect_gguf(self.gguf)
        self.assertNotIn("tokenizer", json.dumps(info.summary()))
        self.assertEqual(info.block_count, 28)

    def test_invalid_magic_and_version_are_rejected(self):
        self.gguf.write_bytes(b"NOPE" + b"\x00" * 32)
        with self.assertRaisesRegex(gm.GGUFError, "magic"):
            gm.inspect_gguf(self.gguf)
        write_gguf(self.gguf, standard_entries(), version=2)
        with self.assertRaisesRegex(gm.GGUFError, "version 2"):
            gm.inspect_gguf(self.gguf)

    def test_architecture_specific_block_count_is_required(self):
        entries = standard_entries()
        entries = [entry for entry in entries if entry[0] != "qwen2.block_count"]
        entries.append(("llama.block_count", gm.TYPE_UINT32, 32))
        write_gguf(self.gguf, entries)
        with self.assertRaisesRegex(gm.GGUFError, "qwen2.block_count"):
            gm.inspect_gguf(self.gguf)

    def test_manifest_uses_gguf_facts_and_streamed_digest(self):
        write_gguf(self.gguf, standard_entries())
        info = gm.inspect_gguf(self.gguf)
        manifest = gm.build_manifest(
            self.gguf,
            info,
            partitioning=("contiguous_layers",),
            redistribution_allowed=False,
        )
        expected_digest = hashlib.sha256(self.gguf.read_bytes()).hexdigest()
        self.assertEqual(manifest["architecture"], "qwen2")
        self.assertEqual(manifest["layer_count"], 28)
        self.assertEqual(manifest["quantizations"], ["Q4_K_M"])
        self.assertEqual(manifest["artifacts"][0]["digest"], f"sha256:{expected_digest}")
        self.assertEqual(manifest["artifacts"][0]["size_bytes"], self.gguf.stat().st_size)
        self.assertEqual(manifest["partitioning"]["allowed"], ["contiguous_layers"])
        self.assertFalse(manifest["license"]["redistribution_allowed"])
        self.assertNotIn(str(self.root), json.dumps(manifest))

    def test_generated_manifest_validates_against_repository_schema(self):
        write_gguf(self.gguf, standard_entries())
        manifest = gm.build_manifest(
            self.gguf,
            gm.inspect_gguf(self.gguf),
            partitioning=("contiguous_layers", "replica", "contiguous_layers"),
        )
        schema_path = Path(__file__).resolve().parents[3] / "protocol" / "schemas" / "model_manifest.schema.json"
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
        Draft202012Validator(schema, format_checker=FormatChecker()).validate(manifest)
        self.assertEqual(manifest["partitioning"]["allowed"], ["contiguous_layers", "replica"])

    def test_missing_semantic_metadata_requires_explicit_overrides(self):
        write_gguf(
            self.gguf,
            standard_entries(include_version=False, include_license=False, file_type=999),
        )
        info = gm.inspect_gguf(self.gguf)
        with self.assertRaisesRegex(gm.GGUFError, "model_version/general.version"):
            gm.build_manifest(self.gguf, info, partitioning=("contiguous_layers",))
        manifest = gm.build_manifest(
            self.gguf,
            info,
            model_version="manual-v1",
            license_id="LicenseRef-Manual",
            license_source="https://example.invalid/manual-license",
            quantization="CUSTOM_Q",
            partitioning=("contiguous_layers",),
        )
        self.assertEqual(manifest["model_version"], "manual-v1")
        self.assertEqual(manifest["quantizations"], ["CUSTOM_Q"])

    def test_partitioning_must_be_explicit(self):
        write_gguf(self.gguf, standard_entries())
        with self.assertRaisesRegex(gm.GGUFError, "partitioning"):
            gm.build_manifest(self.gguf, gm.inspect_gguf(self.gguf))

    def test_truncated_or_oversized_metadata_is_rejected(self):
        self.gguf.write_bytes(
            b"GGUF"
            + struct.pack("<I", 3)
            + struct.pack("<Q", 0)
            + struct.pack("<Q", 1)
            + struct.pack("<Q", 1000)
        )
        with self.assertRaisesRegex(gm.GGUFError, "beyond|truncated"):
            gm.inspect_gguf(self.gguf)

    def test_block_count_accepts_uint64(self):
        entries = standard_entries()
        entries = [
            (key, gm.TYPE_UINT64, value) if key == "qwen2.block_count" else (key, value_type, value)
            for key, value_type, value in entries
        ]
        write_gguf(self.gguf, entries)
        self.assertEqual(gm.inspect_gguf(self.gguf).block_count, 28)

    def test_primary_split_is_reported_and_manifest_build_is_rejected(self):
        write_gguf(
            self.gguf,
            standard_entries() + split_entries(0, 3, 8),
            tensor_count=3,
        )
        info = gm.inspect_gguf(self.gguf)
        self.assertEqual(info.split_no, 0)
        self.assertEqual(info.split_count, 3)
        self.assertEqual(info.split_tensors_count, 8)
        self.assertEqual(info.summary()["split_count"], 3)
        with self.assertRaisesRegex(gm.GGUFError, "split into 3 shards"):
            gm.build_manifest(self.gguf, info, partitioning=("contiguous_layers",))

    def test_non_primary_split_without_full_metadata_is_identified(self):
        write_gguf(
            self.gguf,
            split_entries(1, 3, 8),
            tensor_count=3,
        )
        with self.assertRaisesRegex(gm.GGUFError, "split shard 2/3.*split.no=0"):
            gm.inspect_gguf(self.gguf)

    def test_split_metadata_must_be_complete_and_bounded(self):
        write_gguf(
            self.gguf,
            standard_entries() + [("split.no", gm.TYPE_UINT16, 0)],
            tensor_count=1,
        )
        with self.assertRaisesRegex(gm.GGUFError, "split metadata is incomplete"):
            gm.inspect_gguf(self.gguf)

        write_gguf(
            self.gguf,
            standard_entries() + split_entries(2, 2, 3),
            tensor_count=1,
        )
        with self.assertRaisesRegex(gm.GGUFError, "split.no"):
            gm.inspect_gguf(self.gguf)

        write_gguf(
            self.gguf,
            standard_entries() + split_entries(0, 2, 1),
            tensor_count=2,
        )
        with self.assertRaisesRegex(gm.GGUFError, "tensor_count"):
            gm.inspect_gguf(self.gguf)

    def test_single_split_metadata_remains_buildable(self):
        write_gguf(
            self.gguf,
            standard_entries() + split_entries(0, 1, 3),
            tensor_count=3,
        )
        info = gm.inspect_gguf(self.gguf)
        self.assertEqual(info.split_count, 1)
        manifest = gm.build_manifest(
            self.gguf,
            info,
            partitioning=("contiguous_layers",),
        )
        self.assertEqual(manifest["layer_count"], 28)
        self.assertEqual(len(manifest["artifacts"]), 1)


if __name__ == "__main__":
    unittest.main()
