"""Canonical production handler composition for ComputeMesh.

One server owns the external OpenAI/owner surface. Protected inference contributes
only internal ciphertext transport routes through ``ProtectedTransportMixin``.
"""
from __future__ import annotations

from services.gateway.image_routes import install_image_generation_routes
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

    # The image route wrapper is always composed into the production handler, but
    # remains disabled unless COMPUTEMESH_IMAGE_GENERATION_ENABLED=1 and both a
    # generation backend and mandatory moderation service are configured. Missing
    # moderation therefore fails closed instead of exposing an unsafe model.
    return install_image_generation_routes(UnifiedLiveProtectedGatewayHandler)
