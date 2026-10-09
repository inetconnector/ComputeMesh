"""Authenticated NodeOS transport for authorization-gated model preparation."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Mapping

from protocol.node_session import NodeSessionState, SessionSnapshot
from protocol.session_contracts import SessionMessageContractValidator
from services.orchestrator.persistent_control_channel import PersistentNodeControlClient


class ModelPreparationTransportError(RuntimeError):
    """Raised when a model preparation request cannot be authenticated safely."""


class AuthenticatedModelPreparationClient:
    """Adapt a live authenticated NodeOS channel to the preparation boundary.

    The coordinator remains responsible for authorization and model policy. This
    client only transports an already approved, digest-bound request to the
    exact authenticated node selected by the registry.
    """

    def __init__(
        self,
        control_client: PersistentNodeControlClient,
        *,
        required_capability: str = "model_preparation_v1",
        timeout_seconds: float = 300.0,
    ) -> None:
        if control_client is None:
            raise ValueError("control_client is required")
        if not 0 < float(timeout_seconds) <= 300:
            raise ValueError("timeout_seconds must be within (0,300]")
        capability = str(required_capability or "").strip()
        if not 1 <= len(capability) <= 128:
            raise ValueError("required_capability is invalid")
        self.control_client = control_client
        self.required_capability = capability
        self.timeout_seconds = float(timeout_seconds)
        self.contracts = SessionMessageContractValidator()

    @staticmethod
    def _session_ready(session: SessionSnapshot, *, node_id: str) -> None:
        if session.node_id != node_id or not session.session_id:
            raise ModelPreparationTransportError("model preparation session binding mismatch")
        if session.state is not NodeSessionState.READY:
            raise ModelPreparationTransportError("node session is not ready for model preparation")
        expires = session.credential_expires_at
        if expires <= datetime.now(timezone.utc):
            raise ModelPreparationTransportError("node session credential has expired")

    def __call__(self, node: Any, request: Mapping[str, Any]) -> Mapping[str, Any]:
        node_id = str(getattr(node, "node_id", "") or "")
        if not node_id:
            raise ModelPreparationTransportError("model preparation node is missing")
        if not isinstance(request, Mapping) or request.get("operation") != "prepare_model":
            raise ModelPreparationTransportError("unsupported model preparation operation")
        model = request.get("model")
        if not isinstance(model, Mapping):
            raise ModelPreparationTransportError("model preparation request lacks a model object")
        session = self.control_client.session_for(node_id)
        self._session_ready(session, node_id=node_id)
        capabilities = {str(value) for value in (session.negotiated_capabilities or ())}
        if self.required_capability not in capabilities:
            raise ModelPreparationTransportError("node session lacks model preparation capability")
        payload: dict[str, Any] = {
            "schema_version": 1,
            "session_id": session.session_id,
            "session_revision": int(session.revision),
            "node_id": node_id,
            "model_id": str(model.get("model_id") or ""),
            "artifact_digest": str(model.get("artifact_digest") or ""),
            "size_bytes": int(model.get("size_bytes") or 0),
            "idempotency_key": str(request.get("idempotency_key") or ""),
        }
        for key in ("capabilities", "context_tokens", "source"):
            if key in model:
                value = model[key]
                payload[key] = list(value) if key == "capabilities" and isinstance(value, (tuple, set)) else value
        try:
            self.contracts.validate("ModelPreparationRequest", payload)
            response = self.control_client.request(
                node_id=node_id,
                message_type="ModelPreparationRequest",
                payload=payload,
                timeout_seconds=self.timeout_seconds,
            )
            self.contracts.validate("ModelPreparationResponse", response)
        except Exception as exc:
            if isinstance(exc, ModelPreparationTransportError):
                raise
            raise ModelPreparationTransportError("model preparation transport failed") from exc
        if response.get("session_id") != session.session_id or response.get("session_revision") != session.revision:
            raise ModelPreparationTransportError("model preparation response session binding mismatch")
        if response.get("node_id") != node_id:
            raise ModelPreparationTransportError("model preparation response node binding mismatch")
        if response.get("model_id") != payload["model_id"]:
            raise ModelPreparationTransportError("model preparation response model binding mismatch")
        expected_digest = payload["artifact_digest"].lower().removeprefix("sha256:")
        returned_digest = str(response.get("artifact_digest") or "").lower().removeprefix("sha256:")
        if returned_digest != expected_digest:
            raise ModelPreparationTransportError("model preparation response digest mismatch")
        return dict(response)


__all__ = ["AuthenticatedModelPreparationClient", "ModelPreparationTransportError"]
