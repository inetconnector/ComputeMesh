#!/usr/bin/env python3
"""Build a conservative ComputeMesh model manifest from a GGUF artifact.

The parser intentionally reads only the GGUF v3 header/metadata area needed for
identity and placement bookkeeping. It never loads tensor data into memory.
Model/license/partitioning facts that cannot be established from standardized
GGUF metadata must be supplied explicitly instead of guessed.

GGUF split metadata is recognized explicitly. ComputeMesh schema v1 does not
yet encode shard identity/order strongly enough to represent a multi-file GGUF
as one model artifact set, so this tool refuses to build a manifest from one
shard of a multi-shard model rather than silently hashing only part of it.
"""
from __future__ import annotations

import argparse
from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import re
import struct
from typing import Any, BinaryIO

GGUF_MAGIC = b"GGUF"
GGUF_VERSION = 3
MAX_METADATA_KV = 1_000_000
MAX_KEY_BYTES = 65_535
MAX_STRING_BYTES = 16 * 1024 * 1024
MAX_ARRAY_ITEMS = 2_000_000
MAX_ARRAY_DEPTH = 8
MAX_METADATA_BYTES = 512 * 1024 * 1024
HASH_CHUNK_BYTES = 4 * 1024 * 1024

TYPE_UINT8 = 0
TYPE_INT8 = 1
TYPE_UINT16 = 2
TYPE_INT16 = 3
TYPE_UINT32 = 4
TYPE_INT32 = 5
TYPE_FLOAT32 = 6
TYPE_BOOL = 7
TYPE_STRING = 8
TYPE_ARRAY = 9
TYPE_UINT64 = 10
TYPE_INT64 = 11
TYPE_FLOAT64 = 12

FIXED_TYPES: dict[int, tuple[str, int]] = {
    TYPE_UINT8: ("B", 1),
    TYPE_INT8: ("b", 1),
    TYPE_UINT16: ("H", 2),
    TYPE_INT16: ("h", 2),
    TYPE_UINT32: ("I", 4),
    TYPE_INT32: ("i", 4),
    TYPE_FLOAT32: ("f", 4),
    TYPE_BOOL: ("B", 1),
    TYPE_UINT64: ("Q", 8),
    TYPE_INT64: ("q", 8),
    TYPE_FLOAT64: ("d", 8),
}

# Standardized general.file_type values documented by GGUF for the common
# classic/K-quants. Removed historical types are intentionally not inferred.
FILE_TYPE_NAMES = {
    0: "F32",
    1: "F16",
    2: "Q4_0",
    3: "Q4_1",
    4: "Q4_1_SOME_F16",
    7: "Q8_0",
    8: "Q5_0",
    9: "Q5_1",
    10: "Q2_K",
    11: "Q3_K_S",
    12: "Q3_K_M",
    13: "Q3_K_L",
    14: "Q4_K_S",
    15: "Q4_K_M",
    16: "Q5_K_S",
    17: "Q5_K_M",
    18: "Q6_K",
}

GENERAL_KEYS = {
    "general.architecture",
    "general.name",
    "general.version",
    "general.license",
    "general.license.link",
    "general.file_type",
}
SPLIT_KEYS = {
    "split.no",
    "split.count",
    "split.tensors.count",
}


class GGUFError(ValueError):
    pass


@dataclass(frozen=True)
class GGUFInfo:
    version: int
    tensor_count: int
    metadata_kv_count: int
    architecture: str
    block_count: int
    name: str | None
    model_version: str | None
    license_id: str | None
    license_source: str | None
    file_type: int | None
    split_no: int | None
    split_count: int | None
    split_tensors_count: int | None

    def summary(self) -> dict[str, Any]:
        return {
            "gguf_version": self.version,
            "tensor_count": self.tensor_count,
            "metadata_kv_count": self.metadata_kv_count,
            "architecture": self.architecture,
            "layer_count": self.block_count,
            "name": self.name,
            "model_version": self.model_version,
            "license_id": self.license_id,
            "license_source": self.license_source,
            "file_type": self.file_type,
            "quantization": FILE_TYPE_NAMES.get(self.file_type),
            "split_no": self.split_no,
            "split_count": self.split_count,
            "split_tensors_count": self.split_tensors_count,
        }


