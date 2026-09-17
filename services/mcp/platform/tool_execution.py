"""Capability-aware safety wrapper around the existing MCP ToolRegistry."""
from __future__ import annotations

from dataclasses import asdict, replace
import hashlib
import json
from pathlib import Path
import sqlite3
import threading
import time
from typing import Any, Callable, Iterable, Mapping

from .contracts import (
    SideEffectLevel,
    ToolAuthorizationGrant,
    ToolExecutionContext,
    ToolExecutionResult,
    ToolLifecycle,
    ToolManifest,
    ToolMode,
)
from .tool_contracts import EgressPolicy, ToolEgressGuard, normalize_tool_result


class ToolCapabilityRegistry:
    """Metadata registry layered on top of the existing concrete ToolRegistry."""

    def __init__(self, backend: Any | None = None) -> None:
        self.backend = backend
        self._manifests: dict[str, ToolManifest] = {}
        if backend is not None:
            self.discover_backend(backend)

    def register(self, manifest: ToolManifest) -> None:
        if not manifest.tool_id or not manifest.name:
            raise ValueError("tool_id and name are required")
        self._manifests[manifest.tool_id] = manifest
        self._manifests[manifest.name] = manifest

    def discover_backend(self, backend: Any) -> None:
        try:
            tools = backend.list_tools(is_owner=True)
        except Exception:
            return
        for tool in tools:
            name = str(getattr(tool, "name", "") or "")
            if not name:
                continue
            self.register(ToolManifest(
                tool_id=name,
                name=name,
                description=str(getattr(tool, "description", "") or ""),
                input_schema=getattr(tool, "parameters", {}) or {},
                lifecycle=ToolLifecycle.AVAILABLE,
                side_effect=SideEffectLevel.EXECUTE,
                owner_only=bool(getattr(tool, "owner_only", False)),
                confirmation_required=True,
                idempotent=False,
                reversible=False,
                retry_limit=0,
                source=str(getattr(tool, "source", "legacy") or "legacy"),
            ))

    def get(self, tool_id: str) -> ToolManifest | None:
        return self._manifests.get(tool_id)

    def list(self) -> list[ToolManifest]:
        seen: set[str] = set()
        result: list[ToolManifest] = []
        for manifest in self._manifests.values():
            if manifest.tool_id not in seen:
                seen.add(manifest.tool_id)
                result.append(manifest)
        return sorted(result, key=lambda item: item.tool_id)

    def apply_overrides(self, manifests: Iterable[ToolManifest]) -> None:
        for manifest in manifests:
            self.register(manifest)


