# ComputeMesh Threat Model

**Status:** Draft v0.3 / active pre-production security model  
**Current as of:** 2026-09-03  
**Applies to:** provider execution, protected execution, control plane, model artifacts, telemetry, verification, billing and update pipeline

## 1. Security objective

ComputeMesh deliberately uses machines that may not be owned or administered by the customer. The design therefore assumes that some providers, users, network paths, credentials or services will eventually be faulty or hostile.

The security objective is not “trust every node.” It is to:

- limit what a compromised participant can do;
- prevent provider nodes from becoming arbitrary remote-execution hosts;
- make security-sensitive state auditable;
- avoid false confidentiality claims;
- prevent silent privacy downgrade;
- detect or contain suspicious results;
- prevent duplicate or fabricated financial effects;
- keep compromise of one service from automatically compromising every control plane.

## 2. Primary assets

### Provider-side

- provider operating system and files;
- GPU/CPU resources;
- node identity keys;
- update channel;
- local model cache;
- provider earnings data.

### Customer-side

- prompts and inputs;
- outputs;
- token IDs/KV/intermediate state when protected;
- embeddings;
- usage metadata;
- account/billing information;
- selected privacy policy;
- request-scoped content/transport keys.

### Platform-side

- model/shard manifests;
- artifact signatures;
- node identities;
- benchmark history;
- topology observations;
- scheduler decisions;
- reservations;
- job/session state;
- verification outcomes;
- reputation;
- ledger/escrow entries;
- settlement records;
- release signing keys;
- service credentials;
- confidential attestation policy and verifier/helper identity.

## 3. Threat actors

- malicious provider;
- compromised provider host/root/admin;
- curious provider attempting to inspect workload data;
- malicious customer;
- compromised customer credential;
- external network attacker/MITM;
- compromised gateway/control-plane service;
- malicious/compromised maintainer;
- compromised CI/build/dependency;
- fraudulent payment participant;
- Sybil operator controlling many provider identities.

## 4. Trust assumptions

ComputeMesh assumes:

- a normal consumer provider host can inspect memory of software running under its administrative control;
- signed software proves origin/integrity, not that the host is honest at runtime;
- TLS/QUIC protects transit, not execution on an untrusted endpoint;
- benchmark self-report is not trustworthy without corroboration;
- reputation is not inherently Sybil-proof;
- exact inference correctness is difficult to prove cheaply;
- `PUBLIC` consumer compute is not suitable for strong confidentiality guarantees;
- `CONFIDENTIAL` is valid only for a concrete, attested protected hardware/runtime topology;
- CI or simulated evidence cannot substitute for physical confidential-compute acceptance;
- `CRYPTO_PRIVATE` requires a separately validated cryptographic construction and is not provided by ordinary sharding or the current orthogonal blinding prototype.

## 5. Trust boundaries

```text
Application/SDK <-> local trusted ComputeMesh proxy (protected mode)
Local proxy <-> remote Gateway
Gateway <-> Identity/Auth
Gateway <-> private Control Plane
Private Control Plane <-> authenticated Provider Control Session
Provider Control Session <-> Protected Worker
Protected Worker <-> measured inference runtime <-> GPU/accelerator
Gateway/Worker <-> confidential session/replay state
Protected Worker <-> content-free metering receipt
Billing <-> confidential escrow/ledger
Registry <-> Node cache
Verification <-> Job evidence
CI/Release <-> Update service <-> Node
Telemetry SDK <-> Telemetry service
```

Each boundary needs independent authentication, authorization, validation and logging appropriate to its risk.

The private control plane is **not** the sole trust root for protected content. In protected mode the local trusted client must independently verify the technology-specific attestation and bound endpoint/key identities before sending protected plaintext-derived ciphertext.

## 6. Workload boundary

### Allowed

