"""Unit tests. Run from the kit folder:  python -m unittest discover -s tests -v"""

import asyncio
import hashlib
import json
import os
import shutil
import sys
import tempfile
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from otpnet import onion, packet  # noqa: E402
from otpnet.bootstrap import Bootstrap  # noqa: E402
from otpnet.client import Client, Drive, pair  # noqa: E402
from otpnet.otpcrypto import poly1305, xor_bytes  # noqa: E402
from otpnet.pad import PadExhausted, generate_pad, parse_size, read_segment  # noqa: E402
from otpnet.state import ReplayError, State  # noqa: E402


class TmpDir(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="otpnet-test-")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def path(self, *p):
        return os.path.join(self.tmp, *p)


class Primitives(unittest.TestCase):
    def test_poly1305_rfc8439_vector(self):
        key = bytes.fromhex("85d6be7857556d337f4452fe42d506a80103808afb0db2fd4abff6af4149f51b")
        tag = poly1305(key, b"Cryptographic Forum Research Group")
        self.assertEqual(tag.hex(), "a8061dc1305136c6c22b8baf0c0127a9")

    def test_xor_roundtrip_and_length_check(self):
        p, k = b"attack at dawn", os.urandom(14)
        self.assertEqual(xor_bytes(xor_bytes(p, k), k), p)
        self.assertEqual(xor_bytes(b"\x00\x00", b"\x00\x01"), b"\x00\x01")   # leading zeros kept
        with self.assertRaises(ValueError):
            xor_bytes(b"ab", b"a")

    def test_parse_size(self):
        self.assertEqual(parse_size("10M"), 10 << 20)
        self.assertEqual(parse_size("256GB"), 256 << 30)
        self.assertEqual(parse_size("4096"), 4096)


class Packets(TmpDir):
    def setUp(self):
        super().setUp()
        self.pad = self.path("pad.bin")
        generate_pad(self.pad, 1 << 16, source="os")

    def roundtrip(self, offset, msg=b"hello bob", alg="poly1305-otp"):
        seg = read_segment(self.pad, offset, packet.segment_length(len(msg)))
        pkt = packet.seal("alice", offset, msg, seg, alg)
        return pkt, seg

    def test_seek_to_absolute_offset(self):
        for alg in ("poly1305-otp", "hmac-sha256"):
            pkt, seg = self.roundtrip(12345, alg=alg)
            self.assertEqual(packet.open_(packet.parse(pkt), seg), b"hello bob")
            with open(self.pad, "rb") as f:
                raw = f.read()
            self.assertEqual(seg, raw[12345:12345 + len(seg)])

    def test_ciphertext_bitflip_detected(self):
        pkt, seg = self.roundtrip(100)
        ct = bytearray(onion.b64d(pkt["ciphertext"]))
        ct[0] ^= 0x01                         # XOR malleability: would flip 'h' -> 'i'
        pkt["ciphertext"] = onion.b64e(bytes(ct))
        with self.assertRaises(packet.IntegrityError):
            packet.open_(packet.parse(pkt), seg)

    def test_offset_is_authenticated(self):
        pkt, seg = self.roundtrip(100)
        pkt["otp_offset"] = 101
        with self.assertRaises(packet.IntegrityError):
            packet.open_(packet.parse(pkt), seg)

    def test_wrong_pad_rejected(self):
        pkt, seg = self.roundtrip(100)
        with self.assertRaises(packet.IntegrityError):
            packet.open_(packet.parse(pkt), os.urandom(len(seg)))

    def test_pad_end(self):
        with self.assertRaises(PadExhausted):
            read_segment(self.pad, (1 << 16) - 10, 32)


class Offsets(TmpDir):
    def setUp(self):
        super().setUp()
        self.st = State(self.path("s.db"))
        self.st.add_contact("bob", "pads/bob.bin", "x", (0, 1000), (1000, 2000), "h:1", "k", "poly1305-otp")

    def test_tx_never_reused(self):
        a = self.st.reserve_tx("bob", 100)
        b = self.st.reserve_tx("bob", 100)
        self.assertEqual((a, b), (0, 100))
        with self.assertRaises(PadExhausted):
            self.st.reserve_tx("bob", 801)

    def test_rx_replay_gap_and_forgery(self):
        ok = lambda: b"pt"   # noqa: E731
        self.assertEqual(self.st.accept_rx("bob", 1000, 50, ok), (b"pt", 1000, 0))
        with self.assertRaises(ReplayError):
            self.st.accept_rx("bob", 1000, 50, ok)          # replay
        # forged packet far ahead: MAC fails -> rx_offset must NOT move
        def forged():
            raise packet.IntegrityError("bad mac")
        with self.assertRaises(packet.IntegrityError):
            self.st.accept_rx("bob", 1900, 50, forged)
        self.assertEqual(self.st.get_contact("bob")["rx_offset"], 1050)
        # genuine packet after a lost one: jump forward, burn the gap
        self.assertEqual(self.st.accept_rx("bob", 1300, 50, ok), (b"pt", 1050, 250))
        self.assertEqual(self.st.get_contact("bob")["rx_offset"], 1350)
        with self.assertRaises(ReplayError):
            self.st.accept_rx("bob", 1100, 10, ok)          # the late "lost" packet is now dead


