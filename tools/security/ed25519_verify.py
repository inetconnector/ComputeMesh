"""Pure-Python & Cryptography-Accelerated Ed25519 Signature Verification (RFC 8032).

Provides zero-dependency Ed25519 signature verification that works natively on any
Python 3.8+ environment (including minimal embedded NodeOS appliances without pip/wheels).
"""
from __future__ import annotations

import hashlib
import sys

# ---------------------------------------------------------------------------
# Pure-Python Ed25519 Implementation (RFC 8032)
# ---------------------------------------------------------------------------
p = 2**255 - 19
d = -121665 * pow(121666, p - 2, p) % p
I = pow(2, (p - 1) // 4, p)
By = 4 * pow(5, p - 2, p) % p
Bx = 0


def _recover_x(y: int, sign: int) -> int:
    if y >= p:
        return -1
    x2 = (y * y - 1) * pow(d * y * y + 1, p - 2, p) % p
    if x2 == 0:
        if sign:
            return -1
        return 0
    x = pow(x2, (p + 3) // 8, p)
    if (x * x - x2) % p != 0:
        x = (x * I) % p
    if (x * x - x2) % p != 0:
        return -1
    if (x & 1) != sign:
        x = p - x
    return x


Bx = _recover_x(By, 0)
B = (Bx, By, 1, (Bx * By) % p)


def _edwards_add(P: tuple[int, int, int, int], Q: tuple[int, int, int, int]) -> tuple[int, int, int, int]:
    (x1, y1, z1, t1) = P
    (x2, y2, z2, t2) = Q
    A = (y1 - x1) * (y2 - x2) % p
    B = (y1 + x1) * (y2 + x2) % p
    C = 2 * t1 * t2 * d % p
    D = 2 * z1 * z2 % p
    E = (B - A) % p
    F = (D - C) % p
    G = (D + C) % p
    H = (B + A) % p
    return (E * F % p, G * H % p, F * G % p, E * H % p)


def _scalarmult(P: tuple[int, int, int, int], e: int) -> tuple[int, int, int, int]:
    if e == 0:
        return (0, 1, 1, 0)
    Q = _scalarmult(P, e // 2)
    Q = _edwards_add(Q, Q)
    if e & 1:
        Q = _edwards_add(Q, P)
    return Q


def _decodeint(b: bytes) -> int:
    return int.from_bytes(b, "little")


def _decodepoint(b: bytes) -> tuple[int, int, int, int] | None:
    if len(b) != 32:
        return None
    y = int.from_bytes(b, "little")
    sign = (y >> 255) & 1
    y &= (1 << 255) - 1
    x = _recover_x(y, sign)
    if x < 0:
        return None
    return (x, y, 1, (x * y) % p)


def _pure_verify(public_key: bytes, message: bytes, signature: bytes) -> bool:
    """Verify Ed25519 signature in pure Python without external libraries."""
    if len(signature) != 64 or len(public_key) != 32:
        return False
    R = _decodepoint(signature[:32])
    if R is None:
        return False
    A = _decodepoint(public_key)
    if A is None:
        return False
    S = _decodeint(signature[32:])
    l = 2**252 + 27742317777372353535851937790883648493
    if S >= l:
        return False
    h = hashlib.sha512(signature[:32] + public_key + message).digest()
    k = _decodeint(h) % l
    SB = _scalarmult(B, S)
    RAk = _edwards_add(R, _scalarmult(A, k))
    (x1, y1, z1, _) = SB
    (x2, y2, z2, _) = RAk
    return (x1 * z2 - x2 * z1) % p == 0 and (y1 * z2 - y2 * z1) % p == 0


def verify_ed25519_signature(public_key_bytes: bytes, message_bytes: bytes, signature_bytes: bytes) -> bool:
    """Verify Ed25519 signature using `cryptography` if present, falling back to pure Python."""
    try:
        from cryptography.hazmat.primitives.asymmetric import ed25519
        pub = ed25519.Ed25519PublicKey.from_public_bytes(public_key_bytes)
        pub.verify(signature_bytes, message_bytes)
        return True
    except ImportError:
        return _pure_verify(public_key_bytes, message_bytes, signature_bytes)
    except Exception:
        return False