class _Reader:
    def __init__(self, handle: BinaryIO, file_size: int):
        self.handle = handle
        self.file_size = file_size
        self.metadata_start = 0

    def tell(self) -> int:
        return int(self.handle.tell())

    def _read(self, size: int) -> bytes:
        if size < 0 or self.tell() + size > self.file_size:
            raise GGUFError("GGUF metadata is truncated or declares data beyond the file")
        data = self.handle.read(size)
        if len(data) != size:
            raise GGUFError("GGUF metadata is truncated")
        return data

    def unpack(self, fmt: str) -> Any:
        size = struct.calcsize("<" + fmt)
        return struct.unpack("<" + fmt, self._read(size))[0]

    def u32(self) -> int:
        return int(self.unpack("I"))

    def u64(self) -> int:
        return int(self.unpack("Q"))

    def string(self, *, key: bool = False) -> str:
        length = self.u64()
        maximum = MAX_KEY_BYTES if key else MAX_STRING_BYTES
        if length > maximum:
            label = "metadata key" if key else "metadata string"
            raise GGUFError(f"{label} exceeds bounded parser limit")
        raw = self._read(length)
        try:
            value = raw.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise GGUFError("GGUF metadata string is not valid UTF-8") from exc
        if key:
            try:
                raw.decode("ascii")
            except UnicodeDecodeError as exc:
                raise GGUFError("GGUF metadata key is not ASCII") from exc
        return value

    def skip(self, size: int) -> None:
        if size < 0 or self.tell() + size > self.file_size:
            raise GGUFError("GGUF metadata value extends beyond the file")
        self.handle.seek(size, os.SEEK_CUR)

    def check_metadata_budget(self) -> None:
        if self.tell() - self.metadata_start > MAX_METADATA_BYTES:
            raise GGUFError("GGUF metadata area exceeds bounded parser limit")

    def scalar(self, value_type: int) -> Any:
        if value_type == TYPE_STRING:
            return self.string()
        entry = FIXED_TYPES.get(value_type)
        if entry is None or value_type == TYPE_ARRAY:
            raise GGUFError("required GGUF metadata value is not a supported scalar")
        fmt, _ = entry
        value = self.unpack(fmt)
        if value_type == TYPE_BOOL:
            if value not in (0, 1):
                raise GGUFError("GGUF boolean metadata must be encoded as 0 or 1")
            return bool(value)
        return value

    def skip_value(self, value_type: int, *, depth: int = 0) -> None:
        if depth > MAX_ARRAY_DEPTH:
            raise GGUFError("GGUF metadata arrays exceed maximum nesting depth")
        if value_type == TYPE_STRING:
            length = self.u64()
            if length > MAX_STRING_BYTES:
                raise GGUFError("GGUF metadata string exceeds bounded parser limit")
            self.skip(length)
            return
        if value_type == TYPE_ARRAY:
            element_type = self.u32()
            count = self.u64()
            if count > MAX_ARRAY_ITEMS:
                raise GGUFError("GGUF metadata array exceeds bounded parser item limit")
            if element_type in FIXED_TYPES:
                self.skip(count * FIXED_TYPES[element_type][1])
                return
            if element_type not in (TYPE_STRING, TYPE_ARRAY):
                raise GGUFError(f"unknown GGUF metadata array element type {element_type}")
            for _ in range(count):
                self.skip_value(element_type, depth=depth + 1)
            return
        entry = FIXED_TYPES.get(value_type)
        if entry is None:
            raise GGUFError(f"unknown GGUF metadata value type {value_type}")
        self.skip(entry[1])


def _validate_split_metadata(
    captured: dict[str, Any],
    *,
    tensor_count: int,
) -> tuple[int | None, int | None, int | None]:
    present = [key in captured for key in SPLIT_KEYS]
    if any(present) and not all(present):
        raise GGUFError(
            "GGUF split metadata is incomplete; split.no, split.count, and split.tensors.count must appear together"
        )
    if not any(present):
        return None, None, None

    values: dict[str, int] = {}
    for key in SPLIT_KEYS:
        value = captured[key]
        if isinstance(value, bool) or not isinstance(value, int):
            raise GGUFError(f"{key} must be an integer")
        values[key] = int(value)

    split_no = values["split.no"]
    split_count = values["split.count"]
    split_tensors_count = values["split.tensors.count"]
    if not 1 <= split_count <= 65_535:
        raise GGUFError("split.count must be between 1 and 65535")
    if not 0 <= split_no < split_count:
        raise GGUFError("split.no must be zero-based and smaller than split.count")
    if split_tensors_count < 1:
        raise GGUFError("split.tensors.count must be positive")
    if tensor_count > split_tensors_count:
        raise GGUFError("shard tensor_count cannot exceed split.tensors.count")
    if split_count == 1 and tensor_count != split_tensors_count:
        raise GGUFError("single-split GGUF tensor_count must equal split.tensors.count")
    return split_no, split_count, split_tensors_count


