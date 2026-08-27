#!/usr/bin/env python3
"""Run real two-node llama.cpp sensitivity measurements across delay/jitter points.

This is lab instrumentation. It never synthesizes performance observations: every
matrix row requires a completed llama.cpp shared run and persisted relay metrics.
Packet loss/reordering/bandwidth shaping are intentionally out of scope here and
must be measured with OS/network emulation instead of pretending TCP relay delay
is equivalent to those effects.
"""
from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from pathlib import Path
import queue
import subprocess
import sys
import threading
import time
from typing import Any, Sequence

from runtime.llama.rpc_spike import RpcEndpoint, SpikePlan, compare_results, run_spike
from runtime.llama.shared_trial import (
    SharedTrialError,
    choose_local_device,
    choose_rpc_device,
    discover_devices,
    load_trial_plan,
    preflight_server_rpc,
)

ROOT = Path(__file__).resolve().parents[2]


@dataclass(frozen=True)
class MatrixPoint:
    one_way_delay_ms: float
    jitter_ms: float
    seed: int

    def __post_init__(self) -> None:
        if self.one_way_delay_ms < 0 or self.jitter_ms < 0:
            raise ValueError("delay and jitter must be non-negative")
        if self.jitter_ms > self.one_way_delay_ms and self.one_way_delay_ms > 0:
            raise ValueError("jitter must not exceed one-way delay")


@dataclass
class _Relay:
    process: subprocess.Popen[str]
    endpoint: RpcEndpoint
    reader: threading.Thread


def _numbers(value: str) -> tuple[float, ...]:
    try:
        values = tuple(float(item.strip()) for item in value.split(",") if item.strip())
    except ValueError as exc:
        raise argparse.ArgumentTypeError("matrix values must be comma-separated numbers") from exc
    if not values or any(item < 0 or item > 60_000 for item in values):
        raise argparse.ArgumentTypeError("matrix values must be in 0..60000 ms")
    return values


def build_points(delays: Sequence[float], jitters: Sequence[float], *, seed: int) -> tuple[MatrixPoint, ...]:
    points: list[MatrixPoint] = []
    for delay in delays:
        for jitter in jitters:
            if delay == 0 and jitter > 0:
                continue
            if delay > 0 and jitter > delay:
                continue
            points.append(MatrixPoint(float(delay), float(jitter), seed + len(points)))
    if not points:
        raise ValueError("network matrix contains no valid points")
    return tuple(points)


def _relay_reader(stream: Any, ready: queue.Queue[str]) -> None:
    try:
        for line in iter(stream.readline, ""):
            bounded = line.rstrip("\r\n")[:2048]
            if bounded.startswith("READY "):
                try:
                    ready.put_nowait(bounded)
                except queue.Full:
                    pass
    finally:
        stream.close()


