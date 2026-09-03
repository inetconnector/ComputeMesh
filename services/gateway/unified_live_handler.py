"""Canonical production handler composition for ComputeMesh.

One server owns the external OpenAI/owner surface. Protected inference contributes
only internal ciphertext transport routes through ``ProtectedTransportMixin``.
"""
from __future__ import annotations

from services.gateway.live_handler import LiveGatewayHandler
from services.gateway.owner_server import build_unified_owner_handler
from services.gateway.protected_transport_mixin import ProtectedTransportMixin
from services.gateway.server import GatewayHandler


def build_unified_live_protected_handler() -> type[GatewayHandler]:
    owner_handler = build_unified_owner_handler()

    class UnifiedLiveProtectedGatewayHandler(
        ProtectedTransportMixin,
        LiveGatewayHandler,
        owner_handler,
    ):
        """Single product gateway: OpenAI + owner billing + live + protected internals."""

    UnifiedLiveProtectedGatewayHandler.__name__ = "UnifiedLiveProtectedGatewayHandler"
    UnifiedLiveProtectedGatewayHandler.__qualname__ = "UnifiedLiveProtectedGatewayHandler"
    return UnifiedLiveProtectedGatewayHandler
