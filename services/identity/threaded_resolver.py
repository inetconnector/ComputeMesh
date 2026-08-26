"""Thread-safe read resolver for live node identity verification."""
from __future__ import annotations

from pathlib import Path

from protocol.node_identity import VerificationKey
from services.identity.store import SQLiteIdentityStore


class SQLiteIdentityKeyResolver:
    """Resolve keys using a connection created in the calling thread.

    The live control plane and inference gateway verify identities from worker
    threads. SQLiteIdentityStore owns a normal thread-affine sqlite connection, so
    sharing one instance across those threads is unsafe. This resolver keeps only
    the database path and opens a short-lived read connection per verification.
    """

    def __init__(self, path: str | Path):
        self.path = str(path)
        if not self.path:
            raise ValueError("identity database path is required")

    def resolve_key(self, node_id: str, key_id: str) -> VerificationKey:
        with SQLiteIdentityStore(self.path) as store:
            return store.resolve_key(node_id, key_id)
