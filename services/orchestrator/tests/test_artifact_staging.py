from __future__ import annotations

from pathlib import Path

import pytest
from services.mcp.platform.artifacts import ArtifactAccessDenied, ArtifactStore
from services.mcp.platform.environment import (
    BoundedEnvironmentExecutor,
    EnvironmentKind,
    EnvironmentLease,
    EnvironmentOperation,
    EnvironmentRequest,
    EnvironmentSpec,
    ResourceLimits,
)
from services.orchestrator.artifact_staging import ArtifactStager


class _Transport:
    def __init__(self) -> None:
        self.data = bytearray()

    def prepare(self, spec: EnvironmentSpec) -> EnvironmentLease:
        return EnvironmentLease("lease_stage", spec.environment_id, 100.0, 1000.0, 1)

    def heartbeat(self, lease: EnvironmentLease) -> EnvironmentLease:
        return EnvironmentLease(lease.lease_id, lease.environment_id, lease.issued_at, 1100.0, lease.revision + 1)

    def execute(self, lease: EnvironmentLease, request: EnvironmentRequest) -> dict[str, object]:
        if request.operation is EnvironmentOperation.ARTIFACT_STAGE_STATUS:
            return {"artifact_id": request.payload["artifact_id"], "next_offset": len(self.data), "complete": False, "size_bytes": 10}
        import base64
        chunk = base64.b64decode(str(request.payload["content_base64"]))
        assert int(request.payload["offset"]) == len(self.data)
        self.data.extend(chunk)
        return {"artifact_id": request.payload["artifact_id"], "next_offset": len(self.data), "complete": bool(request.payload["final"]), "size_bytes": 10}

    def shutdown(self, lease: EnvironmentLease, *, reason: str) -> None:
        return None


def test_artifact_stager_enforces_acl_and_transfers_chunks(tmp_path: Path) -> None:
    store = ArtifactStore(tmp_path / "store", tmp_path / "artifacts.sqlite")
    try:
        ref = store.put_bytes(
            b"0123456789",
            session_id="session-a",
            turn_id="turn-a",
            principal_id="principal-a",
            name="payload.bin",
            mime_type="application/octet-stream",
        )
        with pytest.raises(ArtifactAccessDenied):
            store.get_ref(ref.ref_id, principal_id="other")

        transport = _Transport()
        spec = EnvironmentSpec(
            "env_stage",
            "session-a",
            kind=EnvironmentKind.MESH,
            node_id="node-a",
            allowed_operations=frozenset({EnvironmentOperation.ARTIFACT_STAGE, EnvironmentOperation.ARTIFACT_STAGE_STATUS}),
            allowed_paths=("outputs",),
            resources=ResourceLimits(max_runtime_seconds=3600),
        )
        executor = BoundedEnvironmentExecutor(spec, transport=transport, clock=lambda: 100.0)
        executor.prepare()
        result = ArtifactStager(store, chunk_size=3).stage(
            executor, ref.ref_id, principal_id="principal-a", target_path="outputs/payload.bin"
        )
        assert result["complete"] is True
        assert bytes(transport.data) == b"0123456789"
    finally:
        store.close()
