"""Inference backends for the public ComputeMesh gateway.

Production requests execute against a configured runtime endpoint. Synthetic
responses require explicit test/dev opt-in. Orchestrated execution additionally
binds runtime dispatch to durable job/reservation state and can derive reserved
nodes from a validated M1 scheduler placement decision.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import json
import os
import secrets
from typing import Any, Callable, Protocol
from urllib import error, request
from urllib.parse import urlparse

from services.gateway.execution_evidence import (
    ExecutionEvidenceError,
    verify_shared_execution_evidence,
)
from services.gateway.placement_selection import (
    PlacementSelection,
    PlacementSelectionError,
    load_shared_placement_selection,
)
from services.orchestrator.evidence_store import (
    ExecutionEvidenceBindingError,
    ExecutionEvidenceStore,
)
from services.orchestrator.persistence import SQLiteStateStore
from services.orchestrator.state_machine import JobState, ReservationState


class InferenceBackendError(RuntimeError):
    """Raised when a configured inference backend cannot produce a valid result."""


@dataclass(frozen=True)
class BackendResult:
    text: str
    prompt_tokens: int
    completion_tokens: int
    execution_job_id: str | None = None
    provider_shares: tuple[tuple[str, float], ...] | None = None
    evidence_id: str | None = None


class InferenceBackend(Protocol):
    def complete(self, *, model_id: str, messages: list[dict[str, Any]]) -> BackendResult:
        """Execute one non-streaming chat completion."""


class DisabledInferenceBackend:
    """Fail closed when no real inference backend is configured."""

    def complete(self, *, model_id: str, messages: list[dict[str, Any]]) -> BackendResult:
        raise InferenceBackendError(
            "Inference backend is not configured. Set COMPUTEMESH_INFERENCE_BACKEND "
            "and COMPUTEMESH_INFERENCE_URL before serving inference traffic."
        )


class SyntheticInferenceBackend:
    """Deterministic backend for tests and explicitly opted-in development only."""

    def complete(self, *, model_id: str, messages: list[dict[str, Any]]) -> BackendResult:
        last_user_msg = ""
        for message in reversed(messages):
            if isinstance(message, dict) and message.get("role") == "user":
                last_user_msg = str(message.get("content", ""))
                break
        text = (
            f"ComputeMesh distributed response for: {last_user_msg[:60]}"
            if last_user_msg
            else "Hello from ComputeMesh decentralized inference!"
        )
        return BackendResult(
            text=text,
            prompt_tokens=max(len(json.dumps(messages)) // 4, 8),
            completion_tokens=max(len(text) // 4, 12),
        )


class OpenAICompatibleHTTPBackend:
    """Call a llama.cpp/OpenAI-compatible HTTP chat-completions endpoint."""

    def __init__(
        self,
        *,
        base_url: str,
        api_key: str | None = None,
        timeout_seconds: float = 120.0,
        max_response_bytes: int = 8 * 1024 * 1024,
    ) -> None:
        parsed = urlparse(base_url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError("COMPUTEMESH_INFERENCE_URL must be an http(s) URL")
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.timeout_seconds = timeout_seconds
        self.max_response_bytes = max_response_bytes

    def complete(self, *, model_id: str, messages: list[dict[str, Any]]) -> BackendResult:
        payload = json.dumps(
            {"model": model_id, "messages": messages, "stream": False},
            separators=(",", ":"),
        ).encode("utf-8")
        headers = {"Content-Type": "application/json", "Accept": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        req = request.Request(
            f"{self.base_url}/v1/chat/completions",
            data=payload,
            headers=headers,
            method="POST",
        )
        try:
            with request.urlopen(req, timeout=self.timeout_seconds) as response:
                raw = response.read(self.max_response_bytes + 1)
        except (error.HTTPError, error.URLError, TimeoutError, OSError) as exc:
            raise InferenceBackendError("Inference runtime request failed") from exc
        if len(raw) > self.max_response_bytes:
            raise InferenceBackendError("Inference runtime response exceeded size limit")
        try:
            body = json.loads(raw.decode("utf-8"))
            text = body["choices"][0]["message"]["content"]
            usage = body["usage"]
            prompt_tokens = int(usage["prompt_tokens"])
            completion_tokens = int(usage["completion_tokens"])
        except (UnicodeDecodeError, json.JSONDecodeError, KeyError, IndexError, TypeError, ValueError) as exc:
            raise InferenceBackendError("Inference runtime returned an invalid response") from exc
        if not isinstance(text, str) or prompt_tokens < 0 or completion_tokens < 0:
            raise InferenceBackendError("Inference runtime returned invalid content or usage")
        return BackendResult(text, prompt_tokens, completion_tokens)


class OrchestratedInferenceBackend:
    """Bind real runtime execution to durable job, reservation, and evidence state.

    A validated scheduler placement may supply the participating node IDs. When
    scheduler placement is used, current shared-run evidence is mandatory before
    the result can complete and expose provider shares for settlement. Static
    operator nodes remain available as a lab fallback but do not become
    evidence-derived merely by passing through this wrapper.
    """

    def __init__(
        self,
        *,
        delegate: InferenceBackend,
        store: SQLiteStateStore,
        provider_node_ids: list[str] | tuple[str, ...],
        lease_seconds: int = 180,
        id_factory: Callable[[], str] | None = None,
        placement: PlacementSelection | None = None,
        execution_evidence_path: str | None = None,
    ) -> None:
        cleaned = [value.strip() for value in provider_node_ids if value.strip()]
        if len(cleaned) < 2:
            raise ValueError("orchestrated inference requires at least two provider nodes")
        if len(set(cleaned)) != len(cleaned):
            raise ValueError("provider node ids must be unique")
        if lease_seconds < 10 or lease_seconds > 3600:
            raise ValueError("lease_seconds must be between 10 and 3600")
        if placement is not None and tuple(cleaned) != placement.provider_node_ids:
            raise ValueError("provider nodes must exactly match scheduler placement")
        if placement is not None and not execution_evidence_path:
            raise ValueError("scheduler-derived orchestration requires shared-run evidence")
        self.delegate = delegate
        self.store = store
        self.provider_node_ids = tuple(cleaned)
        self.lease_seconds = lease_seconds
        self.id_factory = id_factory or (lambda: f"inf-{secrets.token_hex(12)}")
        self.placement = placement
        self.execution_evidence_path = execution_evidence_path
        self.evidence_store = ExecutionEvidenceStore(store) if placement is not None else None

    @property
    def placement_id(self) -> str:
        return self.placement.decision_id if self.placement else "operator-static"

    def _advance_job(self, job_id: str, target: JobState) -> None:
        record = self.store.get_job(job_id)
        self.store.transition_job(
            job_id,
            request_id=f"{job_id}:job:{target.value.lower()}",
            expected_revision=record.revision,
            target=target,
            request_fingerprint=f"orchestrated-inference:{self.placement_id}:{target.value}",
        )

    def _reservation_ids(self, job_id: str) -> list[str]:
        return [
            f"{job_id}:capacity:{index}:{node_id}"
            for index, node_id in enumerate(self.provider_node_ids)
        ]

    def _reserve_capacity(self, job_id: str) -> list[str]:
        expires_at = datetime.now(timezone.utc) + timedelta(seconds=self.lease_seconds)
        reservation_ids = self._reservation_ids(job_id)
        for index, (reservation_id, node_id) in enumerate(
            zip(reservation_ids, self.provider_node_ids)
        ):
            self.store.ensure_reservation(reservation_id)
            fingerprint = f"node={node_id};job={job_id};placement={self.placement_id}"
            leased = self.store.lease_reservation(
                reservation_id,
                request_id=f"{job_id}:lease:{index}",
                expected_revision=0,
                expires_at=expires_at,
                request_fingerprint=fingerprint,
            )
            self.store.commit_reservation(
                reservation_id,
                request_id=f"{job_id}:commit:{index}",
                expected_revision=leased.revision,
                job_id=job_id,
                stage_id=f"inference:{node_id}",
                request_fingerprint=fingerprint,
            )
        return reservation_ids

    def _activate(self, job_id: str, reservation_ids: list[str]) -> None:
        for index, reservation_id in enumerate(reservation_ids):
            record = self.store.get_reservation(reservation_id)
            if record.state != ReservationState.COMMITTED:
                raise InferenceBackendError("capacity reservation is not committed")
            if record.lease_expires_at is None or record.lease_expires_at <= datetime.now(timezone.utc):
                self.store.transition_reservation(
                    reservation_id,
                    request_id=f"{job_id}:expire:{index}",
                    expected_revision=record.revision,
                    target=ReservationState.RELEASED,
                    request_fingerprint="expired-before-dispatch",
                )
                raise InferenceBackendError("capacity reservation expired before dispatch")
            self.store.transition_reservation(
                reservation_id,
                request_id=f"{job_id}:activate:{index}",
                expected_revision=record.revision,
                target=ReservationState.ACTIVE,
                request_fingerprint=f"dispatch:{job_id}:placement={self.placement_id}",
            )

    def _release(self, job_id: str, reservation_ids: list[str]) -> None:
        for index, reservation_id in enumerate(reservation_ids):
            try:
                record = self.store.get_reservation(reservation_id)
            except KeyError:
                continue
            if record.state in {ReservationState.COMMITTED, ReservationState.ACTIVE}:
                self.store.transition_reservation(
                    reservation_id,
                    request_id=f"{job_id}:release:{index}",
                    expected_revision=record.revision,
                    target=ReservationState.RELEASED,
                    request_fingerprint=f"release:{job_id}",
                )

    def _fail_job(self, job_id: str, exc: Exception) -> None:
        try:
            record = self.store.get_job(job_id)
            if record.state in {
                JobState.CREATED,
                JobState.VALIDATING,
                JobState.PLANNING,
                JobState.RESERVING,
                JobState.PREPARING,
                JobState.RUNNING,
                JobState.VERIFYING,
            }:
                self.store.transition_job(
                    job_id,
                    request_id=f"{job_id}:job:failed",
                    expected_revision=record.revision,
                    target=JobState.FAILED,
                    request_fingerprint=f"runtime-failure:{type(exc).__name__}",
                )
        except Exception:
            pass

    def _verify_and_bind_evidence(
        self,
        *,
        job_id: str,
        result: BackendResult,
        execution_started_at: datetime,
    ) -> BackendResult:
        if self.placement is None:
            return BackendResult(
                result.text,
                result.prompt_tokens,
                result.completion_tokens,
                execution_job_id=job_id,
            )
        assert self.execution_evidence_path is not None
        assert self.evidence_store is not None
        verified = verify_shared_execution_evidence(
            self.execution_evidence_path,
            placement=self.placement,
            output_text=result.text,
            not_before=execution_started_at,
        )
        self.evidence_store.bind(
            job_id=job_id,
            evidence_id=verified.evidence_id,
            document_sha256=verified.document_sha256,
            placement_decision_id=verified.placement_decision_id,
            output_sha256=verified.output_sha256,
            provider_shares=verified.provider_shares,
        )
        return BackendResult(
            result.text,
            result.prompt_tokens,
            result.completion_tokens,
            execution_job_id=job_id,
            provider_shares=verified.provider_shares,
            evidence_id=verified.evidence_id,
        )

    def complete(self, *, model_id: str, messages: list[dict[str, Any]]) -> BackendResult:
        if self.placement is not None and model_id != self.placement.model_id:
            raise InferenceBackendError("requested model does not match scheduler placement")
        job_id = self.id_factory()
        if not job_id:
            raise InferenceBackendError("orchestrator generated an empty job id")
        self.store.ensure_job(job_id)
        reservation_ids: list[str] = []
        try:
            self._advance_job(job_id, JobState.VALIDATING)
            self._advance_job(job_id, JobState.PLANNING)
            self._advance_job(job_id, JobState.RESERVING)
            reservation_ids = self._reserve_capacity(job_id)
            self._advance_job(job_id, JobState.PREPARING)
            self._activate(job_id, reservation_ids)
            self._advance_job(job_id, JobState.RUNNING)
            execution_started_at = datetime.now(timezone.utc)
            result = self.delegate.complete(model_id=model_id, messages=messages)
            self._advance_job(job_id, JobState.VERIFYING)
            if not isinstance(result.text, str) or result.prompt_tokens < 0 or result.completion_tokens < 0:
                raise InferenceBackendError("runtime result failed orchestrator verification")
            verified_result = self._verify_and_bind_evidence(
                job_id=job_id,
                result=result,
                execution_started_at=execution_started_at,
            )
            self._advance_job(job_id, JobState.COMPLETED)
            return verified_result
        except (ExecutionEvidenceError, ExecutionEvidenceBindingError) as exc:
            self._fail_job(job_id, exc)
            raise InferenceBackendError("shared runtime evidence verification failed") from exc
        except Exception as exc:
            self._fail_job(job_id, exc)
            if isinstance(exc, InferenceBackendError):
                raise
            raise InferenceBackendError("orchestrated inference execution failed") from exc
        finally:
            self._release(job_id, reservation_ids)


def _openai_backend_from_env() -> OpenAICompatibleHTTPBackend:
    base_url = os.environ.get("COMPUTEMESH_INFERENCE_URL", "").strip()
    if not base_url:
        raise InferenceBackendError(
            "COMPUTEMESH_INFERENCE_URL is required for the OpenAI-compatible backend"
        )
    try:
        timeout = float(os.environ.get("COMPUTEMESH_INFERENCE_TIMEOUT_SECONDS", "120"))
    except ValueError as exc:
        raise InferenceBackendError("Invalid COMPUTEMESH_INFERENCE_TIMEOUT_SECONDS") from exc
    return OpenAICompatibleHTTPBackend(
        base_url=base_url,
        api_key=os.environ.get("COMPUTEMESH_INFERENCE_API_KEY") or None,
        timeout_seconds=timeout,
    )


def _orchestrated_backend_from_env() -> OrchestratedInferenceBackend:
    store_path = os.environ.get("COMPUTEMESH_ORCHESTRATOR_STATE_PATH", "").strip()
    if not store_path:
        raise InferenceBackendError(
            "COMPUTEMESH_ORCHESTRATOR_STATE_PATH is required for orchestrated inference"
        )
    placement: PlacementSelection | None = None
    decision_path = os.environ.get("COMPUTEMESH_ORCHESTRATOR_PLACEMENT_DECISION", "").strip()
    evidence_path = os.environ.get("COMPUTEMESH_ORCHESTRATOR_SHARED_RUN_EVIDENCE", "").strip() or None
    try:
        if decision_path:
            placement = load_shared_placement_selection(
                decision_path,
                allow_experimental=(
                    os.environ.get("COMPUTEMESH_ALLOW_EXPERIMENTAL_SHARED_PLACEMENT", "").strip()
                    == "1"
                ),
            )
            nodes = list(placement.provider_node_ids)
        else:
            nodes = [
                value.strip()
                for value in os.environ.get("COMPUTEMESH_ORCHESTRATOR_PROVIDER_NODES", "").split(",")
                if value.strip()
            ]
        lease_seconds = int(os.environ.get("COMPUTEMESH_ORCHESTRATOR_LEASE_SECONDS", "180"))
        return OrchestratedInferenceBackend(
            delegate=_openai_backend_from_env(),
            store=SQLiteStateStore(store_path),
            provider_node_ids=nodes,
            lease_seconds=lease_seconds,
            placement=placement,
            execution_evidence_path=evidence_path,
        )
    except (OSError, ValueError, PlacementSelectionError) as exc:
        raise InferenceBackendError("Invalid orchestrated inference configuration") from exc


def build_inference_backend_from_env() -> InferenceBackend:
    """Build the configured gateway backend using secure fail-closed defaults."""
    backend = os.environ.get("COMPUTEMESH_INFERENCE_BACKEND", "disabled").strip().lower()
    if backend in {"", "disabled", "none"}:
        return DisabledInferenceBackend()
    if backend in {"openai", "openai-compatible", "openai_compatible", "llama.cpp", "llama_cpp"}:
        return _openai_backend_from_env()
    if backend in {"orchestrated", "orchestrated_openai", "orchestrated-openai"}:
        return _orchestrated_backend_from_env()
    if backend == "synthetic":
        if os.environ.get("COMPUTEMESH_ALLOW_SYNTHETIC_INFERENCE", "").strip() != "1":
            raise InferenceBackendError(
                "Synthetic inference requires COMPUTEMESH_ALLOW_SYNTHETIC_INFERENCE=1"
            )
        return SyntheticInferenceBackend()
    raise InferenceBackendError(f"Unsupported inference backend: {backend}")
