# ComputeMesh Threat Model

**Status:** Draft v0.2  
**Applies to:** V1 provider execution, control plane, model artifacts, telemetry, verification, billing, and update pipeline

## 1. Security objective

ComputeMesh deliberately uses machines that may not be owned or administered by the customer. The design therefore assumes that some providers, users, network paths, credentials, or services will eventually be faulty or hostile.

The security objective is not “trust every node.” It is to:

- limit what a compromised participant can do;
- prevent provider nodes from becoming arbitrary remote-execution hosts;
- make security-sensitive state auditable;
- avoid false confidentiality claims;
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
- embeddings;
- usage metadata;
- account/billing information;
- selected privacy policy.

### Platform-side

- model/shard manifests;
- artifact signatures;
- node identities;
- benchmark history;
- topology observations;
- scheduler decisions;
- reservations;
- job state;
- verification outcomes;
- reputation;
- ledger entries;
- settlement records;
- release signing keys;
- service credentials.

## 3. Threat actors

- malicious provider;
- compromised provider host;
- malicious customer;
- compromised customer credential;
- external network attacker;
- compromised control-plane service;
- malicious/compromised maintainer;
- compromised CI/build dependency;
- fraudulent payment participant;
- Sybil operator controlling many provider identities;
- curious provider attempting to inspect workload data.

## 4. Trust assumptions

V1 SHOULD assume:

- a consumer provider host can inspect memory of software running under its administrative control;
- signed software proves origin/integrity, not that the host is honest;
- TLS/QUIC protects transit, not execution on an untrusted endpoint;
- benchmark self-report is not trustworthy without corroboration;
- reputation can be manipulated through Sybil identities unless identity/economic controls exist;
- exact inference correctness is difficult to prove cheaply;
- public consumer compute is not suitable for strong confidentiality guarantees unless a specific confidential-computing design exists.

## 5. Trust boundaries

```text
User <-> Gateway
Gateway <-> Identity/Auth
Gateway <-> Orchestrator
Orchestrator <-> Scheduler
Scheduler <-> Node
Registry <-> Node cache
Node <-> Peer node
Node agent <-> Runtime worker
Runtime worker <-> GPU driver
Verification <-> Job evidence
Billing <-> Ledger
Billing <-> Payment provider
CI/Release <-> Update service <-> Node
Telemetry SDK <-> Telemetry service
```

Each boundary needs independent authentication, authorization, validation, and logging appropriate to its risk.

## 6. V1 workload boundary

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

Any feature that effectively reintroduces arbitrary code execution violates the V1 security model even if it is called a “plugin,” “tool,” or “custom op.”

## 7. Threat matrix

| Threat | Example | Impact | Primary controls | Residual risk |
| --- | --- | --- | --- | --- |
| Incorrect inference | provider returns fabricated tensors | wrong user output | redundancy sampling, canaries, reputation, trace checks | non-zero |
| Work fraud | provider claims work not done | financial loss | metering correlation, signed/structured events, scheduler observations | non-zero |
| Benchmark fraud | node reports impossible speed | bad placement | server-issued tests, consistency checks, runtime observations | non-zero |
| Sybil providers | one actor creates many “trusted” nodes | trust manipulation | identity friction, probation, correlated-risk detection | medium |
| Prompt inspection | provider admin reads memory | confidentiality loss | restrict sensitive jobs; confidential tier only with real mechanism | high on public nodes |
| Activation leakage | activations reveal information | confidentiality loss | same as above; minimize routing | workload-dependent |
| Model theft | provider copies cached weights | IP/license issue | license policy, access controls, encryption-at-rest where useful | cannot fully prevent on admin-controlled host |
| Node takeover | bug in worker exploited | provider compromise | narrow parser/runtime surface, sandboxing, signed updates, least privilege | medium |
| Control-plane takeover | attacker schedules malicious jobs | broad compromise | service isolation, least privilege, audit logs, key separation | high impact |
| Update compromise | malicious release | fleet compromise | offline/isolated signing, provenance, reproducible builds, revocation | critical |
| Artifact poisoning | malicious model/shard | incorrect/exploitable execution | digest pinning, signatures, registry policy | medium |
| Replay | old command re-applied | duplicate work/billing | request IDs, expiry, revisions, dedupe | low if implemented |
| DoS | job floods, huge artifacts | availability/cost | quotas, rate limits, size bounds, reservation limits | medium |
| Ledger tampering | false credit/debit | financial loss | append-only double-entry design, DB constraints, reconciliation | low/medium |
| Telemetry exfiltration | prompts enter logs | privacy loss | structured allowlist, redaction, content prohibition | medium |
| Insider abuse | operator queries sensitive data | privacy/financial | RBAC, break-glass, audit, separation of duties | medium |

## 8. Malicious provider

A malicious provider can:

- modify its OS or worker memory;
- inspect plaintext available to the runtime;
- falsify non-attested local telemetry;
- delay, drop, or alter results;
- emulate multiple identities;
- intentionally disconnect at costly moments;
- keep downloaded model artifacts.

Controls:

- probation for new identities;
- scheduler-side performance observation;
- random server-generated benchmark cases;
- artifact and worker signatures;
- sampled redundant execution;
- canaries;
- reputation with decay and confidence;
- per-job risk score;
- stronger verification for high-value work;
- delayed settlement where needed;
- privacy-tier exclusion.

