"""Compatibility wrapper for the internal protected-transport gateway mixin.

New canonical servers should compose :class:`ProtectedTransportMixin` directly.
This named handler remains for focused tests and transitional imports only.
"""
from __future__ import annotations

from services.gateway.confidential_owner_handler import ConfidentialOwnerGatewayHandler
from services.gateway.protected_transport_mixin import (
    INTERNAL_CONFIDENTIAL_COMPLETION_PATH,
    INTERNAL_CONFIDENTIAL_SESSION_PATH,
    INTERNAL_CONFIDENTIAL_STREAM_PATH,
    LEGACY_PUBLIC_CONFIDENTIAL_PATHS,
    ProtectedTransportMixin,
)


class InternalConfidentialOwnerGatewayHandler(
    ProtectedTransportMixin,
    ConfidentialOwnerGatewayHandler,
):
    """Transitional concrete handler; user-facing legacy aliases remain blocked."""


__all__ = [
    "INTERNAL_CONFIDENTIAL_COMPLETION_PATH",
    "INTERNAL_CONFIDENTIAL_SESSION_PATH",
    "INTERNAL_CONFIDENTIAL_STREAM_PATH",
    "LEGACY_PUBLIC_CONFIDENTIAL_PATHS",
    "InternalConfidentialOwnerGatewayHandler",
]
