# Deployment and Release

**Status:** production deployment/release tooling is planned. A local Windows M0 Lab Setup now exists, but it is **not** a production installer.

## Current lab setup

For current Windows experiments, users can double-click repository-root `SETUP.cmd`. It prepares only local development/lab prerequisites and benchmark workflows:

- user-scoped Python when needed;
- repository-local `.venv`;
- local ignored `artifacts/lab/` state/results;
- temporary private-LAN firewall rule for the one-shot network benchmark;
- optional official upstream llama.cpp benchmark binaries.

It does not install a Windows service, register a public provider, configure production credentials, enable automatic updates, or expose runtime endpoints publicly.

## Production release responsibilities still planned

- control-plane deployment;
- provider installer packaging;
- release manifests and signing;
- SBOM/provenance;
- staged rollout/rollback;
- environment configuration;
- credential/revocation integration;
- reproducible release validation.

## Non-goals

- committed secrets;
- unsigned public releases;
- irreversible auto-update;
- treating the M0 Lab Setup as a security-reviewed production distribution.

The release architecture must be defined and tested before any public alpha/provider installer is described as production-capable.
