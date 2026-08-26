#!/usr/bin/env python3
"""Run the M1 shared trial and immediately bind its proof to an orchestrator job.

This intentionally wraps, rather than forks, `shared_trial.run_shared_trial`. A
successful physical shared run produces `shared_run_evidence.json`; this wrapper
then emits the exact execution-attestation request that the selected nodes must
sign before settlement.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

from runtime.llama.job_attestation import write_attestation_request
from runtime.llama.rpc_spike import RpcEndpoint
from runtime.llama.shared_trial import MAX_FAILURE_MESSAGE, run_shared_trial


def run_job_bound_shared_trial(
    *,
    job_id: str,
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
) -> tuple[Path, Path]:
    if not isinstance(job_id, str) or not (1 <= len(job_id) <= 256):
        raise ValueError("job_id must be 1..256 characters")
    evidence_path = run_shared_trial(
        bundle_path=bundle_path,
        llama_server=llama_server,
        llama_cli=llama_cli,
        model_path=model_path,
        worker_rpc=worker_rpc,
        output_dir=output_dir,
        local_device=local_device,
        rpc_device=rpc_device,
        relay_port=relay_port,
        local_port=local_port,
        context_size=context_size,
        n_predict=n_predict,
        seed=seed,
        prompt=prompt,
        startup_timeout=startup_timeout,
        request_timeout=request_timeout,
    )
    request_path = output_dir / "execution_attestation_request.json"
    write_attestation_request(
        job_id=job_id,
        evidence_path=evidence_path,
        output_path=request_path,
    )
    manifest = {
        "schema_version": 1,
        "job_id": job_id,
        "shared_run_evidence": evidence_path.name,
        "execution_attestation_request": request_path.name,
        "settlement_ready": False,
        "next_required_action": "collect one valid signed execution attestation from every expected node",
    }
    (output_dir / "job_bound_shared_trial.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return evidence_path, request_path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run a job-bound ComputeMesh two-node shared proof")
    parser.add_argument("--job-id", required=True)
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
        evidence, request = run_job_bound_shared_trial(
            job_id=args.job_id,
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
        print(f"job-bound shared trial failed: {type(exc).__name__}: {str(exc)[:MAX_FAILURE_MESSAGE]}", file=sys.stderr)
        return 2
    print(json.dumps({"evidence": str(evidence), "attestation_request": str(request)}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
