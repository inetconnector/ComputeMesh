#!/usr/bin/env python3
"""Execute one real request on the planner-selected two-node llama.cpp RPC topology.

Unlike the M1 shared trial, this path does not run a local baseline. It returns the
actual completion text to the caller and emits request-scoped evidence suitable
for later node attestation. Placement remains experimental while the M1 planner
marks production_scheduling=false.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import subprocess
import time
from typing import Any

from runtime.llama.rpc_spike import (
    RpcEndpoint,
    SpikePlan,
    _json_request,
    build_coordinator_command,
    completion_payload,
    parse_completion_response,
    parse_runtime_build_identity,
    runtime_build_matches,
    runtime_version,
    wait_until_ready,
)
from runtime.llama.shared_trial import (
    SharedTrialError,
    choose_local_device,
    choose_rpc_device,
    discover_devices,
    load_trial_plan,
    preflight_server_rpc,
    start_measurement_relay,
    stop_relay,
    wait_relay_success,
)


class SharedRequestError(RuntimeError):
    pass


@dataclass(frozen=True)
class SharedRequestResult:
    text: str
    prompt_tokens: int
    completion_tokens: int
    evidence_path: Path


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _read_relay_metrics(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise SharedRequestError("relay metrics are unavailable") from exc
    if not isinstance(value, dict):
        raise SharedRequestError("relay metrics must be an object")
    c2w = value.get("client_to_target_bytes")
    w2c = value.get("target_to_client_bytes")
    if not isinstance(c2w, int) or not isinstance(w2c, int) or c2w <= 0 or w2c <= 0:
        raise SharedRequestError("shared request did not prove bidirectional RPC traffic")
    return value


def build_shared_request_evidence(
    *,
    job_id: str,
    plan: Any,
    runtime_version_text: str,
    prompt: str,
    content: str,
    timings: dict[str, Any],
    relay_metrics: dict[str, Any],
) -> dict[str, Any]:
    if not isinstance(job_id, str) or not (1 <= len(job_id) <= 256):
        raise ValueError("job_id must be 1..256 characters")
    if not isinstance(content, str):
        raise ValueError("content must be text")
    required_timings = {"prompt_n", "predicted_n", "request_ms"}
    if not required_timings <= timings.keys():
        raise SharedRequestError("shared request timings are incomplete")
    runtime = {"name": "llama.cpp", "version": runtime_version_text}
    evidence = {
        "schema_version": 1,
        "captured_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "scope": "shared_request_execution",
        "job_id": job_id,
        "placement_decision_id": plan.placement_decision_id,
        "model": {
            "basename": plan.model_basename,
            "size_bytes": plan.model_size_bytes,
            "sha256": plan.model_sha256,
        },
        "runtime": runtime,
        "planner_split": {
            "tensor_split": list(plan.tensor_split),
            "layer_ranges": list(plan.layer_ranges),
        },
        "participants": [plan.coordinator_node_id, plan.worker_node_id],
        "request": {
            "prompt_sha256": _sha256_text(prompt),
            "output_sha256": _sha256_text(content),
            "prompt_tokens": int(timings["prompt_n"]),
            "completion_tokens": int(timings["predicted_n"]),
            "request_ms": float(timings["request_ms"]),
        },
        "network": {
            "coordinator_to_worker_bytes": int(relay_metrics["client_to_target_bytes"]),
            "worker_to_coordinator_bytes": int(relay_metrics["target_to_client_bytes"]),
        },
        "production_scheduling": False,
    }
    canonical = json.dumps(evidence, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    evidence["evidence_id"] = "shared-request-evidence-" + hashlib.sha256(canonical).hexdigest()[:16]
    return evidence


def run_shared_request(
    *,
    job_id: str,
    bundle_path: Path,
    llama_server: Path,
    model_path: Path,
    worker_rpc: RpcEndpoint,
    output_dir: Path,
    prompt: str,
    llama_cli: Path | None = None,
    local_device: str | None = None,
    rpc_device: str | None = None,
    relay_port: int = 50053,
    local_port: int = 18080,
    context_size: int = 4096,
    n_predict: int = 256,
    seed: int = 1,
    startup_timeout: float = 300.0,
    request_timeout: float = 300.0,
) -> SharedRequestResult:
    if not isinstance(prompt, str) or not prompt:
        raise ValueError("prompt must be non-empty text")
    output_dir.mkdir(parents=True, exist_ok=False)
    plan = load_trial_plan(bundle_path, model_path)
    if llama_server.is_symlink() or not llama_server.is_file():
        raise SharedRequestError("llama-server must be an existing non-symlink file")
    version = runtime_version(llama_server)
    current_build = parse_runtime_build_identity(version)
    if not runtime_build_matches(
        current_build,
        expected_number=plan.llama_build_number,
        expected_commit=plan.llama_build_commit,
    ):
        raise SharedRequestError("current llama.cpp build does not match scheduler evidence")

    local_listing = discover_devices(llama_server)
    selected_local = choose_local_device(local_listing, plan, local_device)
    remote_listing = preflight_server_rpc(llama_server, worker_rpc, llama_cli=llama_cli)
    selected_rpc = choose_rpc_device(remote_listing, rpc_device)

    relay_metrics_path = output_dir / "relay_metrics.json"
    relay = start_measurement_relay(worker_rpc, relay_metrics_path, listen_port=relay_port)
    process: subprocess.Popen | None = None
    try:
        spike_plan = SpikePlan(
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
        )
        process = subprocess.Popen(
            build_coordinator_command(spike_plan),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        model_ready_ms = wait_until_ready(local_port, timeout=startup_timeout, process=process)
        started = time.monotonic()
        doc = _json_request(
            "POST",
            f"http://127.0.0.1:{local_port}/completion",
            completion_payload(prompt, n_predict=n_predict, seed=seed),
            request_timeout,
        )
        request_ms = (time.monotonic() - started) * 1000.0
        content, _tokens, timings = parse_completion_response(doc)
        timings = dict(timings)
        timings["request_ms"] = request_ms
        timings["model_ready_ms"] = model_ready_ms
    except Exception as exc:
        raise SharedRequestError("shared runtime request failed") from exc
    finally:
        if process is not None and process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)
    try:
        wait_relay_success(relay, relay_metrics_path)
    except SharedTrialError as exc:
        stop_relay(relay)
        raise SharedRequestError("shared request relay did not complete cleanly") from exc

    relay_metrics = _read_relay_metrics(relay_metrics_path)
    evidence = build_shared_request_evidence(
        job_id=job_id,
        plan=plan,
        runtime_version_text=version,
        prompt=prompt,
        content=content,
        timings=timings,
        relay_metrics=relay_metrics,
    )
    evidence_path = output_dir / "shared_request_evidence.json"
    evidence_path.write_text(json.dumps(evidence, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return SharedRequestResult(
        text=content,
        prompt_tokens=int(timings["prompt_n"]),
        completion_tokens=int(timings["predicted_n"]),
        evidence_path=evidence_path,
    )
