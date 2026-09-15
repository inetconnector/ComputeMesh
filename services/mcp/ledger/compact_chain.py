# SPDX-License-Identifier: Apache-2.0
"""
Compact Cryptographic Ledger Engine for ComputeMesh.
Append-only chain with Merkle batching, SQLite storage, and tamper-evident proof validation.
"""

from __future__ import annotations

import contextlib
import json
import logging
import os
import sqlite3
import threading
import time
from typing import Any, Dict, Generator, List, Optional, Tuple

from .block import LedgerBlock, ProofOfExecutionReceipt
from .merkle_tree import MerkleTree, sha256_hash

logger = logging.getLogger("ComputeMesh.MCP.Ledger")

GENESIS_PREV_HASH = "0000000000000000000000000000000000000000000000000000000000000000"


class CompactLedger:
    """Manages the append-only cryptographic block chain and proof-of-execution receipts."""

    def __init__(self, db_path: Optional[str] = None, auto_commit_batch_size: int = 50) -> None:
        self.db_path = db_path or os.path.join(os.path.dirname(__file__), "computemesh_ledger.db")
        self.auto_commit_batch_size = auto_commit_batch_size
        self._lock = threading.Lock()
        self._pending_receipts: List[ProofOfExecutionReceipt] = []
        self._init_db()
        self._ensure_genesis()

    @contextlib.contextmanager
    def _db_session(self) -> Generator[sqlite3.Connection, None, None]:
        conn = sqlite3.connect(self.db_path, timeout=10.0)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    def _init_db(self) -> None:
        with self._db_session() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS blocks (
                    block_index INTEGER PRIMARY KEY,
                    timestamp REAL NOT NULL,
                    prev_hash TEXT NOT NULL,
                    merkle_root TEXT NOT NULL,
                    receipt_count INTEGER NOT NULL,
                    receipt_leaf_hashes TEXT NOT NULL,
                    node_id TEXT NOT NULL,
                    block_hash TEXT NOT NULL UNIQUE
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS receipts (
                    receipt_id TEXT PRIMARY KEY,
                    timestamp REAL NOT NULL,
                    tool_name TEXT NOT NULL,
                    task_hash TEXT NOT NULL,
                    code_ast_hash TEXT NOT NULL,
                    inputs_hash TEXT NOT NULL,
                    outputs_hash TEXT NOT NULL,
                    elapsed_seconds REAL NOT NULL,
                    node_id TEXT NOT NULL,
                    status TEXT NOT NULL,
                    block_index INTEGER,
                    FOREIGN KEY(block_index) REFERENCES blocks(block_index)
                )
            """)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_receipts_block ON receipts(block_index)")

    def _ensure_genesis(self) -> None:
        with self._lock:
            with self._db_session() as conn:
                cur = conn.cursor()
                cur.execute("SELECT COUNT(*) FROM blocks")
                count = cur.fetchone()[0]
                if count == 0:
                    genesis_receipt = ProofOfExecutionReceipt.create(
                        tool_name="genesis_init",
                        task_description="ComputeMesh Cryptographic Ledger Genesis Anchor",
                        code="genesis",
                        inputs={"genesis": True},
                        outputs={"status": "genesis_active"},
                        elapsed_seconds=0.0,
                        node_id="genesis_root",
                    )
                    genesis_block = LedgerBlock.create(
                        index=0,
                        prev_hash=GENESIS_PREV_HASH,
                        receipts=[genesis_receipt],
                        node_id="genesis_root",
                    )
                    self._write_block_and_receipts(conn, genesis_block, [genesis_receipt])
                    logger.info(f"Initialized ComputeMesh Genesis Block: {genesis_block.block_hash[:16]}")

    def _write_block_and_receipts(
        self,
        conn: sqlite3.Connection,
        block: LedgerBlock,
        receipts: List[ProofOfExecutionReceipt],
    ) -> None:
        conn.execute(
            """
            INSERT INTO blocks (
                block_index, timestamp, prev_hash, merkle_root, receipt_count,
                receipt_leaf_hashes, node_id, block_hash
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                block.index,
                block.timestamp,
                block.prev_hash,
                block.merkle_root,
                block.receipt_count,
                json.dumps(block.receipt_leaf_hashes),
                block.node_id,
                block.block_hash,
            ),
        )
        for r in receipts:
            conn.execute(
                """
                INSERT OR REPLACE INTO receipts (
                    receipt_id, timestamp, tool_name, task_hash, code_ast_hash,
                    inputs_hash, outputs_hash, elapsed_seconds, node_id, status, block_index
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    r.receipt_id,
                    r.timestamp,
                    r.tool_name,
                    r.task_hash,
                    r.code_ast_hash,
                    r.inputs_hash,
                    r.outputs_hash,
                    r.elapsed_seconds,
                    r.node_id,
                    r.status,
                    block.index,
                ),
            )

    def record_execution(
        self,
        tool_name: str,
        task_description: str,
        code: str,
        inputs: Dict[str, Any],
        outputs: Dict[str, Any],
        elapsed_seconds: float,
        node_id: str = "node_mesh_primary",
        status: str = "verified_success",
        force_commit: bool = False,
    ) -> ProofOfExecutionReceipt:
        """Records a new execution job and triggers batch commit if threshold is met."""
        receipt = ProofOfExecutionReceipt.create(
            tool_name=tool_name,
            task_description=task_description,
            code=code,
            inputs=inputs,
            outputs=outputs,
            elapsed_seconds=elapsed_seconds,
            node_id=node_id,
            status=status,
        )

        with self._lock:
            self._pending_receipts.append(receipt)
            if len(self._pending_receipts) >= self.auto_commit_batch_size or force_commit:
                self._commit_pending_batch_locked()

        return receipt

    def commit_block(self, node_id: str = "node_mesh_primary") -> Optional[LedgerBlock]:
        """Manually seals all pending execution receipts into a new block."""
        with self._lock:
            return self._commit_pending_batch_locked(node_id=node_id)

    def _commit_pending_batch_locked(self, node_id: str = "node_mesh_primary") -> Optional[LedgerBlock]:
        if not self._pending_receipts:
            return None

        receipts_to_commit = list(self._pending_receipts)
        self._pending_receipts.clear()

        with self._db_session() as conn:
            cur = conn.cursor()
            cur.execute("SELECT block_index, block_hash FROM blocks ORDER BY block_index DESC LIMIT 1")
            row = cur.fetchone()
            last_index = row[0] if row else -1
            last_hash = row[1] if row else GENESIS_PREV_HASH

            new_block = LedgerBlock.create(
                index=last_index + 1,
                prev_hash=last_hash,
                receipts=receipts_to_commit,
                node_id=node_id,
            )
            self._write_block_and_receipts(conn, new_block, receipts_to_commit)
            logger.info(f"Committed Ledger Block #{new_block.index} ({len(receipts_to_commit)} receipts, hash: {new_block.block_hash[:16]})")
            return new_block

    def get_receipt(self, receipt_id: str) -> Optional[Dict[str, Any]]:
        """Retrieves a receipt and its associated Merkle proof."""
        with self._db_session() as conn:
            cur = conn.cursor()
            cur.execute(
                """
                SELECT receipt_id, timestamp, tool_name, task_hash, code_ast_hash,
                       inputs_hash, outputs_hash, elapsed_seconds, node_id, status, block_index
                FROM receipts WHERE receipt_id = ?
                """,
                (receipt_id,),
            )
            row = cur.fetchone()
            if not row:
                return None

            receipt = ProofOfExecutionReceipt(
                receipt_id=row[0],
                timestamp=row[1],
                tool_name=row[2],
                task_hash=row[3],
                code_ast_hash=row[4],
                inputs_hash=row[5],
                outputs_hash=row[6],
                elapsed_seconds=row[7],
                node_id=row[8],
                status=row[9],
                block_index=row[10],
            )

            if receipt.block_index is None:
                return {
                    "receipt": receipt.to_dict(),
                    "block": None,
                    "merkle_proof": None,
                    "is_confirmed": False,
                }

            cur.execute(
                """
                SELECT block_index, timestamp, prev_hash, merkle_root, receipt_count,
                       receipt_leaf_hashes, node_id, block_hash
                FROM blocks WHERE block_index = ?
                """,
                (receipt.block_index,),
            )
            b_row = cur.fetchone()
            if not b_row:
                return {"receipt": receipt.to_dict(), "is_confirmed": False}

            block = LedgerBlock(
                index=b_row[0],
                timestamp=b_row[1],
                prev_hash=b_row[2],
                merkle_root=b_row[3],
                receipt_count=b_row[4],
                receipt_leaf_hashes=json.loads(b_row[5]),
                node_id=b_row[6],
                block_hash=b_row[7],
            )

            # Generate Merkle Proof
            leaf_hash = receipt.compute_leaf_hash()
            proof = None
            if leaf_hash in block.receipt_leaf_hashes:
                leaf_idx = block.receipt_leaf_hashes.index(leaf_hash)
                tree = MerkleTree(block.receipt_leaf_hashes)
                proof = tree.get_proof(leaf_idx)

            return {
                "receipt": receipt.to_dict(),
                "block": block.to_dict(),
                "merkle_proof": proof,
                "is_confirmed": True,
            }

    def verify_chain_integrity(self) -> Tuple[bool, Optional[str]]:
        """Verifies full cryptographic continuity of all blocks from Genesis to Head."""
        with self._db_session() as conn:
            cur = conn.cursor()
            cur.execute("SELECT block_index, timestamp, prev_hash, merkle_root, receipt_count, receipt_leaf_hashes, node_id, block_hash FROM blocks ORDER BY block_index ASC")
            rows = cur.fetchall()

            if not rows:
                return False, "Ledger ist leer (Kein Genesis Block vorhanden)."

            expected_prev = GENESIS_PREV_HASH
            for row in rows:
                block = LedgerBlock(
                    index=row[0],
                    timestamp=row[1],
                    prev_hash=row[2],
                    merkle_root=row[3],
                    receipt_count=row[4],
                    receipt_leaf_hashes=json.loads(row[5]),
                    node_id=row[6],
                    block_hash=row[7],
                )
                if not block.verify_integrity(expected_prev):
                    return False, f"Block #{block.index} ({block.block_hash[:16]}) ist korrupt oder manipuliert!"

                # Verify Merkle Root matches leaf hashes
                tree = MerkleTree(block.receipt_leaf_hashes)
                if tree.root != block.merkle_root:
                    return False, f"Merkle-Root in Block #{block.index} stimmt nicht mit Leaf-Hashes überein."

                expected_prev = block.block_hash

            return True, None

    def get_stats(self) -> Dict[str, Any]:
        """Returns high-level statistics for fleet monitoring and health checks."""
        with self._db_session() as conn:
            cur = conn.cursor()
            cur.execute("SELECT COUNT(*), MAX(block_index) FROM blocks")
            b_count, max_idx = cur.fetchone()
            cur.execute("SELECT COUNT(*) FROM receipts")
            r_count = cur.fetchone()[0]

            is_valid, err = self.verify_chain_integrity()
            db_size = os.path.getsize(self.db_path) if os.path.exists(self.db_path) else 0

            return {
                "block_height": max_idx if max_idx is not None else 0,
                "total_blocks": b_count or 0,
                "total_receipts": r_count or 0,
                "pending_receipts": len(self._pending_receipts),
                "is_chain_valid": is_valid,
                "integrity_error": err,
                "db_size_kb": round(db_size / 1024, 2),
            }


_global_ledger: Optional[CompactLedger] = None


def get_compact_ledger() -> CompactLedger:
    """Returns singleton instance of the ComputeMesh Compact Ledger."""
    global _global_ledger
    if _global_ledger is None:
        _global_ledger = CompactLedger()
    return _global_ledger
