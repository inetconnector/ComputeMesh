# ComputeMesh documentation

Start here for public documentation:

1. [`CURRENT_STATUS.md`](CURRENT_STATUS.md) / [`CURRENT_STATUS.de.md`](CURRENT_STATUS.de.md) — current public-safe implementation/readiness status.
2. [`DOCUMENTATION_INDEX.md`](DOCUMENTATION_INDEX.md) — complete documentation authority map and audit classification.
3. [`DOCUMENTATION_REVIEW.md`](DOCUMENTATION_REVIEW.md) — findings from the 2026-08-27 full documentation audit.
4. [`CONFIDENTIAL_GLOBAL_MESH.md`](CONFIDENTIAL_GLOBAL_MESH.md) and [`GLOBAL_MESH_POLICY_MATRIX.md`](GLOBAL_MESH_POLICY_MATRIX.md) — orthogonal provider-trust/execution-privacy model, global PUBLIC routing and fail-closed confidential gates.
5. Root `README.md` / `README.de.md` — project overview and detailed public engineering paths.
6. The nearest component `README.md` — implementation details for a specific subsystem.
7. Root `ARCHITECTURE.md`, `PROTOCOL.md`, `THREAT_MODEL.md`, `IMPLEMENTATION_PLAN.md` and ADRs — target/historical design context.
8. Root `state.md` — detailed public engineering/evidence chronology.

The production scheduler/ranking, private empirical data, reputation/fraud policy, pricing/marketplace/settlement policy and private current state are intentionally outside this public repository in `ComputeMesh-ControlPlane`. Do not copy proprietary implementation details into public docs merely to make the documentation appear self-contained.

The public global-mesh policy code is deliberately limited to enforceable contracts and fail-closed gates. Concrete production confidential-compute technologies remain disabled until a technology-specific verifier is implemented, tested and explicitly enabled.

For portal marketing/readiness claim limits see [`PORTAL_CLAIMS_AUDIT.md`](PORTAL_CLAIMS_AUDIT.md).