**Important:** code signing does not prove the signed process is unmodified in memory on a fully compromised host.

## 9. Malicious customer

A customer may attempt:

- parser exploitation;
- oversized inputs;
- resource exhaustion;
- prompt-based abuse;
- arbitrary-code escape via model/runtime features;
- billing disputes/fraud;
- cancellation abuse;
- probing provider identities/network locations.

Controls:

- strict schemas and size limits;
- model/runtime allowlists;
- rate and budget limits;
- per-principal quotas;
- workload-boundary tests;
- no user-provided binaries or dynamic kernels;
- provider identity minimization;
- immutable usage records.

## 10. Provider-host compromise

Even an honest provider may run malware.

The node agent should:

- store long-lived secrets using OS-protected key storage where practical;
- use short-lived session credentials;
- run workers with least privilege;
- isolate cache paths;
- restrict inbound listeners;
- default to outbound authenticated connections/tunnels;
- avoid requiring public port forwarding;
- allow immediate drain/revoke;
- support signed updates and rollback.

## 11. Network threats

Threats:

- interception;
- tampering;
- replay;
- traffic analysis;
- downgrade;
- path manipulation;
- connection exhaustion.

Controls:

- authenticated encryption;
- version negotiation with downgrade protection;
- replay-safe application messages;
- connection quotas;
- bounded handshakes;
- endpoint identity validation.

Encrypted transport does not hide message timing/volume and does not secure plaintext after endpoint termination.

## 12. Data confidentiality

### Public compute

Assume the provider can inspect workload data accessible to its runtime. Suitable only for workloads whose policy allows that exposure.

### Region/datacenter restrictions

Geography and operator class reduce policy risk but do not inherently provide cryptographic confidentiality.

### Confidential compute

This label MUST NOT be enabled until a concrete design defines:

- supported hardware/TEE;
- attestation root;
- measured software identity;
- key release policy;
- memory confidentiality assumptions;
- GPU/accelerator path;
- rollback/replay protection;
- failure behavior;
- independent security review.

## 13. Model and artifact supply chain

Required:

- immutable digest;
- source metadata;
- license metadata;
- signer identity;
- signature verification;
- canonical manifest representation;
- artifact size bounds;
- quarantine on mismatch.

Future:

- transparency log;
- provenance/SBOM;
- reproducible conversion/quantization pipeline;
- multi-party approval for production model updates.

## 14. Software update supply chain

The update channel is one of the highest-impact attack surfaces.

Before public alpha:

- release signing keys separated from CI;
- signed release manifest;
- version monotonicity/anti-downgrade policy;
- rollback to known-good signed version;
- revocation mechanism;
- provenance/SBOM;
- staged rollout;
- emergency stop;
- auditable release history.

## 15. Identity and Sybil resistance

Node identity alone does not prove unique human/operator identity.

Reputation should include:

- identity age;
- successful verified work;
- failure history;
- correlated network/payment/device signals where legally appropriate;
- uncertainty/confidence;
- decay;
- probation.

The platform should avoid pretending reputation is Sybil-proof.

## 16. Verification limits

V1 verification can reduce risk but not guarantee correctness.

Levels may include:

- baseline integrity/reputation;
- canary;
- sampled redundancy;
- trace/challenge;
- stronger future proof systems.

No level should be marketed as “mathematical proof” unless the implemented mechanism actually provides it for the exact computation.

## 17. Billing threats

Threats:

- duplicate events;
- stale retries;
- provider self-report inflation;
- race conditions;
- partial job ambiguity;
- refund duplication;
- settlement replay.

Controls:

- append-only double-entry ledger;
- stable event IDs;
- unique constraints;
- job/segment attribution;
- scheduler + node correlation;
- explicit billable-state transitions;
- reconciliation.

## 18. Telemetry privacy

Default telemetry MUST exclude:

- raw prompts;
- raw outputs;
- authentication secrets;
- full model-generated content;
- arbitrary memory dumps.

Crash dumps are disabled or scrubbed by default on public provider nodes unless an explicit diagnostic consent path exists.

## 19. Security test requirements

Before public alpha:

- protocol parser fuzzing;
- malformed manifest tests;
- replay/idempotency tests;
- authn/authz tests;
- worker sandbox escape review;
- update downgrade/revocation tests;
- cache path traversal tests;
- oversized frame tests;
- cancellation/race tests;
- ledger duplication tests;
- secrets/logging audit;
- dependency/SBOM scanning.

## 20. Launch blockers

Public alpha is blocked until:

- node workload boundary exists and is tested;
- installer and updates are signed;
- rollback/revocation works;
- protocol authentication is production-grade;
- privacy tiers are accurately enforced and described;
- no sensitive content enters default logs;
- incident ownership exists;
- vulnerability disclosure channel exists;
- payment/privacy/terms review is complete;
- known critical/high findings are resolved or explicitly accepted.

## 21. Residual-risk statement

ComputeMesh cannot make an untrusted consumer PC equivalent to a confidential datacenter merely by encrypting network traffic. Some workloads may be inappropriate for public compute. Product UX and API policy must communicate this before dispatch, not bury it in legal text.
