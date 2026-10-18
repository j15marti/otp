"""Secrecy layer: the end-to-end inner packet.

One message consumes one contiguous pad segment starting at ``otp_offset``::

    [ 32-byte one-time MAC key | payload_length bytes of XOR keystream ]

The offset travels in plaintext (so lost packets never desynchronise the pair)
and is covered by the MAC together with the ciphertext, so neither can be
altered in transit.
"""

import base64
import json
import struct
import time

from .otpcrypto import MAC_ALGS, MAC_KEY_LEN, compute_mac, verify_mac, xor_bytes

MAX_PLAINTEXT = 1 << 20      # 1 MB
_DOMAIN = b"OTPNET/1 inner\x00"


class PacketError(Exception):
    pass


class IntegrityError(PacketError):
    pass


def segment_length(payload_length: int) -> int:
    return MAC_KEY_LEN + payload_length


def mac_input(sender_id: str, otp_offset: int, payload_length: int, mac_alg: str,
              ciphertext: bytes) -> bytes:
    sid = sender_id.encode()
    alg = mac_alg.encode()
    return b"".join([
        _DOMAIN,
        struct.pack(">H", len(sid)), sid,
        struct.pack(">QQ", otp_offset, payload_length),
        struct.pack(">B", len(alg)), alg,
        ciphertext,
    ])


def seal(sender_id: str, otp_offset: int, plaintext: bytes, segment: bytes,
         mac_alg: str) -> dict:
    """Encrypt and authenticate ``plaintext`` with an already-reserved pad segment."""
    if len(plaintext) > MAX_PLAINTEXT:
        raise PacketError("message is %d bytes; the limit is %d" % (len(plaintext), MAX_PLAINTEXT))
    if len(segment) != segment_length(len(plaintext)):
        raise PacketError("pad segment has the wrong length")
    mac_key, keystream = segment[:MAC_KEY_LEN], segment[MAC_KEY_LEN:]
    ciphertext = xor_bytes(plaintext, keystream)
    tag = compute_mac(mac_alg, mac_key, mac_input(sender_id, otp_offset, len(plaintext),
                                                  mac_alg, ciphertext))
    return {
        "sender_id": sender_id,
        "otp_offset": otp_offset,
        "payload_length": len(plaintext),
        "mac_alg": mac_alg,
        "ciphertext": base64.b64encode(ciphertext).decode(),
        "mac": base64.b64encode(tag).decode(),
    }


def parse(packet) -> dict:
    """Validate the shape of an inner packet without touching the pad."""
    try:
        sender_id = packet["sender_id"]
        otp_offset = packet["otp_offset"]
        length = packet["payload_length"]
        mac_alg = packet["mac_alg"]
        ciphertext = base64.b64decode(packet["ciphertext"], validate=True)
        tag = base64.b64decode(packet["mac"], validate=True)
    except (KeyError, TypeError, ValueError) as e:
        raise PacketError("malformed inner packet: %s" % e)
    if not isinstance(sender_id, str) or not sender_id:
        raise PacketError("bad sender_id")
    if not isinstance(otp_offset, int) or otp_offset < 0:
        raise PacketError("bad otp_offset")
    if not isinstance(length, int) or not 0 <= length <= MAX_PLAINTEXT or len(ciphertext) != length:
        raise PacketError("payload_length does not match ciphertext")
    if mac_alg not in MAC_ALGS:
        raise PacketError("unsupported mac_alg %r" % mac_alg)
    return {"sender_id": sender_id, "otp_offset": otp_offset, "payload_length": length,
            "mac_alg": mac_alg, "ciphertext": ciphertext, "mac": tag}


def open_(fields: dict, segment: bytes) -> bytes:
    """Verify the MAC, then decrypt. ``fields`` comes from :func:`parse`."""
    if len(segment) != segment_length(fields["payload_length"]):
        raise PacketError("pad segment has the wrong length")
    mac_key, keystream = segment[:MAC_KEY_LEN], segment[MAC_KEY_LEN:]
    data = mac_input(fields["sender_id"], fields["otp_offset"], fields["payload_length"],
                     fields["mac_alg"], fields["ciphertext"])
    if not verify_mac(fields["mac_alg"], mac_key, data, fields["mac"]):
        raise IntegrityError("MAC verification failed: packet forged, corrupted, or "
                             "encrypted with a different pad")
    return xor_bytes(fields["ciphertext"], keystream)


def encode_email(sender, recipient, subject, body, attachments=None) -> bytes:
    """Serialise an email. ``attachments`` is a list of (filename, bytes)."""
    doc = {
        "from": sender,
        "to": recipient,
        "subject": subject,
        "date": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "body": body,
        "attachments": [{"name": n, "data": base64.b64encode(d).decode()}
                        for n, d in (attachments or [])],
    }
    return json.dumps(doc, separators=(",", ":")).encode()


def decode_email(raw: bytes) -> dict:
    return json.loads(raw.decode())
