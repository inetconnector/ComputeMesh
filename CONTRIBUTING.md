# Contributing

ComputeMesh is at the planning and research bootstrap stage. Contributions should make the project more measurable, safer, or closer to the first technical proof.

## Principles

- Prefer evidence over opinion.
- Keep changes small and reviewable.
- Tie implementation work to `IMPLEMENTATION_PLAN.md`.
- Record architecture decisions in `docs/adr/`.
- Do not introduce token, marketplace, or launch work before the technical gates are addressed.
- Do not weaken the V1 rule that provider nodes cannot run arbitrary customer code.

## Development Flow

1. Create a branch for each focused change.
2. Update or add tests for code changes.
3. Update `README.md` and `state.md` when behavior, setup, structure, or project status changes.
4. Add an ADR for material architecture decisions.
5. Document verification commands and actual results.

## Commit Style

Use clear, scoped commit messages:

```text
docs: add scheduler ADR template
runtime: prototype remote shard loader
tests: add node state machine cases
```

## Review Expectations

Review should focus on:

- correctness
- safety
- observability
- test coverage
- failure handling
- billing and ledger implications
- provider host security

## Current Priority

The current priority is M0:

- architecture
- protocol
- threat model
- benchmark harness design
- two-node lab preparation
