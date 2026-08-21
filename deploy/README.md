# Deployment and Release

**Status:** production deployment/release tooling is planned. Local Windows and Linux M0 Lab Setup launchers exist, but they are **not** production installers.

## Current lab setup

- Windows: `SETUP.cmd`
- Linux: `./setup.sh` or `bash setup.sh`

They prepare only local development/lab prerequisites and benchmark workflows:

- repository-local `.venv`;
- local ignored `artifacts/lab/` state/results;
- private-LAN network benchmark assistance with temporary supported firewall rules;
- optional official upstream llama.cpp benchmark binaries;
- current local test suites.

Windows may install Python user-scoped via `winget`. Linux can offer base-package installation via `apt`, `dnf`, `zypper`, `pacman`, or `apk` after explicit confirmation.

Neither setup installs a system service, registers public provider capacity, configures production credentials, enables automatic updates, or makes runtime endpoints safe for public exposure.

## Production release responsibilities still planned

- control-plane deployment;
- provider installer/package formats for supported operating systems;
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
