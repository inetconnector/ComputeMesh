# SPDX-License-Identifier: Apache-2.0
"""
ComputeMesh Multi-Node Ledger Sync & Gossip Engine.
Enables cryptographically verified P2P/RPC block and PoE receipt replication across cluster nodes.
"""

from __future__ import annotations

import json
import logging
import urllib.request
import urllib.error
from typing import Any, Dict, List, Optional, Tuple

from .block import LedgerBlock, ProofOfExecutionReceipt
from .merkle_tree import MerkleTree
from .compact_chain import CompactLedger, get_compact_ledger, GENESIS_PREV_HASH

logger = logging.getLogger("ComputeMesh.MCP.LedgerSync")


class LedgerSyncEngine:
    """Orchestrates block replication, cryptographic validation, and broadcast across fleet nodes."""

    def __init__(self, ledger: Optional[CompactLedger] = None) -> None:
        self.ledger = ledger or get_compact_ledger()

    def get_blocks_since(self, since_index: int = -1, limit: int = 50) -> List[Dict[str, Any]]:
        """Extracts sequential blocks and their receipts starting immediately after since_index."""
        safe_limit = max(1, min(100, limit))
        with self.ledger._db_session() as conn:
            cur = conn.cursor()
            cur.execute(
                """
                SELECT block_index, timestamp, prev_hash, merkle_root, receipt_count,
                       receipt_leaf_hashes, node_id, block_hash
                FROM blocks
                WHERE block_index > ?
                ORDER BY block_index ASC
                LIMIT ?
                """,
                (since_index, safe_limit),
            )
            rows = cur.fetchall()
            results = []
            for r in rows:
                b_idx = r[0]
                block_obj = LedgerBlock(
                    index=b_idx,
                    timestamp=r[1],
                    prev_hash=r[2],
                    merkle_root=r[3],
                    receipt_count=r[4],
                    receipt_leaf_hashes=json.loads(r[5]),
                    node_id=r[6],
                    block_hash=r[7],
                )

                # Fetch receipts for this block
                cur.execute(
                    """
                    SELECT receipt_id, timestamp, tool_name, task_hash, code_ast_hash,
                           inputs_hash, outputs_hash, elapsed_seconds, node_id, status, block_index
                    FROM receipts
                    WHERE block_index = ?
                    ORDER BY timestamp ASC
                    """,
                    (b_idx,),
                )
                r_rows = cur.fetchall()
                receipts = []
                for rr in r_rows:
                    receipts.append({
                        "receipt_id": rr[0],
                        "timestamp": rr[1],
                        "tool_name": rr[2],
                        "task_hash": rr[3],
                        "code_ast_hash": rr[4],
                        "inputs_hash": rr[5],
                        "outputs_hash": rr[6],
                        "elapsed_seconds": rr[7],
                        "node_id": rr[8],
                        "status": rr[9],
                        "block_index": rr[10],
                    })

                results.append({
                    "block": block_obj.to_dict(),
                    "receipts": receipts,
                })

            return results

    def ingest_remote_block(
        self,
        block_data: Dict[str, Any],
        receipts_data: List[Dict[str, Any]],
    ) -> Tuple[bool, str]:
        """Validates the cryptographic integrity of an incoming remote block and writes it to the local chain."""
        try:
            block = LedgerBlock(
                index=int(block_data["index"]),
                timestamp=float(block_data["timestamp"]),
                prev_hash=str(block_data["prev_hash"]),
                merkle_root=str(block_data["merkle_root"]),
                receipt_count=int(block_data["receipt_count"]),
                receipt_leaf_hashes=list(block_data.get("receipt_leaf_hashes", [])),
                node_id=str(block_data["node_id"]),
                block_hash=str(block_data["block_hash"]),
            )

            # Check if block already exists
            existing = self.ledger.get_block_by_index(block.index, include_receipts=False)
            if existing:
                if existing.get("block_hash") == block.block_hash:
                    return True, f"Block #{block.index} existiert bereits und ist identisch."
                return False, f"Konflikt: Lokaler Block #{block.index} hat abweichenden Hash."

            # Verify previous block hash links correctly
            if block.index > 0:
                prev_block = self.ledger.get_block_by_index(block.index - 1, include_receipts=False)
                if not prev_block:
                    return False, f"Fehlender Vorgänger-Block #{block.index - 1}. Synchronisation erforderlich."
                if prev_block.get("block_hash") != block.prev_hash:
                    return False, f"Ungültiger prev_hash in Block #{block.index}. Vorgänger-Hash stimmt nicht überein."
            else:
                if block.prev_hash != GENESIS_PREV_HASH:
                    return False, "Genesis Block hat ungültigen prev_hash."

            # Reconstruct Receipts and verify leaf hashes
            reconstructed_receipts: List[ProofOfExecutionReceipt] = []
            leaf_hashes: List[str] = []
            for rd in receipts_data:
                r_obj = ProofOfExecutionReceipt(
                    receipt_id=rd["receipt_id"],
                    timestamp=float(rd["timestamp"]),
                    tool_name=rd["tool_name"],
                    task_hash=rd["task_hash"],
                    code_ast_hash=rd["code_ast_hash"],
                    inputs_hash=rd["inputs_hash"],
                    outputs_hash=rd["outputs_hash"],
                    elapsed_seconds=float(rd["elapsed_seconds"]),
                    node_id=rd["node_id"],
                    status=rd.get("status", "verified_success"),
                    block_index=block.index,
                )
                reconstructed_receipts.append(r_obj)
                leaf_hashes.append(r_obj.compute_leaf_hash())

            # Verify leaf hashes match block
            if leaf_hashes != block.receipt_leaf_hashes:
                return False, "Berechnete Receipt-Leaf-Hashes stimmen nicht mit Block-Header überein."

            # Verify Merkle Root
            tree = MerkleTree(leaf_hashes)
            if tree.root != block.merkle_root:
                return False, f"Merkle-Root Diskrepanz: Erwartet {block.merkle_root}, berechnet {tree.root}."

            # Verify Block Hash
            expected_prev = block.prev_hash
            if not block.verify_integrity(expected_prev):
                return False, "Block-Hash Integritätsprüfung fehlgeschlagen (Header manipuliert)."

            # Commit to local SQLite ledger
            self.ledger.ingest_block_direct(block, reconstructed_receipts)
            logger.info(f"Erfolgreich Remote-Block #{block.index} ({block.block_hash[:16]}) synchronisiert.")
            return True, f"Block #{block.index} erfolgreich verifiziert und synchronisiert."

        except Exception as exc:
            logger.error(f"Fehler bei Ingestion von Remote-Block: {exc}", exc_info=True)
            return False, f"Ausnahmefehler bei Block-Ingestion: {exc}"

    def sync_from_peer(
        self,
        peer_url: str,
        auth_token: Optional[str] = None,
        timeout: float = 8.0,
    ) -> Dict[str, Any]:
        """Fetches and applies missing blocks sequentially from a peer node."""
        clean_url = peer_url.rstrip("/")
        stats = self.ledger.get_stats()
        current_height = stats.get("block_height", 0)

        sync_endpoint = f"{clean_url}/v1/mcp/ledger/sync?since={current_height}"
        req = urllib.request.Request(sync_endpoint, method="GET")
        req.add_header("User-Agent", "ComputeMesh-LedgerSync/1.0")
        if auth_token:
            req.add_header("Authorization", f"Bearer {auth_token}")

        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                if resp.status != 200:
                    return {
                        "success": False,
                        "error": f"Peer antwortete mit HTTP {resp.status}",
                        "peer_url": peer_url,
                    }
                data = json.loads(resp.read().decode("utf-8"))

            blocks_to_sync = data.get("blocks", [])
            synced_count = 0
            for item in blocks_to_sync:
                b_dict = item.get("block")
                r_list = item.get("receipts", [])
                if not b_dict:
                    continue
                ok, msg = self.ingest_remote_block(b_dict, r_list)
                if not ok:
                    return {
                        "success": False,
                        "error": f"Abbruch bei Block #{b_dict.get('index')}: {msg}",
                        "synced_count": synced_count,
                        "peer_url": peer_url,
                    }
                synced_count += 1

            new_stats = self.ledger.get_stats()
            return {
                "success": True,
                "synced_count": synced_count,
                "previous_height": current_height,
                "new_height": new_stats.get("block_height", current_height),
                "peer_url": peer_url,
            }

        except urllib.error.URLError as exc:
            return {"success": False, "error": f"Verbindungsfehler zu Peer '{peer_url}': {exc}", "peer_url": peer_url}
        except Exception as exc:
            return {"success": False, "error": f"Synchronisationsfehler: {exc}", "peer_url": peer_url}

    def broadcast_block(
        self,
        block: LedgerBlock,
        receipts: List[ProofOfExecutionReceipt],
        peer_urls: List[str],
        timeout: float = 3.0,
    ) -> Dict[str, Any]:
        """Broadcasts a newly sealed block and its receipts to peer cluster nodes."""
        payload = json.dumps({
            "block": block.to_dict(),
            "receipts": [r.to_dict() for r in receipts],
        }, ensure_ascii=False).encode("utf-8")

        results = {}
        for peer in peer_urls:
            clean_url = peer.rstrip("/")
            broadcast_endpoint = f"{clean_url}/v1/mcp/ledger/blocks/broadcast"
            req = urllib.request.Request(broadcast_endpoint, data=payload, method="POST")
            req.add_header("Content-Type", "application/json; charset=utf-8")
            req.add_header("User-Agent", "ComputeMesh-LedgerGossip/1.0")
            try:
                with urllib.request.urlopen(req, timeout=timeout) as resp:
                    results[peer] = {"status": resp.status, "ok": resp.status == 200}
            except Exception as exc:
                results[peer] = {"status": 0, "ok": False, "error": str(exc)}

        return {"broadcast_count": len(peer_urls), "results": results}


_global_sync_engine: Optional[LedgerSyncEngine] = None


def get_ledger_sync_engine() -> LedgerSyncEngine:
    """Returns singleton instance of the ComputeMesh Ledger Sync Engine."""
    global _global_sync_engine
    if _global_sync_engine is None:
        _global_sync_engine = LedgerSyncEngine()
    return _global_sync_engine
