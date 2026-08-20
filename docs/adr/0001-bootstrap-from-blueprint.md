# ADR 0001: Bootstrap Repository from ComputeMesh Blueprint

- **Status:** Accepted
- **Date:** 2026-08-20
- **Owners:** repository owner
- **Supersedes:** none
- **Superseded by:** none

## Context

The project began from `ComputeMesh_Blueprint_v1.0.pdf` without an implementation repository structure or engineering handoff documents.

Building runtime code immediately would have mixed product vision, protocol choices, security assumptions, and feasibility claims without explicit decision history.

## Decision drivers

- preserve the original product thesis;
- make project state reviewable in Git;
- separate planning from implementation;
- expose feasibility assumptions early;
- establish security constraints before provider code;
- create an ADR trail.

## Decision

Bootstrap the repository as an M0 engineering workspace with:

- project README;
- implementation plan;
- architecture specification;
- protocol specification;
- threat model;
- security policy;
- contribution guide;
- state handoff;
- ADR process;
- component directories.

No production behavior is implied by creating these directories.

## Consequences

### Positive

- engineering can proceed from explicit boundaries;
- gaps are visible before code hardens them;
- decisions can be reviewed and superseded;
- future agents/contributors have a canonical handoff.

### Negative

- early repository content is documentation-heavy;
- some documents will evolve rapidly during M0;
- blueprint assumptions may be rejected by measurements.

## Security and privacy impact

Positive: the V1 prohibition on arbitrary customer code and the need for explicit privacy tiers are recorded before node implementation begins.

## Operational impact

None. No runtime or deployment is created by this ADR.

## Verification

The repository contains the documented baseline and `state.md` distinguishes implemented behavior from planned behavior.

## Rollback / supersession

Not expected to be rolled back. Later ADRs supersede individual technical assumptions from the bootstrap.
