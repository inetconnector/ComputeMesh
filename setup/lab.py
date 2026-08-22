#!/usr/bin/env python3
"""User-facing ComputeMesh M0/M1 lab workflow helper.

This helper intentionally orchestrates only tooling that actually exists today.
It does not pretend to install the future provider-node product/runtime.
"""

from __future__ import annotations

import argparse
import json
import secrets
import subprocess
import sys
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Sequence

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from setup.evidence_transfer import (
    EvidenceTransferError,
    build_lab_bundle,
    export_node_evidence,
    import_node_export,
)

DEFAULT_OUTPUT_ROOT = REPO_ROOT / "artifacts" / "lab"
DEFAULT_CONFIG = DEFAULT_OUTPUT_ROOT / "config.json"


@dataclass
class LabConfig:
    node_id: str
    profile_revision: int = 0
    llama_bench: str | None = None
    model_path: str | None = None


def _utc_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%SZ")


def new_node_id() -> str:
    return f"lab-{secrets.token_hex(4)}"


def load_config(path: Path = DEFAULT_CONFIG) -> LabConfig:
    if not path.exists():
        return LabConfig(node_id=new_node_id())
    raw = json.loads(path.read_text(encoding="utf-8"))
    return LabConfig(
        node_id=str(raw["node_id"]),
        profile_revision=int(raw.get("profile_revision", 0)),
        llama_bench=raw.get("llama_bench"),
        model_path=raw.get("model_path"),
    )


def save_config(config: LabConfig, path: Path = DEFAULT_CONFIG) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(asdict(config), indent=2, sort_keys=True) + "\n", encoding="utf-8")


def run_dir(output_root: Path, config: LabConfig, kind: str) -> Path:
    return output_root / config.node_id / f"{_utc_stamp()}-{kind}"


def _run(command: Sequence[str], *, runner: Callable[..., subprocess.CompletedProcess] = subprocess.run) -> None:
    runner(list(command), cwd=REPO_ROOT, check=True)


def capture_inventory(
    config: LabConfig,
    config_path: Path,
    output_root: Path,
    *,
    runner: Callable[..., subprocess.CompletedProcess] = subprocess.run,
) -> Path:
    revision = config.profile_revision + 1
    output = run_dir(output_root, config, "inventory")
    command = [
        sys.executable,
        str(REPO_ROOT / "tools" / "benchmark" / "benchmark.py"),
        "--node-id",
        config.node_id,
        "--profile-revision",
        str(revision),
        "--output-dir",
        str(output),
    ]
    _run(command, runner=runner)
    config.profile_revision = revision
    save_config(config, config_path)
    return output


def ensure_profile(config: LabConfig, config_path: Path, output_root: Path) -> None:
    if config.profile_revision == 0:
        capture_inventory(config, config_path, output_root)


def network_server(config: LabConfig, bind: str, port: int, *, runner=subprocess.run) -> None:
    command = [
        sys.executable,
        str(REPO_ROOT / "tools" / "benchmark" / "network_benchmark.py"),
        "server",
        "--bind",
        bind,
        "--port",
        str(port),
        "--node-id",
        config.node_id,
        "--once",
    ]
    _run(command, runner=runner)


def network_client(
    config: LabConfig,
    host: str,
    port: int,
    output_root: Path,
    *,
    expected_peer_node_id: str | None = None,
    runner=subprocess.run,
) -> Path:
    if config.profile_revision <= 0:
        raise RuntimeError("capture a node profile before running the network client")
    output = run_dir(output_root, config, "network")
    command = [
        sys.executable,
        str(REPO_ROOT / "tools" / "benchmark" / "network_benchmark.py"),
        "client",
        "--host",
        host,
        "--port",
        str(port),
        "--profile-revision",
        str(config.profile_revision),
        "--local-node-id",
        config.node_id,
        "--output-dir",
        str(output),
    ]
    if expected_peer_node_id:
        command.extend(["--expected-peer-node-id", expected_peer_node_id])
    _run(command, runner=runner)
    return output


