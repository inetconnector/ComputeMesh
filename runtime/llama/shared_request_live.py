"""Single-pass shared llama.cpp request from a validated in-memory TrialPlan."""
from __future__ import annotations

from pathlib import Path
import subprocess
import threading
import time

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
    sha256_file,
    wait_until_ready,
)
from runtime.llama.shared_request import (
    SharedRequestError,
    SharedRequestResult,
    _read_relay_metrics,
    build_shared_request_evidence,
)
from runtime.llama.shared_trial import (
    SharedTrialError,
    TrialPlan,
    choose_local_device,
    choose_rpc_device,
    discover_devices,
    preflight_server_rpc,
    start_measurement_relay,
    stop_relay,
    wait_relay_success,
)


class SharedRequestCancelled(SharedRequestError):
    pass


class SharedRequestAborted(SharedRequestError):
    pass


def run_live_shared_request(
    *,
    job_id: str,
    plan: TrialPlan,
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
    cancel_event: threading.Event | None = None,
    abort_event: threading.Event | None = None,
) -> SharedRequestResult:
    cancelled = cancel_event or threading.Event()
    aborted = abort_event or threading.Event()

    def require_live(reason: str) -> None:
        if cancelled.is_set():
            raise SharedRequestCancelled(f"shared request was cancelled {reason}")
        if aborted.is_set():
            raise SharedRequestAborted(f"shared request execution health was lost {reason}")

    require_live("before dispatch")
    if not isinstance(prompt, str) or not prompt:
        raise ValueError("prompt must be non-empty text")
    output_dir.mkdir(parents=True, exist_ok=False)
    if llama_server.is_symlink() or not llama_server.is_file():
        raise SharedRequestError("llama-server must be an existing non-symlink file")
    if model_path.is_symlink() or not model_path.is_file():
        raise SharedRequestError("model must be an existing non-symlink file")
    if model_path.name != plan.model_basename:
        raise SharedRequestError("local model basename does not match live plan")
    if model_path.stat().st_size < plan.model_size_bytes:
        raise SharedRequestError("local model file is smaller than planned artifact")
    if sha256_file(model_path) != plan.model_sha256:
        raise SharedRequestError("local model SHA-256 does not match live plan")

    version = runtime_version(llama_server)
    current_build = parse_runtime_build_identity(version)
    if not runtime_build_matches(
        current_build,
        expected_number=plan.llama_build_number,
        expected_commit=plan.llama_build_commit,
    ):
        raise SharedRequestError("current llama.cpp build does not match live node evidence")

    local_listing = discover_devices(llama_server)
    selected_local = choose_local_device(local_listing, plan, local_device)
    remote_listing = preflight_server_rpc(llama_server, worker_rpc, llama_cli=llama_cli)
    selected_rpc = choose_rpc_device(remote_listing, rpc_device)
    require_live("before runtime start")

    relay_metrics_path = output_dir / "relay_metrics.json"
    relay = start_measurement_relay(worker_rpc, relay_metrics_path, listen_port=relay_port)
    process: subprocess.Popen | None = None
    watcher: threading.Thread | None = None
    watcher_stop = threading.Event()

    def watch_stop() -> None:
        while not watcher_stop.wait(0.1):
            if cancelled.is_set() or aborted.is_set():
                current = process
                if current is not None and current.poll() is None:
                    try:
                        current.terminate()
                    except OSError:
                        pass
                return

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
        watcher = threading.Thread(target=watch_stop, name=f"cm-stop-{job_id}", daemon=True)
        watcher.start()
        model_ready_ms = wait_until_ready(local_port, timeout=startup_timeout, process=process)
        require_live("during model startup")
        started = time.monotonic()
        doc = _json_request(
            "POST",
            f"http://127.0.0.1:{local_port}/completion",
            completion_payload(prompt, n_predict=n_predict, seed=seed),
            request_timeout,
        )
        require_live("during inference")
        request_ms = (time.monotonic() - started) * 1000.0
        content, _tokens, timings = parse_completion_response(doc)
        timings = dict(timings)
        timings["request_ms"] = request_ms
        timings["model_ready_ms"] = model_ready_ms
    except (SharedRequestCancelled, SharedRequestAborted):
        stop_relay(relay)
        raise
    except Exception as exc:
        stop_relay(relay)
        if cancelled.is_set():
            raise SharedRequestCancelled("shared request was cancelled during inference") from exc
        if aborted.is_set():
            raise SharedRequestAborted("shared request execution health was lost during inference") from exc
        raise SharedRequestError("live shared runtime request failed") from exc
    finally:
        watcher_stop.set()
        if watcher is not None:
            watcher.join(timeout=0.5)
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
        if cancelled.is_set():
            raise SharedRequestCancelled("shared request was cancelled before relay completion") from exc
        if aborted.is_set():
            raise SharedRequestAborted("shared request execution health was lost before relay completion") from exc
        raise SharedRequestError("live shared request relay did not complete cleanly") from exc

    require_live("before evidence creation")
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
    import json
    evidence_path.write_text(json.dumps(evidence, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return SharedRequestResult(
        text=content,
        prompt_tokens=int(timings["prompt_n"]),
        completion_tokens=int(timings["predicted_n"]),
        evidence_path=evidence_path,
    )
