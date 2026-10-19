"""Routing layer: onion layers with X25519 ECDH + HKDF-SHA256 + AES-256-GCM.

This is *computational* cryptography and, per the threat model, may eventually
fall to a quantum or AI adversary. That's acceptable by design: a broken onion
reveals routing metadata (who handed what to whom), never message content,
which is sealed by the one-time pad inside. ``seal``/``unseal`` are the only
KEM touch points, so a post-quantum KEM (ML-KEM/Kyber) or an X25519+ML-KEM
hybrid can be dropped in here without touching the rest of the protocol.

Layer wire format (raw bytes, base64'd once at the outermost frame)::

    sealed  = epk(32) || nonce(12) || AES-GCM(key, layer, aad=hop_id)
    layer   = len(header)(4, big-endian) || header JSON || payload
    payload = the next hop's sealed blob (or the inner OTP packet at the end)
"""

import base64
import json
import os
import struct

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey, X25519PublicKey
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

_INFO = b"OTPNET/1 onion layer"
DELIVER_AAD = b"OTPNET/1 deliver"


class OnionError(Exception):
    pass


def b64e(b: bytes) -> str:
    return base64.b64encode(b).decode()


def b64d(s: str) -> bytes:
    return base64.b64decode(s, validate=True)


def generate_private() -> bytes:
    return X25519PrivateKey.generate().private_bytes_raw()


def public_from_private(priv: bytes) -> bytes:
    return X25519PrivateKey.from_private_bytes(priv).public_key().public_bytes_raw()


def _derive(shared, epk, rpk):
    return HKDF(algorithm=hashes.SHA256(), length=32, salt=epk + rpk, info=_INFO).derive(shared)


def seal(recipient_pub: bytes, plaintext: bytes, aad: bytes) -> bytes:
    eph = X25519PrivateKey.generate()
    epk = eph.public_key().public_bytes_raw()
    key = _derive(eph.exchange(X25519PublicKey.from_public_bytes(recipient_pub)), epk, recipient_pub)
    nonce = os.urandom(12)
    return epk + nonce + AESGCM(key).encrypt(nonce, plaintext, aad)


def unseal(priv: bytes, blob: bytes, aad: bytes) -> bytes:
    if len(blob) < 32 + 12 + 16:
        raise OnionError("onion layer too short")
    sk = X25519PrivateKey.from_private_bytes(priv)
    epk, nonce, ct = blob[:32], blob[32:44], blob[44:]
    key = _derive(sk.exchange(X25519PublicKey.from_public_bytes(epk)), epk,
                  sk.public_key().public_bytes_raw())
    try:
        return AESGCM(key).decrypt(nonce, ct, aad)
    except Exception:
        raise OnionError("onion layer failed to decrypt (wrong hop or tampered)")


def pack_layer(header: dict, payload: bytes) -> bytes:
    h = json.dumps(header, separators=(",", ":")).encode()
    return struct.pack(">I", len(h)) + h + payload


def unpack_layer(raw: bytes):
    if len(raw) < 4:
        raise OnionError("truncated layer")
    (n,) = struct.unpack(">I", raw[:4])
    if 4 + n > len(raw):
        raise OnionError("truncated layer header")
    return json.loads(raw[4:4 + n]), raw[4 + n:]


def build_onion(route, recipient, inner: bytes, secrets, escrow_ids) -> dict:
    """Wrap ``inner`` for source-routed delivery through ``route``.

    route      list of relays: {node_id, host, port, pub (bytes), fee}
    recipient  {host, port, pub (bytes)} — the receiving client's inbox
    secrets    hashlock preimages; relay i is paid when it learns secrets[i],
               which only the *next* hop can reveal, i.e. only after relay i
               actually forwarded the packet.
    escrow_ids ledger escrow locking relay i's fee to sha256(secrets[i])

    Each relay learns only its predecessor (from the TCP connection) and its
    successor (from its decrypted header).
    """
    if not (len(route) == len(secrets) == len(escrow_ids)) or not route:
        raise OnionError("route, secrets and escrows must line up")
    blob = seal(recipient["pub"],
                pack_layer({"type": "deliver", "receipt": b64e(secrets[-1])}, inner),
                DELIVER_AAD)
    next_hop = {"kind": "client", "host": recipient["host"], "port": recipient["port"]}
    for i in reversed(range(len(route))):
        node = route[i]
        header = {
            "next": next_hop,
            "escrow_id": escrow_ids[i],
            # the previous relay's preimage: revealing it upstream pays them
            "release": b64e(secrets[i - 1]) if i > 0 else None,
        }
        blob = seal(node["pub"], pack_layer(header, blob), node["node_id"].encode())
        next_hop = {"kind": "relay", "node_id": node["node_id"], "host": node["host"],
                    "port": node["port"], "fee": node["fee"]}
    return onion_frame(route[0]["node_id"], route[0]["fee"], blob)


def onion_frame(hop, fee, blob) -> dict:
    return {"type": "onion", "hop": hop, "token_fee": fee, "encrypted_body": b64e(blob)}
