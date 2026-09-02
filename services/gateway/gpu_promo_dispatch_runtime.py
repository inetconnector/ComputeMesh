"""Optional loopback GPU promo dispatcher owned by the live gateway process."""
from __future__ import annotations

import os
import threading
from dataclasses import dataclass
from http.server import ThreadingHTTPServer

from services.orchestrator.authenticated_gpu_promo_transport import (
    SessionAuthenticatedGpuPromoTransport,
)
from services.orchestrator.gpu_promo_dispatch import create_gpu_promo_dispatch_server
from services.orchestrator.live_control_plane import IntegratedLiveControlPlane
from services.orchestrator.live_shared_runtime import LiveSharedRuntimeRegistry


def _env_truthy(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in {"1", "true", "yes", "on"}


@dataclass
class RunningGpuPromoDispatch:
    server: ThreadingHTTPServer
    thread: threading.Thread

    @property
    def port(self) -> int:
        return int(self.server.server_address[1])

    def close(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)


def start_optional_gpu_promo_dispatch(
    *,
    control_plane: IntegratedLiveControlPlane,
    registry: LiveSharedRuntimeRegistry,
) -> RunningGpuPromoDispatch | None:
    if not _env_truthy("COMPUTEMESH_GPU_PROMO_DISPATCH_ENABLED"):
        return None
    token = os.environ.get("COMPUTEMESH_GPU_PROMO_DISPATCH_TOKEN", "").strip()
    if not token:
        raise RuntimeError(
            "COMPUTEMESH_GPU_PROMO_DISPATCH_TOKEN is required when GPU promo dispatch is enabled"
        )
    try:
        port = int(os.environ.get("COMPUTEMESH_GPU_PROMO_DISPATCH_PORT", "7490"))
    except ValueError as exc:
        raise RuntimeError("COMPUTEMESH_GPU_PROMO_DISPATCH_PORT must be an integer") from exc

    server = create_gpu_promo_dispatch_server(
        transport=SessionAuthenticatedGpuPromoTransport(
            sessions=registry,
            client=control_plane.control_client,
        ),
        bearer_token=token,
        port=port,
    )
    thread = threading.Thread(
        target=server.serve_forever,
        name="cm-gpu-promo-dispatch",
        daemon=True,
    )
    thread.start()
    return RunningGpuPromoDispatch(server=server, thread=thread)


__all__ = ["RunningGpuPromoDispatch", "start_optional_gpu_promo_dispatch"]