def inspect_gguf(path: Path) -> GGUFInfo:
    path = Path(path)
    try:
        file_size = path.stat().st_size
    except OSError as exc:
        raise GGUFError(f"cannot stat GGUF file: {exc}") from exc
    if file_size < 24:
        raise GGUFError("file is too small to be a GGUF v3 artifact")

    captured: dict[str, Any] = {}
    block_counts: dict[str, int] = {}
    try:
        with path.open("rb") as handle:
            reader = _Reader(handle, file_size)
            if reader._read(4) != GGUF_MAGIC:
                raise GGUFError("file magic is not GGUF")
            version = reader.u32()
            if version != GGUF_VERSION:
                raise GGUFError(
                    f"unsupported GGUF version {version}; this bounded parser currently requires v{GGUF_VERSION}"
                )
            tensor_count = reader.u64()
            metadata_count = reader.u64()
            if metadata_count > MAX_METADATA_KV:
                raise GGUFError("GGUF metadata key/value count exceeds bounded parser limit")
            reader.metadata_start = reader.tell()

            for _ in range(metadata_count):
                key = reader.string(key=True)
                value_type = reader.u32()
                interesting = key in GENERAL_KEYS or key in SPLIT_KEYS or key.endswith(".block_count")
                if interesting:
                    value = reader.scalar(value_type)
                    if key.endswith(".block_count"):
                        if isinstance(value, bool) or not isinstance(value, int):
                            raise GGUFError(f"{key} must be an integer")
                        block_counts[key] = int(value)
                    else:
                        captured[key] = value
                else:
                    reader.skip_value(value_type)
                reader.check_metadata_budget()
    except OSError as exc:
        raise GGUFError(f"cannot read GGUF file: {exc}") from exc

    split_no, split_count, split_tensors_count = _validate_split_metadata(
        captured,
        tensor_count=tensor_count,
    )

    architecture = captured.get("general.architecture")
    if not isinstance(architecture, str) or not re.fullmatch(r"[a-z0-9]+", architecture):
        if split_no is not None and split_no > 0:
            raise GGUFError(
                f"GGUF split shard {split_no + 1}/{split_count} does not carry full model metadata; "
                "inspect/build from the primary shard with split.no=0"
            )
        raise GGUFError("GGUF is missing a valid general.architecture")
    block_key = f"{architecture}.block_count"
    block_count = block_counts.get(block_key)
    if block_count is None:
        if split_no is not None and split_no > 0:
            raise GGUFError(
                f"GGUF split shard {split_no + 1}/{split_count} does not carry required {block_key}; "
                "inspect/build from the primary shard with split.no=0"
            )
        raise GGUFError(f"GGUF is missing required {block_key}")
    if not 2 <= block_count <= 100_000:
        raise GGUFError(f"{block_key} must be between 2 and 100000 for the M1 manifest")

    file_type = captured.get("general.file_type")
    if file_type is not None and (isinstance(file_type, bool) or not isinstance(file_type, int)):
        raise GGUFError("general.file_type must be an integer when present")

    def optional_string(key: str) -> str | None:
        value = captured.get(key)
        if value is None:
            return None
        if not isinstance(value, str) or not value.strip():
            raise GGUFError(f"{key} must be a non-empty string when present")
        return value.strip()

    return GGUFInfo(
        version=version,
        tensor_count=tensor_count,
        metadata_kv_count=metadata_count,
        architecture=architecture,
        block_count=block_count,
        name=optional_string("general.name"),
        model_version=optional_string("general.version"),
        license_id=optional_string("general.license"),
        license_source=optional_string("general.license.link"),
        file_type=int(file_type) if file_type is not None else None,
        split_no=split_no,
        split_count=split_count,
        split_tensors_count=split_tensors_count,
    )


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    try:
        with Path(path).open("rb") as handle:
            while True:
                chunk = handle.read(HASH_CHUNK_BYTES)
                if not chunk:
                    break
                digest.update(chunk)
    except OSError as exc:
        raise GGUFError(f"cannot hash GGUF file: {exc}") from exc
    return digest.hexdigest()


