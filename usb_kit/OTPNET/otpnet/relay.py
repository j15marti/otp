"""Routing layer: a relay node.

A relay peels exactly one onion layer, checks that its fee is escrowed, forwards
the remainder to the next hop and, once the next hop hands back the receipt
preimage, claims the fee. It sees the previous hop, the next hop and an opaque
blob — never the sender/recipient pair, and never anything pad-related.
"""

import asyncio
import hashlib
import json
import os
import secrets as _secrets
import time

from . import onion, wire

FORWARD_TIMEOUT = 30.0
REANNOUNCE_EVERY = 300
REPLAY_WINDOW = 3600


class Relay:
    def __init__(self, node_id, host, port, fee, key_dir, bootstrap, advertise_host=None,
                 log=print):
        self.node_id = node_id
        self.host, self.port = host, port
        self.advertise_host = advertise_host or (host if host not in ("0.0.0.0", "::") else "127.0.0.1")
        self.fee = float(fee)
        self.bootstrap = bootstrap               # (host, port)
        self.log = log
        self.earned = 0.0
        self.forwarded = 0
        self._seen = {}                           # ephemeral key hash -> time, for replay rejection
        os.makedirs(key_dir, exist_ok=True)
        keyfile = os.path.join(key_dir, "relay.json")
        if os.path.exists(keyfile):
            with open(keyfile) as f:
                k = json.load(f)
        else:
            k = {"node_id": node_id, "routing_key": onion.b64e(onion.generate_private()),
                 "ledger_secret": _secrets.token_hex(32)}
        # remember the network so `otpnet wallet --relay ID` can find this relay's wallet
        k["bootstrap"] = "%s:%d" % tuple(bootstrap)
        with open(keyfile, "w") as f:
            json.dump(k, f, indent=2)
        self.priv = onion.b64d(k["routing_key"])
        self.pub = onion.public_from_private(self.priv)
        self.ledger_secret = k["ledger_secret"]

    async def _ledger(self, req):
        resp = await wire.request(*self.bootstrap, req, timeout=15)
        if not resp.get("ok"):
            raise RuntimeError("ledger: %s" % resp.get("error"))
        return resp

    async def announce(self):
        await self._ledger({"type": "register_relay", "node_id": self.node_id,
                            "host": self.advertise_host, "port": self.port,
                            "pub": onion.b64e(self.pub), "fee": self.fee,
                            "secret": self.ledger_secret})

    async def _announce_loop(self):
        while True:
            await asyncio.sleep(REANNOUNCE_EVERY)
            try:
                await self.announce()
            except Exception as e:
                self.log("[%s] re-announce failed: %s" % (self.node_id, e))

    async def run(self):
        await self.announce()
        self.log("[%s] relay up on %s:%d, fee %s tokens/hop" % (self.node_id, self.host, self.port, self.fee))
        asyncio.ensure_future(self._announce_loop())
        await wire.serve(self.handle, self.host, self.port)

    def _replayed(self, blob):
        now = time.time()
        for k in [k for k, t in self._seen.items() if now - t > REPLAY_WINDOW]:
            del self._seen[k]
        tag = hashlib.sha256(blob[:32]).digest()
        if tag in self._seen:
            return True
        self._seen[tag] = now
        return False

    async def handle(self, req):
        if req.get("type") == "ping":
            return {"ok": True, "node_id": self.node_id, "forwarded": self.forwarded,
                    "earned": self.earned}
        if req.get("type") != "onion":
            return {"ok": False, "error": "relay only accepts onion frames"}
        if req.get("hop") != self.node_id:
            return {"ok": False, "error": "frame is addressed to %r, not us" % req.get("hop")}

        blob = onion.b64d(req["encrypted_body"])
        if self._replayed(blob):
            return {"ok": False, "error": "replayed onion layer dropped"}
        header, payload = onion.unpack_layer(onion.unseal(self.priv, blob, self.node_id.encode()))

        # Fee check: refuse to work unless our token is escrowed to us.
        esc = await self._ledger({"type": "escrow_info", "escrow_id": header["escrow_id"]})
        if esc["payee"] != self.node_id or esc["status"] != "locked" or esc["amount"] + 1e-9 < self.fee:
            return {"ok": False, "error": "fee not escrowed (need %s tokens)" % self.fee}

        nxt = header["next"]
        if nxt["kind"] == "relay":
            frame = onion.onion_frame(nxt["node_id"], nxt["fee"], payload)
            label = nxt["node_id"]
        elif nxt["kind"] == "client":
            frame = {"type": "deliver", "encrypted_body": onion.b64e(payload)}
            label = "client %s:%s" % (nxt["host"], nxt["port"])
        else:
            return {"ok": False, "error": "unknown next-hop kind"}

        try:
            resp = await wire.request(nxt["host"], nxt["port"], frame, timeout=FORWARD_TIMEOUT)
        except wire.WireError as e:
            self.log("[%s] next hop %s unreachable; fee stays locked until refund" % (self.node_id, label))
            return {"ok": False, "error": "hop %s: %s" % (self.node_id, e)}

        receipt = resp.get("receipt")
        if not receipt or hashlib.sha256(onion.b64d(receipt)).hexdigest() != esc["hashlock"]:
            return {"ok": False, "error": resp.get("error") or "no valid receipt from %s" % label,
                    "delivered": False}

        claim = await self._ledger({"type": "escrow_claim", "escrow_id": header["escrow_id"],
                                    "preimage": onion.b64d(receipt).hex()})
        self.earned += claim["amount"]
        self.forwarded += 1
        self.log("[%s] forwarded %d B -> %s, claimed %s tokens (total earned %.2f)"
                 % (self.node_id, len(payload), label, claim["amount"], self.earned))
        return {"ok": True, "receipt": header.get("release"), "delivered": resp.get("delivered"),
                "status": resp.get("status")}
