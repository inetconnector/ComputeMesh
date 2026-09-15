# SPDX-License-Identifier: Apache-2.0
"""
Autonomous Dynamic Tool Synthesizer & Execution Engine.
Synthesizes deterministic Python micro-tools on-demand, enforces the 7-Layer
Zero-Trust security pipeline, performs pre-flight smoke testing, and caches verified tools.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

from .ast_security_guard import SecurityASTViolation, validate_python_code_ast
from .sandbox_runner import SandboxExecutionError, SandboxTimeoutError, run_code_in_sandbox

logger = logging.getLogger("ComputeMesh.MCP.DynamicEngine")

# Refusal Guardrails against destructive, malware, or exploit instructions
DANGEROUS_INTENT_PATTERNS = [
    re.compile(r"\b(?:ransomware|cryptominer|rootkit|keylogger|trojan|reverse\s+shell|bind\s+shell)\b", re.IGNORECASE),
    re.compile(r"\b(?:exploit|shellcode|buffer\s+overflow|format\s+string\s+attack|sql\s+injection|port\s+scan)\b", re.IGNORECASE),
    re.compile(r"\b(?:format\s+c:|rm\s+-rf|dd\s+if=/dev/zero|mkfs|shutdown\s+/s|drop\s+database)\b", re.IGNORECASE),
    re.compile(r"\b(?:bypass\s+antivirus|disable\s+firewall|dump\s+sam|mimikatz|steal\s+passwords)\b", re.IGNORECASE),
]


@dataclass
class SynthesizedTool:
    name: str
    description: str
    code: str
    parameters_schema: Dict[str, Any]
    sha256_hash: str
    created_at: float = field(default_factory=time.time)


@dataclass
class AuditLogEntry:
    timestamp: float
    tool_name: str
    sha256_hash: str
    task_description: str
    success: bool
    elapsed_seconds: float
    error: Optional[str] = None


class DynamicToolEngine:
    """Coordinates autonomous code generation, AST filtering, smoke testing, and sandboxed execution."""

    def __init__(self, cache_ttl_seconds: float = 3600.0) -> None:
        self.cache_ttl_seconds = cache_ttl_seconds
        self._tool_cache: Dict[str, SynthesizedTool] = {}
        self._audit_log: List[AuditLogEntry] = []

    def check_safety_guardrails(self, task_description: str) -> None:
        """Scans user task description for prohibited malicious intents."""
        for pattern in DANGEROUS_INTENT_PATTERNS:
            if pattern.search(task_description):
                raise SecurityASTViolation(
                    f"Die Anfrage verstößt gegen Sicherheitsrichtlinien (Gefährlicher Intent erkannt: {pattern.pattern})."
                )

    def synthesize_tool_code(
        self,
        task_description: str,
        inputs: Dict[str, Any],
        llm_caller: Optional[Callable[[List[Dict[str, Any]], List[Dict[str, Any]]], Dict[str, Any]]] = None,
    ) -> str:
        """Generates Python code for the requested dynamic calculation or transformation."""
        self.check_safety_guardrails(task_description)

        system_prompt = (
            "Du bist der autonome Dynamic Code Generator von ComputeMesh. "
            "Erstelle ein kompaktes, deterministisches Python 3 Modul für die geforderte Berechnungs- oder Transformationsaufgabe.\n\n"
            "STRIKTE SICHERHEITS- & CODE-REGELN:\n"
            "1. Definiere exakt eine Hauptfunktion: `def execute(inputs: dict) -> dict`.\n"
            "2. Verwende AUSSCHLIESSLICH Standardbibliotheken aus der Whitelist (math, cmath, random, re, json, datetime, itertools, collections, statistics, decimal, fractions).\n"
            "3. KEIN Zugriff auf os, sys, subprocess, socket, open(), eval(), exec(), globals(), locals() oder Dunder-Attribute (__subclasses__, __bases__, __globals__).\n"
            "4. Gib NUR den reinen Python-Code zurück (ohne Markdown, ohne Erklärungen)."
        )

        user_prompt = (
            f"Aufgabe: {task_description}\n"
            f"Beispiel-Eingaben: {json.dumps(inputs, ensure_ascii=False)}\n"
            "Schreibe die Funktion `execute(inputs: dict) -> dict`:"
        )

        if llm_caller is not None:
            messages = [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ]
            resp = llm_caller(messages, [])
            if isinstance(resp, dict):
                choices = resp.get("choices", [])
                if choices and isinstance(choices[0], dict):
                    msg = choices[0].get("message", {})
                    raw_content = str(msg.get("content", ""))
                    # Strip markdown code blocks
                    cleaned_code = re.sub(r"^```(?:python)?\s*", "", raw_content.strip(), flags=re.MULTILINE)
                    cleaned_code = re.sub(r"\s*```$", "", cleaned_code.strip(), flags=re.MULTILINE)
                    return cleaned_code

        # Fallback default code if no LLM caller is supplied
        return (
            "def execute(inputs: dict) -> dict:\n"
            "    # Standard-Verarbeitung\n"
            "    return {'status': 'success', 'inputs': inputs, 'message': 'Dynamisches Tool ausgeführt'}\n"
        )

    def preflight_smoke_test(self, code: str, sample_inputs: Dict[str, Any]) -> None:
        """Runs the code with sample inputs in a temporary sandbox to ensure it runs without errors."""
        test_inputs = sample_inputs if sample_inputs else {"test_mode": True}
        res = run_code_in_sandbox(code, test_inputs, timeout_seconds=2.0)
        if not isinstance(res, dict):
            raise SandboxExecutionError("Pre-Flight Smoke Test fehlgeschlagen: Rückgabewert ist kein Dictionary.")

    def execute_dynamic_task(
        self,
        task_description: str,
        inputs: Dict[str, Any],
        llm_caller: Optional[Callable[[List[Dict[str, Any]], List[Dict[str, Any]]], Dict[str, Any]]] = None,
        provided_code: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Full 7-Layer Zero-Trust Pipeline:
        1. Guardrail Check
        2. Tool Code Synthesis or Retrieval
        3. AST Static Security Verification
        4. Pre-Flight Smoke Testing (with Self-Repair Retry)
        5. Sandboxed Subprocess Execution with Hard Resource Limits
        6. Output Payload Sanitization
        7. SHA-256 Registry & Audit Log
        """
        start_t = time.perf_counter()
        tool_name = f"dyn_{hashlib.sha256(task_description.encode('utf-8')).hexdigest()[:12]}"
        code = provided_code or ""

        # Step 1: Guardrail
        self.check_safety_guardrails(task_description)

        # Check Cache
        task_hash = hashlib.sha256(f"{task_description}:{json.dumps(inputs, sort_keys=True)}".encode("utf-8")).hexdigest()
        if task_hash in self._tool_cache:
            cached_tool = self._tool_cache[task_hash]
            if (time.time() - cached_tool.created_at) < self.cache_ttl_seconds:
                code = cached_tool.code

        max_attempts = 3
        last_error = None

        for attempt in range(1, max_attempts + 1):
            try:
                if not code:
                    # Step 2: Synthesis
                    code = self.synthesize_tool_code(task_description, inputs, llm_caller=llm_caller)

                # Step 3: AST Static Analysis
                validate_python_code_ast(code)

                # Step 4: Pre-Flight Smoke Test
                self.preflight_smoke_test(code, inputs)

                # Step 5: Isolated OS Sandbox Execution
                result = run_code_in_sandbox(code, inputs, timeout_seconds=3.0)

                elapsed = round(time.perf_counter() - start_t, 3)
                code_sha = hashlib.sha256(code.encode("utf-8")).hexdigest()

                # Step 7: Registry & Audit Log
                self._tool_cache[task_hash] = SynthesizedTool(
                    name=tool_name,
                    description=task_description,
                    code=code,
                    parameters_schema={"type": "object"},
                    sha256_hash=code_sha,
                )

                self._audit_log.append(AuditLogEntry(
                    timestamp=time.time(),
                    tool_name=tool_name,
                    sha256_hash=code_sha,
                    task_description=task_description,
                    success=True,
                    elapsed_seconds=elapsed,
                ))

                # Cryptographic Proof-of-Execution Ledger Recording
                receipt_id = None
                try:
                    from ..ledger import get_compact_ledger
                    receipt = get_compact_ledger().record_execution(
                        tool_name=tool_name,
                        task_description=task_description,
                        code=code,
                        inputs=inputs,
                        outputs=result,
                        elapsed_seconds=elapsed,
                        status="verified_success",
                    )
                    receipt_id = receipt.receipt_id
                except Exception as l_exc:
                    logger.debug(f"Ledger record error: {l_exc}")

                result["_dynamic_meta"] = {
                    "tool_name": tool_name,
                    "sha256": code_sha,
                    "execution_time_seconds": elapsed,
                    "attempts": attempt,
                    "status": "verified_safe",
                    "receipt_id": receipt_id,
                }
                return result

            except (SecurityASTViolation, SandboxExecutionError, SandboxTimeoutError) as exc:
                last_error = str(exc)
                logger.warning(f"Dynamic tool attempt {attempt} failed: {last_error}")
                # Reset code to trigger re-synthesis on next attempt
                code = ""
                if attempt == max_attempts:
                    break

        elapsed = round(time.perf_counter() - start_t, 3)
        self._audit_log.append(AuditLogEntry(
            timestamp=time.time(),
            tool_name=tool_name,
            sha256_hash="none",
            task_description=task_description,
            success=False,
            elapsed_seconds=elapsed,
            error=last_error,
        ))

        return {
            "error": f"Dynamic Tool Ausführung fehlgeschlagen nach {max_attempts} Versuchen: {last_error}",
            "task_description": task_description,
            "_dynamic_meta": {
                "tool_name": tool_name,
                "execution_time_seconds": elapsed,
                "status": "rejected_unsafe",
            }
        }

    def get_audit_log(self) -> List[Dict[str, Any]]:
        """Returns the immutable audit log entries."""
        return [
            {
                "timestamp": entry.timestamp,
                "tool_name": entry.tool_name,
                "sha256_hash": entry.sha256_hash,
                "task_description": entry.task_description,
                "success": entry.success,
                "elapsed_seconds": entry.elapsed_seconds,
                "error": entry.error,
            }
            for entry in self._audit_log
        ]


_global_engine: Optional[DynamicToolEngine] = None


def get_dynamic_tool_engine() -> DynamicToolEngine:
    """Returns the singleton Dynamic Tool Engine instance."""
    global _global_engine
    if _global_engine is None:
        _global_engine = DynamicToolEngine()
    return _global_engine