- signed ComputeMesh node agent;
- signed/approved runtime workers;
- approved model artifacts;
- declared inference operations;
- bounded runtime-specific kernels/graphs;
- controlled artifact/cache operations;
- defined telemetry.

### Disallowed

- remote shell;
- arbitrary Python;
- arbitrary user-supplied CUDA;
- arbitrary containers;
- arbitrary binaries;
- arbitrary filesystem paths;
- arbitrary host process launch;
- generic plugin upload;
- provider-to-provider arbitrary RPC.

Any feature that effectively reintroduces arbitrary code execution violates the security model even if called a plugin, tool or custom operation.

## 7. Threat matrix

| Threat | Example | Impact | Primary controls | Residual risk |
| --- | --- | --- | --- | --- |
| Incorrect inference | provider returns fabricated tensors/output | wrong user output | evidence, redundancy/canaries where used, reputation, runtime binding | non-zero |
| Work fraud | provider claims work not done | financial loss | content-free signed usage receipts, scheduler observations, idempotent ledger | non-zero |
| Benchmark fraud | node reports impossible speed | bad placement | server-issued tests, consistency checks, runtime observations | non-zero |
| Sybil providers | one actor creates many identities | trust manipulation | identity friction, probation, correlated-risk detection | medium |
| Prompt inspection on PUBLIC | provider admin reads runtime memory | confidentiality loss | do not route sensitive jobs to PUBLIC | high on public nodes |
| Prompt inspection on CONFIDENTIAL | root/admin attacks declared protected boundary | confidentiality loss | real hardware TEE/CC, attestation, protected memory, physical adversarial acceptance | must be physically validated |
| Activation/KV leakage | intermediate state reveals content | confidentiality loss | protected boundary or separately validated cryptographic construction | topology-dependent |
| Endpoint/key substitution | attacker replaces worker endpoint/X25519/metering key | confidentiality/billing loss | attestation-bound keys/TLS identity + local independent verification | low only after full validation |
| Replay | request/stream/receipt reused | duplicate compute/billing | durable replay tombstones, sequence/final binding, idempotent settlement | low if complete |
| MITM/downgrade | redirect protected traffic to wrong endpoint | confidentiality loss | TLS pinning + attestation endpoint binding + no fallback | low if complete |
| Model theft | provider copies cached weights | IP/license issue | license policy, access controls | cannot fully prevent on admin-controlled PUBLIC host |
| Node takeover | worker bug exploited | provider compromise | narrow parser/runtime surface, sandboxing, signed updates, least privilege | medium |
| Control-plane takeover | attacker manipulates placement/provision | broad compromise | service isolation, least privilege, reduced responses, local attestation verification | high impact |
| Update compromise | malicious release | fleet compromise | isolated signing, provenance, reproducible builds, revocation | critical |
| Artifact poisoning | malicious model/shard | incorrect/exploitable execution | digest pinning, signatures, registry policy | medium |
| DoS | job floods/huge frames | availability/cost | quotas, rate limits, size bounds, reservations | medium |
| Ledger tampering | false credit/debit | financial loss | double-entry, deterministic event IDs, DB constraints, reconciliation | low/medium |
| Telemetry exfiltration | prompts/token IDs enter logs | privacy loss | structured allowlist/content prohibition | medium |
| Insider abuse | operator queries sensitive data | privacy/financial | RBAC, break-glass, audit, separation of duties | medium |

## 8. Malicious provider

A malicious provider can:

- modify its OS or unprotected worker memory;
- inspect any plaintext available outside a real protected boundary;
- falsify non-attested local telemetry;
- delay, drop or alter results;
- emulate multiple identities;
- intentionally disconnect at costly moments;
- keep downloaded model artifacts;
- attempt stale/fake attestation, endpoint substitution, replay, debug-mode execution or memory inspection.

Controls include authenticated node sessions, signed/approved software/artifacts, scheduler observations, evidence, private risk policy, protected-execution exclusion, fresh attestation, endpoint/key binding, replay protection, content-free metering and delayed/idempotent settlement where appropriate.

