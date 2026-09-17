# ComputeMesh Memory Contract

Memory is selective, scoped, privacy-aware persistent context; it is not chat history.

## Classes

Support facts, preferences, standing instructions, goals, projects, decisions, corrections, routines, temporary state and negative constraints. Every durable item should carry provenance, confidence/authority, explicitness, sensitivity, consent/purpose, scope, validity/expiry and supersession/conflict metadata where applicable.

Scopes are isolated: `USER`, `FLEET`, `PROJECT`, `SESSION`, `GLOBAL`. A record from one user or fleet must never be retrieved into another scope merely because it is semantically similar.

## Write policy

Persist only information with legitimate future utility, durable project value, an explicit save request, a correction, or a standing instruction. Do not persist incidental conversation by default. Sensitive data requires stricter purpose/consent handling and data minimization.

## Retrieval policy

Retrieve only relevant records; rank by scope, authority, recency and relevance. Negative memory and explicit forget/suppression constraints take precedence. Contradictory records remain visible until resolved; assumptions and inference must not be promoted to confirmed facts without evidence.

## Deletion and migration

Deletion/suppression must prevent future retrieval. Temporary records expire. Derived records depending on removed inputs must be re-evaluated. The existing JSON user-memory store remains readable during migration; the structured store is the target representation and must support export/audit without exposing secrets.