class _ExecutionStore:
    def __init__(self, path: str | Path = ":memory:") -> None:
        self.path = str(path)
        if self.path != ":memory:":
            Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(self.path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.lock = threading.RLock()
        with self.conn:
            self.conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS idempotency (
                    tool_id TEXT NOT NULL, idem_key TEXT NOT NULL, arguments_hash TEXT NOT NULL,
                    result_json TEXT NOT NULL, created_at REAL NOT NULL,
                    PRIMARY KEY(tool_id, idem_key)
                );
                CREATE TABLE IF NOT EXISTS breaker (
                    tool_id TEXT PRIMARY KEY, failures INTEGER NOT NULL, opened_until REAL NOT NULL, updated_at REAL NOT NULL
                );
                """
            )

    @staticmethod
    def args_hash(arguments: Mapping[str, Any]) -> str:
        return hashlib.sha256(
            json.dumps(dict(arguments), sort_keys=True, ensure_ascii=False, separators=(",", ":"), default=str).encode("utf-8")
        ).hexdigest()

    def replay(self, tool_id: str, key: str, arguments: dict[str, Any]) -> Any | None:
        with self.lock:
            row = self.conn.execute(
                "SELECT arguments_hash,result_json FROM idempotency WHERE tool_id=? AND idem_key=?",
                (tool_id, key),
            ).fetchone()
        if not row:
            return None
        if row["arguments_hash"] != self.args_hash(arguments):
            raise ValueError("idempotency key reused with different arguments")
        return json.loads(row["result_json"])

    def remember(self, tool_id: str, key: str, arguments: dict[str, Any], result: Any) -> None:
        with self.lock, self.conn:
            self.conn.execute(
                "INSERT OR REPLACE INTO idempotency(tool_id,idem_key,arguments_hash,result_json,created_at) VALUES(?,?,?,?,?)",
                (tool_id, key, self.args_hash(arguments), json.dumps(result, ensure_ascii=False, default=str), time.time()),
            )

    def breaker_state(self, tool_id: str) -> tuple[int, float]:
        with self.lock:
            row = self.conn.execute(
                "SELECT failures,opened_until FROM breaker WHERE tool_id=?", (tool_id,)
            ).fetchone()
        return (int(row["failures"]), float(row["opened_until"])) if row else (0, 0.0)

    def success(self, tool_id: str) -> None:
        with self.lock, self.conn:
            self.conn.execute(
                "INSERT INTO breaker(tool_id,failures,opened_until,updated_at) VALUES(?,?,?,?) "
                "ON CONFLICT(tool_id) DO UPDATE SET failures=0,opened_until=0,updated_at=excluded.updated_at",
                (tool_id, 0, 0.0, time.time()),
            )

    def failure(self, tool_id: str, threshold: int, cooldown_seconds: float) -> None:
        failures, _ = self.breaker_state(tool_id)
        failures += 1
        opened_until = time.time() + cooldown_seconds if failures >= threshold else 0.0
        with self.lock, self.conn:
            self.conn.execute(
                "INSERT INTO breaker(tool_id,failures,opened_until,updated_at) VALUES(?,?,?,?) "
                "ON CONFLICT(tool_id) DO UPDATE SET failures=excluded.failures,opened_until=excluded.opened_until,updated_at=excluded.updated_at",
                (tool_id, failures, opened_until, time.time()),
            )


    def close(self) -> None:
        with self.lock:
            if hasattr(self, "conn") and self.conn is not None:
                try:
                    self.conn.close()
                except Exception:
                    pass
                self.conn = None


class SafeToolExecutor:
    """Policy layer that delegates real execution to the existing ToolRegistry.

    Every enforced execution passes authorization, confirmation/idempotency,
    egress-secret scanning and normalized result classification before returning.
    """

    def __init__(
        self,
        backend: Any,
        capabilities: ToolCapabilityRegistry | None = None,
        *,
        state_db: str | Path = ":memory:",
        breaker_threshold: int = 3,
        breaker_cooldown_seconds: float = 30.0,
        verifier: Callable[[ToolManifest, dict[str, Any], Any], bool | dict[str, Any]] | None = None,
        egress_guard: ToolEgressGuard | None = None,
        egress_policy_resolver: Callable[[ToolManifest], EgressPolicy] | None = None,
    ) -> None:
        self.backend = backend
        self.capabilities = capabilities or ToolCapabilityRegistry(backend)
        self.store = _ExecutionStore(state_db)
        self.breaker_threshold = max(1, int(breaker_threshold))
        self.breaker_cooldown_seconds = max(0.1, float(breaker_cooldown_seconds))
        self.verifier = verifier
        self.egress_guard = egress_guard or ToolEgressGuard()
        self.egress_policy_resolver = egress_policy_resolver or (lambda _manifest: EgressPolicy())

    def close(self) -> None:
        if hasattr(self, "store") and self.store is not None:
            self.store.close()

    @staticmethod
    def _error(tool_id: str, mode: ToolMode, error: str, **extra: Any) -> ToolExecutionResult:
        return ToolExecutionResult(status="blocked", tool_id=tool_id, mode=mode, error=error, **extra)

    def preview(self, tool_id: str, arguments: dict[str, Any], context: ToolExecutionContext) -> ToolExecutionResult:
        manifest = self.capabilities.get(tool_id)
        if manifest is None:
            return self._error(tool_id, ToolMode.PREVIEW, "tool manifest not found")
        side_effecting = manifest.side_effect.rank >= SideEffectLevel.WRITE_REVERSIBLE.rank
        return ToolExecutionResult(
            status="preview",
            tool_id=manifest.tool_id,
            mode=ToolMode.PREVIEW,
            result={
                "tool": manifest.to_dict(),
                "argument_keys": sorted(str(key) for key in arguments),
                "arguments_hash": _ExecutionStore.args_hash(arguments),
                "requires_confirmation": manifest.confirmation_required or side_effecting,
                "requires_idempotency_key": side_effecting and not manifest.idempotent,
                "authorized": context.authorized,
            },
            confirmation_required=manifest.confirmation_required or side_effecting,
            provenance={"source": manifest.source, "executed": False},
        )

    def execute(self, tool_id: str, arguments: dict[str, Any], context: ToolExecutionContext) -> ToolExecutionResult:
        if not isinstance(arguments, dict):
            return self._error(tool_id, context.mode, "arguments must be an object")
        manifest = self.capabilities.get(tool_id)
        if manifest is None:
            return self._error(tool_id, context.mode, "tool manifest not found")
        if manifest.lifecycle in {ToolLifecycle.DISABLED, ToolLifecycle.BROKEN}:
            return self._error(manifest.tool_id, context.mode, f"tool lifecycle is {manifest.lifecycle.value}")
        if manifest.owner_only and not context.is_owner:
            return self._error(manifest.tool_id, context.mode, "owner authorization required")
        missing_permissions = sorted(set(manifest.permissions) - set(context.allowed_permissions))
        if missing_permissions:
            return self._error(manifest.tool_id, context.mode, f"missing permissions: {', '.join(missing_permissions)}")
        if context.mode == ToolMode.PREVIEW:
            return self.preview(tool_id, arguments, context)

        side_effecting = manifest.side_effect.rank >= SideEffectLevel.WRITE_REVERSIBLE.rank
        if side_effecting and not context.authorized:
            return self._error(manifest.tool_id, context.mode, "side-effect action is not authorized")
        needs_confirmation = manifest.confirmation_required or side_effecting
        if context.mode == ToolMode.CONFIRM and not context.confirmed:
            return ToolExecutionResult(
                status="confirmation_required",
                tool_id=manifest.tool_id,
                mode=context.mode,
                confirmation_required=True,
                provenance={"source": manifest.source, "executed": False},
            )
        if needs_confirmation and not context.confirmed:
            return self._error(
                manifest.tool_id,
                context.mode,
                "confirmation required",
                confirmation_required=True,
            )
        if side_effecting and not context.idempotency_key and not manifest.idempotent:
            return self._error(
                manifest.tool_id,
                context.mode,
                "idempotency key required for non-idempotent write/execute action",
            )

        try:
            egress_policy = self.egress_policy_resolver(manifest)
            egress = self.egress_guard.check(arguments, egress_policy)
        except Exception as exc:
            return self._error(manifest.tool_id, context.mode, f"egress policy evaluation failed: {exc}")
        if not egress.get("allowed"):
            return self._error(
                manifest.tool_id,
                context.mode,
                f"egress blocked: {egress.get('reason', 'policy_denied')}",
                provenance={"source": manifest.source, "executed": False, "egress": egress},
            )

        if context.idempotency_key:
            try:
                replay = self.store.replay(manifest.tool_id, context.idempotency_key, arguments)
            except ValueError as exc:
                return self._error(manifest.tool_id, context.mode, str(exc))
            if replay is not None:
                normalized = normalize_tool_result(manifest.tool_id, replay, source=manifest.source, version=manifest.version)
                return ToolExecutionResult(
                    status="completed",
                    tool_id=manifest.tool_id,
                    mode=context.mode,
                    result=replay,
                    idempotency_replay=True,
                    provenance={
                        "source": manifest.source,
                        "executed": False,
                        "idempotency_replay": True,
                        "result_status": normalized.status.value,
                        "pagination": asdict(normalized.pagination),
                    },
                )

        _, opened_until = self.store.breaker_state(manifest.tool_id)
        if opened_until > time.time():
            return self._error(manifest.tool_id, context.mode, "circuit breaker open")

        attempts = max(1, manifest.retry_limit + 1)
        # A local idempotency record cannot prove that an ambiguous remote write
        # did not already happen. Never retry non-idempotent side effects blindly.
        if side_effecting and not manifest.idempotent:
            attempts = 1
        result: Any = None
        for attempt in range(1, attempts + 1):
            try:
                result = self.backend.execute_tool(
                    manifest.name,
                    arguments,
                    is_owner=context.is_owner,
                    owner_id=context.owner_id,
                )
                normalized_attempt = normalize_tool_result(
                    manifest.tool_id,
                    result,
                    source=manifest.source,
                    version=manifest.version,
                )
                if normalized_attempt.status.value == "FAILURE":
                    message = normalized_attempt.errors[0] if normalized_attempt.errors else "tool failure"
                    raise RuntimeError(str(message))
                self.store.success(manifest.tool_id)
                break
            except Exception as exc:
                self.store.failure(manifest.tool_id, self.breaker_threshold, self.breaker_cooldown_seconds)
                if attempt >= attempts:
                    return ToolExecutionResult(
                        status="failed",
                        tool_id=manifest.tool_id,
                        mode=context.mode,
                        error=str(exc),
                        provenance={"source": manifest.source, "attempts": attempt, "executed": True},
                    )

        normalized = normalize_tool_result(
            manifest.tool_id,
            result,
            source=manifest.source,
            version=manifest.version,
        )
        if context.idempotency_key:
            self.store.remember(manifest.tool_id, context.idempotency_key, arguments, result)

        verification: Any = None
        if context.mode == ToolMode.VERIFY:
            if self.verifier is None:
                verification = {"verified": False, "reason": "no verifier configured"}
            else:
                try:
                    verification = self.verifier(manifest, arguments, result)
                except Exception as exc:
                    verification = {"verified": False, "error": str(exc)}
        return ToolExecutionResult(
            status="completed",
            tool_id=manifest.tool_id,
            mode=context.mode,
            result={"result": result, "verification": verification} if context.mode == ToolMode.VERIFY else result,
            provenance={
                "source": manifest.source,
                "executed": True,
                "side_effect": manifest.side_effect.value,
                "request_id": context.request_id,
                "egress": {"allowed": True, "size_bytes": egress.get("size_bytes")},
                "result_status": normalized.status.value,
                "pagination": asdict(normalized.pagination),
                "resources": [asdict(resource) for resource in normalized.resources],
            },
        )


_READ_ONLY_TOOLS = {
    "list_available_tools", "search_web", "get_market_quote", "get_market_movers", "search_product_prices",
    "get_current_weather", "get_weather_forecast", "get_wikipedia_summary", "get_live_news", "calculate_math",
    "get_time_and_calendar", "convert_currency", "fetch_recent_timeline", "verify_fact_multi_source",
    "cross_source_knowledge_search", "fetch_multilingual_wikipedia", "lookup_network_host", "search_events",
    "search_places", "get_sports_data", "lookup_company", "get_gpu_telemetry", "get_system_info",
    "list_workspace_files", "read_workspace_file", "analyze_data_table", "extract_document_content",
    "lookup_chemical_compound", "lookup_country_data", "lookup_word_definition", "get_world_bank_stats",
    "lookup_food_product", "lookup_software_package", "search_arxiv_papers", "get_distance_route",
    "lookup_train_schedule", "get_recent_earthquakes", "check_url_safety", "get_git_status", "get_git_diff",
    "get_git_log", "github_get_repo", "github_search_repositories", "github_get_file_contents", "github_list_repo_tree",
    "github_search_code", "github_list_issues", "github_get_issue", "github_list_pull_requests", "github_get_pull_request",
    "github_get_pull_request_diff", "github_get_pull_request_files", "github_list_releases", "github_get_latest_release",
    "github_list_commits", "github_get_workflow_runs", "run_doctor_diagnostics", "adb_list_devices",
    "adb_capture_screenshot", "adb_get_system_log", "list_deployed_webapps", "search_knowledge_base",
    "list_indexed_documents", "get_user_memory", "mission_get_summary", "detect_missing_tools",
}
_TRANSFORM_TOOLS = {
    "generate_ai_image", "execute_finance_quote", "transcribe_audio_data", "synthesize_speech_audio",
    "convert_data_to_markdown_table", "run_python_calc",
}
_WRITE_REVERSIBLE_TOOLS = {
    "generate_office_document", "index_document_text", "update_user_memory", "replace_file_content",
    "multi_replace_file_content", "quarantine_stage_files", "quarantine_rollback", "mission_start",
    "mission_log_step", "deploy_local_webapp",
}
_WRITE_IRREVERSIBLE_TOOLS = {
    "delete_user_memory", "github_create_issue", "github_add_issue_comment", "remove_deployed_webapp",
    "quarantine_commit",
}
_EXECUTE_TOOLS = {
    "execute_python_code", "run_terminal_command", "run_project_tests", "install_dev_tool", "adb_install_app",
    "launch_deployed_webapp", "execute_http_request", "execute_universal_skill",
}


def apply_default_compute_mesh_tool_policy(registry: ToolCapabilityRegistry) -> None:
    """Apply explicit safety metadata for known built-ins, leaving unknowns fail-closed."""
    for manifest in list(registry.list()):
        if manifest.name in _READ_ONLY_TOOLS:
            registry.register(replace(manifest, side_effect=SideEffectLevel.READ, confirmation_required=False, idempotent=True))
        elif manifest.name in _TRANSFORM_TOOLS:
            registry.register(replace(manifest, side_effect=SideEffectLevel.NONE, confirmation_required=False, idempotent=True))
        elif manifest.name in _WRITE_REVERSIBLE_TOOLS:
            registry.register(replace(manifest, side_effect=SideEffectLevel.WRITE_REVERSIBLE, confirmation_required=True, reversible=True))
        elif manifest.name in _WRITE_IRREVERSIBLE_TOOLS:
            registry.register(replace(manifest, side_effect=SideEffectLevel.WRITE_IRREVERSIBLE, confirmation_required=True, reversible=False))
        elif manifest.name in _EXECUTE_TOOLS:
            registry.register(replace(manifest, side_effect=SideEffectLevel.EXECUTE, confirmation_required=True, reversible=False))


class PolicyToolRegistryProxy:
    """Drop-in ToolRegistry facade enforcing SafeToolExecutor for AgentLoop calls."""

    def __init__(
        self,
        backend: Any,
        executor: SafeToolExecutor,
        *,
        is_owner: bool,
        request_id: str | None = None,
        owner_id: str | None = None,
        allowed_tools: Iterable[str] | None = None,
        max_side_effect: SideEffectLevel = SideEffectLevel.EXECUTE,
        authorization_grants: Mapping[str, ToolAuthorizationGrant] | None = None,
    ) -> None:
        self.backend = backend
        self.executor = executor
        self.is_owner = is_owner
        self.request_id = request_id
        self.owner_id = owner_id
        self.allowed_tools = None if allowed_tools is None else {str(x) for x in allowed_tools}
        self.max_side_effect = max_side_effect
        self.authorization_grants = dict(authorization_grants or {})

    def __getattr__(self, name: str) -> Any:
        return getattr(self.backend, name)

    def _manifest_allowed(self, name: str) -> bool:
        manifest = self.executor.capabilities.get(name)
        if manifest is None:
            return False
        if self.allowed_tools is not None and manifest.name not in self.allowed_tools and manifest.tool_id not in self.allowed_tools:
            return False
        return manifest.side_effect.rank <= self.max_side_effect.rank

    def get_tool(self, name: str) -> Any:
        if not self._manifest_allowed(name):
            return None
        return self.backend.get_tool(name)

    def list_tools(self, is_owner: bool = True) -> Any:
        return [
            tool for tool in self.backend.list_tools(is_owner=is_owner and self.is_owner)
            if self._manifest_allowed(str(getattr(tool, "name", "") or ""))
        ]

    def get_openai_tools(self, is_owner: bool = True) -> Any:
        allowed_names = {
            str(getattr(tool, "name", "") or "")
            for tool in self.list_tools(is_owner=is_owner)
        }
        return [
            tool for tool in self.backend.get_openai_tools(is_owner=is_owner and self.is_owner)
            if str((tool.get("function") or {}).get("name") or "") in allowed_names
        ]

    def _grant_for(self, manifest: ToolManifest, arguments: dict[str, Any]) -> ToolAuthorizationGrant | None:
        grant = self.authorization_grants.get(manifest.tool_id) or self.authorization_grants.get(manifest.name)
        if grant is None:
            return None
        grant.validate(
            tool_id=manifest.tool_id,
            request_id=self.request_id,
            arguments=arguments,
        )
        return grant

    @staticmethod
    def _present(result: ToolExecutionResult) -> Any:
        if result.status != "completed":
            return {
                "error": result.error or result.status,
                "status": result.status,
                "confirmation_required": result.confirmation_required,
                "agents_platform_policy": True,
                "provenance": dict(result.provenance),
            }
        metadata = {
            "status": result.provenance.get("result_status", "SUCCESS"),
            "pagination": result.provenance.get("pagination", {}),
            "resources": result.provenance.get("resources", []),
            "idempotency_replay": result.idempotency_replay,
        }
        if isinstance(result.result, dict):
            presented = dict(result.result)
            presented.setdefault("_agents_platform_result", metadata)
            return presented
        return {"data": result.result, "_agents_platform_result": metadata}

    def execute_tool(
        self,
        name: str,
        arguments: dict[str, Any],
        is_owner: bool = True,
        owner_id: str | None = None,
    ) -> Any:
        manifest = self.executor.capabilities.get(name)
        if manifest is None:
            return {"error": f"Tool '{name}' has no capability manifest"}
        if not self._manifest_allowed(name):
            return {"error": f"Tool '{name}' is not allowed by runtime policy", "agents_platform_policy": True}

        safe_auto = manifest.side_effect.rank <= SideEffectLevel.READ.rank and not manifest.confirmation_required
        grant: ToolAuthorizationGrant | None = None
        if not safe_auto:
            try:
                grant = self._grant_for(manifest, arguments)
            except PermissionError as exc:
                return {"error": str(exc), "agents_platform_policy": True}

        context = ToolExecutionContext(
            mode=ToolMode.EXECUTE,
            is_owner=is_owner and self.is_owner,
            authorized=safe_auto or bool(grant and grant.authorized),
            confirmed=safe_auto or bool(grant and grant.confirmed),
            owner_id=owner_id or self.owner_id,
            idempotency_key=None if grant is None else grant.idempotency_key,
            request_id=self.request_id,
            allowed_permissions=() if grant is None else grant.allowed_permissions,
        )
        return self._present(self.executor.execute(name, arguments, context))

    def execute_tools_batch(
        self,
        tool_calls: list[dict[str, Any]],
        is_owner: bool = True,
        owner_id: str | None = None,
        max_workers: int = 8,
    ) -> list[dict[str, Any]]:
        # Keep ordering deterministic. Side-effect calls must not be launched in
        # parallel unless a future transaction contract explicitly permits it.
        results: list[dict[str, Any]] = []
        for index, tc in enumerate(tool_calls):
            cid = str(tc.get("id") or f"call_{index + 1}")
            fn = tc.get("function") if isinstance(tc.get("function"), dict) else {}
            name = str(fn.get("name") or "")
            raw_args = fn.get("arguments", {})
            if isinstance(raw_args, str):
                try:
                    args = json.loads(raw_args)
                except Exception as exc:
                    results.append({
                        "id": cid,
                        "name": name,
                        "arguments": {},
                        "result": {"error": f"invalid JSON arguments: {exc}"},
                    })
                    continue
            else:
                args = raw_args
            if not isinstance(args, dict):
                results.append({
                    "id": cid,
                    "name": name,
                    "arguments": {},
                    "result": {"error": "arguments must be an object"},
                })
                continue
            results.append({
                "id": cid,
                "name": name,
                "arguments": args,
                "result": self.execute_tool(name, args, is_owner=is_owner, owner_id=owner_id),
            })
        return results