**Important:** code signing does not prove the signed process is unmodified in memory on a fully compromised host. `CONFIDENTIAL` therefore requires the declared hardware-backed protection and attestation chain.

## 9. Malicious customer

A customer may attempt:

- parser exploitation;
- oversized inputs;
- resource exhaustion;
- arbitrary-code escape via model/runtime features;
- billing disputes/fraud;
- cancellation/replay abuse;
- probing provider identities/network locations;
- malformed protected envelopes/streams.

Controls:

- strict schemas and size limits;
- model/runtime allowlists;
- rate and budget limits;
- per-principal quotas;
- workload-boundary tests;
- no user-provided binaries/dynamic kernels;
- provider identity minimization;
- replay-safe state;
- authenticated accounting records.

## 10. Provider-host compromise

Even an honest provider may run malware.

The node agent/runtime should:

- use OS-protected storage for long-lived node keys where practical;
- use short-lived authenticated control sessions;
- run workers with least privilege;
- isolate cache paths;
- restrict inbound listeners;
- default to outbound authenticated control connections where possible;
- allow immediate drain/revoke;
- support signed updates/rollback;
- keep the protected worker separate from raw public runtime transport;
- disable dumps and page sensitive memory where required;
- keep request-scoped protected keys inside the declared protected boundary.

## 11. Network threats

Threats:

- interception;
- tampering;
- replay;
- traffic analysis;
- downgrade;
- path/endpoint manipulation;
- connection exhaustion.

Controls:

- authenticated encryption;
- TLS certificate fingerprint pinning for protected endpoints;
- attestation binding of endpoint identity;
- replay-safe application messages;
- stream sequence/final authentication;
- connection quotas and bounded frames;
- no protected fallback to raw RPC/public compute.

Encrypted transport does not hide timing/volume and does not secure plaintext after an unprotected endpoint terminates TLS.

## 12. Data confidentiality

### `PUBLIC`

Assume the provider can inspect workload data accessible to its runtime. Suitable only for workloads whose policy allows that exposure.

### Region/operator/datacenter restrictions

Geography/operator class can constrain policy risk but does not inherently provide execution-memory confidentiality.

### `CONFIDENTIAL`

A concrete implementation foundation now exists, but the production guarantee remains blocked until the full hardware-backed path is physically validated.

Merged foundations include fail-closed protected execution, an attestation-bound confidential envelope and a hash-pinned NVIDIA verifier-process boundary.

Open draft PR #76 additionally implements branch-local protected request/response/stream transport, local OpenAI proxying, durable confidential sessions, content-free metering/escrow, unified gateway composition, reduced remote broker, authenticated provider-control provisioning and a dedicated protected-worker HTTPS boundary.

Production `CONFIDENTIAL` requires all of the following to be verified for the exact job:

- supported confidential-compute hardware/topology;
- fresh technology-specific attestation;
- approved measured runtime;
- production/debug-disabled confidential-compute state where applicable;
- account/job/model/privacy/operation/token-budget binding;
- attested request-scoped X25519 recipient key;
- attested Ed25519 metering key;
- attested TLS endpoint identity;
- local independent attestation verification;
- request/stream replay protection;
- bounded plaintext lifetime, page/dump hardening and zeroization;
- encrypted response before data leaves the protected boundary;
- content-free authenticated metering and idempotent accounting.

Until the vendor-supported verifier/helper is built and physically/adversarially validated on supported hardware, ComputeMesh must not claim that `CONFIDENTIAL` provides a production hardware confidentiality guarantee.

### `CRYPTO_PRIVATE`

This class requires a separately validated cryptographic private-computation design. Ordinary sharding, TLS or the current simple orthogonal hidden-state transform do not satisfy it.

## 13. Model and artifact supply chain

Required:

