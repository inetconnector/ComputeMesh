#!/usr/bin/env python3
"""Vendor-neutral entry point for the public ComputeMesh provider agent.

It reuses the normal public provider agent and changes only local GPU-promo runner
construction so operators can select ``cuda``, ``rocm`` or ``vulkan`` explicitly
through ``COMPUTEMESH_PROMO_BACKEND``.  No private control-plane logic is imported.
"""
from __future__ import annotations

import os

from apps.node import provider_agent as _base
from runtime.llama.gpu_promo_challenge import GpuPromoChallengeConfig, GpuPromoChallengeRunner


def _gpu_promo_runner_from_args(args):
    values = (
        args.promo_llama_server,
        args.promo_model,
        args.promo_device,
        args.promo_accelerator_id,
    )
    configured = tuple(value is not None for value in values)
    if any(configured) and not all(configured):
        raise _base.ProviderAgentError(
            "GPU promo requires --promo-llama-server, --promo-model, --promo-device and "
            "--promo-accelerator-id together"
        )
    if not any(configured):
        return None
    backend = os.environ.get("COMPUTEMESH_PROMO_BACKEND", "auto").strip().lower() or "auto"
    config = GpuPromoChallengeConfig(
        llama_server=args.promo_llama_server,
        model=args.promo_model,
        device=args.promo_device,
        accelerator_id=args.promo_accelerator_id,
        runtime_backend=backend,
        local_port=args.promo_port,
        context_size=args.promo_ctx_size,
        max_timeout_seconds=args.promo_max_timeout,
    )
    return GpuPromoChallengeRunner(config)


_base._gpu_promo_runner_from_args = _gpu_promo_runner_from_args
ProviderAgentError = _base.ProviderAgentError


def main(argv: list[str] | None = None) -> int:
    return _base.main(argv)


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except ProviderAgentError as exc:
        print(f"provider agent failed: {exc}")
        raise SystemExit(2) from exc
