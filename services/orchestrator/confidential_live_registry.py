"""Internal live-session snapshot for the private confidential broker.

This is not a public HTTP API. It exposes only authenticated control-session facts
to the trusted control-plane process so private policy can rank eligible providers.
"""
from __future__ import annotations

from dataclasses import dataclass

from protocol.node_session import SessionSnapshot
from runtime.confidential.protected_worker import CONFIDENTIAL_PROVISION_CAPABILITY
from services.orchestrator.live_shared_runtime import LiveSharedRuntimeRegistry


@dataclass(frozen=True)
class ConfidentialControlCandidate:
    node_id: str
    session: SessionSnapshot


class ConfidentialLiveRuntimeRegistry(LiveSharedRuntimeRegistry):
    def confidential_candidates(self) -> tuple[ConfidentialControlCandidate, ...]:
        with self._lock:
            snapshots = [state.session for state in self._nodes.values()]
        result: list[ConfidentialControlCandidate] = []
        for session in snapshots:
            node_id = session.node_id
            if not node_id:
                continue
            if CONFIDENTIAL_PROVISION_CAPABILITY not in session.negotiated_capabilities:
                continue
            if not self.is_node_control_healthy(node_id):
                continue
            result.append(ConfidentialControlCandidate(node_id=node_id, session=session))
        result.sort(key=lambda item: item.node_id)
        return tuple(result)