- immutable digest;
- source/license metadata;
- signer/authenticity policy;
- canonical manifest representation;
- artifact size bounds;
- quarantine on mismatch.

Future/production hardening includes transparency/provenance/SBOM, reproducible conversion/quantization and stronger production approval policy.

## 14. Software update and verifier-helper supply chain

The update channel and any security-critical vendor-attestation helper are high-impact attack surfaces.

Before production:

- release signing keys separated from ordinary CI;
- signed release manifests;
- version monotonicity/anti-downgrade policy;
- rollback to known-good signed version;
- revocation mechanism;
- provenance/SBOM;
- staged rollout/emergency stop;
- auditable release history;
- hash-pinning and operator review of the attestation helper used by protected policy.

## 15. Identity and Sybil resistance

Node identity does not prove unique human/operator identity. Reputation/private risk policy may use identity age, verified work, failures, correlated signals where lawful, uncertainty and probation. The platform must not claim Sybil-proof trust.

## 16. Verification limits

Verification can reduce risk but must not be overstated. Canaries, redundancy, traces and attestation prove different properties. No mechanism should be described as mathematical proof unless it actually proves the exact claimed computation/security property.

## 17. Billing threats

Threats include duplicate events, stale retries, provider self-report inflation, races, partial jobs, refund duplication and settlement replay.

Protected billing controls include pre-content reservation, content-free signed usage receipts, durable `METERED` state, double-entry escrow, deterministic event IDs, unique/idempotent settlement and reconciliation.

Prompt/output/token IDs are not required for billing and must not be persisted there.

## 18. Telemetry privacy

Default telemetry MUST exclude:

- raw prompts;
- raw outputs;
- authentication secrets;
- full generated content;
- reusable content keys;
- token IDs or semantically useful protected intermediate state;
- arbitrary memory dumps.

Crash dumps are disabled or scrubbed by default on provider nodes; protected worker processes require stricter dump/page handling according to policy.

## 19. Security test requirements

Before public production use:

- protocol parser fuzzing;
- malformed/oversized input tests;
- replay/idempotency tests;
- authn/authz tests;
- worker sandbox/boundary review;
- update downgrade/revocation tests;
- cache path traversal tests;
- cancellation/race tests;
- ledger/escrow duplication tests;
- secrets/logging audit;
- dependency/SBOM scanning;
- protected MITM/wrong-endpoint tests;
- stale/wrong/debug-enabled attestation tests;
- runtime/X25519/metering-key substitution tests;
- provider-root/admin memory inspection acceptance;
- core-dump/swap/pagefile attempts;
- protected stream reorder/replay/truncation tests;
- crash-before/after settlement recovery tests.

## 20. Launch blockers

Public production is blocked until the relevant scope has:

- tested workload boundaries;
- signed/revocable release/update path;
- production-grade authentication/authorization;
- accurate enforced privacy classes;
- no sensitive content in default logs;
- hardened key lifecycle;
- authenticated/encrypted production data plane;
- incident ownership and vulnerability disclosure process;
- payment/privacy/terms review;
- known critical/high findings resolved or explicitly accepted.

Enabling a production `CONFIDENTIAL` guarantee has additional blockers:

- complete private broker → authenticated provider-control → protected worker deployment;
- complete fail-closed confidential startup/readiness;
- vendor-supported attestation helper integration;
- physical supported-hardware acceptance;
- adversarial provider-root/MITM/replay/substitution/dump/swap/logging acceptance;
- documentation and deployed product claims synchronized with the validated reality.

## 21. Residual-risk statement

ComputeMesh cannot make an ordinary untrusted consumer PC equivalent to a confidential datacenter merely by encrypting network traffic. `PUBLIC` workloads remain visible to a sufficiently privileged provider host. `CONFIDENTIAL` is only as strong as the exact physically validated protected hardware/software chain used for that job, and side channels or platform-specific residual risks must be documented for each supported topology.
