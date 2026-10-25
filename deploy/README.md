# Deployment and Release

**Status:** Production release builders, signed update manifests, and staging deployment tooling are implemented. The local Windows and Linux M0 Lab Setup launchers remain available for developer workflows.

## Implemented Release and Deployment Tooling

The repository provides the following canonical tooling:

- **Windows Installer Builder (`deploy/windows/build_installer.py`):** Packages a self-contained Windows installer executable (`ComputeMesh-Setup-v{VERSION}.exe`) including required Python dependencies, Tcl/Tk runtime hooks, Windows service helpers, and firewall setup.
- **NodeOS Live Appliance Builder (`deploy/appliance/build_real_live_appliance.py`):** Authoritative Debian 13 (Trixie) Live ISO and compressed raw disk image (`.img.xz`) builder. Bundles upstream llama.cpp built with `-DGGML_VULKAN=ON` (commit `29aaf1c27faa48292357cea2120d94114a545006`), AMD/NVIDIA runtime packages, `computemesh-node.service`, and an ext4 persistence partition (`/ union` in `persistence.conf`).
- **Linux Provider Package & Service (`deploy/systemd/`):** Hardened systemd unit and environment configuration templates with least-privilege sandboxing, automatic restarts, and unblocked SIGTERM shutdown.
- **Unified Release Orchestrator (`tools/build_all_releases.py`):** Coordinates multi-platform build artifact generation across Windows, Linux, and NodeOS.
- **Cryptographic Release Signer (`tools/security/release_signer.py`):** Computes SHA-256 digests and generates Ed25519 digital signatures for release artifacts, writing the signed release manifest to `portal/updates/version.json`.
- **Plesk Portal Synchronization (`deploy/sync_plesk_portal.sh`):** Atomic rsync-based deployment to production webroots with rollback archive creation. **Explicitly protects the `downloads/` directory (`--exclude=downloads/`) to preserve released binaries, ISOs, and user data.**
- **Production Deployment Script (`deploy/deploy_production.sh`):** Verifies release tags, artifact signatures, and deployment prerequisites before rolling out to production hosts.

## Current Lab Setup

The developer and research lab setup remains available:

- Windows: `SETUP.cmd`
- Linux: `./setup.sh` or `bash setup.sh`

They prepare local development/lab prerequisites and benchmark workflows:

- repository-local `.venv`;
- local ignored `artifacts/lab/` state/results;
- private-LAN network benchmark assistance with temporary supported firewall rules;
- optional official upstream llama.cpp benchmark binaries;
- current local test suites (887 tests passing).

Windows may install Python user-scoped via `winget`. Linux can offer base-package installation via `apt`, `dnf`, `zypper`, `pacman`, or `apk` after explicit confirmation.

## Open Release Gates

The following release gates must be satisfied before public production distribution:

1. **Issue #65 Integrity Gate:** Cryptographic cross-shard BFT attestation, fail-closed authentication, leak-free quota/lease reservations, and multi-host physical validation.
2. **Physical NodeOS Multi-GPU Acceptance:** Physical acceptance run on the 6-GPU AMD Polaris rig (`cm-inference-node-01`) with mounted persistent ext4 storage and working Vulkan llama-server.
3. **Operator Authorization:** Explicit operator authorization before utilizing production deployment credentials or tokens.

## Non-goals

- committed secrets or private SSH keys;
- unsigned public releases;
- irreversible auto-update without rollback capability;
- treating the developer M0 Lab Setup as a replacement for the signed production installers.

