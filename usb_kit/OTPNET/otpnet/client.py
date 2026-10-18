"""The user's side: a drive's data directory, pairing, sending and the inbox server.

This module is where the two layers meet, and the boundary is strict: pad bytes
are read, used and (optionally) wiped here, and only the finished inner packet
— ciphertext + MAC + plaintext offset — is ever handed to the routing layer.
"""

import asyncio
import hashlib
import json
import os
import random
import secrets as _secrets

from . import PROTOCOL, onion, packet, wire
from .otpcrypto import DEFAULT_MAC, MAC_ALGS
from .pad import burn_segment, copy_pad, generate_pad, read_segment
from .state import State

CLIENT_TIMEOUT = 90.0


class ClientError(Exception):
    pass


class Drive:
    """An OTPNET data directory — normally ``<USB>/OTPNET/data``."""

    def __init__(self, home):
        self.home = os.path.abspath(home)
        cfg = os.path.join(self.home, "config.json")
        if not os.path.exists(cfg):
            raise ClientError("%s is not initialised; run `otpnet init` first" % self.home)
        with open(cfg) as f:
            self.config = json.load(f)
        with open(os.path.join(self.home, "identity.json")) as f:
            self.identity = json.load(f)
        self.state = State(os.path.join(self.home, "state.db"))

    @classmethod
    def init(cls, home, name, listen, advertise=None, bootstrap="127.0.0.1:7000",
             mac_alg=DEFAULT_MAC, wipe_used_pad=True):
        if mac_alg not in MAC_ALGS:
            raise ClientError("mac_alg must be one of %s" % ", ".join(MAC_ALGS))
        wire.parse_addr(listen)
        wire.parse_addr(bootstrap)
        if os.path.exists(os.path.join(home, "config.json")):
            raise ClientError("%s is already initialised" % home)
        for d in ("", "pads", "inbox"):
            os.makedirs(os.path.join(home, d), exist_ok=True)
        config = {"protocol": PROTOCOL, "user_id": name, "listen": listen,
                  "advertise": advertise or listen, "bootstrap": bootstrap, "hops": 3,
                  "mac_alg": mac_alg, "wipe_used_pad": wipe_used_pad}
        identity = {"user_id": name, "routing_key": onion.b64e(onion.generate_private()),
                    "ledger_secret": _secrets.token_hex(32)}
        with open(os.path.join(home, "config.json"), "w") as f:
            json.dump(config, f, indent=2)
        with open(os.path.join(home, "identity.json"), "w") as f:
            json.dump(identity, f, indent=2)
        return cls(home)

    @property
    def user_id(self):
        return self.config["user_id"]

    @property
    def routing_private(self):
        return onion.b64d(self.identity["routing_key"])

    @property
    def routing_public(self):
        return onion.public_from_private(self.routing_private)

    def save_config(self):
        with open(os.path.join(self.home, "config.json"), "w") as f:
            json.dump(self.config, f, indent=2)

    def pad_path(self, contact):
        return os.path.join(self.home, contact["pad_file"])


def pair(drive_a: Drive, drive_b: Drive, size, entropy=None, progress=None):
    """The physical exchange ceremony: both drives plugged into one machine.

    One pad is generated from the TRNG straight onto drive A, copied to drive B
    and verified. ``A`` (initiator) sends with the first half and ``B`` with the
    second, so the directions can never collide.
    """
    if drive_a.user_id == drive_b.user_id:
        raise ClientError("both drives have user_id %r; ids must differ" % drive_a.user_id)
    for d, other in ((drive_a, drive_b), (drive_b, drive_a)):
        if d.state.has_contact(other.user_id):
            raise ClientError("%s already has a pad with %s" % (d.user_id, other.user_id))
    if size < 2 * 1024:
        raise ClientError("pad is too small to be useful")
    size -= size % 2
    half = size // 2
    rel_a = os.path.join("pads", "%s.bin" % drive_b.user_id)
    rel_b = os.path.join("pads", "%s.bin" % drive_a.user_id)
    source = generate_pad(os.path.join(drive_a.home, rel_a), size, entropy,
                          progress and (lambda d, t: progress("generate", d, t)))
    digest = copy_pad(os.path.join(drive_a.home, rel_a), os.path.join(drive_b.home, rel_b),
                      progress and (lambda d, t: progress("copy", d, t)))
    mac_alg = drive_a.config["mac_alg"]
    drive_a.state.add_contact(drive_b.user_id, rel_a, digest, (0, half), (half, size),
                              drive_b.config["advertise"], onion.b64e(drive_b.routing_public), mac_alg)
    drive_b.state.add_contact(drive_a.user_id, rel_b, digest, (half, size), (0, half),
                              drive_a.config["advertise"], onion.b64e(drive_a.routing_public), mac_alg)
    return {"size": size, "sha256": digest, "entropy": source, "mac_alg": mac_alg}


