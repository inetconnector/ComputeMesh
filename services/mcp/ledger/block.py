# SPDX-License-Identifier: Apache-2.0
"""
Block & Proof-of-Execution Receipt Data Models for ComputeMesh Ledger.
"""

from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional

from .merkle_tree import MerkleTree, sha256_hash


@dataclass
class ProofOfExecutionReceipt:
    """Tamper-evident receipt for a single tool or inference execution job."""
    receipt_id: str
    timestamp: float
    tool_name: str
    task_hash: str
    code_ast_hash: str
    inputs_hash: str
    outputs_hash: str
    elapsed_seconds: float
    node_id: str
    status: str = "verified_success"
    block_index: Optional[int] = None

    @classmethod
    def create(
        cls,
        tool_name: str,
        task_description: str,
        code: str,
        inputs: Dict[str, Any],
        outputs: Dict[str, Any],
        elapsed_seconds: float,
        node_id: str = "node_mesh_primary",
        status: str = "verified_success",
    ) -> ProofOfExecutionReceipt:
        t = time.time()
        t_hash = sha256_hash(task_description or "none")
        c_hash = sha256_hash(code or "builtin")
        i_hash = sha256_hash(json.dumps(inputs, sort_keys=True, ensure_ascii=False))
        o_hash = sha256_hash(json.dumps(outputs, sort_keys=True, ensure_ascii=False))
        
        # Unique receipt ID derived from constituent execution hashes
        receipt_seed = f"{t}:{tool_name}:{t_hash}:{c_hash}:{i_hash}:{o_hash}:{node_id}"
        receipt_id = f"poe_{sha256_hash(receipt_seed)[:16]}"

        return cls(
            receipt_id=receipt_id,
            timestamp=t,
            tool_name=tool_name,
            task_hash=t_hash,
            code_ast_hash=c_hash,
            inputs_hash=i_hash,
            outputs_hash=o_hash,
            elapsed_seconds=round(elapsed_seconds, 4),
            node_id=node_id,
            status=status,
        )

    def compute_leaf_hash(self) -> str:
        """Returns canonical leaf hash representing this receipt in the Merkle Tree."""
        payload = (
            f"{self.receipt_id}:{self.timestamp}:{self.tool_name}:{self.task_hash}:"
            f"{self.code_ast_hash}:{self.inputs_hash}:{self.outputs_hash}:"
            f"{self.elapsed_seconds}:{self.node_id}:{self.status}"
        )
        return sha256_hash(payload)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class LedgerBlock:
    """Cryptographically chained block anchoring a batch of execution receipts."""
    index: int
    timestamp: float
    prev_hash: str
    merkle_root: str
    receipt_count: int
    receipt_leaf_hashes: List[str]
    node_id: str
    block_hash: str = ""

    @classmethod
    def create(
        cls,
        index: int,
        prev_hash: str,
        receipts: List[ProofOfExecutionReceipt],
        node_id: str = "node_mesh_primary",
    ) -> LedgerBlock:
        t = time.time()
        leaf_hashes = [r.compute_leaf_hash() for r in receipts] if receipts else [sha256_hash("EMPTY_BLOCK")]
        tree = MerkleTree(leaf_hashes)
        m_root = tree.root

        header_str = f"{index}:{t}:{prev_hash}:{m_root}:{len(receipts)}:{node_id}"
        b_hash = sha256_hash(header_str)

        block = cls(
            index=index,
            timestamp=t,
            prev_hash=prev_hash,
            merkle_root=m_root,
            receipt_count=len(receipts),
            receipt_leaf_hashes=leaf_hashes,
            node_id=node_id,
            block_hash=b_hash,
        )
        for r in receipts:
            r.block_index = index
        return block

    def verify_integrity(self, expected_prev_hash: str) -> bool:
        """Verifies block header digest and chain connectivity."""
        if self.prev_hash != expected_prev_hash:
            return False
        header_str = f"{self.index}:{self.timestamp}:{self.prev_hash}:{self.merkle_root}:{self.receipt_count}:{self.node_id}"
        return sha256_hash(header_str) == self.block_hash

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)
