# AI Capability Baseline (Paket 0, v1)

This is **infrastructure**, not an achieved AI-quality baseline or approval to activate
a model, MCP server, browser, device or deployment.

## Versioned task corpus

`ai_capability_tasks_v1.json` contains 22 synthetic DE/EN tasks across the
three tiers `basic`, `intermediate`, `advanced`. It covers research with
citations, multi-tool work, file analysis, code changes with real test results,
durable restart, images, speech, Android offline/reconnect, hostile tool output,
principal changes and budget exhaustion. `fixture_id` labels a future synthetic
fixture; it is **not** evidence that a fixture environment or model was run.

No private user data, prompts or secret tokens belong in this public corpus.

## Reproducible static inventory

```sh
python tests/evals/source_inventory.py --output /tmp/source-inventory.json
```

This output is a source-level AST inventory, not a probe of authenticated,
runtime-enabled tools. It records each literal ToolRegistry registration site,
its source-declared owner scope and schema expression, config flag names,
declared MCP server IDs, and source hashes. Runtime model inventories,
authenticated endpoints, staging/live status, signed releases, NodeOS and
physical phones remain `NOT_VERIFIED`. Never promote those fields from a
source scan. Obtain the separate, authorized on-target probes first.

## Model evidence and scoring

Run the **same immutable task corpus** against each expressly configured local
or external model with the same documented tool policy, synthetic fixtures and
hardware capabilities. Never silently fall back to external models. Human
reviewers must retain redacted execution evidence in their **access-controlled
operator evidence store**, not this public repository.

For each actually executed task, prepare one JSONL observation with
`task_id`, `status` (`passed` or `failed`), `model_id`, `config_id`,
`evidence_ref` (opaque approved record identifier), `review_rationale` and
`latency_ms`. Additional sensitive fields are **not copied into reports**.
Unmeasured tasks may be omitted or marked `not_measured`. Do not turn
unexecuted tasks into passing samples. Model/tool versions, tokenizer, usage,
cost and privacy class must be documented by the operator before an empirical
SLO is proposed.

```sh
python tests/evals/ai_capability_baseline.py --output /tmp/capability-baseline.json
python tests/evals/ai_capability_baseline.py \
  --observations /path/to/approved-redacted-observations.jsonl \
  --require-complete --output /tmp/capability-baseline.json
python -m unittest discover -s tests/evals -p 'test_*.py' -v
```

Without real observations, the first command generates a correctly **BLOCKED**
report (zero passed, all 22 unmeasured). The strict command exits `2` if any
task is unmeasured or failed. A non-BLOCKED task report still does **not**
satisfy the other security, release, quality, mobile or performance gates.
Quantitative SLOs are deliberately `null` until empirical measurements and
explicit review; this implementation never invents a target.

## Security / rollback

No new runtime tool or model capability is enabled by this directory.
Removing this directory rolls back the evaluation infrastructure; it does not
alter production runtime or persisted user data. Before Paket 1–3 changes,
resolve the hard-coded `is_owner=True` gateway call and in-process Python
execution by test-driven, fail-closed changes. Never treat a passing unittest
run as proof of non-owner safety, remote MCP health, or physical Android/NodeOS.