def start_relay(
    target: RpcEndpoint,
    metrics: Path,
    *,
    delay_ms: float,
    jitter_ms: float,
    seed: int,
    port: int,
    timeout: float = 15.0,
) -> _Relay:
    if metrics.exists():
        raise SharedTrialError("relay metrics path already exists")
    metrics.parent.mkdir(parents=True, exist_ok=True)
    command = [
        sys.executable,
        "-m",
        "runtime.network.tcp_relay",
        "--target",
        target.text(),
        "--listen-port",
        str(port),
        "--delay-ms",
        str(delay_ms),
        "--jitter-ms",
        str(jitter_ms),
        "--seed",
        str(seed),
        "--idle-timeout",
        "2",
        "--metrics",
        str(metrics),
    ]
    process = subprocess.Popen(
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
        raise SharedTrialError("relay stdout pipe was not created")
    ready: queue.Queue[str] = queue.Queue(maxsize=1)
    reader = threading.Thread(target=_relay_reader, args=(process.stdout, ready), daemon=True)
    reader.start()
    endpoint = RpcEndpoint("127.0.0.1", port)
    expected = f"READY {endpoint.text()} -> {target.text()}"
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise SharedTrialError(f"measurement relay exited before READY with code {process.returncode}")
        try:
            line = ready.get(timeout=0.1)
        except queue.Empty:
            continue
        if line != expected:
            process.terminate()
            raise SharedTrialError("measurement relay announced an unexpected endpoint")
        return _Relay(process=process, endpoint=endpoint, reader=reader)
    process.terminate()
    raise SharedTrialError("measurement relay did not become ready")


def stop_relay(relay: _Relay) -> None:
    if relay.process.poll() is None:
        relay.process.terminate()
        try:
            relay.process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            relay.process.kill()
            relay.process.wait(timeout=5)
    relay.reader.join(timeout=1)


def _wait_relay(relay: _Relay, metrics: Path, timeout: float = 20.0) -> None:
    try:
        code = relay.process.wait(timeout=timeout)
    except subprocess.TimeoutExpired as exc:
        stop_relay(relay)
        raise SharedTrialError("relay did not finish after shared run") from exc
    relay.reader.join(timeout=1)
    if code != 0:
        raise SharedTrialError(f"relay exited with code {code}")
    if not metrics.is_file():
        raise SharedTrialError("relay did not persist metrics")


def _read(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise SharedTrialError(f"expected JSON object: {path}")
    return value


def run_matrix(
    *,
    bundle: Path,
    llama_server: Path,
    model: Path,
    worker: RpcEndpoint,
    output_dir: Path,
    points: Sequence[MatrixPoint],
    local_device: str | None = None,
    rpc_device: str | None = None,
    relay_port: int = 50053,
    local_port: int = 18080,
    context_size: int = 2048,
    n_predict: int = 32,
    prompt: str = "ComputeMesh network sensitivity probe. Reply with READY.",
) -> Path:
    output_dir.mkdir(parents=True, exist_ok=False)
    plan = load_trial_plan(bundle, model)
    local_listing = discover_devices(llama_server)
    selected_local = choose_local_device(local_listing, plan, local_device)
    remote_listing = preflight_server_rpc(llama_server, worker)
    selected_rpc = choose_rpc_device(remote_listing, rpc_device)

    baseline = run_spike(
        SpikePlan(
            llama_server=llama_server,
            model=model,
            rpc_endpoints=(),
            devices=(selected_local,),
            tensor_split=(1.0,),
            mode="local_baseline",
            local_port=local_port,
            context_size=context_size,
            n_predict=n_predict,
            seed=1,
        ),
        prompt=prompt,
        output_dir=output_dir / "baseline",
    )

    rows: list[dict[str, Any]] = []
    for index, point in enumerate(points):
        point_dir = output_dir / f"point-{index:03d}"
        point_dir.mkdir()
        metrics = point_dir / "relay_metrics.json"
        relay = start_relay(
            worker,
            metrics,
            delay_ms=point.one_way_delay_ms,
            jitter_ms=point.jitter_ms,
            seed=point.seed,
            port=relay_port,
        )
        try:
            shared = run_spike(
                SpikePlan(
                    llama_server=llama_server,
                    model=model,
                    rpc_endpoints=(relay.endpoint,),
                    devices=(selected_local, selected_rpc),
                    tensor_split=plan.tensor_split,
                    mode="shared_rpc",
                    local_port=local_port,
                    context_size=context_size,
                    n_predict=n_predict,
                    seed=1,
                ),
                prompt=prompt,
                output_dir=point_dir / "shared",
            )
            _wait_relay(relay, metrics)
            relay = None
        finally:
            if relay is not None:
                stop_relay(relay)

        comparison = compare_results(baseline, shared)
        if not comparison["exact_output_match"]:
            raise SharedTrialError(f"matrix point {index} output differs from baseline")
        shared_doc = _read(shared)
        relay_doc = _read(metrics)
        timing = shared_doc.get("timings", {})
        traffic = relay_doc.get("traffic", {})
        rows.append(
            {
                "index": index,
                "one_way_delay_ms": point.one_way_delay_ms,
                "estimated_rtt_ms": point.one_way_delay_ms * 2.0,
                "jitter_ms": point.jitter_ms,
                "seed": point.seed,
                "request_ms": timing.get("request_ms"),
                "prefill_tps": timing.get("prompt_per_second"),
                "decode_tps": timing.get("predicted_per_second"),
                "coordinator_to_worker_bytes": traffic.get("coordinator_to_worker_bytes"),
                "worker_to_coordinator_bytes": traffic.get("worker_to_coordinator_bytes"),
                "comparison": comparison["shared_over_baseline"],
            }
        )

    result = {
        "schema_version": 1,
        "experiment": "real_llama_cpp_delay_jitter_matrix",
        "bundle_id": plan.bundle_id,
        "placement_decision_id": plan.placement_decision_id,
        "model_sha256": plan.model_sha256,
        "coordinator_node_id": plan.coordinator_node_id,
        "worker_node_id": plan.worker_node_id,
        "tensor_split": list(plan.tensor_split),
        "limitations": {
            "packet_loss_measured": False,
            "reordering_measured": False,
            "bandwidth_shaping_measured": False,
        },
        "points": rows,
    }
    output = output_dir / "network_matrix.json"
    output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return output


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run real ComputeMesh llama.cpp delay/jitter matrix")
    parser.add_argument("--bundle", type=Path, required=True)
    parser.add_argument("--llama-server", type=Path, required=True)
    parser.add_argument("--model", type=Path, required=True)
    parser.add_argument("--worker-rpc", type=RpcEndpoint.parse, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--delays-ms", type=_numbers, default=(0.0, 1.0, 2.5, 5.0, 10.0, 25.0, 50.0))
    parser.add_argument("--jitters-ms", type=_numbers, default=(0.0, 0.5, 1.0, 2.0, 5.0))
    parser.add_argument("--seed", type=int, default=1000)
    parser.add_argument("--local-device")
    parser.add_argument("--rpc-device")
    parser.add_argument("--relay-port", type=int, default=50053)
    args = parser.parse_args(argv)
    points = build_points(args.delays_ms, args.jitters_ms, seed=args.seed)
    path = run_matrix(
        bundle=args.bundle,
        llama_server=args.llama_server,
        model=args.model,
        worker=args.worker_rpc,
        output_dir=args.output_dir,
        points=points,
        local_device=args.local_device,
        rpc_device=args.rpc_device,
        relay_port=args.relay_port,
    )
    print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