def build_manifest(
    path: Path,
    info: GGUFInfo,
    *,
    model_id: str | None = None,
    model_version: str | None = None,
    license_id: str | None = None,
    license_source: str | None = None,
    quantization: str | None = None,
    partitioning: tuple[str, ...] = (),
    runtime_min_version: str | None = None,
    redistribution_allowed: bool | None = None,
) -> dict[str, Any]:
    if info.split_count is not None and info.split_count > 1:
        raise GGUFError(
            f"GGUF is split into {info.split_count} shards; refusing to build a schema-v1 manifest from only "
            "one shard because its digest/size would not represent the complete model. Merge the shard set to "
            "one GGUF before building a ComputeMesh manifest."
        )

    resolved_model_id = (model_id or info.name or "").strip()
    resolved_model_version = (model_version or info.model_version or "").strip()
    resolved_license_id = (license_id or info.license_id or "").strip()
    resolved_license_source = (license_source or info.license_source or "").strip()
    resolved_quantization = (quantization or FILE_TYPE_NAMES.get(info.file_type) or "").strip()

    missing = []
    for name, value in (
        ("model_id/general.name", resolved_model_id),
        ("model_version/general.version", resolved_model_version),
        ("license_id/general.license", resolved_license_id),
        ("license_source/general.license.link", resolved_license_source),
        ("quantization/general.file_type", resolved_quantization),
    ):
        if not value:
            missing.append(name)
    if missing:
        raise GGUFError(
            "cannot build manifest without explicit or GGUF metadata for: " + ", ".join(missing)
        )
    if not partitioning:
        raise GGUFError("at least one explicit partitioning mode is required")
    allowed_partitioning = {"contiguous_layers", "experts", "replica"}
    if any(mode not in allowed_partitioning for mode in partitioning):
        raise GGUFError("unknown partitioning mode")
    unique_partitioning = list(dict.fromkeys(partitioning))

    license_record: dict[str, Any] = {
        "id": resolved_license_id,
        "source": resolved_license_source,
    }
    if redistribution_allowed is not None:
        license_record["redistribution_allowed"] = redistribution_allowed

    runtime: dict[str, Any] = {"runtime": "llama.cpp"}
    if runtime_min_version:
        runtime["min_version"] = runtime_min_version.strip()

    size = Path(path).stat().st_size
    digest = sha256_file(path)
    return {
        "schema_version": 1,
        "model_id": resolved_model_id,
        "model_version": resolved_model_version,
        "architecture": info.architecture,
        "layer_count": info.block_count,
        "license": license_record,
        "runtime_compatibility": [runtime],
        "quantizations": [resolved_quantization],
        "partitioning": {"allowed": unique_partitioning},
        "artifacts": [{
            "digest": f"sha256:{digest}",
            "size_bytes": size,
            "media_type": "application/x-gguf",
        }],
    }


def write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Inspect GGUF v3 metadata or build a conservative ComputeMesh model manifest"
    )
    sub = parser.add_subparsers(dest="command", required=True)

    inspect_cmd = sub.add_parser("inspect", help="print bounded GGUF metadata used by ComputeMesh")
    inspect_cmd.add_argument("--gguf", type=Path, required=True)

    build_cmd = sub.add_parser("build", help="build model_manifest.schema.json-compatible JSON")
    build_cmd.add_argument("--gguf", type=Path, required=True)
    build_cmd.add_argument("--model-id")
    build_cmd.add_argument("--model-version")
    build_cmd.add_argument("--license-id")
    build_cmd.add_argument("--license-source")
    build_cmd.add_argument("--quantization")
    build_cmd.add_argument(
        "--partitioning",
        action="append",
        choices=("contiguous_layers", "experts", "replica"),
        required=True,
        help="explicitly allowed model partitioning mode; repeat as needed",
    )
    build_cmd.add_argument("--runtime-min-version")
    redistribution = build_cmd.add_mutually_exclusive_group()
    redistribution.add_argument("--redistribution-allowed", action="store_true")
    redistribution.add_argument("--redistribution-disallowed", action="store_true")
    build_cmd.add_argument("--output", type=Path)
    build_cmd.add_argument("--dry-run", action="store_true")

    args = parser.parse_args(argv)
    try:
        info = inspect_gguf(args.gguf)
        if args.command == "inspect":
            print(json.dumps(info.summary(), indent=2, sort_keys=True))
            return 0

        redistribution_allowed: bool | None = None
        if args.redistribution_allowed:
            redistribution_allowed = True
        elif args.redistribution_disallowed:
            redistribution_allowed = False
        manifest = build_manifest(
            args.gguf,
            info,
            model_id=args.model_id,
            model_version=args.model_version,
            license_id=args.license_id,
            license_source=args.license_source,
            quantization=args.quantization,
            partitioning=tuple(args.partitioning),
            runtime_min_version=args.runtime_min_version,
            redistribution_allowed=redistribution_allowed,
        )
    except (OSError, GGUFError) as exc:
        parser.error(str(exc))

    if args.dry_run:
        print(json.dumps(manifest, indent=2, sort_keys=True))
        return 0
    output = args.output or args.gguf.with_suffix(".computemesh-model-manifest.json")
    write_json(output, manifest)
    print(output.resolve())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())