class Client:
    def __init__(self, drive: Drive, log=print):
        self.drive = drive
        self.state = drive.state
        self.log = log
        self.bootstrap = wire.parse_addr(drive.config["bootstrap"])

    # -- network services ---------------------------------------------------

    def _bootstrap(self, req):
        resp = wire.request_sync(*self.bootstrap, req, timeout=15)
        if not resp.get("ok"):
            raise ClientError("bootstrap: %s" % resp.get("error"))
        return resp

    def wallet(self):
        return self._bootstrap({"type": "open_account", "account_id": self.drive.user_id,
                                "secret": self.drive.identity["ledger_secret"]})["balance"]

    def relays(self):
        return self._bootstrap({"type": "list_relays"})["relays"]

    # -- sending ------------------------------------------------------------

    def send(self, to, subject, body, attachments=None, hops=None):
        contact = self.state.get_contact(to)
        hops = hops or self.drive.config.get("hops", 3)
        plaintext = packet.encode_email(self.drive.user_id, to, subject, body, attachments)
        if len(plaintext) > packet.MAX_PLAINTEXT:
            raise ClientError("message is %d bytes; the limit is 1 MB" % len(plaintext))
        seglen = packet.segment_length(len(plaintext))
        if contact["tx_offset"] + seglen > contact["tx_end"]:
            raise ClientError("pad with %s is exhausted (%d bytes left, need %d); meet up and "
                              "pair a fresh pad" % (to, contact["tx_end"] - contact["tx_offset"], seglen))

        # Pick the route and pay for it before touching the pad, so a network
        # problem here doesn't waste pad bytes.
        self.wallet()
        directory = self.relays()
        if len(directory) < hops:
            raise ClientError("need %d relays, directory lists %d" % (hops, len(directory)))
        route = random.SystemRandom().sample(directory, hops)
        for r in route:
            r["pub"] = onion.b64d(r["pub"])
        secrets = [os.urandom(32) for _ in route]
        escrows = [self._bootstrap({
            "type": "escrow_create", "account_id": self.drive.user_id,
            "secret": self.drive.identity["ledger_secret"], "payee": r["node_id"],
            "amount": r["fee"], "hashlock": hashlib.sha256(s).hexdigest(), "ttl": 300,
        })["escrow_id"] for r, s in zip(route, secrets)]

        # Step 1: burn rule — reserve (advance tx_offset) first, then read and encrypt.
        offset = self.state.reserve_tx(to, seglen)
        pad_path = self.drive.pad_path(contact)
        segment = read_segment(pad_path, offset, seglen)
        inner = packet.seal(self.drive.user_id, offset, plaintext, segment, contact["mac_alg"])
        del segment
        if self.drive.config.get("wipe_used_pad", True):
            burn_segment(pad_path, offset, seglen)
        msg_id = self.state.log_message(to, "out", offset, len(plaintext), subject, body, "sending")

        # Step 3: onion-wrap and hand to the first hop.
        host, port = wire.parse_addr(contact["address"])
        frame = onion.build_onion(route, {"host": host, "port": port,
                                          "pub": onion.b64d(contact["routing_pub"])},
                                  json.dumps(inner).encode(), secrets, escrows)
        result = {"msg_id": msg_id, "otp_offset": offset, "pad_bytes_used": seglen,
                  "route": [r["node_id"] for r in route], "fees": sum(r["fee"] for r in route)}
        try:
            resp = wire.request_sync(route[0]["host"], route[0]["port"], frame, timeout=CLIENT_TIMEOUT)
        except wire.WireError as e:
            resp = {"ok": False, "error": str(e)}
        delivered = bool(resp.get("ok") and resp.get("delivered"))
        status = "delivered" if delivered else "failed: %s" % (resp.get("error") or resp.get("status"))
        self.state.set_message_status(msg_id, status)
        result.update(delivered=delivered, status=status)
        return result

    # -- receiving ----------------------------------------------------------

    def receive_inner(self, inner_obj):
        """Authenticate, sync offsets and decrypt one inner packet."""
        fields = packet.parse(inner_obj)
        contact = self.state.get_contact(fields["sender_id"])
        if fields["mac_alg"] != contact["mac_alg"]:
            raise packet.IntegrityError("mac_alg %s not agreed with this contact" % fields["mac_alg"])
        seglen = packet.segment_length(fields["payload_length"])
        pad_path = self.drive.pad_path(contact)

        def verify():
            return packet.open_(fields, read_segment(pad_path, fields["otp_offset"], seglen))

        plaintext, prev_rx, skipped = self.state.accept_rx(
            fields["sender_id"], fields["otp_offset"], seglen, verify)
        if self.drive.config.get("wipe_used_pad", True):
            # wipe the skipped gap too: those bytes can never be used again
            burn_segment(pad_path, prev_rx, fields["otp_offset"] + seglen - prev_rx)
        email = packet.decode_email(plaintext)
        msg_id = self.state.log_message(fields["sender_id"], "in", fields["otp_offset"],
                                        fields["payload_length"], email.get("subject"),
                                        email.get("body"), "received")
        if email.get("attachments"):
            d = os.path.join(self.drive.home, "inbox", str(msg_id))
            os.makedirs(d, exist_ok=True)
            for a in email["attachments"]:
                with open(os.path.join(d, os.path.basename(a["name"]) or "attachment"), "wb") as f:
                    f.write(onion.b64d(a["data"]))
        return {"msg_id": msg_id, "email": email, "otp_offset": fields["otp_offset"],
                "prev_rx_offset": prev_rx, "skipped": skipped,
                "new_rx_offset": fields["otp_offset"] + seglen}

    async def handle(self, req):
        if req.get("type") == "ping":
            return {"ok": True, "user_id": self.drive.user_id}
        if req.get("type") != "deliver":
            return {"ok": False, "error": "inbox only accepts deliver frames"}
        layer = onion.unseal(self.drive.routing_private, onion.b64d(req["encrypted_body"]),
                             onion.DELIVER_AAD)
        header, inner = onion.unpack_layer(layer)
        # The relays did their job once the envelope opens, so the receipt is
        # released even if the OTP layer below rejects the packet.
        resp = {"ok": True, "receipt": header["receipt"]}
        try:
            r = await asyncio.to_thread(self.receive_inner, json.loads(inner))
        except Exception as e:
            self.log("[%s] REJECTED packet: %s: %s" % (self.drive.user_id, type(e).__name__, e))
            resp.update(delivered=False, status="rejected by recipient: %s" % e)
            return resp
        if r["skipped"]:
            self.log("[%s] offset auto-correction: rx_offset %d -> %d, burned %d missed bytes"
                     % (self.drive.user_id, r["prev_rx_offset"], r["otp_offset"], r["skipped"]))
        self.log("[%s] message #%d from %s @ offset %d: %r"
                 % (self.drive.user_id, r["msg_id"], r["email"]["from"], r["otp_offset"],
                    r["email"].get("subject")))
        resp.update(delivered=True, status="delivered")
        return resp

    async def serve(self):
        host, port = wire.parse_addr(self.drive.config["listen"])
        self.log("[%s] inbox listening on %s:%d" % (self.drive.user_id, host, port))
        await wire.serve(self.handle, host, port)
