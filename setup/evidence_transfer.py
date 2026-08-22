#!/usr/bin/env python3
"""Safe local transfer helpers for the two-machine ComputeMesh M1 lab.

The archive format contains only contract-valid node-profile / benchmark JSON
records from one Lab node. It never includes model weights, llama.cpp binaries,
local config, or arbitrary files. Imports are bounded, hash-verified, traversal-
resistant and extracted atomically before being exposed to the bundle builder.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import stat
import tempfile
from typing import Any
import zipfile

from services.scheduler.evidence_bundle import (
    EvidenceBundleError,
    build_experiment_bundle,
    discover_evidence,
    select_evidence,
    write_json,
)
from services.scheduler.placement import PlacementInputError

EXPORT_SCHEMA_VERSION = 1
EXPORT_MANIFEST_NAME = "computemesh-lab-export.json"
EVIDENCE_PREFIX = "evidence"
MAX_EVIDENCE_FILES = 10_000
MAX_EVIDENCE_FILE_BYTES = 16 * 1024 * 1024
MAX_TOTAL_UNCOMPRESSED_BYTES = 256 * 1024 * 1024
MAX_ARCHIVE_BYTES = 256 * 1024 * 1024
MAX_MANIFEST_BYTES = 2 * 1024 * 1024
_EXPORT_ID_RE = re.compile(r"^lab-export-[a-f0-9]{16}$")
_SHA256_RE = re.compile(r"^sha256:[a-f0-9]{64}$")


class EvidenceTransferError(ValueError):
    pass


@dataclass(frozen=True)
class ExportResult:
    archive: Path
    export_id: str
    node_id: str
    profile_revision: int
    file_count: int


@dataclass(frozen=True)
class ImportResult:
    evidence_root: Path
    export_id: str
    node_id: str
    profile_revision: int
    file_count: int


def _utc_now(now: datetime | None = None) -> datetime:
    value = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    if value.tzinfo is None:
        raise EvidenceTransferError("timestamp must be timezone-aware")
    return value


def _canonical_json(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _validate_node_id(node_id: str) -> str:
    if not isinstance(node_id, str) or not 1 <= len(node_id) <= 128:
        raise EvidenceTransferError("node_id must be 1..128 characters")
    if not node_id.isprintable() or any(ch in node_id for ch in "/\\"):
        raise EvidenceTransferError("node_id contains unsafe path characters")
    return node_id


def _safe_relative_path(value: str) -> PurePosixPath:
    if not isinstance(value, str) or not value or len(value) > 4096:
        raise EvidenceTransferError("archive evidence path is empty or too long")
    if "\\" in value or value.startswith("/"):
        raise EvidenceTransferError(f"unsafe archive path: {value!r}")
    raw_parts = value.split("/")
    if any(part in {"", ".", ".."} for part in raw_parts):
        raise EvidenceTransferError(f"unsafe archive path: {value!r}")
    for part in raw_parts:
        if len(part) > 255 or ":" in part or not part.isprintable():
            raise EvidenceTransferError(f"archive path is not cross-platform safe: {value!r}")
    path = PurePosixPath(value)
    if path.is_absolute():
        raise EvidenceTransferError(f"unsafe archive path: {value!r}")
    return path


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _export_id(node_id: str, profile_revision: int, files: list[dict[str, Any]]) -> str:
    identity = {
        "node_id": node_id,
        "profile_revision": profile_revision,
        "files": files,
    }
    return "lab-export-" + hashlib.sha256(_canonical_json(identity)).hexdigest()[:16]


def _collect_export_files(
    node_root: Path,
    *,
    node_id: str,
    profile_revision: int,
) -> list[dict[str, Any]]:
    node_id = _validate_node_id(node_id)
    if isinstance(profile_revision, bool) or not isinstance(profile_revision, int) or profile_revision <= 0:
        raise EvidenceTransferError("capture a node profile before exporting evidence")
    try:
        resolved_root = Path(node_root).resolve(strict=True)
    except OSError as exc:
        raise EvidenceTransferError(f"cannot resolve local evidence root: {exc}") from exc
    if not resolved_root.is_dir():
        raise EvidenceTransferError("local evidence root is not a directory")

    try:
        profiles, benchmarks = discover_evidence(resolved_root)
    except EvidenceBundleError as exc:
        raise EvidenceTransferError(str(exc)) from exc
    if not profiles:
        raise EvidenceTransferError("local evidence root contains no node profile")
    profile_node_ids = {str(doc.value["node_id"]) for doc in profiles}
    if profile_node_ids != {node_id}:
        raise EvidenceTransferError(
            f"local evidence root contains unexpected node IDs: {sorted(profile_node_ids)}"
        )
    newest_revision = max(int(doc.value["profile_revision"]) for doc in profiles)
    if newest_revision != profile_revision:
        raise EvidenceTransferError(
            f"config profile_revision={profile_revision} does not match newest captured revision={newest_revision}"
        )

    documents = [*profiles, *benchmarks]
    if not documents:
        raise EvidenceTransferError("no exportable evidence documents found")
    if len(documents) > MAX_EVIDENCE_FILES:
        raise EvidenceTransferError(f"more than {MAX_EVIDENCE_FILES} evidence files")

    entries: list[dict[str, Any]] = []
    seen: set[str] = set()
    total = 0
    for doc in documents:
        if doc.path.is_symlink():
            raise EvidenceTransferError(f"evidence file must not be a symlink: {doc.path.name}")
        try:
            resolved = doc.path.resolve(strict=True)
            relative = resolved.relative_to(resolved_root).as_posix()
        except (OSError, ValueError) as exc:
            raise EvidenceTransferError(f"evidence file escapes local root: {doc.path.name}") from exc
        _safe_relative_path(relative)
        if relative in seen:
            raise EvidenceTransferError(f"duplicate evidence path: {relative}")
        seen.add(relative)
        size = resolved.stat().st_size
        if not 1 <= size <= MAX_EVIDENCE_FILE_BYTES:
            raise EvidenceTransferError(
                f"evidence file {relative} must be 1..{MAX_EVIDENCE_FILE_BYTES} bytes"
            )
        total += size
        if total > MAX_TOTAL_UNCOMPRESSED_BYTES:
            raise EvidenceTransferError("evidence export exceeds total uncompressed size limit")
        actual = _sha256_file(resolved)
        if actual != doc.sha256:
            raise EvidenceTransferError(f"evidence file changed during export scan: {relative}")
        entries.append(
            {
                "path": relative,
                "sha256": f"sha256:{actual}",
                "size_bytes": size,
            }
        )
    entries.sort(key=lambda item: item["path"])
    return entries


def _zip_write_bytes(archive: zipfile.ZipFile, name: str, data: bytes) -> None:
    info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
    info.compress_type = zipfile.ZIP_DEFLATED
    info.external_attr = (stat.S_IFREG | 0o600) << 16
    archive.writestr(info, data)


def export_node_evidence(
    *,
    node_root: Path,
    node_id: str,
    profile_revision: int,
    export_root: Path,
    destination: Path | None = None,
    now: datetime | None = None,
) -> ExportResult:
    files = _collect_export_files(
        Path(node_root),
        node_id=node_id,
        profile_revision=profile_revision,
    )
    export_id = _export_id(node_id, profile_revision, files)
    created = _utc_now(now).isoformat().replace("+00:00", "Z")
    manifest = {
        "schema_version": EXPORT_SCHEMA_VERSION,
        "export_id": export_id,
        "created_at": created,
        "node_id": node_id,
        "profile_revision": profile_revision,
        "files": files,
    }
    manifest_bytes = json.dumps(manifest, indent=2, sort_keys=True).encode("utf-8") + b"\n"
    if len(manifest_bytes) > MAX_MANIFEST_BYTES:
        raise EvidenceTransferError("export manifest exceeds size limit")

    export_root = Path(export_root)
    destination = Path(destination) if destination is not None else export_root / f"{export_id}.zip"
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.is_dir():
        raise EvidenceTransferError("export destination is a directory")

    fd, temp_name = tempfile.mkstemp(
        prefix=f".{destination.name}.",
        suffix=".tmp",
        dir=str(destination.parent),
    )
    os.close(fd)
    temp_path = Path(temp_name)
    try:
        with zipfile.ZipFile(
            temp_path,
            mode="w",
            compression=zipfile.ZIP_DEFLATED,
            compresslevel=9,
            allowZip64=False,
        ) as archive:
            _zip_write_bytes(archive, EXPORT_MANIFEST_NAME, manifest_bytes)
            resolved_root = Path(node_root).resolve(strict=True)
            for entry in files:
                source = resolved_root.joinpath(*PurePosixPath(entry["path"]).parts)
                data = source.read_bytes()
                if len(data) != int(entry["size_bytes"]):
                    raise EvidenceTransferError(f"evidence file changed during archive write: {entry['path']}")
                digest = hashlib.sha256(data).hexdigest()
                if f"sha256:{digest}" != entry["sha256"]:
                    raise EvidenceTransferError(f"evidence file changed during archive write: {entry['path']}")
                _zip_write_bytes(archive, f"{EVIDENCE_PREFIX}/{entry['path']}", data)
        if temp_path.stat().st_size > MAX_ARCHIVE_BYTES:
            raise EvidenceTransferError("compressed export archive exceeds size limit")
        os.replace(temp_path, destination)
    finally:
        if temp_path.exists():
            temp_path.unlink()

    return ExportResult(
        archive=destination.resolve(),
        export_id=export_id,
        node_id=node_id,
        profile_revision=profile_revision,
        file_count=len(files),
    )


def _validate_manifest(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise EvidenceTransferError("export manifest root must be an object")
    expected = {"schema_version", "export_id", "created_at", "node_id", "profile_revision", "files"}
    if set(value) != expected:
        raise EvidenceTransferError(
            f"export manifest keys differ from contract: {sorted(set(value) ^ expected)}"
        )
    if value["schema_version"] != EXPORT_SCHEMA_VERSION:
        raise EvidenceTransferError("unsupported export schema version")
    export_id = value["export_id"]
    if not isinstance(export_id, str) or not _EXPORT_ID_RE.fullmatch(export_id):
        raise EvidenceTransferError("invalid export_id")
    node_id = _validate_node_id(value["node_id"])
    revision = value["profile_revision"]
    if isinstance(revision, bool) or not isinstance(revision, int) or revision <= 0:
        raise EvidenceTransferError("profile_revision must be a positive integer")
    try:
        captured = datetime.fromisoformat(str(value["created_at"]).replace("Z", "+00:00"))
    except ValueError as exc:
        raise EvidenceTransferError("created_at must be RFC3339 date-time") from exc
    if captured.tzinfo is None:
        raise EvidenceTransferError("created_at must be timezone-aware")

    files = value["files"]
    if not isinstance(files, list) or not 1 <= len(files) <= MAX_EVIDENCE_FILES:
        raise EvidenceTransferError("files must be a non-empty bounded array")
    normalized: list[dict[str, Any]] = []
    seen: set[str] = set()
    total = 0
    for item in files:
        if not isinstance(item, dict) or set(item) != {"path", "sha256", "size_bytes"}:
            raise EvidenceTransferError("invalid export file record")
        path = str(_safe_relative_path(item["path"]))
        if path in seen:
            raise EvidenceTransferError(f"duplicate export file path: {path}")
        seen.add(path)
        digest = item["sha256"]
        if not isinstance(digest, str) or not _SHA256_RE.fullmatch(digest):
            raise EvidenceTransferError(f"invalid SHA-256 for {path}")
        size = item["size_bytes"]
        if isinstance(size, bool) or not isinstance(size, int) or not 1 <= size <= MAX_EVIDENCE_FILE_BYTES:
            raise EvidenceTransferError(f"invalid size for {path}")
        total += size
        if total > MAX_TOTAL_UNCOMPRESSED_BYTES:
            raise EvidenceTransferError("export exceeds total uncompressed size limit")
        normalized.append({"path": path, "sha256": digest, "size_bytes": size})
    if normalized != sorted(normalized, key=lambda item: item["path"]):
        raise EvidenceTransferError("export file records must be path-sorted")
    if _export_id(node_id, revision, normalized) != export_id:
        raise EvidenceTransferError("export_id does not match manifest contents")
    return {
        "schema_version": EXPORT_SCHEMA_VERSION,
        "export_id": export_id,
        "created_at": value["created_at"],
        "node_id": node_id,
        "profile_revision": revision,
        "files": normalized,
    }


def _zip_entry_is_symlink(info: zipfile.ZipInfo) -> bool:
    mode = (info.external_attr >> 16) & 0xFFFF
    return stat.S_IFMT(mode) == stat.S_IFLNK


def _read_archive_manifest(archive: zipfile.ZipFile) -> dict[str, Any]:
    try:
        info = archive.getinfo(EXPORT_MANIFEST_NAME)
    except KeyError as exc:
        raise EvidenceTransferError("archive is missing export manifest") from exc
    if info.flag_bits & 0x1:
        raise EvidenceTransferError("encrypted ZIP entries are not supported")
    if info.file_size > MAX_MANIFEST_BYTES:
        raise EvidenceTransferError("export manifest exceeds size limit")
    if _zip_entry_is_symlink(info):
        raise EvidenceTransferError("export manifest must not be a symlink")
    raw = archive.read(info)
    if len(raw) != info.file_size:
        raise EvidenceTransferError("export manifest size changed during read")
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise EvidenceTransferError("export manifest is not valid UTF-8 JSON") from exc
    return _validate_manifest(value)


def _validate_archive_members(
    archive: zipfile.ZipFile,
    manifest: dict[str, Any],
) -> dict[str, zipfile.ZipInfo]:
    infos = archive.infolist()
    if len(infos) > MAX_EVIDENCE_FILES + 1:
        raise EvidenceTransferError("archive contains too many entries")
    names = [info.filename for info in infos]
    if len(names) != len(set(names)):
        raise EvidenceTransferError("archive contains duplicate entry names")

    expected = {EXPORT_MANIFEST_NAME}
    expected.update(f"{EVIDENCE_PREFIX}/{item['path']}" for item in manifest["files"])
    if set(names) != expected:
        raise EvidenceTransferError("archive entries do not exactly match export manifest")

    by_name: dict[str, zipfile.ZipInfo] = {}
    manifest_sizes = {f"{EVIDENCE_PREFIX}/{item['path']}": item["size_bytes"] for item in manifest["files"]}
    total = 0
    for info in infos:
        _safe_relative_path(info.filename)
        if info.is_dir():
            raise EvidenceTransferError("archive must not contain directory entries")
        if info.flag_bits & 0x1:
            raise EvidenceTransferError("encrypted ZIP entries are not supported")
        if _zip_entry_is_symlink(info):
            raise EvidenceTransferError(f"archive contains symlink entry: {info.filename}")
        if info.filename != EXPORT_MANIFEST_NAME:
            expected_size = int(manifest_sizes[info.filename])
            if info.file_size != expected_size:
                raise EvidenceTransferError(f"archive size disagrees with manifest: {info.filename}")
            total += info.file_size
            if total > MAX_TOTAL_UNCOMPRESSED_BYTES:
                raise EvidenceTransferError("archive exceeds total uncompressed size limit")
        by_name[info.filename] = info
    return by_name


def _verify_import_tree(destination: Path, manifest: dict[str, Any]) -> None:
    manifest_path = destination / EXPORT_MANIFEST_NAME
    evidence_root = destination / EVIDENCE_PREFIX
    if not manifest_path.is_file() or not evidence_root.is_dir():
        raise EvidenceTransferError("existing import is incomplete")
    try:
        existing_manifest = _validate_manifest(json.loads(manifest_path.read_text(encoding="utf-8")))
    except (OSError, json.JSONDecodeError) as exc:
        raise EvidenceTransferError("existing import manifest is invalid") from exc
    if existing_manifest != manifest:
        raise EvidenceTransferError("existing import manifest conflicts with archive")

    expected_paths = {item["path"] for item in manifest["files"]}
    actual_paths: set[str] = set()
    for path in evidence_root.rglob("*"):
        if path.is_symlink():
            raise EvidenceTransferError("existing import contains a symlink")
        if path.is_file():
            actual_paths.add(path.relative_to(evidence_root).as_posix())
    if actual_paths != expected_paths:
        raise EvidenceTransferError("existing import files differ from manifest")
    for item in manifest["files"]:
        path = evidence_root.joinpath(*PurePosixPath(item["path"]).parts)
        if path.stat().st_size != item["size_bytes"]:
            raise EvidenceTransferError(f"existing import size mismatch: {item['path']}")
        if f"sha256:{_sha256_file(path)}" != item["sha256"]:
            raise EvidenceTransferError(f"existing import hash mismatch: {item['path']}")


def import_node_export(
    *,
    archive_path: Path,
    import_root: Path,
) -> ImportResult:
    archive_path = Path(archive_path)
    if archive_path.is_symlink():
        raise EvidenceTransferError("peer export archive must not be a symlink")
    try:
        archive_size = archive_path.stat().st_size
    except OSError as exc:
        raise EvidenceTransferError(f"cannot stat peer export archive: {exc}") from exc
    if not 1 <= archive_size <= MAX_ARCHIVE_BYTES:
        raise EvidenceTransferError("peer export archive exceeds compressed size limit")

    try:
        archive = zipfile.ZipFile(archive_path, mode="r")
    except (OSError, zipfile.BadZipFile) as exc:
        raise EvidenceTransferError("peer export is not a valid ZIP archive") from exc

    with archive:
        manifest = _read_archive_manifest(archive)
        infos = _validate_archive_members(archive, manifest)
        destination = Path(import_root) / manifest["node_id"] / manifest["export_id"]
        evidence_destination = destination / EVIDENCE_PREFIX
        if destination.exists():
            _verify_import_tree(destination, manifest)
            return ImportResult(
                evidence_root=evidence_destination.resolve(),
                export_id=manifest["export_id"],
                node_id=manifest["node_id"],
                profile_revision=manifest["profile_revision"],
                file_count=len(manifest["files"]),
            )

        destination.parent.mkdir(parents=True, exist_ok=True)
        temp_path = Path(tempfile.mkdtemp(prefix=f".{manifest['export_id']}.", dir=str(destination.parent)))
        try:
            evidence_temp = temp_path / EVIDENCE_PREFIX
            evidence_temp.mkdir(parents=True, exist_ok=True)
            for item in manifest["files"]:
                member_name = f"{EVIDENCE_PREFIX}/{item['path']}"
                info = infos[member_name]
                target = evidence_temp.joinpath(*PurePosixPath(item["path"]).parts)
                target.parent.mkdir(parents=True, exist_ok=True)
                digest = hashlib.sha256()
                written = 0
                with archive.open(info, "r") as source, target.open("xb") as sink:
                    while True:
                        chunk = source.read(1024 * 1024)
                        if not chunk:
                            break
                        written += len(chunk)
                        if written > item["size_bytes"]:
                            raise EvidenceTransferError(f"decompressed size exceeds manifest: {item['path']}")
                        digest.update(chunk)
                        sink.write(chunk)
                if written != item["size_bytes"]:
                    raise EvidenceTransferError(f"decompressed size mismatch: {item['path']}")
                if f"sha256:{digest.hexdigest()}" != item["sha256"]:
                    raise EvidenceTransferError(f"SHA-256 mismatch: {item['path']}")
            (temp_path / EXPORT_MANIFEST_NAME).write_text(
                json.dumps(manifest, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            temp_path.rename(destination)
        except Exception:
            shutil.rmtree(temp_path, ignore_errors=True)
            raise

    return ImportResult(
        evidence_root=evidence_destination.resolve(),
        export_id=manifest["export_id"],
        node_id=manifest["node_id"],
        profile_revision=manifest["profile_revision"],
        file_count=len(manifest["files"]),
    )


def build_lab_bundle(
    *,
    local_node_root: Path,
    local_node_id: str,
    peer_evidence_root: Path,
    model_manifest: Path,
    output: Path,
    artifact_digest: str | None = None,
    benchmark_model_name: str | None = None,
    network_run_id: str | None = None,
) -> Path:
    try:
        selected = select_evidence(
            coordinator_root=Path(local_node_root),
            worker_root=Path(peer_evidence_root),
            model_manifest=Path(model_manifest),
            artifact_digest=artifact_digest,
            coordinator_node_id=_validate_node_id(local_node_id),
            benchmark_model_name=benchmark_model_name,
            network_run_id=network_run_id,
        )
        bundle = build_experiment_bundle(selected)
        write_json(Path(output), bundle)
    except (EvidenceBundleError, PlacementInputError, OSError, json.JSONDecodeError, ValueError) as exc:
        raise EvidenceTransferError(str(exc)) from exc
    return Path(output).resolve()
