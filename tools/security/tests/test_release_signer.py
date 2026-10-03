import json

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ed25519
from tools.security import release_signer


def test_verify_manifest_requires_a_trusted_signing_key(tmp_path, monkeypatch) -> None:
    private_key = ed25519.Ed25519PrivateKey.generate()
    public_hex = private_key.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    ).hex()
    manifest = {
        "version": "1.2.3",
        "release_date": "2026-09-26T00:00:00+00:00",
        "min_compatible_version": "1.0.0",
        "public_key": public_hex,
        "platforms": {},
    }
    signature = private_key.sign(json.dumps(manifest, sort_keys=True).encode("utf-8"))
    manifest["signature"] = signature.hex()
    manifest_path = tmp_path / "version.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    monkeypatch.setattr(release_signer, "TRUSTED_RELEASE_PUBLIC_KEYS_HEX", (public_hex,))
    assert release_signer.verify_manifest(manifest_path)

    monkeypatch.setattr(release_signer, "TRUSTED_RELEASE_PUBLIC_KEYS_HEX", ())
    assert not release_signer.verify_manifest(manifest_path)
