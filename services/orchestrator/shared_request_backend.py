"""Direct orchestrated two-node llama.cpp request with signed settlement evidence."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import secrets
from typing import Any, Callable

from runtime.llama.rpc_spike import RpcEndpoint
from runtime.llama.shared_request import SharedRequestResult, run_shared_request
from runtime.llama.shared_request_live import SharedRequestCancelled
from services.gateway.execution_attestation import VerificationKeyResolver, verify_execution_attestations
from services.gateway.inference_backend import BackendResult, InferenceBackendError
from services.gateway.placement_selection import PlacementSelection
from services.gateway.shared_request_evidence import SharedRequestEvidenceError, verify_shared_request_evidence
from services.orchestrator.attestation_collection import NodeAttestationTransport, collect_execution_attestations
from services.orchestrator.evidence_store import ExecutionEvidenceStore
from services.orchestrator.persistence import SQLiteStateStore
from services.orchestrator.state_machine import JobState, ReservationState


class SharedRequestSettlementError(InferenceBackendError):
    pass


def _canonical_digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")).hexdigest()


def build_shared_request_attestation_request(*, evidence_path: Path) -> dict[str, Any]:
    try:
        evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise SharedRequestSettlementError("shared-request evidence could not be read for attestation") from exc
    if not isinstance(evidence, dict) or evidence.get("scope") != "shared_request_execution":
        raise SharedRequestSettlementError("attestation requires shared_request_execution evidence")
    nodes = evidence.get("participants")
    if not isinstance(nodes, list) or len(nodes) < 2 or len(set(nodes)) != len(nodes):
        raise SharedRequestSettlementError("shared-request evidence participant set is invalid")
    request = {
        "schema_version": 1,
        "job_id": evidence["job_id"],
        "placement_decision_id": evidence["placement_decision_id"],
        "model_sha256": evidence["model"]["sha256"],
        "runtime_sha256": _canonical_digest(evidence["runtime"]),
        "evidence_sha256": hashlib.sha256(evidence_path.read_bytes()).hexdigest(),
        "output_sha256": evidence["request"]["output_sha256"],
        "expected_nodes": list(nodes),
    }
    request["request_id"] = "execution-attestation-request-" + _canonical_digest(request)[:16]
    return request


def _render_messages(messages: list[dict[str, Any]]) -> str:
    if not isinstance(messages, list) or not messages:
        raise SharedRequestSettlementError("messages must be a non-empty list")
    lines: list[str] = []
    for message in messages:
        if not isinstance(message, dict):
            raise SharedRequestSettlementError("chat message must be an object")
        role = message.get("role")
        content = message.get("content")
        if role not in {"system", "user", "assistant"} or not isinstance(content, str):
            raise SharedRequestSettlementError("shared request currently requires text system/user/assistant messages")
        lines.append(f"{role}: {content}")
    lines.append("assistant:")
    return "\n".join(lines)


class SharedRequestOrchestratedBackend:
    """Execute and settle one scheduler-selected two-node request end-to-end."""

    def __init__(
        self,
        *,
        store: SQLiteStateStore,
        placement: PlacementSelection,
        bundle_path: Path,
        llama_server: Path,
        model_path: Path,
        worker_rpc: RpcEndpoint,
        work_root: Path,
        attestation_transport: NodeAttestationTransport,
        attestation_resolver: VerificationKeyResolver,
        lease_seconds: int = 600,
        id_factory: Callable[[], str] | None = None,
        runner: Callable[..., SharedRequestResult] = run_shared_request,
        prompt_renderer: Callable[[list[dict[str, Any]]], str] = _render_messages,
    ) -> None:
        if len(placement.provider_node_ids) < 2:
            raise ValueError("shared request orchestration requires at least two providers")
        if lease_seconds < 30 or lease_seconds > 3600:
            raise ValueError("lease_seconds must be 30..3600")
        self.store = store
        self.placement = placement
        self.bundle_path = Path(bundle_path)
        self.llama_server = Path(llama_server)
        self.model_path = Path(model_path)
        self.worker_rpc = worker_rpc
        self.work_root = Path(work_root)
        self.attestation_transport = attestation_transport
        self.attestation_resolver = attestation_resolver
        self.lease_seconds = lease_seconds
        self.id_factory = id_factory or (lambda: f"inf-{secrets.token_hex(12)}")
        self.runner = runner
        self.prompt_renderer = prompt_renderer
        self.evidence_store = ExecutionEvidenceStore(store)

    def _advance(self, job_id: str, target: JobState) -> None:
        current = self.store.get_job(job_id)
        self.store.transition_job(
            job_id,
            request_id=f"{job_id}:job:{target.value.lower()}",
            expected_revision=current.revision,
            target=target,
            request_fingerprint=f"shared-request:{self.placement.decision_id}:{target.value}",
        )

    def _reservation_ids(self, job_id: str) -> list[str]:
        return [f"{job_id}:capacity:{index}:{node}" for index, node in enumerate(self.placement.provider_node_ids)]

    def _reserve(self, job_id: str) -> list[str]:
        expires = datetime.now(timezone.utc) + timedelta(seconds=self.lease_seconds)
        ids = self._reservation_ids(job_id)
        for index, (reservation_id, node_id) in enumerate(zip(ids, self.placement.provider_node_ids)):
            self.store.ensure_reservation(reservation_id)
            fingerprint = f"node={node_id};job={job_id};placement={self.placement.decision_id}"
            leased = self.store.lease_reservation(
                reservation_id,
                request_id=f"{job_id}:lease:{index}",
                expected_revision=0,
                expires_at=expires,
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
        return ids

    def _activate(self, job_id: str, ids: list[str]) -> None:
        for index, reservation_id in enumerate(ids):
            current = self.store.get_reservation(reservation_id)
            if current.state != ReservationState.COMMITTED or current.lease_expires_at is None or current.lease_expires_at <= datetime.now(timezone.utc):
                raise SharedRequestSettlementError("capacity reservation is not dispatchable")
            self.store.transition_reservation(
                reservation_id,
                request_id=f"{job_id}:activate:{index}",
                expected_revision=current.revision,
                target=ReservationState.ACTIVE,
                request_fingerprint=f"dispatch:{job_id}:{self.placement.decision_id}",
            )

    def _release(self, job_id: str, ids: list[str]) -> None:
        for index, reservation_id in enumerate(ids):
            try:
                current = self.store.get_reservation(reservation_id)
            except KeyError:
                continue
            if current.state in {ReservationState.COMMITTED, ReservationState.ACTIVE}:
                self.store.transition_reservation(
                    reservation_id,
                    request_id=f"{job_id}:release:{index}",
                    expected_revision=current.revision,
                    target=ReservationState.RELEASED,
                    request_fingerprint=f"release:{job_id}",
                )

    def _terminal(self, job_id: str, target: JobState, fingerprint: str) -> None:
        try:
            current = self.store.get_job(job_id)
            if current.state not in {JobState.FAILED, JobState.CANCELLED, JobState.COMPLETED, JobState.SETTLED}:
                self.store.transition_job(
                    job_id,
                    request_id=f"{job_id}:job:{target.value.lower()}",
                    expected_revision=current.revision,
                    target=target,
                    request_fingerprint=fingerprint,
                )
        except Exception:
            pass

    def _fail(self, job_id: str, exc: Exception) -> None:
        self._terminal(job_id, JobState.FAILED, f"shared-request-failure:{type(exc).__name__}")

    def _cancel(self, job_id: str) -> None:
        self._terminal(job_id, JobState.CANCELLED, "shared-request-cancel:stop_new_billable_work")

    def complete(self, *, model_id: str, messages: list[dict[str, Any]]) -> BackendResult:
        if model_id != self.placement.model_id:
            raise SharedRequestSettlementError("requested model does not match scheduler placement")
        job_id = self.id_factory()
        self.store.ensure_job(job_id)
        reservations: list[str] = []
        try:
            self._advance(job_id, JobState.VALIDATING)
            self._advance(job_id, JobState.PLANNING)
            self._advance(job_id, JobState.RESERVING)
            reservations = self._reserve(job_id)
            self._advance(job_id, JobState.PREPARING)
            self._activate(job_id, reservations)
            self._advance(job_id, JobState.RUNNING)
            started = datetime.now(timezone.utc)
            prompt = self.prompt_renderer(messages)
            work_dir = self.work_root / job_id
            runtime_result = self.runner(
                job_id=job_id,
                bundle_path=self.bundle_path,
                llama_server=self.llama_server,
                model_path=self.model_path,
                worker_rpc=self.worker_rpc,
                output_dir=work_dir,
                prompt=prompt,
            )
            self._advance(job_id, JobState.VERIFYING)
            verified = verify_shared_request_evidence(
                runtime_result.evidence_path,
                placement=self.placement,
                job_id=job_id,
                output_text=runtime_result.text,
                prompt_tokens=runtime_result.prompt_tokens,
                completion_tokens=runtime_result.completion_tokens,
                not_before=started,
            )
            request_doc = build_shared_request_attestation_request(evidence_path=runtime_result.evidence_path)
            request_path = work_dir / "execution_attestation_request.json"
            request_path.write_text(json.dumps(request_doc, indent=2, sort_keys=True) + "\n", encoding="utf-8")
            bundle_path = work_dir / "execution_attestations.json"
            collect_execution_attestations(
                request_path=request_path,
                output_path=bundle_path,
                transport=self.attestation_transport,
            )
            verify_execution_attestations(
                bundle_path,
                resolver=self.attestation_resolver,
                expected_nodes=self.placement.provider_node_ids,
                job_id=job_id,
                placement_decision_id=verified.placement_decision_id,
                model_sha256=verified.model_sha256,
                runtime_sha256=verified.runtime_sha256,
                evidence_sha256=verified.document_sha256.removeprefix("sha256:"),
                output_sha256=verified.output_sha256,
            )
            self.evidence_store.bind(
                job_id=job_id,
                evidence_id=verified.evidence_id,
                document_sha256=verified.document_sha256,
                placement_decision_id=verified.placement_decision_id,
                output_sha256=verified.output_sha256,
                provider_shares=verified.provider_shares,
            )
            self._advance(job_id, JobState.COMPLETED)
            return BackendResult(
                runtime_result.text,
                runtime_result.prompt_tokens,
                runtime_result.completion_tokens,
                execution_job_id=job_id,
                provider_shares=verified.provider_shares,
                evidence_id=verified.evidence_id,
            )
        except SharedRequestCancelled as exc:
            self._cancel(job_id)
            raise SharedRequestSettlementError("shared request was cancelled") from exc
        except Exception as exc:
            self._fail(job_id, exc)
            if isinstance(exc, InferenceBackendError):
                raise
            if isinstance(exc, SharedRequestEvidenceError):
                raise SharedRequestSettlementError("shared-request evidence verification failed") from exc
            raise SharedRequestSettlementError("shared-request orchestration failed") from exc
        finally:
            self._release(job_id, reservations)
