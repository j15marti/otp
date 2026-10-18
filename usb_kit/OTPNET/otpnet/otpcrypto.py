"""Secrecy-layer primitives: XOR cipher and one-time MACs.

Nothing in this module is computational: given truly random, never-reused key
material, XOR gives perfect secrecy and the one-time Poly1305 MAC gives an
unconditional forgery bound (~2^-100 for a 1 MB message) no matter how much
compute, quantum or otherwise, the adversary has.

HMAC-SHA256 is also offered because the V1 spec names it. With a one-time key it
is very strong in practice, but its security rests on SHA-256 rather than on
information theory, so ``poly1305-otp`` is the default.
"""

import hashlib
import hmac

MAC_KEY_LEN = 32          # first 32 bytes of every pad segment
MAC_ALGS = ("poly1305-otp", "hmac-sha256")
DEFAULT_MAC = "poly1305-otp"

_P1305 = (1 << 130) - 5
_R_CLAMP = 0x0FFFFFFC0FFFFFFC0FFFFFFC0FFFFFFF
_MASK128 = (1 << 128) - 1


def xor_bytes(a: bytes, b: bytes) -> bytes:
    """C = P xor K. Both inputs must be the same length."""
    if len(a) != len(b):
        raise ValueError("xor operands differ in length (%d != %d)" % (len(a), len(b)))
    n = len(a)
    return (int.from_bytes(a, "little") ^ int.from_bytes(b, "little")).to_bytes(n, "little")


def poly1305(key: bytes, msg: bytes) -> bytes:
    """One-time Poly1305 (RFC 8439 s2.5) — a Carter-Wegman universal-hash MAC.

    Secure unconditionally as long as ``key`` is uniformly random and used once,
    which the pad guarantees.
    """
    if len(key) != 32:
        raise ValueError("poly1305 key must be 32 bytes")
    r = int.from_bytes(key[:16], "little") & _R_CLAMP
    s = int.from_bytes(key[16:], "little")
    acc = 0
    for i in range(0, len(msg), 16):
        block = msg[i:i + 16] + b"\x01"
        acc = (acc + int.from_bytes(block, "little")) * r % _P1305
    return ((acc + s) & _MASK128).to_bytes(16, "little")


def compute_mac(alg: str, key: bytes, data: bytes) -> bytes:
    if alg == "poly1305-otp":
        return poly1305(key, data)
    if alg == "hmac-sha256":
        return hmac.new(key, data, hashlib.sha256).digest()
    raise ValueError("unknown MAC algorithm %r" % alg)


def verify_mac(alg: str, key: bytes, data: bytes, tag: bytes) -> bool:
    return hmac.compare_digest(compute_mac(alg, key, data), tag)
