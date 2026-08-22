#!/usr/bin/env python3
"""Run the narrow M1 two-node llama.cpp proof from one coordinator command.

The runner consumes an already validated experiment bundle, verifies the exact
local GGUF, preflights current llama-server RPC visibility, runs a deterministic
local baseline, runs the planner-selected shared split through the measurement
relay, compares correctness, and finally builds shared_run_evidence.json.

It remains trusted-private-lab tooling. It does not authenticate upstream RPC.
"""
from __future__ import annotations

import argparse
from collections import deque
from dataclasses import dataclass
from datetime import datetime, timezone
import json
import math
from pathlib import Path
import queue
import re
import subprocess
import sys
import threading
import time
from typing import Any, Callable, Sequence

from jsonschema import Draft202012Validator, FormatChecker

from runtime.llama.rpc_spike import (
    RpcEndpoint,
    SpikePlan,
    compare_results,
    parse_runtime_build_identity,
    run_spike,
    runtime_build_matches,
    runtime_version,
    sha256_file,
)
from runtime.llama.shared_run_evidence import write_shared_run_evidence
from services.scheduler.placement import PlannerPolicy

ROOT = Path(__file__).resolve().parents[2]
BUNDLE_SCHEMA = ROOT / "services" / "scheduler" / "experiment_bundle.schema.json"
PLACEMENT_SCHEMA = ROOT / "services" / "scheduler" / "placement_decision.schema.json"
MAX_JSON_BYTES = 4 * 1024 * 1024
MAX_DISCOVERY_OUTPUT_BYTES = 1024 * 1024
MAX_FAILURE_MESSAGE = 1024
DEVICE_NAME = re.compile(r"^[A-Za-z][A-Za-z0-9_.-]{0,63}$")


class SharedTrialError(RuntimeError):
    """Raised when the one-command physical proof cannot proceed safely."""


@dataclass(frozen=True)
class DeviceInfo:
    name: str
    description: str


@dataclass(frozen=True)
class TrialPlan:
    bundle_id: str
    placement_decision_id: str
    coordinator_node_id: str
    worker_node_id: str
    coordinator_kind: str
    coordinator_name: str
    llama_build_commit: str
    llama_build_number: int
    model_basename: str
    model_size_bytes: int
    model_sha256: str
    tensor_split: tuple[float, float]
    layer_ranges: tuple[dict[str, Any], dict[str, Any]]


def _reject_constant(value: str) -> None:
    raise ValueError(f"non-finite JSON number is forbidden: {value}")