class Onion(unittest.TestCase):
    def test_three_layers_each_reveal_only_next_hop(self):
        keys = [onion.generate_private() for _ in range(3)]
        bob = onion.generate_private()
        route = [{"node_id": "n%d" % i, "host": "127.0.0.1", "port": 8001 + i,
                  "pub": onion.public_from_private(k), "fee": 0.5} for i, k in enumerate(keys)]
        secrets = [os.urandom(32) for _ in route]
        frame = onion.build_onion(route, {"host": "127.0.0.1", "port": 5002,
                                          "pub": onion.public_from_private(bob)},
                                  b'{"inner":1}', secrets, ["e0", "e1", "e2"])
        self.assertEqual(frame["hop"], "n0")
        blob = onion.b64d(frame["encrypted_body"])
        with self.assertRaises(onion.OnionError):
            onion.unseal(keys[1], blob, b"n1")                # n1 can't read n0's layer
        for i, k in enumerate(keys):
            header, blob = onion.unpack_layer(onion.unseal(k, blob, ("n%d" % i).encode()))
            self.assertEqual(header["escrow_id"], "e%d" % i)
            self.assertEqual(header["release"], onion.b64e(secrets[i - 1]) if i else None)
        self.assertEqual(header["next"], {"kind": "client", "host": "127.0.0.1", "port": 5002})
        last, inner = onion.unpack_layer(onion.unseal(bob, blob, onion.DELIVER_AAD))
        self.assertEqual(inner, b'{"inner":1}')
        self.assertEqual(onion.b64d(last["receipt"]), secrets[2])


class Ledger(TmpDir):
    def call(self, **req):
        return asyncio.run(self.b.handle(req))

    def test_hashlocked_escrow(self):
        self.b = Bootstrap(self.path("n.db"), faucet=10, log=lambda *_: None)
        self.addCleanup(self.b.db.close)
        self.call(type="open_account", account_id="alice", secret="s")
        self.call(type="open_account", account_id="relay", secret="r")
        self.assertFalse(self.call(type="open_account", account_id="alice", secret="wrong")["ok"])
        pre = os.urandom(32)
        e = self.call(type="escrow_create", account_id="alice", secret="s", payee="relay",
                      amount=0.5, hashlock=hashlib.sha256(pre).hexdigest())["escrow_id"]
        self.assertFalse(self.call(type="escrow_claim", escrow_id=e, preimage=os.urandom(32).hex())["ok"])
        self.assertTrue(self.call(type="escrow_claim", escrow_id=e, preimage=pre.hex())["ok"])
        self.assertFalse(self.call(type="escrow_claim", escrow_id=e, preimage=pre.hex())["ok"])
        self.assertEqual(self.call(type="balance", account_id="relay", secret="r")["balance"], 10.5)
        # unclaimed escrow is refunded on expiry
        self.call(type="escrow_create", account_id="alice", secret="s", payee="relay", amount=1,
                  hashlock="00", ttl=0.01)
        time.sleep(0.05)
        self.assertEqual(self.call(type="balance", account_id="alice", secret="s")["balance"], 9.5)
        self.assertFalse(self.call(type="escrow_create", account_id="alice", secret="s",
                                   payee="relay", amount=1000, hashlock="00")["ok"])


class Pairing(TmpDir):
    def test_pair_and_receive_without_network(self):
        a = Drive.init(self.path("a"), "alice", "127.0.0.1:5001")
        b = Drive.init(self.path("b"), "bob", "127.0.0.1:5002")
        info = pair(a, b, 64 << 10, entropy="os")
        ca, cb = a.state.get_contact("bob"), b.state.get_contact("alice")
        self.assertEqual((ca["tx_offset"], ca["tx_end"]), (cb["rx_offset"], cb["rx_end"]))
        self.assertEqual((ca["rx_offset"], ca["rx_end"]), (cb["tx_offset"], cb["tx_end"]))
        self.assertEqual(ca["tx_end"], ca["rx_offset"])                   # halves don't overlap
        self.assertEqual(info["size"], 64 << 10)
        with self.assertRaises(Exception):
            pair(a, b, 64 << 10, entropy="os")                            # no silent re-pair

        # Alice-side packet construction exactly as Client.send does it
        msg = packet.encode_email("alice", "bob", "hi", "body")
        seglen = packet.segment_length(len(msg))
        off = a.state.reserve_tx("bob", seglen)
        inner = packet.seal("alice", off, msg, read_segment(a.pad_path(ca), off, seglen), ca["mac_alg"])
        r = Client(b, log=lambda *_: None).receive_inner(json.loads(json.dumps(inner)))
        self.assertEqual((r["email"]["body"], r["skipped"]), ("body", 0))
        with self.assertRaises(ReplayError):
            Client(b, log=lambda *_: None).receive_inner(inner)


if __name__ == "__main__":
    unittest.main()
