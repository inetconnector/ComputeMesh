"""Release signer preflight must not access private signing keys prematurely."""

from pathlib import Path
from unittest.mock import patch

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from tools.release.verify_portal_bundle import REQUIRED
from tools.security import release_signer


def test_missing_required_assets_fail_before_private_key_lookup(tmp_path: Path) -> None:
    downloads = tmp_path / "downloads"
    downloads.mkdir()
    with patch.object(
        release_signer, "get_or_create_keypair",
        side_effect=AssertionError("private signing key was accessed"),
    ) as lookup, pytest.raises(FileNotFoundError, match="missing mandatory physical"):
        release_signer.sign_manifest(
            "1.2.190", downloads, tmp_path / "manifest.json",
            base_url="https://mesh.inetconnector.com/downloads",
        )
    lookup.assert_not_called()
    assert not (tmp_path / "manifest.json").exists()


def test_symlinked_download_is_rejected_even_in_partial_mode(tmp_path: Path) -> None:
    downloads = tmp_path / "downloads"
    downloads.mkdir()
    external = tmp_path / "external-release-bytes"
    external.write_bytes(b"untrusted")
    link = downloads / REQUIRED["windows-x64"]
    try:
        link.symlink_to(external)
    except (OSError, NotImplementedError) as exc:
        pytest.skip(f"symlinks unsupported: {exc}")
    with patch.object(
        release_signer, "get_or_create_keypair",
        side_effect=AssertionError("private signing key was accessed"),
    ) as lookup, pytest.raises(ValueError, match="must not be a symlink"):
        release_signer.sign_manifest(
            "1.2.190", downloads, tmp_path / "manifest.json",
            allow_partial=True, base_url="https://mesh.inetconnector.com/downloads",
        )
    lookup.assert_not_called()


def test_symlinked_staged_artifact_is_rejected(tmp_path: Path) -> None:
    downloads = tmp_path / "downloads"
    staging = tmp_path / "staging"
    downloads.mkdir()
    staging.mkdir()
    original = tmp_path / "outside"
    original.write_bytes(b"some bytes")
    link = staging / REQUIRED["windows-x64"]
    try:
        link.symlink_to(original)
    except (OSError, NotImplementedError) as exc:
        pytest.skip(f"symlinks unsupported: {exc}")
    with patch.object(
        release_signer, "get_or_create_keypair",
        side_effect=AssertionError("private signing key was accessed"),
    ) as lookup, pytest.raises(ValueError, match="staged release artifact must not be a symlink"):
        release_signer.sign_manifest(
            "1.2.190", downloads, tmp_path / "manifest.json",
            staging_dir=staging, allow_partial=True,
            base_url="https://mesh.inetconnector.com/downloads",
        )
    lookup.assert_not_called()


def test_complete_physical_inventory_signed_using_ephemeral_test_key(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    downloads = tmp_path / "downloads"
    downloads.mkdir()
    for platform, filename in REQUIRED.items():
        (downloads / filename).write_bytes(("fixture:" + platform).encode("ascii"))
    private = Ed25519PrivateKey.generate()
    public = private.public_key()
    public_hex = public.public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    ).hex()
    output = tmp_path / "manifest.json"
    with patch.object(
        release_signer, "get_or_create_keypair", return_value=(private, public)
    ) as lookup:
        manifest = release_signer.sign_manifest(
            "1.2.190", downloads, output,
            base_url="https://mesh.inetconnector.com/downloads",
        )
    lookup.assert_called_once_with(allow_generate=False)
    assert set(manifest["platforms"]) == set(REQUIRED)
    monkeypatch.setattr(release_signer, "TRUSTED_RELEASE_PUBLIC_KEYS_HEX", (public_hex,))
    assert release_signer.verify_manifest(output)
