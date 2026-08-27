# Portal technical-claims audit — 2026-08-27

The public portal was included in the full documentation audit because its landing, docs, benchmark and status pages contain technical/product-readiness statements.

## Current authority

Portal copy is marketing/user-facing material, not the engineering source of truth. Technical and readiness claims must be consistent with:

- `docs/CURRENT_STATUS.md` / `docs/CURRENT_STATUS.de.md`;
- measured evidence in the repository;
- component READMEs;
- security/privacy boundaries in `SECURITY.md` and `THREAT_MODEL.md`.

## Normalization completed

The dedicated portal-content follow-up normalized the following technical surfaces:

- `portal/index.html` — removed unsupported universal cost/SLA/hardware/performance promises and static fake-live global metrics while retaining the interactive playground, calculator inputs/outputs, downloads, registration, top-up and conversion paths;
- `portal/docs.html` — bounded OpenAI compatibility to the implemented surface, made model/provider support deployment-dependent, removed universal PCIe/latency conclusions and aligned architecture/billing wording with the public/private boundary;
- `portal/benchmarks.html` — removed unsupported synthetic/fixed benchmark and TTFT rows and replaced them with only recorded engineering evidence plus explicit scope/limitations;
- `portal/status.html` — replaced “Public Alpha Active” and static capacity/latency/node-status claims with evidence-bound pre-production engineering status and `unavailable` where no authenticated live source exists.

The corrected technical pages intentionally avoid `data-i18n` bindings on key readiness/performance/economics assertions where legacy shared translation strings could otherwise overwrite the corrected evidence-bound text at runtime. Navigation and non-claim UI translation hooks remain available.

## Evidence rules now reflected in portal technical pages

- Do not display global VRAM/GPU/uptime/latency values as live without an authenticated current source.
- Do not claim a universal discount, provider income, SLA, data residency, model entitlement or hardware compatibility without an actual offer/deployment/evidence basis.
- Do not publish TTFT when the measured path did not directly measure true time-to-first-token.
- Performance numbers must be tied to a named hardware/model/runtime/topology measurement.
- The narrow trusted-lab two-machine proof is not a universal throughput or production-readiness result.
- Upstream llama.cpp RPC remains experimental/insecure and must not be represented as a public production security boundary.
- The public gateway is OpenAI-compatible for implemented endpoints; it is not described as 100% compatible with every OpenAI API/SDK behavior.
- Production pricing/ranking/reputation/fraud/settlement internals remain private.

## Shared translations and legal/privacy pages

`portal/portal.js` still contains shared translation strings used by legacy/legal/user-facing surfaces. The corrected technical pages no longer rely on legacy translation keys for their critical engineering claims, preventing those strings from undoing the normalization on these pages.

`privacy.html`, `terms.html` and `impressum.html` remain separate legal/policy surfaces. This technical audit does not purport to supply legal advice. Factual technical assertions embedded in legal/privacy text or shared legal translations should be checked against the actual deployed production configuration before launch, and the legal wording itself should be reviewed by appropriate counsel rather than silently rewritten as part of an engineering-status cleanup.

## Maintenance rule

Future portal claims that state availability, performance, economics, privacy/security implementation or production readiness must link back to an authenticated live source, an actual commercial offer or reproducible measured evidence. When no such source exists, use `unknown`/`unavailable`, describe the feature as an engineering target, or clearly label a value as illustrative.
