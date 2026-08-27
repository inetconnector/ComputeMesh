# Portal technical-claims audit — 2026-08-27

The public portal was included in the full documentation audit because `portal/docs.html`, `portal/status.html` and `portal/portal.js` contain technical/product-readiness statements.

## Current authority

Portal copy is marketing/user-facing material, not the engineering source of truth. Technical and readiness claims must be consistent with:

- `docs/CURRENT_STATUS.md` / `docs/CURRENT_STATUS.de.md`;
- measured evidence in the repository;
- component READMEs;
- security/privacy boundaries in `SECURITY.md` and `THREAT_MODEL.md`.

## Claims requiring normalization before production/public-alpha representation

The current portal contains legacy wording that is stronger than the presently validated system, including examples such as:

- generic “Genesis Network & Public Alpha Active” / “network online” language;
- “full” or “100%” OpenAI drop-in compatibility claims where only the implemented compatibility surface should be claimed;
- universal provider/hardware support wording not proven across all NVIDIA/AMD/Intel combinations;
- fixed “80% cheaper” or provider-earnings assertions that are not a measured universal economic result;
- fixed PCIe/activation-transfer examples presented as general end-to-end latency conclusions;
- “live” global capacity/status/latency values without an authenticated live registry/measurement source;
- privacy/security wording that implies mTLS, encrypted vault implementation or zero-prompt behavior more broadly than the current deployed path can prove.

These statements must not be used as evidence that production-readiness gates have passed.

## Safe current positioning

Until the claims above are individually backed by current deployment evidence, portal wording should describe ComputeMesh as an **engineering/developer preview / pre-production distributed-inference project** with a verified narrow trusted-lab shared-runtime proof and implemented live/provider/control-plane foundations.

Metrics should be shown only when they come from a named authenticated source and should expose `unknown`/`unavailable` rather than placeholders or historical values as though they were live.

Performance/cost statements should be tied to a named benchmark/model/hardware/topology or explicitly labeled estimates/hypotheses.

## Legal/privacy pages

`privacy.html`, `terms.html` and `impressum.html` are separate legal/policy surfaces. This technical audit does not purport to supply legal advice. Factual technical assertions embedded in those pages or in shared translation strings should be reviewed against the deployed implementation before a production launch, and legal text should be reviewed by appropriate counsel rather than silently rewritten as part of a code-status cleanup.

## Follow-up rule

Portal technical claims should be normalized in a dedicated portal/content PR so visual/i18n behavior, translations and legal review can be tested together. This separation prevents a documentation audit from accidentally deleting or changing legal terms while still making the current evidence gap explicit in the repository.