def llama_benchmark(
    config: LabConfig,
    config_path: Path,
    executable: str,
    model: str,
    output_root: Path,
    *,
    runner=subprocess.run,
) -> Path:
    if config.profile_revision <= 0:
        raise RuntimeError("capture a node profile before running llama-bench")
    output = run_dir(output_root, config, "llama")
    command = [
        sys.executable,
        str(REPO_ROOT / "tools" / "benchmark" / "llama_bench_adapter.py"),
        "--llama-bench",
        executable,
        "--model",
        model,
        "--profile-revision",
        str(config.profile_revision),
        "--output-dir",
        str(output),
    ]
    _run(command, runner=runner)
    config.llama_bench = str(Path(executable).resolve())
    config.model_path = str(Path(model).resolve())
    save_config(config, config_path)
    return output


def export_evidence(config: LabConfig, output_root: Path, archive: Path | None = None):
    return export_node_evidence(
        node_root=Path(output_root) / config.node_id,
        node_id=config.node_id,
        profile_revision=config.profile_revision,
        export_root=Path(output_root) / "exports",
        destination=archive,
    )


def import_evidence(archive: Path, output_root: Path):
    return import_node_export(
        archive_path=archive,
        import_root=Path(output_root) / "imports",
    )


def build_bundle(
    config: LabConfig,
    output_root: Path,
    *,
    peer_export: Path | None,
    peer_root: Path | None,
    model_manifest: Path,
    output: Path | None,
    artifact_digest: str | None = None,
    benchmark_model_name: str | None = None,
    network_run_id: str | None = None,
) -> tuple[Path, object | None]:
    imported = None
    if peer_export is not None:
        imported = import_evidence(peer_export, output_root)
        resolved_peer_root = imported.evidence_root
    elif peer_root is not None:
        resolved_peer_root = Path(peer_root)
    else:
        raise EvidenceTransferError("peer export or peer evidence root is required")
    bundle_output = Path(output) if output is not None else run_dir(output_root, config, "bundle") / "experiment_bundle.json"
    result = build_lab_bundle(
        local_node_root=Path(output_root) / config.node_id,
        local_node_id=config.node_id,
        peer_evidence_root=resolved_peer_root,
        model_manifest=model_manifest,
        output=bundle_output,
        artifact_digest=artifact_digest,
        benchmark_model_name=benchmark_model_name,
        network_run_id=network_run_id,
    )
    return result, imported


def run_tests(*, runner=subprocess.run) -> None:
    commands = [
        [sys.executable, "-m", "unittest", "discover", "-s", "tools/benchmark/tests", "-v"],
        [sys.executable, "-m", "unittest", "discover", "-s", "services/orchestrator/tests", "-v"],
        [sys.executable, "-m", "unittest", "discover", "-s", "protocol/tests", "-v"],
        [sys.executable, "-m", "unittest", "discover", "-s", "services/identity/tests", "-v"],
        [sys.executable, "-m", "unittest", "discover", "-s", "services/scheduler/tests", "-v"],
        [sys.executable, "-m", "unittest", "discover", "-s", "runtime/llama/tests", "-v"],
        [sys.executable, "-m", "unittest", "discover", "-s", "runtime/network/tests", "-v"],
        [sys.executable, "-m", "unittest", "discover", "-s", "tools/appliance/tests", "-v"],
        [sys.executable, "-m", "unittest", "discover", "-s", "services/appliance_dashboard/tests", "-v"],
        [sys.executable, "-m", "unittest", "discover", "-s", "services/portal/tests", "-v"],
        [sys.executable, "-m", "unittest", "discover", "-s", "services/billing/tests", "-v"],
        [sys.executable, "-m", "unittest", "discover", "-s", "services/gateway/tests", "-v"],
        [sys.executable, "-m", "unittest", "discover", "-s", "setup/tests", "-v"],
    ]
    for command in commands:
        _run(command, runner=runner)


