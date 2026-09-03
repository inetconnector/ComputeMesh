"""Authenticated provider-control handler for fresh confidential sessions.

Provisioning rides the existing Ed25519-authenticated persistent NodeSession. The
private broker supplies both the durable job id and a fresh random challenge; the
provider returns only one attested endpoint for that exact content-free contract.
"""
from __future__ import annotations

from typing import Any, Mapping

from protocol.node_session import SessionSnapshot
from runtime.confidential.protected_worker import (
    CONFIDENTIAL_PROVISION_CAPABILITY,
    ProtectedWorkerError,
    ProtectedWorkerSessionManager,
    decode_freshness_challenge,
)


CONFIDENTIAL_PROVISION_MESSAGE = "ConfidentialSessionProvisionRequest"


class ConfidentialProviderControlError(RuntimeError):
    pass


def handle_confidential_provision_request(
    *,
    payload: Mapping[str, Any],
    session: SessionSnapshot,
    manager: ProtectedWorkerSessionManager,
) -> dict[str, Any]:
    """Provision exactly one session through an already authenticated NodeSession."""
    if CONFIDENTIAL_PROVISION_CAPABILITY not in session.negotiated_capabilities:
        raise ConfidentialProviderControlError("confidential provision capability was not negotiated")
    if session.node_id != manager.node_id:
        raise ConfidentialProviderControlError("protected worker identity does not match authenticated node")
    expected = {"session_id", "session_revision", "freshness_challenge", "request"}
    if not isinstance(payload, Mapping) or set(payload) != expected:
        raise ConfidentialProviderControlError("invalid confidential provider-control contract")
    if payload.get("session_id") != session.session_id:
        raise ConfidentialProviderControlError("confidential request is bound to another control session")
    if payload.get("session_revision") != session.revision:
        raise ConfidentialProviderControlError("confidential request uses a stale control-session revision")
    request = payload.get("request")
    if not isinstance(request, Mapping):
        raise ConfidentialProviderControlError("confidential provision request is missing")
    model_id = request.get("model_id")
    supports_model = getattr(manager.backend, "supports_model", None)
    if not isinstance(model_id, str) or not model_id:
        raise ConfidentialProviderControlError("confidential provision model is invalid")
    if not callable(supports_model):
        raise ConfidentialProviderControlError("protected runtime cannot prove model availability")
    try:
        if supports_model(model_id) is not True:
            raise ConfidentialProviderControlError("requested model is not loaded in protected runtime")
        challenge = decode_freshness_challenge(payload.get("freshness_challenge"))
        provision = manager.provision(request, freshness_challenge=challenge)
    except ProtectedWorkerError as exc:
        raise ConfidentialProviderControlError("protected worker rejected confidential provision") from exc
    return {
        "session_id": session.session_id,
        "session_revision": session.revision,
        "node_id": manager.node_id,
        "provision": provision,
    }
