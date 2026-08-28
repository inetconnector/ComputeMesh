"""Client-side content-key release guard.

The public gateway/control-plane must not become a content-key custodian. This
module validates attested release bindings and intentionally has no decrypt or
universal-master-key path.
"""
from __future__ import annotations

from dataclasses import dataclass


class KeyReleaseError(ValueError):
    pass


@dataclass(frozen=True)
class KeyReleaseBinding:
    job_id: str
    node_id: str
    attestation_nonce: str
    attested_ephemeral_public_key: str

    def validate(self) -> None:
        for name, value in (
            ("job_id", self.job_id), ("node_id", self.node_id),
            ("attestation_nonce", self.attestation_nonce),
            ("attested_ephemeral_public_key", self.attested_ephemeral_public_key),
        ):
            if not isinstance(value, str) or not value.strip():
                raise KeyReleaseError(f"{name} must be non-empty")

    def bind_ciphertext_recipient(self, *, node_id: str, nonce: str, public_key: str) -> None:
        self.validate()
        if node_id != self.node_id:
            raise KeyReleaseError("key release node binding mismatch")
        if nonce != self.attestation_nonce:
            raise KeyReleaseError("key release nonce binding mismatch")
        if public_key != self.attested_ephemeral_public_key:
            raise KeyReleaseError("key release ephemeral-key binding mismatch")


def reject_server_side_content_key(*_args: object, **_kwargs: object) -> None:
    raise KeyReleaseError(
        "content keys are client-side/dedicated-release material and must not enter gateway/control-plane"
    )