def emit_result(
    kind: str,
    config: LabConfig,
    path: Path | None = None,
    *,
    extra: dict[str, object] | None = None,
) -> None:
    result: dict[str, object] = {
        "kind": kind,
        "node_id": config.node_id,
        "profile_revision": config.profile_revision,
    }
    if path is not None:
        result["path"] = str(path.resolve())
    if kind == "status":
        result["llama_bench"] = config.llama_bench
        result["model_path"] = config.model_path
    if extra:
        result.update(extra)
    print(json.dumps(result, sort_keys=True))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="ComputeMesh M0/M1 lab workflow helper")
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT_ROOT)
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("status")
    sub.add_parser("inventory")

    server = sub.add_parser("network-server")
    server.add_argument("--bind", required=True)
    server.add_argument("--port", type=int, default=43191)

    client = sub.add_parser("network-client")
    client.add_argument("--host", required=True)
    client.add_argument("--port", type=int, default=43191)
    client.add_argument("--expected-peer-node-id")

    llama = sub.add_parser("llama")
    llama.add_argument("--llama-bench", required=True)
    llama.add_argument("--model", required=True)

    export_parser = sub.add_parser("export", help="Create a bounded ZIP containing this node's evidence JSON")
    export_parser.add_argument("--archive", type=Path)

    import_parser = sub.add_parser("import", help="Validate and atomically import a peer evidence ZIP")
    import_parser.add_argument("--archive", type=Path, required=True)

    bundle_parser = sub.add_parser("bundle", help="Build a current two-node experiment bundle")
    peer = bundle_parser.add_mutually_exclusive_group(required=True)
    peer.add_argument("--peer-export", type=Path)
    peer.add_argument("--peer-root", type=Path)
    bundle_parser.add_argument("--model-manifest", type=Path, required=True)
    bundle_parser.add_argument("--artifact-digest")
    bundle_parser.add_argument("--benchmark-model-name")
    bundle_parser.add_argument("--network-run-id")
    bundle_parser.add_argument("--output", type=Path)

    sub.add_parser("tests")
    args = parser.parse_args(argv)

    config = load_config(args.config)
    if not args.config.exists():
        save_config(config, args.config)

    if args.command == "status":
        emit_result("status", config)
        return 0
    if args.command == "inventory":
        output = capture_inventory(config, args.config, args.output_root)
        emit_result("inventory", config, output)
        return 0
    if args.command == "network-server":
        ensure_profile(config, args.config, args.output_root)
        network_server(config, args.bind, args.port)
        emit_result("network-server", config)
        return 0
    if args.command == "network-client":
        ensure_profile(config, args.config, args.output_root)
        output = network_client(
            config,
            args.host,
            args.port,
            args.output_root,
            expected_peer_node_id=args.expected_peer_node_id,
        )
        emit_result("network-client", config, output)
        return 0
    if args.command == "llama":
        ensure_profile(config, args.config, args.output_root)
        output = llama_benchmark(config, args.config, args.llama_bench, args.model, args.output_root)
        emit_result("llama", config, output)
        return 0
    try:
        if args.command == "export":
            exported = export_evidence(config, args.output_root, args.archive)
            emit_result(
                "export",
                config,
                exported.archive,
                extra={"export_id": exported.export_id, "file_count": exported.file_count},
            )
            return 0
        if args.command == "import":
            imported = import_evidence(args.archive, args.output_root)
            emit_result(
                "import",
                config,
                imported.evidence_root,
                extra={
                    "peer_node_id": imported.node_id,
                    "peer_profile_revision": imported.profile_revision,
                    "export_id": imported.export_id,
                    "file_count": imported.file_count,
                },
            )
            return 0
        if args.command == "bundle":
            output, imported = build_bundle(
                config,
                args.output_root,
                peer_export=args.peer_export,
                peer_root=args.peer_root,
                model_manifest=args.model_manifest,
                output=args.output,
                artifact_digest=args.artifact_digest,
                benchmark_model_name=args.benchmark_model_name,
                network_run_id=args.network_run_id,
            )
            extra: dict[str, object] = {}
            if imported is not None:
                extra.update({"peer_node_id": imported.node_id, "peer_export_id": imported.export_id})
            emit_result("bundle", config, output, extra=extra)
            return 0
    except EvidenceTransferError as exc:
        parser.error(str(exc))
    if args.command == "tests":
        run_tests()
        emit_result("tests", config)
        return 0
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
