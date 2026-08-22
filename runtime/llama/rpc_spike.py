#!/usr/bin/env python3
"""Controlled llama.cpp RPC research harness for the ComputeMesh M1 spike.

Upstream RPC remains an implementation detail. Assisted RPC endpoints are limited
to loopback/RFC1918 IPv4 and the coordinator HTTP listener is always loopback.
"""
from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import hashlib
import ipaddress
import json
from pathlib import Path
import re
import secrets
import subprocess
import time
from typing import Any, Iterable, Sequence
from urllib import error as urlerror
from urllib import request as urlrequest

MAX_RPC_SERVERS = 16
RFC1918 = tuple(ipaddress.ip_network(v) for v in ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16"))


class RpcSpikeError(RuntimeError):
    pass


@dataclass(frozen=True)
class RpcEndpoint:
    host: str
    port: int

    def __post_init__(self) -> None:
        try:
            addr = ipaddress.ip_address(self.host)
        except ValueError as exc:
            raise ValueError("RPC endpoint host must be a literal IPv4 address") from exc
        if addr.version != 4 or not (addr.is_loopback or any(addr in net for net in RFC1918)):
            raise ValueError("RPC endpoint must be loopback or RFC1918 private IPv4")
        if isinstance(self.port, bool) or not isinstance(self.port, int) or not 1 <= self.port <= 65535:
            raise ValueError("RPC endpoint port must be 1..65535")

    @classmethod
    def parse(cls, value: str) -> "RpcEndpoint":
        if not isinstance(value, str) or value.count(":") != 1:
            raise ValueError("RPC endpoint must use IPv4:port")
        host, raw_port = value.rsplit(":", 1)
        try:
            port = int(raw_port)
        except ValueError as exc:
            raise ValueError("RPC endpoint port must be an integer") from exc
        return cls(host, port)

    def text(self) -> str:
        return f"{self.host}:{self.port}"


@dataclass(frozen=True)
class LlamaBuildIdentity:
    build_number: int
    commit: str


_RUNTIME_BUILD_RE = re.compile(
    r"(?im)^\s*version:\s*(\d+)\s+\(\s*`?([0-9a-fA-F]{7,40})`?\s*\)"
)


def parse_runtime_build_identity(text: str) -> LlamaBuildIdentity:
    if not isinstance(text, str) or not text.strip():
        raise RpcSpikeError("llama.cpp --version output is empty")
    if len(text.encode("utf-8", errors="replace")) > 4096:
        raise RpcSpikeError("llama.cpp --version output exceeded 4096 bytes")
    match = _RUNTIME_BUILD_RE.search(text)
    if match is None:
        raise RpcSpikeError("llama.cpp --version output lacks a concrete build number/commit")
    number = int(match.group(1))
    if number < 1:
        raise RpcSpikeError("llama.cpp build number must be positive")
    return LlamaBuildIdentity(build_number=number, commit=match.group(2).lower())


def runtime_build_matches(
    actual: LlamaBuildIdentity, *, expected_number: int, expected_commit: str
) -> bool:
    if actual.build_number != expected_number:
        return False
    expected = expected_commit.lower()
    if re.fullmatch(r"[0-9a-f]{7,40}", expected) is None:
        return False
    return actual.commit == expected or actual.commit.startswith(expected) or expected.startswith(actual.commit)


@dataclass(frozen=True)
class SpikePlan:
    llama_server: Path
    model: Path
    rpc_endpoints: tuple[RpcEndpoint, ...]
    devices: tuple[str, ...]
    tensor_split: tuple[float, ...]
    mode: str = "shared_rpc"
    local_port: int = 18080
    context_size: int = 2048
    n_predict: int = 32
    seed: int = 1

    def __post_init__(self) -> None:
        if self.mode not in {"local_baseline", "shared_rpc"}:
            raise ValueError("mode must be local_baseline or shared_rpc")
        if len(self.rpc_endpoints) > MAX_RPC_SERVERS:
            raise ValueError(f"at most {MAX_RPC_SERVERS} RPC endpoints are supported")
        if self.mode == "shared_rpc" and not self.rpc_endpoints:
            raise ValueError("shared_rpc mode requires an RPC endpoint")
        if self.mode == "local_baseline" and self.rpc_endpoints:
            raise ValueError("local_baseline cannot use RPC endpoints")
        if len({x.text() for x in self.rpc_endpoints}) != len(self.rpc_endpoints):
            raise ValueError("duplicate RPC endpoints are not allowed")
        if not 1 <= self.local_port <= 65535:
            raise ValueError("local_port must be 1..65535")
        if not 128 <= self.context_size <= 1_048_576:
            raise ValueError("context_size must be 128..1048576")
        if not 1 <= self.n_predict <= 4096:
            raise ValueError("n_predict must be 1..4096")
        if not self.devices or len(self.devices) != len(self.tensor_split):
            raise ValueError("devices and tensor_split must be non-empty with equal length")
        if len(set(self.devices)) != len(self.devices):
            raise ValueError("duplicate devices are not allowed")
        if any(not isinstance(x, str) or not 1 <= len(x) <= 256 for x in self.devices):
            raise ValueError("invalid device name")
        if any(isinstance(x, bool) or not isinstance(x, (int, float)) or x <= 0 for x in self.tensor_split):
            raise ValueError("tensor_split entries must be positive numbers")
        has_rpc = any("RPC" in x.upper() for x in self.devices)
        has_local = any("RPC" not in x.upper() for x in self.devices)
        if self.mode == "shared_rpc" and (len(self.devices) < 2 or not has_rpc or not has_local):
            raise ValueError("shared_rpc requires explicit local and RPC devices")
        if self.mode == "local_baseline" and has_rpc:
            raise ValueError("local_baseline cannot contain RPC devices")


@dataclass(frozen=True)
class SpikeResult:
    schema_version: int
    run_id: str
    captured_at: str
    runtime: dict[str, Any]
    model: dict[str, Any]
    topology: dict[str, Any]
    placement: dict[str, Any]
    timings: dict[str, Any]
    correctness: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def build_worker_command(rpc_server: str | Path, *, bind: str, port: int = 50052,
                         devices: Sequence[str] = (), threads: int | None = None) -> list[str]:
    endpoint = RpcEndpoint(bind, port)
    cmd = [str(rpc_server), "--host", endpoint.host, "--port", str(endpoint.port)]
    if devices:
        if any(not x or len(x) > 256 for x in devices):
            raise ValueError("invalid worker device")
        cmd += ["--device", ",".join(devices)]
    if threads is not None:
        if isinstance(threads, bool) or not isinstance(threads, int) or not 1 <= threads <= 4096:
            raise ValueError("threads must be 1..4096")
        cmd += ["--threads", str(threads)]
    return cmd  # upstream RPC file cache deliberately stays disabled


def build_discover_command(llama_server: str | Path, endpoints: Iterable[RpcEndpoint]) -> list[str]:
    values = tuple(endpoints)
    if not 1 <= len(values) <= MAX_RPC_SERVERS:
        raise ValueError("at least one RPC endpoint is required")
    return [str(llama_server), "--offline", "--rpc", ",".join(x.text() for x in values), "--list-devices"]


def build_coordinator_command(plan: SpikePlan) -> list[str]:
    cmd = [str(plan.llama_server), "--model", str(plan.model), "--offline",
           "--host", "127.0.0.1", "--port", str(plan.local_port)]
    if plan.rpc_endpoints:
        cmd += ["--rpc", ",".join(x.text() for x in plan.rpc_endpoints)]
    cmd += ["--device", ",".join(plan.devices)]
    if len(plan.devices) == 1:
        cmd += ["--split-mode", "none"]
    else:
        cmd += ["--split-mode", "layer", "--tensor-split",
                ",".join(format(float(x), ".12g") for x in plan.tensor_split)]
    cmd += ["--n-gpu-layers", "all", "--fit", "off", "--ctx-size", str(plan.context_size),
            "--parallel", "1", "--cache-ram", "0", "--no-warmup"]
    return cmd


def completion_payload(prompt: str, *, n_predict: int, seed: int) -> dict[str, Any]:
    if not isinstance(prompt, str) or not 1 <= len(prompt.encode("utf-8")) <= 1_048_576:
        raise ValueError("prompt must be 1 byte..1 MiB UTF-8")
    return {"prompt": prompt, "n_predict": n_predict, "seed": seed, "temperature": 0.0,
            "stream": False, "cache_prompt": False, "return_tokens": True}


def sha256_file(path: Path, *, chunk_size: int = 8 * 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(chunk_size):
            digest.update(chunk)
    return digest.hexdigest()


def _json_request(method: str, url: str, payload: dict[str, Any] | None, timeout: float) -> dict[str, Any]:
    data = None if payload is None else json.dumps(payload, separators=(",", ":")).encode()
    req = urlrequest.Request(url, data=data, method=method, headers={"Content-Type": "application/json"})
    try:
        with urlrequest.urlopen(req, timeout=timeout) as response:
            raw = response.read(4 * 1024 * 1024 + 1)
    except (urlerror.URLError, TimeoutError) as exc:
        raise RpcSpikeError(f"local llama-server request failed: {exc}") from exc
    if len(raw) > 4 * 1024 * 1024:
        raise RpcSpikeError("local llama-server response exceeded 4 MiB")
    try:
        doc = json.loads(raw.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise RpcSpikeError("local llama-server returned invalid JSON") from exc
    if not isinstance(doc, dict):
        raise RpcSpikeError("local llama-server response must be an object")
    return doc


def wait_until_ready(port: int, *, timeout: float = 300.0,
                     process: subprocess.Popen | None = None) -> float:
    start, deadline = time.monotonic(), time.monotonic() + timeout
    while time.monotonic() < deadline:
        if process is not None and process.poll() is not None:
            raise RpcSpikeError(f"llama-server exited during startup with code {process.returncode}")
        try:
            doc = _json_request("GET", f"http://127.0.0.1:{port}/health", None, 5.0)
            if doc.get("status") == "ok":
                return (time.monotonic() - start) * 1000.0
        except RpcSpikeError:
            pass
        time.sleep(0.25)
    raise RpcSpikeError("llama-server did not become ready before startup timeout")


def parse_completion_response(doc: dict[str, Any]) -> tuple[str, list[int] | None, dict[str, Any]]:
    content = doc.get("content")
    if not isinstance(content, str):
        raise RpcSpikeError("completion response missing text content")
    raw_tokens = doc.get("tokens")
    tokens = None
    if raw_tokens is not None:
        if not isinstance(raw_tokens, list) or len(raw_tokens) > 4096 or any(isinstance(x, bool) or not isinstance(x, int) for x in raw_tokens):
            raise RpcSpikeError("completion response contains invalid token list")
        tokens = list(raw_tokens)
    raw = doc.get("timings")
    if not isinstance(raw, dict):
        raise RpcSpikeError("completion response missing timings")
    keys = {"cache_n", "prompt_n", "prompt_ms", "prompt_per_token_ms", "prompt_per_second",
            "predicted_n", "predicted_ms", "predicted_per_token_ms", "predicted_per_second"}
    timings = {k: raw[k] for k in keys if k in raw}
    required = {"prompt_n", "prompt_ms", "prompt_per_second", "predicted_n", "predicted_ms", "predicted_per_second"}
    if not required <= timings.keys():
        raise RpcSpikeError("completion response timings are incomplete")
    return content, tokens, timings


def runtime_version(executable: Path) -> str:
    result = subprocess.run([str(executable), "--version"], stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT, text=True, timeout=15, check=False)
    text = (result.stdout or "").strip().replace("\x00", "")
    if result.returncode or not text:
        raise RpcSpikeError("llama-server --version failed")
    return text[:4096]


def run_spike(plan: SpikePlan, *, prompt: str, output_dir: Path,
              startup_timeout: float = 300.0, request_timeout: float = 300.0) -> Path:
    if not plan.llama_server.is_file() or not plan.model.is_file():
        raise FileNotFoundError("llama-server and model must exist")
    if startup_timeout <= 0 or request_timeout <= 0:
        raise ValueError("timeouts must be positive")
    output_dir.mkdir(parents=True, exist_ok=False)
    run_id, phase, process = "llama-rpc-" + secrets.token_hex(8), "runtime_version", None
    try:
        version = runtime_version(plan.llama_server)
        phase = "model_digest"
        model_digest = sha256_file(plan.model)
        phase = "server_start"
        process = subprocess.Popen(build_coordinator_command(plan), stdin=subprocess.DEVNULL,
                                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        ready_ms = wait_until_ready(plan.local_port, timeout=startup_timeout, process=process)
        phase = "completion_request"
        started = time.monotonic()
        doc = _json_request("POST", f"http://127.0.0.1:{plan.local_port}/completion",
                            completion_payload(prompt, n_predict=plan.n_predict, seed=plan.seed), request_timeout)
        request_ms = (time.monotonic() - started) * 1000.0
        phase = "completion_parse"
        content, tokens, timings = parse_completion_response(doc)
    except Exception as exc:
        failure = {"schema_version": 1, "run_id": run_id,
                   "captured_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
                   "phase": phase, "error_type": type(exc).__name__[:128],
                   "message": (str(exc) or type(exc).__name__)[:1024]}
        (output_dir / "runtime_spike_failure.json").write_text(json.dumps(failure, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        raise
    finally:
        if process is not None and process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill(); process.wait(timeout=5)

    token_digest = None
    if tokens is not None:
        token_digest = hashlib.sha256(json.dumps(tokens, separators=(",", ":")).encode("ascii")).hexdigest()
    result = SpikeResult(
        1, run_id, datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        {"name": "llama.cpp", "version": version},
        {"basename": plan.model.name, "size_bytes": plan.model.stat().st_size, "sha256": model_digest},
        {"rpc_endpoints": [x.text() for x in plan.rpc_endpoints], "coordinator_http": f"127.0.0.1:{plan.local_port}"},
        {"mode": plan.mode, "split_mode": "none" if len(plan.devices) == 1 else "layer",
         "devices": list(plan.devices), "tensor_split": [float(x) for x in plan.tensor_split], "fit": False},
        {"model_ready_ms": ready_ms, "request_ms": request_ms, **timings},
        {"prompt_sha256": hashlib.sha256(prompt.encode()).hexdigest(),
         "output_sha256": hashlib.sha256(content.encode()).hexdigest(), "token_ids_sha256": token_digest},
    )
    path = output_dir / "runtime_spike_result.json"
    path.write_text(json.dumps(result.to_dict(), indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def compare_results(baseline_path: Path, shared_path: Path) -> dict[str, Any]:
    baseline = json.loads(baseline_path.read_text(encoding="utf-8"))
    shared = json.loads(shared_path.read_text(encoding="utf-8"))
    if baseline.get("placement", {}).get("mode") != "local_baseline" or shared.get("placement", {}).get("mode") != "shared_rpc":
        raise RpcSpikeError("comparison requires local_baseline and shared_rpc results")
    if baseline.get("model", {}).get("sha256") != shared.get("model", {}).get("sha256"):
        raise RpcSpikeError("cannot compare different model digests")
    if baseline.get("correctness", {}).get("prompt_sha256") != shared.get("correctness", {}).get("prompt_sha256"):
        raise RpcSpikeError("cannot compare different prompt digests")
    btoken, stoken = baseline["correctness"].get("token_ids_sha256"), shared["correctness"].get("token_ids_sha256")
    basis = "token_ids_sha256" if btoken is not None and stoken is not None else "output_sha256"
    exact = baseline["correctness"].get(basis) == shared["correctness"].get(basis)
    def ratio(key: str) -> float | None:
        b, s = baseline.get("timings", {}).get(key), shared.get("timings", {}).get(key)
        return float(s) / float(b) if isinstance(b, (int, float)) and isinstance(s, (int, float)) and b > 0 else None
    return {"schema_version": 1, "model_sha256": baseline["model"]["sha256"],
            "prompt_sha256": baseline["correctness"]["prompt_sha256"],
            "exact_output_match": exact, "match_basis": basis,
            "shared_over_baseline": {"prompt_tokens_per_second": ratio("prompt_per_second"),
                                     "predicted_tokens_per_second": ratio("predicted_per_second"),
                                     "request_ms": ratio("request_ms")}}


def _devices(value: str) -> tuple[str, ...]:
    result = tuple(x.strip() for x in value.split(",") if x.strip())
    if not result: raise argparse.ArgumentTypeError("devices must not be empty")
    return result


def _split(value: str) -> tuple[float, ...]:
    try: result = tuple(float(x.strip()) for x in value.split(",") if x.strip())
    except ValueError as exc: raise argparse.ArgumentTypeError("tensor split must contain numbers") from exc
    if not result or any(x <= 0 for x in result): raise argparse.ArgumentTypeError("tensor split must be positive")
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="ComputeMesh controlled llama.cpp RPC M1 spike")
    sub = parser.add_subparsers(dest="command", required=True)
    worker = sub.add_parser("worker"); worker.add_argument("--rpc-server", type=Path, required=True); worker.add_argument("--bind", required=True); worker.add_argument("--port", type=int, default=50052); worker.add_argument("--devices", type=_devices, default=()); worker.add_argument("--threads", type=int)
    discover = sub.add_parser("discover"); discover.add_argument("--llama-server", type=Path, required=True); discover.add_argument("--rpc", action="append", required=True, type=RpcEndpoint.parse)
    for name in ("baseline", "run"):
        p = sub.add_parser(name); p.add_argument("--llama-server", type=Path, required=True); p.add_argument("--model", type=Path, required=True); p.add_argument("--devices", required=True, type=_devices); p.add_argument("--tensor-split", type=_split, required=name == "run"); p.add_argument("--port", type=int, default=18080); p.add_argument("--ctx-size", type=int, default=2048); p.add_argument("--n-predict", type=int, default=32); p.add_argument("--seed", type=int, default=1); p.add_argument("--prompt", default="ComputeMesh deterministic M1 correctness probe. Reply with READY."); p.add_argument("--output-dir", type=Path, required=True); p.add_argument("--startup-timeout", type=float, default=300.0); p.add_argument("--request-timeout", type=float, default=300.0)
        if name == "run": p.add_argument("--rpc", action="append", required=True, type=RpcEndpoint.parse)
    compare = sub.add_parser("compare"); compare.add_argument("--baseline", type=Path, required=True); compare.add_argument("--shared", type=Path, required=True); compare.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    if args.command == "worker": return subprocess.run(build_worker_command(args.rpc_server, bind=args.bind, port=args.port, devices=args.devices, threads=args.threads), check=False).returncode
    if args.command == "discover": return subprocess.run(build_discover_command(args.llama_server, args.rpc), check=False).returncode
    if args.command in {"baseline", "run"}:
        endpoints = () if args.command == "baseline" else tuple(args.rpc)
        split = args.tensor_split or tuple(1.0 for _ in args.devices)
        plan = SpikePlan(args.llama_server, args.model, endpoints, args.devices, split,
                         mode="local_baseline" if args.command == "baseline" else "shared_rpc",
                         local_port=args.port, context_size=args.ctx_size, n_predict=args.n_predict, seed=args.seed)
        print(run_spike(plan, prompt=args.prompt, output_dir=args.output_dir,
                        startup_timeout=args.startup_timeout, request_timeout=args.request_timeout)); return 0
    result = compare_results(args.baseline, args.shared)
    text = json.dumps(result, indent=2, sort_keys=True) + "\n"
    if args.output: args.output.parent.mkdir(parents=True, exist_ok=True); args.output.write_text(text, encoding="utf-8")
    else: print(text, end="")
    return 0 if result["exact_output_match"] else 3


if __name__ == "__main__":
    raise SystemExit(main())
