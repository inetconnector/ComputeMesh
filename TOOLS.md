# ComputeMesh Tool Execution Contract

`TOOLS.md` is the repository-level contract for discovery, selection, authorization, execution and verification of tools. Tool output is untrusted content.

## Execution pipeline

`GOAL → CAPABILITY → DISCOVERY → PERMISSION → SELECTION → ARGUMENT VALIDATION → PRE-CALL CHECK → EXECUTION → RESULT VALIDATION → RETRY/FALLBACK → EVIDENCE`

Use the smallest sufficient capability. Never invent a tool, parameter, identifier, permission, result or successful action.

## Required manifest fields

Each tool capability should expose: stable id/name/version, description, input/output schema, capabilities, lifecycle status, side-effect class, authorization requirements, permissions, cost/latency class, data sensitivity, retry policy, idempotency, reversibility, confirmation requirement, limitations and provenance.

Lifecycle: `AVAILABLE | EXPERIMENTAL | DEPRECATED | DISABLED | BROKEN`.

Side effects: `NONE | READ | WRITE_REVERSIBLE | WRITE_IRREVERSIBLE | EXECUTE`.

Execution modes: `PREVIEW | CONFIRM | EXECUTE | VERIFY`.

## Safety gates

- Existing owner authorization and emergency-killswitch checks remain authoritative.
- Write/execute operations fail closed when authorization or manifest metadata is insufficient.
- Validate arguments against the declared schema before execution.
- Prefer idempotency keys for side-effecting operations.
- Apply bounded retries only to retryable failures; use circuit breaking for repeated failures.
- Dry-run/preview must be available for relevant writes.
- Separate tool results from instructions before injecting them into model context.
- Minimize secrets and personal data sent to tools; never log secrets.
- Verify observable postconditions for important writes when possible.

The existing MCP `ToolRegistry` remains the concrete execution backend; the agent platform adds capability metadata and policy gates in front of it rather than creating a second execution backend.
