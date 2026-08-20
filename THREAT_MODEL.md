# ComputeMesh Threat Model

This document defines the initial security posture for ComputeMesh. It must be updated as implementation begins.

## Primary Assets

- provider machines
- user prompts and outputs
- model shards and manifests
- node identities
- benchmark and reputation records
- job execution traces
- billing ledger
- payment records
- scheduler decisions
- update channel

## Trust Boundaries

- user client to gateway
- gateway to scheduler
- scheduler to node
- node to data plane peer
- node to local GPU/runtime
- registry to node shard cache
- verification service to job execution
- billing service to payment provider

## V1 Security Rule

V1 must not execute arbitrary customer code on provider machines.

Allowed:

- signed ComputeMesh worker
- approved inference workloads
- approved model shards
- constrained runtime operations

Disallowed:

- remote shell
- arbitrary Python
- arbitrary containers
- user-supplied binaries
- unrestricted filesystem access
- unreviewed plugins or extensions on provider nodes

## Threats

### Malicious Provider

Risks:

- returns incorrect results
- claims work not performed
- manipulates benchmark results
- exfiltrates data
- hosts modified worker

Controls:

- signed worker attestation where possible
- canary jobs
- random redundancy
- challenge/response
- reputation penalties
- benchmark validation
- privacy-tier restrictions

### Malicious User

Risks:

- tries to execute arbitrary code
- sends adversarial prompts to extract data
- abuses API for denial of service
- disputes valid billing

Controls:

- no arbitrary code execution
- workload validation
- rate limits
- billing audit trail
- abuse detection
- privacy policy and terms

### Compromised Control Plane

Risks:

- malicious assignments
- false ledger entries
- poisoned scheduler data
- leaked job metadata

Controls:

- least privilege service accounts
- append-only audit logs
- separation of billing, scheduler, and verification privileges
- signed release pipeline
- incident response process

### Compromised Update Channel

Risks:

- malware delivered to provider nodes
- silent downgrade
- supply-chain attack

Controls:

- signed releases
- reproducible builds
- rollback support
- version pinning
- update transparency log
- emergency revocation

### Data Leakage

Risks:

- prompts or activations exposed to unsuitable nodes
- sensitive workloads scheduled to public compute
- logs contain private data

Controls:

- privacy tiers as hard constraints
- data-minimizing telemetry
- redaction in logs
- datacenter-only and confidential-compute routing
- user-facing workload classification

## Verification Levels

- Level 0: benchmark and reputation only
- Level 1: canary jobs with known result
- Level 2: random redundancy on a second node
- Level 3: challenge/response and trace checks
- Level 4: stronger proof-of-inference research

Verification rate should be adaptive:

- higher for new nodes
- higher for high-value jobs
- higher for privacy-sensitive workloads
- lower for long-lived reliable nodes where risk allows

## Launch Blockers

Public alpha must not launch until:

- signed installer exists
- auto-update rollback exists
- provider workload boundary is enforced
- security disclosure process exists
- payment and privacy review are complete
- crash reporting is data-minimizing
- incident response ownership is defined
