# SPDX-License-Identifier: Apache-2.0
"""
Persistent Custom Tool Store for ComputeMesh.
Enables permanent storage, tagging, AST validation, execution metering, and auto-registration
of user-defined and AI-synthesized dynamic tools into the MCP ecosystem.
"""

from __future__ import annotations

import contextlib
import json
import logging
import os
import re
import sqlite3
import threading
import time
from typing import Any, Dict, Generator, List, Optional, Tuple

from .ast_security_guard import ASTSecurityGuard, SecurityViolationError
from .sandbox_runner import SandboxRunner, SandboxExecutionError
from ..ledger import get_compact_ledger

logger = logging.getLogger("ComputeMesh.MCP.CustomToolStore")

TOOL_NAME_PATTERN = re.compile(r"^[a-zA-Z0-9_-]{2,64}$")


class CustomToolStore:
    """Manages persistent custom tool artifacts, schemas, security verification, and lifecycle."""

    def __init__(self, db_path: Optional[str] = None) -> None:
        self.db_path = db_path or os.path.join(os.path.dirname(__file__), "custom_tools.db")
        self.security_guard = ASTSecurityGuard()
        self.sandbox_runner = SandboxRunner(timeout_seconds=15, max_memory_mb=256)
        self._lock = threading.Lock()
        self._init_db()

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
                CREATE TABLE IF NOT EXISTS custom_tools (
                    name TEXT PRIMARY KEY,
                    description TEXT NOT NULL,
                    parameters TEXT NOT NULL,
                    code TEXT NOT NULL,
                    tags TEXT NOT NULL,
                    author_node TEXT NOT NULL,
                    version TEXT NOT NULL DEFAULT '1.0.0',
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL,
                    execution_count INTEGER DEFAULT 0,
                    avg_elapsed_ms REAL DEFAULT 0.0,
                    receipt_count INTEGER DEFAULT 0,
                    is_enabled INTEGER DEFAULT 1
                )
            """)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_custom_tools_tags ON custom_tools(tags)")

    def save_tool(
        self,
        name: str,
        description: str,
        parameters: Dict[str, Any],
        code: str,
        tags: Optional[List[str]] = None,
        author_node: str = "local_node",
        version: str = "1.0.0",
    ) -> Dict[str, Any]:
        """Validates and persists a custom tool into the store."""
        clean_name = str(name).strip()
        if not TOOL_NAME_PATTERN.match(clean_name):
            raise ValueError(f"Ungültiger Tool-Name '{clean_name}'. Nur 2-64 alphanumerische Zeichen, Bindestrich und Unterstrich erlaubt.")

        clean_desc = str(description).strip()
        if not clean_desc:
            raise ValueError("Tool-Beschreibung darf nicht leer sein.")

        clean_code = str(code).strip()
        if not clean_code:
            raise ValueError("Tool-Code darf nicht leer sein.")

        # Perform Zero-Trust AST Static Analysis
        ast_valid, ast_err = self.security_guard.validate(clean_code)
        if not ast_valid:
            raise SecurityViolationError(f"AST-Sicherheitsverstoß im Tool-Code: {ast_err}")

        # Ensure parameters has valid structure
        params_schema = parameters if isinstance(parameters, dict) else {}
        if "type" not in params_schema:
            params_schema = {
                "type": "object",
                "properties": params_schema.get("properties", params_schema),
                "required": params_schema.get("required", []),
            }

        tags_list = list(tags) if isinstance(tags, list) else ["custom", "dynamic"]
        now = time.time()

        with self._lock:
            with self._db_session() as conn:
                cur = conn.cursor()
                cur.execute("SELECT created_at, execution_count, avg_elapsed_ms, receipt_count FROM custom_tools WHERE name = ?", (clean_name,))
                existing = cur.fetchone()

                created_at = existing[0] if existing else now
                exec_count = existing[1] if existing else 0
                avg_ms = existing[2] if existing else 0.0
                r_count = existing[3] if existing else 0

                conn.execute(
                    """
                    INSERT OR REPLACE INTO custom_tools (
                        name, description, parameters, code, tags, author_node,
                        version, created_at, updated_at, execution_count,
                        avg_elapsed_ms, receipt_count, is_enabled
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1)
                    """,
                    (
                        clean_name,
                        clean_desc,
                        json.dumps(params_schema, ensure_ascii=False),
                        clean_code,
                        json.dumps(tags_list, ensure_ascii=False),
                        str(author_node),
                        str(version),
                        created_at,
                        now,
                        exec_count,
                        avg_ms,
                        r_count,
                    ),
                )

        logger.info(f"Custom Tool '{clean_name}' (v{version}) erfolgreich im Persistent Tool Store gespeichert.")
        return self.get_tool(clean_name) or {}

    def get_tool(self, name: str) -> Optional[Dict[str, Any]]:
        """Retrieves full details of a single custom tool by name."""
        clean_name = str(name).strip()
        with self._db_session() as conn:
            cur = conn.cursor()
            cur.execute(
                """
                SELECT name, description, parameters, code, tags, author_node,
                       version, created_at, updated_at, execution_count,
                       avg_elapsed_ms, receipt_count, is_enabled
                FROM custom_tools WHERE name = ?
                """,
                (clean_name,),
            )
            row = cur.fetchone()
            if not row:
                return None

            return {
                "name": row[0],
                "description": row[1],
                "parameters": json.loads(row[2]),
                "code": row[3],
                "tags": json.loads(row[4]),
                "author_node": row[5],
                "version": row[6],
                "created_at": row[7],
                "updated_at": row[8],
                "execution_count": row[9],
                "avg_elapsed_ms": round(row[10], 2),
                "receipt_count": row[11],
                "is_enabled": bool(row[12]),
            }

    def list_tools(
        self,
        tag: Optional[str] = None,
        search: Optional[str] = None,
        enabled_only: bool = True,
    ) -> List[Dict[str, Any]]:
        """Lists custom tools with optional tag and text filtering."""
        with self._db_session() as conn:
            cur = conn.cursor()
            query = "SELECT name, description, parameters, tags, author_node, version, created_at, updated_at, execution_count, avg_elapsed_ms, receipt_count, is_enabled FROM custom_tools WHERE 1=1"
            params: List[Any] = []

            if enabled_only:
                query += " AND is_enabled = 1"

            if tag:
                query += " AND tags LIKE ?"
                params.append(f'%"{tag}"%')

            if search:
                query += " AND (name LIKE ? OR description LIKE ?)"
                params.extend([f"%{search}%", f"%{search}%"])

            query += " ORDER BY updated_at DESC"
            cur.execute(query, params)
            rows = cur.fetchall()

            tools = []
            for r in rows:
                tools.append({
                    "name": r[0],
                    "description": r[1],
                    "parameters": json.loads(r[2]),
                    "tags": json.loads(r[3]),
                    "author_node": r[4],
                    "version": r[5],
                    "created_at": r[6],
                    "updated_at": r[7],
                    "execution_count": r[8],
                    "avg_elapsed_ms": round(r[9], 2),
                    "receipt_count": r[10],
                    "is_enabled": bool(r[11]),
                })
            return tools

    def delete_tool(self, name: str) -> bool:
        """Removes a custom tool from persistent storage."""
        clean_name = str(name).strip()
        with self._lock:
            with self._db_session() as conn:
                cur = conn.cursor()
                cur.execute("DELETE FROM custom_tools WHERE name = ?", (clean_name,))
                deleted = cur.rowcount > 0
        if deleted:
            logger.info(f"Custom Tool '{clean_name}' aus dem Persistent Tool Store gelöscht.")
        return deleted

    def execute_tool(
        self,
        name: str,
        inputs: Dict[str, Any],
        node_id: str = "local_node",
    ) -> Dict[str, Any]:
        """Executes a custom tool securely in the sandbox and registers a Merkle PoE receipt."""
        tool = self.get_tool(name)
        if not tool:
            return {"error": f"Custom Tool '{name}' nicht gefunden.", "status": "tool_not_found"}
        if not tool.get("is_enabled", True):
            return {"error": f"Custom Tool '{name}' ist deaktiviert.", "status": "tool_disabled"}

        code = tool["code"]
        start_time = time.perf_counter()

        # Execute code in isolated subprocess sandbox
        sandbox_res = self.sandbox_runner.execute(code=code, inputs=inputs or {})
        elapsed_seconds = time.perf_counter() - start_time
        elapsed_ms = round(elapsed_seconds * 1000, 2)

        # Record PoE receipt in Cryptographic Merkle Ledger
        ledger = get_compact_ledger()
        receipt = ledger.record_execution(
            tool_name=f"custom:{name}",
            task_description=tool["description"],
            code=code,
            inputs=inputs or {},
            outputs=sandbox_res.output if sandbox_res.success else {"error": sandbox_res.error},
            elapsed_seconds=elapsed_seconds,
            node_id=node_id,
            status="verified_success" if sandbox_res.success else "execution_failed",
            force_commit=True,
        )

        # Update execution metrics in SQLite
        with self._lock:
            with self._db_session() as conn:
                cur = conn.cursor()
                old_count = tool.get("execution_count", 0)
                old_avg = tool.get("avg_elapsed_ms", 0.0)
                new_count = old_count + 1
                new_avg = ((old_avg * old_count) + elapsed_ms) / new_count
                conn.execute(
                    """
                    UPDATE custom_tools
                    SET execution_count = ?, avg_elapsed_ms = ?, receipt_count = receipt_count + 1
                    WHERE name = ?
                    """,
                    (new_count, new_avg, name),
                )

        return {
            "name": name,
            "success": sandbox_res.success,
            "output": sandbox_res.output,
            "error": sandbox_res.error,
            "stdout": sandbox_res.stdout,
            "elapsed_ms": elapsed_ms,
            "poe_receipt_id": receipt.receipt_id,
            "poe_status": receipt.status,
        }

    def load_into_registry(self, registry: Any) -> int:
        """Registers all active custom tools dynamically into an active MCP ToolRegistry."""
        tools = self.list_tools(enabled_only=True)
        registered_count = 0

        for t in tools:
            tool_name = t["name"]
            tool_desc = t["description"]
            tool_params = t["parameters"]

            def _make_runner(t_name: str):
                def _runner(**kwargs: Any) -> Dict[str, Any]:
                    return self.execute_tool(t_name, kwargs)
                return _runner

            try:
                registry.register_tool(
                    name=tool_name,
                    description=f"[Custom Tool] {tool_desc}",
                    parameters=tool_params,
                    handler=_make_runner(tool_name),
                    source="custom_store",
                )
                registered_count += 1
            except Exception as exc:
                logger.warning(f"Konnte Custom Tool '{tool_name}' nicht registrieren: {exc}")

        return registered_count


_global_custom_tool_store: Optional[CustomToolStore] = None


def get_custom_tool_store() -> CustomToolStore:
    """Returns singleton instance of CustomToolStore."""
    global _global_custom_tool_store
    if _global_custom_tool_store is None:
        _global_custom_tool_store = CustomToolStore()
    return _global_custom_tool_store
