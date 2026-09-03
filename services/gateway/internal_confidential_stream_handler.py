"""Compatibility wrapper for internal encrypted protected streaming."""
from __future__ import annotations

from services.gateway.confidential_owner_handler import ConfidentialOwnerGatewayHandler
from services.gateway.protected_transport_mixin import (
    INTERNAL_CONFIDENTIAL_COMPLETION_PATH,
    INTERNAL_CONFIDENTIAL_SESSION_PATH,
    INTERNAL_CONFIDENTIAL_STREAM_PATH,
    LEGACY_PUBLIC_CONFIDENTIAL_PATHS,
    ProtectedTransportMixin,
)


class StreamingInternalConfidentialOwnerGatewayHandler(
    ProtectedTransportMixin,
    ConfidentialOwnerGatewayHandler,
):
    """Transitional concrete handler; canonical servers compose the mixin directly."""


__all__ = [
    "INTERNAL_CONFIDENTIAL_COMPLETION_PATH",
    "INTERNAL_CONFIDENTIAL_SESSION_PATH",
    "INTERNAL_CONFIDENTIAL_STREAM_PATH",
    "LEGACY_PUBLIC_CONFIDENTIAL_PATHS",
    "StreamingInternalConfidentialOwnerGatewayHandler",
]
