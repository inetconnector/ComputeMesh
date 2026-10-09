"""Contract tests for immutable, scoped agent artifacts."""
from __future__ import annotations

import tempfile
import time
import unittest
from pathlib import Path

from services.mcp.platform.artifacts import ArtifactAccessDenied, ArtifactNotFound, ArtifactStore


class TestArtifactStore(unittest.TestCase):
    def test_content_addressing_acl_and_integrity(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = ArtifactStore(Path(directory) / "objects", Path(directory) / "artifacts.sqlite3")
            try:
                ref = store.put_bytes(
                    b"hello artifact",
                    session_id="sess_1",
                    turn_id="turn_1",
                    principal_id="user_1",
                    name="result.txt",
                    mime_type="text/plain",
                )
                replay = store.put_bytes(
                    b"hello artifact",
                    session_id="sess_1",
                    turn_id="turn_1",
                    principal_id="user_1",
                    name="copy.txt",
                    mime_type="text/plain",
                )
                self.assertEqual(ref.artifact_id, replay.artifact_id)
                self.assertEqual(store.read_bytes(ref.ref_id, principal_id="user_1"), b"hello artifact")
                with self.assertRaises(ArtifactAccessDenied):
                    store.read_bytes(ref.ref_id, principal_id="user_2")
            finally:
                store.close()

    def test_missing_or_expired_bytes_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = ArtifactStore(Path(directory) / "objects")
            try:
                with self.assertRaises(ArtifactNotFound):
                    store.get_ref("missing", principal_id="user_1")
                expires_at = time.time() + 100
                ref = store.put_bytes(
                    b"temporary",
                    session_id="sess_1",
                    turn_id="turn_1",
                    principal_id="user_1",
                    name="tmp.bin",
                    mime_type="application/octet-stream",
                    expires_at=expires_at,
                )
                self.assertEqual(store.purge_expired(now=expires_at + 1), 1)
                with self.assertRaises(ArtifactNotFound):
                    store.read_bytes(ref.ref_id, principal_id="user_1")
            finally:
                store.close()

    def test_shared_content_keeps_longer_lived_reference(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = ArtifactStore(Path(directory) / "objects")
            try:
                now = time.time()
                short = store.put_bytes(
                    b"shared",
                    session_id="sess_1",
                    turn_id="turn_1",
                    principal_id="user_1",
                    name="short.bin",
                    mime_type="application/octet-stream",
                    expires_at=now + 10,
                )
                long = store.put_bytes(
                    b"shared",
                    session_id="sess_1",
                    turn_id="turn_2",
                    principal_id="user_1",
                    name="long.bin",
                    mime_type="application/octet-stream",
                    expires_at=now + 100,
                )
                self.assertEqual(store.purge_expired(now=now + 20), 0)
                with self.assertRaises(ArtifactNotFound):
                    store.read_bytes(short.ref_id, principal_id="user_1")
                self.assertEqual(store.read_bytes(long.ref_id, principal_id="user_1"), b"shared")
            finally:
                store.close()

    def test_read_chunk_supports_bounded_resumable_transfer(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = ArtifactStore(Path(directory) / "objects")
            try:
                ref = store.put_bytes(
                    b"0123456789",
                    session_id="sess_1",
                    turn_id="turn_1",
                    principal_id="user_1",
                    name="result.bin",
                    mime_type="application/octet-stream",
                )
                chunk = store.read_chunk(ref.ref_id, principal_id="user_1", offset=3, length=4)
                self.assertEqual(chunk.data, b"3456")
                self.assertEqual(chunk.end_offset, 7)
                self.assertFalse(chunk.complete)
                with self.assertRaises(ValueError):
                    store.read_chunk(ref.ref_id, principal_id="user_1", offset=0, length=5 * 1024 * 1024)
                with self.assertRaises(ArtifactNotFound):
                    store.read_chunk(ref.ref_id, principal_id="user_1", offset=10, length=1)
            finally:
                store.close()


if __name__ == "__main__":
    unittest.main()
