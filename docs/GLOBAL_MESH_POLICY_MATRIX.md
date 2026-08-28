# Global Mesh Policy Matrix

| Workload | Minimum trust | Global OPEN pool | Region restriction | Extra gate |
|---|---|---:|---|---|
| PUBLIC consumer/research | OPEN | yes | optional/policy-driven | technical admission |
| PUBLIC B2B | VERIFIED by default | only if contract policy allows | contract/policy-driven | existing production compliance |
| CONFIDENTIAL | VERIFIED | no | policy-driven | feature flag + concrete fresh attestation + no plaintext logging |
| CRYPTO_PRIVATE | VERIFIED | no | policy-driven | feature flag + exact crypto capability set |
| RESTRICTED customer workload | RESTRICTED | no | explicit allowlist | customer/contract policy |

Rules: no silent privacy downgrade; no protected job on `OPEN`; no confidential claim based only on TLS/container/VM/sharding; feature flags default OFF; existing EEA/B2B controls remain the conservative default.
