# Fleet-aware provider identity

This document covers the public ComputeMesh side of the fleet-governance rollout on `feature/fleet-governance`. The authorization source of truth remains private in `ComputeMesh-ControlPlane`.

## Compatibility and migration

The existing deployment has one fleet. No public node ID or Ed25519 enrollment needs to be replaced for the migration.

During the compatibility window:

- existing providers that do not publish fleet metadata remain valid;
- the private control plane assigns those legacy profiles to its one migrated bootstrap fleet (`primary` unless the deployment pins another existing fleet ID);
- upgraded providers publish their explicit fleet ID and privacy-preserving hardware fingerprint;
- the Ed25519 `node_id` continues to be the authenticated network principal.

This makes fleet rollout additive rather than a flag-day protocol break.

## Governed provider launcher

Use `apps/node/governed_provider_agent.py` for fleet-aware provider deployments. It wraps the existing authenticated provider agent and does not replace its TLS, Ed25519, benchmark or runtime controls.

Example:

```bash
python -m apps.node.governed_provider_agent \
  --fleet-id primary \
  --control-host 10.0.0.10 \
  --control-port 7443 \
  --ca-file /etc/computemesh/control-ca.pem \
  --server-hostname computemesh-control \
  --node-id node_xxx \
  --private-key /var/lib/computemesh/node-ed25519.pem \
  --profile /var/lib/computemesh/evidence/node_profile.json \
  --prefill /var/lib/computemesh/evidence/prefill.json \
  --decode /var/lib/computemesh/evidence/decode.json \
  --rpc-host 10.0.0.22 \
  --rpc-port 50052 \
  --llama-build-number 12345 \
  --llama-build-commit abcdef123456
```

`COMPUTEMESH_FLEET_ID` may be used instead of `--fleet-id`. The command-line value wins. If neither is supplied, the compatibility fleet ID is `primary`.

The launcher reads the existing profile, adds governance metadata to an in-memory copy, writes a private temporary profile, and invokes the existing provider agent. The original measured profile file is not modified.

## Machine fingerprint

The public side computes a stable versioned fingerprint locally. Raw identifiers are never placed in the NodeProfile.

Source priority is designed to avoid unnecessary identity churn:

1. firmware/system UUID (`DMI product UUID`, Windows system UUID, macOS platform UUID), strengthened by available chassis/board serials;
2. chassis/board/product serials if no firmware UUID exists;
3. OS machine ID if stronger hardware identity is unavailable;
4. processor ID as a fallback where exposed by the operating system;
5. a real NIC MAC as the final fallback.

CPU model and architecture are descriptive and are not accepted as a unique machine identity. A synthetic `uuid.getnode()` fallback with the multicast bit set is ignored.

This means, for example, replacing a NIC does not change the fingerprint when a stable firmware UUID is present.

The published profile contains only a shape like:

```json
{
  "fleet_id": "primary",
  "machine_identity": {
    "machine_id": "hw1:<64 lowercase hex characters>",
    "identity_version": 1,
    "sources": ["dmi_product_uuid", "dmi_board_serial"]
  }
}
```

The SHA-256 preimage contains the normalized local source values; only the digest and source-class names leave the machine.

## Security boundary

The hardware fingerprint is not an authentication credential. It must not be used in place of the enrolled Ed25519 key.

The security model is:

```text
Ed25519 node_id  -> proves which enrolled provider is connected
machine_id       -> identifies the physical/logical host for fleet inventory
fleet_id         -> states which governed fleet owns that host
ControlPlane     -> decides whether that fleet is eligible/admin/blocked
```

The private control plane durably binds a machine fingerprint to one fleet and rejects conflicting re-assignment.

## Placement and confidential dispatch

The authenticated live registry retains the NodeProfile bound to each NodeSession. The public placement request already carries that profile to the private scheduler, so the private fleet policy can filter it without a second identity channel.

For confidential inference, the remote confidential broker now copies only the bounded governance fields from that authenticated profile into the content-free private candidate list:

- `fleet_id`
- `machine_id`
- `identity_version`
- `identity_sources`

Prompt text, response text and raw hardware identifiers remain outside this boundary.

## Schema compatibility

`protocol/schemas/node_profile.schema.json` adds `fleet_id` and `machine_identity` as optional properties. They are not required in schema version 1, so old provider profiles remain contract-valid while nodes are upgraded progressively.

## Operational recommendation

For the current one-fleet deployment:

1. deploy the private ControlPlane migration first;
2. confirm the existing fleet appears as the first active administrator;
3. keep its fleet ID stable;
4. migrate providers to `apps.node.governed_provider_agent` progressively;
5. verify each upgraded computer appears with a `hw1:` machine fingerprint before relying on machine-level quarantine/drain behavior;
6. only after inventory is populated, onboard additional fleets and delegate their admin credentials as required.

## Tests

The branch includes tests for normalization, privacy, firmware-ID changes, stability across NIC changes, fallback ordering, rejection of non-unique CPU-description-only identity, additive profile attachment and confidential candidate propagation.
