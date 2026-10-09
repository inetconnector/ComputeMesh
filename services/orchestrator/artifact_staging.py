"""Resumable, authenticated staging of control-plane artifacts into Mesh envs."""
from __future__ import annotations

import base64
import uuid
from typing import Any

from services.mcp.platform.artifacts import ArtifactStore
from services.mcp.platform.environment import (
    BoundedEnvironmentExecutor,
    EnvironmentOperation,
    EnvironmentRequest,
)


class ArtifactStagingError(RuntimeError):
    """Raised when an artifact cannot be staged into a Mesh environment."""


class ArtifactStager:
    """Copy an immutable artifact through a bounded environment lease.

    The control plane remains the only artifact source. The node receives only
    verified chunks and a relative workspace path, never a host filesystem path
    or a generic file/command request.
    """

    def __init__(self, artifact_store: ArtifactStore, *, chunk_size: int = 512 * 1024) -> None:
        if not isinstance(artifact_store, ArtifactStore):
            raise TypeError("artifact_store must be an ArtifactStore")
        if not 1 <= int(chunk_size) <= 512 * 1024:
            raise ValueError("chunk_size must be between 1 and 524288 bytes")
        self.artifact_store = artifact_store
        self.chunk_size = int(chunk_size)

    def stage(
        self,
        executor: BoundedEnvironmentExecutor,
        ref_id: str,
        *,
        principal_id: str,
        target_path: str,
        overwrite: bool = False,
    ) -> dict[str, Any]:
        ref = self.artifact_store.get_ref(ref_id, principal_id=principal_id)
        if not ref.artifact_id.startswith("sha256:"):
            raise ArtifactStagingError("artifact reference does not contain a sha256 digest")
        digest = ref.artifact_id.removeprefix("sha256:")
        if len(digest) != 64:
            raise ArtifactStagingError("artifact digest is invalid")

        status = self._status(executor, target_path, ref.artifact_id, ref.size_bytes)
        if status.get("artifact_id") not in {None, ref.artifact_id}:
            raise ArtifactStagingError("node returned a different artifact identity")
        try:
            if int(status.get("size_bytes", ref.size_bytes)) != ref.size_bytes:
                raise ArtifactStagingError("node returned a different artifact size")
        except (TypeError, ValueError) as exc:
            raise ArtifactStagingError("node returned an invalid artifact size") from exc
        offset = int(status.get("next_offset", 0))
        if bool(status.get("complete")):
            return {"ref_id": ref.ref_id, "artifact_id": ref.artifact_id, "path": target_path, "size_bytes": ref.size_bytes, "complete": True, "resumed": offset > 0}
        if offset < 0 or offset > ref.size_bytes:
            raise ArtifactStagingError("node returned an invalid staging offset")

        while offset < ref.size_bytes or (ref.size_bytes == 0 and offset == 0):
            chunk = self.artifact_store.read_chunk(
                ref.ref_id,
                principal_id=principal_id,
                offset=offset,
                length=min(self.chunk_size, max(1, ref.size_bytes - offset)),
            ) if ref.size_bytes else None
            data = chunk.data if chunk is not None else b""
            next_offset = offset + len(data)
            final = next_offset == ref.size_bytes
            request = EnvironmentRequest(
                request_id=self._request_id("artifact_stage"),
                operation=EnvironmentOperation.ARTIFACT_STAGE,
                payload={
                    "path": target_path,
                    "artifact_id": ref.artifact_id,
                    "total_bytes": ref.size_bytes,
                    "offset": offset,
                    "content_base64": base64.b64encode(data).decode("ascii"),
                    "final": final,
                    "overwrite": bool(overwrite),
                },
                idempotency_key=f"artifact_stage_{digest}_{offset}",
            )
            result = dict(executor.execute(request))
            reported = int(result.get("next_offset", -1))
            if (
                reported != next_offset
                or bool(result.get("complete")) != final
                or result.get("artifact_id") not in {None, ref.artifact_id}
            ):
                raise ArtifactStagingError("node returned an invalid artifact staging result")
            offset = reported
            if final:
                return {
                    "ref_id": ref.ref_id,
                    "artifact_id": ref.artifact_id,
                    "path": target_path,
                    "size_bytes": ref.size_bytes,
                    "complete": True,
                    "resumed": bool(status.get("next_offset", 0)),
                }
        raise ArtifactStagingError("artifact staging did not make progress")

    @staticmethod
    def _request_id(prefix: str) -> str:
        return f"{prefix}_{uuid.uuid4().hex}"

    def _status(
        self,
        executor: BoundedEnvironmentExecutor,
        target_path: str,
        artifact_id: str,
        total_bytes: int,
    ) -> dict[str, Any]:
        result = executor.execute(
            EnvironmentRequest(
                request_id=self._request_id("artifact_stage_status"),
                operation=EnvironmentOperation.ARTIFACT_STAGE_STATUS,
                payload={"path": target_path, "artifact_id": artifact_id, "total_bytes": total_bytes},
            )
        )
        return dict(result)


__all__ = ["ArtifactStager", "ArtifactStagingError"]
