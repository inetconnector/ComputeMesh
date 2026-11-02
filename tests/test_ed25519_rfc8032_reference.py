"""Published RFC 8032 Ed25519 test vector protects pure verifier refactors."""

from tools.security.ed25519_verify import _pure_verify, verify_ed25519_signature


PUBLIC_KEY = bytes.fromhex(
    "d75a980182b10ab7d54bfed3c964073a0ee172f3daa62325af021a68f707511a"
)
SIGNATURE = bytes.fromhex(
    "e5564300c360ac729086e2cc806e828a84877f1eb8e5d974d873e06522490155"
    "5fb8821590a33bacc61e39701cf9b46bd25bf5f0595bbe24655141438e7a100b"
)


def test_public_rfc8032_empty_message_vector() -> None:
    assert _pure_verify(PUBLIC_KEY, b"", SIGNATURE)
    assert verify_ed25519_signature(PUBLIC_KEY, b"", SIGNATURE)


def test_altered_message_fails_signature_verification() -> None:
    assert not _pure_verify(PUBLIC_KEY, b"changed", SIGNATURE)


def test_altered_signature_is_rejected() -> None:
    corrupted = bytearray(SIGNATURE)
    corrupted[7] ^= 1
    assert not _pure_verify(PUBLIC_KEY, b"", bytes(corrupted))
