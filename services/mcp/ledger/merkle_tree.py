# SPDX-License-Identifier: Apache-2.0
"""
Cryptographic Merkle Tree & Inclusion Proof Engine for ComputeMesh Ledger.
Enables mathematical verification of execution receipts with O(log N) proof size.
"""

from __future__ import annotations

import hashlib
from typing import List, Optional, Tuple


def sha256_hash(data: str | bytes) -> str:
    """Computes standard SHA-256 hexadecimal digest."""
    if isinstance(data, str):
        data = data.encode("utf-8")
    return hashlib.sha256(data).hexdigest()


def hash_pair(left: str, right: str) -> str:
    """Combines and hashes two adjacent tree node digests."""
    return sha256_hash(left + right)


class MerkleTree:
    """Computes balanced Merkle Trees and generates inclusion proofs."""

    def __init__(self, leaf_hashes: List[str]) -> None:
        self.leaf_hashes = list(leaf_hashes) if leaf_hashes else [sha256_hash("EMPTY_BLOCK_LEAF")]
        self.levels: List[List[str]] = [self.leaf_hashes]
        self._build_tree()

    def _build_tree(self) -> None:
        current_level = self.leaf_hashes
        while len(current_level) > 1:
            next_level: List[str] = []
            for i in range(0, len(current_level), 2):
                left = current_level[i]
                right = current_level[i + 1] if (i + 1 < len(current_level)) else left  # Duplicate odd leaf
                next_level.append(hash_pair(left, right))
            self.levels.append(next_level)
            current_level = next_level

    @property
    def root(self) -> str:
        """Returns the 32-byte hexadecimal Merkle Root digest."""
        return self.levels[-1][0]

    def get_proof(self, leaf_index: int) -> List[Tuple[str, str]]:
        """
        Generates an inclusion proof for a leaf at given index.
        Returns a list of tuples: (sibling_hash, 'left' | 'right').
        """
        if leaf_index < 0 or leaf_index >= len(self.leaf_hashes):
            raise IndexError("Leaf-Index außerhalb des gültigen Bereichs.")

        proof: List[Tuple[str, str]] = []
        idx = leaf_index

        for level in self.levels[:-1]:
            is_right = (idx % 2 == 1)
            sibling_idx = idx - 1 if is_right else idx + 1
            if sibling_idx >= len(level):
                sibling_idx = idx  # Paired with self
            sibling_hash = level[sibling_idx]
            proof.append((sibling_hash, "left" if is_right else "right"))
            idx //= 2

        return proof

    @staticmethod
    def verify_proof(leaf_hash: str, proof: List[Tuple[str, str]], expected_root: str) -> bool:
        """Mathematically verifies whether a leaf hash belongs to the given Merkle Root."""
        current = leaf_hash
        for sibling, position in proof:
            if position == "left":
                current = hash_pair(sibling, current)
            else:
                current = hash_pair(current, sibling)
        return current == expected_root