def _schema(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise SharedTrialError(f"invalid repository schema: {path.name}")
    return value


def _validate(value: dict[str, Any], path: Path, label: str) -> None:
    validator = Draft202012Validator(_schema(path), format_checker=FormatChecker())
    errors = sorted(validator.iter_errors(value), key=lambda error: list(error.absolute_path))
    if errors:
        first = errors[0]
        where = ".".join(str(part) for part in first.absolute_path) or "<root>"
        raise SharedTrialError(f"{label} failed schema validation at {where}: {first.message}")


def _read_bundle(path: Path) -> dict[str, Any]:
    if path.is_symlink() or not path.is_file():
        raise SharedTrialError("experiment bundle must be an existing non-symlink file")
    size = path.stat().st_size
    if not 0 < size <= MAX_JSON_BYTES:
        raise SharedTrialError(f"experiment bundle must be 1..{MAX_JSON_BYTES} bytes")
    try:
        value = json.loads(path.read_text(encoding="utf-8"), parse_constant=_reject_constant)
    except (UnicodeError, json.JSONDecodeError, ValueError) as exc:
        raise SharedTrialError("experiment bundle must contain strict finite UTF-8 JSON") from exc
    if not isinstance(value, dict):
        raise SharedTrialError("experiment bundle must contain a JSON object")
    _validate(value, BUNDLE_SCHEMA, "experiment bundle")
    _validate(value["placement_decision"], PLACEMENT_SCHEMA, "placement decision")
    return value


def _parse_time(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise SharedTrialError("bundle captured_at is invalid") from exc
    if parsed.tzinfo is None:
        raise SharedTrialError("bundle captured_at must include a timezone")
    return parsed.astimezone(timezone.utc)


def _current_profile_age_ok(bundle: dict[str, Any], now: datetime) -> None:
    policy = PlannerPolicy()
    captured = _parse_time(bundle["captured_at"])
    elapsed_hours = (now - captured).total_seconds() / 3600.0
    if elapsed_hours < -(policy.max_future_skew_minutes / 60.0):
        raise SharedTrialError("experiment bundle timestamp is too far in the future")
    elapsed_hours = max(0.0, elapsed_hours)
    for role in ("coordinator", "worker"):
        recorded = float(bundle["placement_decision"]["nodes"][role]["profile_age_hours"])
        if recorded + elapsed_hours > policy.max_profile_age_hours:
            raise SharedTrialError(
                f"{role} profile is now older than the {policy.max_profile_age_hours:g} hour planner limit; rebuild fresh evidence"
            )


def _selected_candidate(bundle: dict[str, Any]) -> dict[str, Any]:
    placement = bundle["placement_decision"]
    if placement["recommendation"]["mode"] != "shared_experiment":
        raise SharedTrialError("bundle does not recommend shared_experiment; do not force a shared split")
    matches = [
        candidate
        for candidate in placement["candidates"]
        if candidate.get("mode") == "shared_contiguous_layers" and candidate.get("feasible") is True
    ]
    if len(matches) != 1:
        raise SharedTrialError("bundle must contain exactly one feasible shared_contiguous_layers candidate")
    candidate = matches[0]
    split = candidate.get("tensor_split")
    if not isinstance(split, list) or len(split) != 2:
        raise SharedTrialError("planner-selected shared split must contain exactly two entries")
    if any(
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(float(value))
        or float(value) <= 0
        for value in split
    ):
        raise SharedTrialError("planner-selected tensor_split entries must be finite positive numbers")
    return candidate


def load_trial_plan(bundle_path: Path, model_path: Path, *, now: datetime | None = None) -> TrialPlan:
    bundle = _read_bundle(bundle_path)
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        raise ValueError("now must be timezone-aware")
    _current_profile_age_ok(bundle, current.astimezone(timezone.utc))
    candidate = _selected_candidate(bundle)
    placement = bundle["placement_decision"]
    coordinator = placement["nodes"]["coordinator"]
    worker = placement["nodes"]["worker"]
    if coordinator["kind"] == "cpu":
        raise SharedTrialError(
            "one-command shared trial currently requires an accelerator-backed coordinator; "
            "local CPU + RPC tensor-split is not represented safely by this M1 runner"
        )
    ranges = candidate["layer_ranges"]
    if len(ranges) != 2 or ranges[0]["node_id"] != coordinator["node_id"] or ranges[1]["node_id"] != worker["node_id"]:
        raise SharedTrialError("planner layer ranges are not ordered coordinator then worker")

    if model_path.is_symlink() or not model_path.is_file():
        raise SharedTrialError("model must be an existing non-symlink GGUF file")
    model = placement["model"]
    if model_path.name != bundle["benchmark_model_name"]:
        raise SharedTrialError("local model basename does not match experiment bundle")
    if model_path.stat().st_size != int(model["artifact_size_bytes"]):
        raise SharedTrialError("local model byte size does not match experiment bundle")
    digest = sha256_file(model_path)
    expected = model["artifact_digest"].removeprefix("sha256:")
    if digest != expected:
        raise SharedTrialError("local model SHA-256 does not match experiment bundle")

    runtime_build = bundle.get("runtime_build")
    if not isinstance(runtime_build, dict):
        raise SharedTrialError(
            "experiment bundle lacks current llama.cpp runtime_build binding; rebuild it from fresh two-node llama-bench evidence"
        )
    return TrialPlan(
        bundle_id=bundle["bundle_id"],
        placement_decision_id=placement["decision_id"],
        coordinator_node_id=coordinator["node_id"],
        worker_node_id=worker["node_id"],
        coordinator_kind=coordinator["kind"],
        coordinator_name=coordinator["name"],
        llama_build_commit=runtime_build["llama_build_commit"],
        llama_build_number=int(runtime_build["llama_build_number"]),
        model_basename=model_path.name,
        model_size_bytes=model_path.stat().st_size,
        model_sha256=digest,
        tensor_split=(float(candidate["tensor_split"][0]), float(candidate["tensor_split"][1])),
        layer_ranges=(dict(ranges[0]), dict(ranges[1])),
    )


def parse_device_listing(text: str) -> tuple[DeviceInfo, ...]:
    if not isinstance(text, str):
        raise TypeError("device listing must be text")
    if len(text.encode("utf-8", errors="replace")) > MAX_DISCOVERY_OUTPUT_BYTES:
        raise SharedTrialError("llama.cpp device listing exceeded 1 MiB")
    lines = text.splitlines()
    markers = [index for index, line in enumerate(lines) if line.strip() == "Available devices:"]
    if not markers:
        raise SharedTrialError("llama.cpp output did not contain an Available devices section")
    result: list[DeviceInfo] = []
    seen: set[str] = set()
    for line in lines[markers[-1] + 1 :]:
        match = re.match(r"^\s*([A-Za-z][A-Za-z0-9_.-]{0,63}):\s+(.+?)\s*$", line)
        if not match:
            continue
        name, description = match.group(1), match.group(2)
        if not DEVICE_NAME.fullmatch(name) or len(description) > 1024:
            raise SharedTrialError("llama.cpp returned an invalid device record")
        if name in seen:
            raise SharedTrialError("llama.cpp returned duplicate device names")
        seen.add(name)
        result.append(DeviceInfo(name=name, description=description))
    return tuple(result)


def _discover_command(executable: Path, endpoints: Sequence[RpcEndpoint]) -> list[str]:
    command = [str(executable), "--offline"]
    if endpoints:
        command += ["--rpc", ",".join(endpoint.text() for endpoint in endpoints)]
    command.append("--list-devices")
    return command


def discover_devices(
    executable: Path,
    endpoints: Sequence[RpcEndpoint] = (),
    *,
    timeout: float = 30.0,
    runner: Callable[..., subprocess.CompletedProcess] = subprocess.run,
) -> tuple[DeviceInfo, ...]:
    if executable.is_symlink() or not executable.is_file():
        raise SharedTrialError("llama.cpp discovery executable must be an existing non-symlink file")
    try:
        result = runner(
            _discover_command(executable, endpoints),
            cwd=ROOT,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            errors="replace",
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise SharedTrialError("llama.cpp device discovery timed out") from exc
    output = result.stdout or ""
    if len(output.encode("utf-8", errors="replace")) > MAX_DISCOVERY_OUTPUT_BYTES:
        raise SharedTrialError("llama.cpp device discovery output exceeded 1 MiB")
    if result.returncode != 0:
        raise SharedTrialError(f"llama.cpp device discovery exited with code {result.returncode}")
    return parse_device_listing(output)


def _rpc_devices(devices: Sequence[DeviceInfo]) -> tuple[DeviceInfo, ...]:
    return tuple(device for device in devices if "RPC" in device.name.upper())


def _local_devices(devices: Sequence[DeviceInfo]) -> tuple[DeviceInfo, ...]:
    return tuple(device for device in devices if "RPC" not in device.name.upper())


def choose_local_device(
    devices: Sequence[DeviceInfo],
    plan: TrialPlan,
    requested: str | None = None,
) -> str:
    available = _local_devices(devices)
    if requested is not None:
        if requested == "none" and plan.coordinator_kind == "cpu":
            return requested
        if not any(device.name == requested for device in available):
            raise SharedTrialError("requested local device is not in llama.cpp --list-devices output")
        return requested
    if plan.coordinator_kind == "cpu" and not available:
        return "none"
    wanted = plan.coordinator_name.casefold()
    by_description = [
        device for device in available
        if wanted in device.description.casefold() or device.description.casefold().startswith(wanted)
    ]
    if len(by_description) == 1:
        return by_description[0].name
    if len(available) == 1:
        return available[0].name
    raise SharedTrialError("local llama.cpp device is ambiguous; pass --local-device explicitly")


def choose_rpc_device(devices: Sequence[DeviceInfo], requested: str | None = None) -> str:
    available = _rpc_devices(devices)
    if requested is not None:
        if not any(device.name == requested for device in available):
            raise SharedTrialError("requested RPC device is not in llama.cpp --list-devices output")
        return requested
    if len(available) == 1:
        return available[0].name
    if not available:
        raise SharedTrialError("llama-server did not expose an RPC device")
    raise SharedTrialError("worker exposes multiple RPC devices; pass --rpc-device explicitly")


def sibling_llama_cli(llama_server: Path) -> Path | None:
    suffix = ".exe" if llama_server.suffix.lower() == ".exe" else ""
    candidate = llama_server.with_name("llama-cli" + suffix)
    return candidate if candidate.is_file() and not candidate.is_symlink() else None


def preflight_server_rpc(
    llama_server: Path,
    worker: RpcEndpoint,
    *,
    llama_cli: Path | None = None,
    discovery: Callable[[Path, Sequence[RpcEndpoint]], tuple[DeviceInfo, ...]] = discover_devices,
) -> tuple[DeviceInfo, ...]:
    server_error: SharedTrialError | None = None
    try:
        devices = discovery(llama_server, (worker,))
        if _rpc_devices(devices):
            return devices
        server_error = SharedTrialError("llama-server completed discovery but exposed no RPC device")
    except SharedTrialError as exc:
        server_error = exc

    diagnostic_cli = llama_cli or sibling_llama_cli(llama_server)
    if diagnostic_cli is not None:
        try:
            cli_devices = discovery(diagnostic_cli, (worker,))
        except SharedTrialError:
            cli_devices = ()
        if _rpc_devices(cli_devices):
            raise SharedTrialError(
                "llama-server cannot expose the RPC worker while llama-cli can; stop here and use a llama.cpp build without the current server-RPC compatibility regression"
            ) from server_error
    raise SharedTrialError(
        "llama-server cannot expose the RPC worker; verify worker process, private-LAN firewall, and matching RPC-capable llama.cpp builds"
    ) from server_error


@dataclass
class _RelayHandle:
    process: subprocess.Popen
    endpoint: RpcEndpoint
    reader: threading.Thread
    diagnostics: deque[str]


def _relay_reader(stream: Any, ready: queue.Queue[str], diagnostics: deque[str]) -> None:
    try:
        for line in iter(stream.readline, ""):
            bounded = line.rstrip("\r\n")[:2048]
            diagnostics.append(bounded)
            if bounded.startswith("READY "):
                try:
                    ready.put_nowait(bounded)
                except queue.Full:
                    pass
    finally:
        try:
            stream.close()
        except Exception:
            pass


def start_measurement_relay(
    target: RpcEndpoint,
    metrics_path: Path,
    *,
    listen_port: int = 50053,
    startup_timeout: float = 10.0,
    popen: Callable[..., subprocess.Popen] = subprocess.Popen,
) -> _RelayHandle:
    if not 1 <= listen_port <= 65535:
        raise ValueError("relay listen port must be 1..65535")
    if metrics_path.exists():
        raise SharedTrialError("relay metrics path already exists")
    metrics_path.parent.mkdir(parents=True, exist_ok=True)
    command = [
        sys.executable,
        "-m",
        "runtime.network.tcp_relay",
        "--target",
        target.text(),
        "--listen-port",
        str(listen_port),
        "--metrics",
        str(metrics_path),
    ]
    process = popen(
        command,
        cwd=ROOT,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        errors="replace",
        bufsize=1,
    )
    if process.stdout is None:
        process.terminate()
        raise SharedTrialError("measurement relay stdout pipe was not created")
    ready: queue.Queue[str] = queue.Queue(maxsize=1)
    diagnostics: deque[str] = deque(maxlen=32)
    reader = threading.Thread(
        target=_relay_reader,
        args=(process.stdout, ready, diagnostics),
        daemon=True,
    )
    reader.start()
    expected = RpcEndpoint("127.0.0.1", listen_port)
    deadline = time.monotonic() + startup_timeout
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise SharedTrialError(f"measurement relay exited before READY with code {process.returncode}")
        try:
            line = ready.get(timeout=min(0.1, max(0.01, deadline - time.monotonic())))
        except queue.Empty:
            continue
        expected_line = f"READY {expected.text()} -> {target.text()}"
        if line != expected_line:
            process.terminate()
            raise SharedTrialError("measurement relay announced an unexpected endpoint")
        return _RelayHandle(process=process, endpoint=expected, reader=reader, diagnostics=diagnostics)
    process.terminate()
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=5)
    raise SharedTrialError("measurement relay did not become ready before timeout")


def stop_relay(handle: _RelayHandle) -> None:
    if handle.process.poll() is None:
        handle.process.terminate()
        try:
            handle.process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            handle.process.kill()
            handle.process.wait(timeout=5)
    handle.reader.join(timeout=1)


def wait_relay_success(handle: _RelayHandle, metrics_path: Path, *, timeout: float = 15.0) -> None:
    try:
        code = handle.process.wait(timeout=timeout)
    except subprocess.TimeoutExpired as exc:
        stop_relay(handle)
        raise SharedTrialError("measurement relay did not terminate after shared run") from exc
    handle.reader.join(timeout=1)
    if code != 0:
        raise SharedTrialError(f"measurement relay exited with code {code}")
    if not metrics_path.is_file():
        raise SharedTrialError("measurement relay did not persist metrics")


def _write_failure(root: Path, phase: str, exc: BaseException) -> None:
    message = (str(exc) or type(exc).__name__)[:MAX_FAILURE_MESSAGE]
    record = {
        "schema_version": 1,
        "captured_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "phase": phase[:64],
        "error_type": type(exc).__name__[:128],
        "message": message,
    }
    (root / "shared_trial_failure.json").write_text(
        json.dumps(record, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


def run_shared_trial(
    *,
    bundle_path: Path,
    llama_server: Path,
    model_path: Path,
    worker_rpc: RpcEndpoint,
    output_dir: Path,
    llama_cli: Path | None = None,
    local_device: str | None = None,
    rpc_device: str | None = None,
    relay_port: int = 50053,
    local_port: int = 18080,
    context_size: int = 2048,
    n_predict: int = 32,
    seed: int = 1,
    prompt: str = "ComputeMesh deterministic M1 correctness probe. Reply with READY.",
    startup_timeout: float = 300.0,
    request_timeout: float = 300.0,
) -> Path:
    output_dir.mkdir(parents=True, exist_ok=False)
    phase = "bundle_and_model_preflight"
    relay: _RelayHandle | None = None
    try:
        plan = load_trial_plan(bundle_path, model_path)
        phase = "runtime_version"
        if llama_server.is_symlink() or not llama_server.is_file():
            raise SharedTrialError("llama-server must be an existing non-symlink file")
        version = runtime_version(llama_server)
        if not version:
            raise SharedTrialError("llama-server version is empty")
        phase = "runtime_build_binding"
        current_build = parse_runtime_build_identity(version)
        if not runtime_build_matches(
            current_build,
            expected_number=plan.llama_build_number,
            expected_commit=plan.llama_build_commit,
        ):
            raise SharedTrialError(
                "current llama-server build does not match the build bound by the selected two-node llama-bench evidence "
                f"(expected {plan.llama_build_number}/{plan.llama_build_commit}, "
                f"got {current_build.build_number}/{current_build.commit})"
            )

        phase = "local_device_discovery"
        local_listing = discover_devices(llama_server)
        selected_local = choose_local_device(local_listing, plan, local_device)

        phase = "rpc_preflight"
        remote_listing = preflight_server_rpc(llama_server, worker_rpc, llama_cli=llama_cli)
        if not any(device.name == selected_local for device in _local_devices(remote_listing)):
            raise SharedTrialError(
                "llama-server RPC preflight no longer exposes the selected coordinator device"
            )
        selected_rpc = choose_rpc_device(remote_listing, rpc_device)

        phase = "baseline"
        baseline_dir = output_dir / "baseline"
        baseline = run_spike(
            SpikePlan(
                llama_server=llama_server,
                model=model_path,
                rpc_endpoints=(),
                devices=(selected_local,),
                tensor_split=(1.0,),
                mode="local_baseline",
                local_port=local_port,
                context_size=context_size,
                n_predict=n_predict,
                seed=seed,
            ),
            prompt=prompt,
            output_dir=baseline_dir,
            startup_timeout=startup_timeout,
            request_timeout=request_timeout,
        )

        phase = "shared_relay"
        relay_metrics = output_dir / "relay_metrics.json"
        relay = start_measurement_relay(worker_rpc, relay_metrics, listen_port=relay_port)

        phase = "shared_run"
        shared_dir = output_dir / "shared"
        shared = run_spike(
            SpikePlan(
                llama_server=llama_server,
                model=model_path,
                rpc_endpoints=(relay.endpoint,),
                devices=(selected_local, selected_rpc),
                tensor_split=plan.tensor_split,
                mode="shared_rpc",
                local_port=local_port,
                context_size=context_size,
                n_predict=n_predict,
                seed=seed,
            ),
            prompt=prompt,
            output_dir=shared_dir,
            startup_timeout=startup_timeout,
            request_timeout=request_timeout,
        )
        wait_relay_success(relay, relay_metrics)
        relay = None

        phase = "comparison"
        comparison = compare_results(baseline, shared)
        comparison_path = output_dir / "comparison.json"
        comparison_path.write_text(
            json.dumps(comparison, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        if not comparison["exact_output_match"]:
            raise SharedTrialError("shared run output does not exactly match local baseline")

        phase = "proof_binding"
        proof = output_dir / "shared_run_evidence.json"
        write_shared_run_evidence(
            bundle_path=bundle_path,
            baseline_path=baseline,
            shared_path=shared,
            relay_path=relay_metrics,
            output_path=proof,
        )
        return proof
    except Exception as exc:
        if relay is not None:
            stop_relay(relay)
        try:
            _write_failure(output_dir, phase, exc)
        except Exception:
            pass
        raise


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the ComputeMesh M1 two-node shared proof on the coordinator")
    parser.add_argument("--bundle", type=Path, required=True)
    parser.add_argument("--llama-server", type=Path, required=True)
    parser.add_argument("--llama-cli", type=Path)
    parser.add_argument("--model", type=Path, required=True)
    parser.add_argument("--worker-rpc", type=RpcEndpoint.parse, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--local-device")
    parser.add_argument("--rpc-device")
    parser.add_argument("--relay-port", type=int, default=50053)
    parser.add_argument("--local-port", type=int, default=18080)
    parser.add_argument("--ctx-size", type=int, default=2048)
    parser.add_argument("--n-predict", type=int, default=32)
    parser.add_argument("--seed", type=int, default=1)
    parser.add_argument("--prompt", default="ComputeMesh deterministic M1 correctness probe. Reply with READY.")
    parser.add_argument("--startup-timeout", type=float, default=300.0)
    parser.add_argument("--request-timeout", type=float, default=300.0)
    args = parser.parse_args(argv)
    try:
        proof = run_shared_trial(
            bundle_path=args.bundle,
            llama_server=args.llama_server,
            llama_cli=args.llama_cli,
            model_path=args.model,
            worker_rpc=args.worker_rpc,
            output_dir=args.output_dir,
            local_device=args.local_device,
            rpc_device=args.rpc_device,
            relay_port=args.relay_port,
            local_port=args.local_port,
            context_size=args.ctx_size,
            n_predict=args.n_predict,
            seed=args.seed,
            prompt=args.prompt,
            startup_timeout=args.startup_timeout,
            request_timeout=args.request_timeout,
        )
    except Exception as exc:
        print(f"shared trial failed: {type(exc).__name__}: {str(exc)[:MAX_FAILURE_MESSAGE]}", file=sys.stderr)
        return 2
    print(proof)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
