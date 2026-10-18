# OTPNET: Decentralized TRNG-OTP Relay Protocol (V1 prototype)

A proof of concept for information-theoretically secure messaging. Users share
physically exchanged, true-random one-time pads on USB drives. Payloads are
XOR-encrypted and authenticated with a one-time MAC, then carried by a
token-incentivized, 3-hop onion-routing relay network.

**The downloadable folder is [`usb_kit/OTPNET/`](usb_kit/OTPNET/).** Copy it to
the root of a USB drive and it has everything needed to join a network. Its
[README](usb_kit/OTPNET/README.md) is the user guide. To build the zip, with
offline dependency wheels for Linux, macOS and Windows:

```sh
python build_kit.py        # -> dist/OTPNET-usb-kit.zip
```

## Architecture

```
 SECRECY LAYER (local only: pad bytes never leave the drive)
 ┌──────────────────────────────────────────────────────────────────────────┐
 │ pad.py      TRNG pad generation, absolute-offset reads, zero-wipe         │
 │ state.py    SQLite: tx_offset / rx_offset per contact, burn log, mailbox  │
 │ otpcrypto   XOR, one-time Poly1305 (default) / HMAC-SHA256                │
 │ packet.py   inner packet: {sender_id, otp_offset, payload_length,         │
 │             mac_alg, ciphertext, mac}                                     │
 └──────────────────────────────────────────────────────────────────────────┘
                          │ only ciphertext + MAC + offset cross this line
 ROUTING LAYER (public; computational crypto protects metadata only)
 ┌──────────────────────────────────────────────────────────────────────────┐
 │ onion.py    X25519 ECDH + HKDF-SHA256 + AES-256-GCM layers                │
 │ relay.py    peel one layer, check escrowed fee, forward, claim fee        │
 │ bootstrap   relay directory + hash-locked escrow token ledger             │
 │ wire.py     length-prefixed JSON over TCP                                 │
 └──────────────────────────────────────────────────────────────────────────┘

 Alice ──► relay A ──► relay B ──► relay C ──► Bob
        each hop sees only its neighbours; Bob's envelope is sealed to Bob
```

### Payment flow (hash-locked escrow)

For each hop *i*, the sender picks a random secret `s_i` and escrows hop *i*'s
fee on the ledger, locked to `sha256(s_i)`. The secret `s_i` is placed in hop
*i+1*'s onion layer, and the last secret goes in the recipient's envelope.
When hop *i+1* receives and decrypts the packet, it returns `s_i` upstream, and
hop *i* claims its fee with it. A relay is paid **if and only if** the next hop
actually got the packet. Unclaimed escrows are refunded after their TTL.

## Spec → implementation

| Spec item | Where |
|---|---|
| Mock pads from `os.urandom()` (10 MB, identical on two drives) | `pad.generate_pad` / `client.pair`; uses `/dev/hwrng` or `--entropy DEV` XOR `os.urandom` when a hardware TRNG is present |
| SQLite `tx_offset` / `rx_offset` | `state.py` (`contacts` table) |
| Burn rule | `State.reserve_tx` advances before the pad is read; bytes are also zeroed on disk |
| XOR engine with absolute seeks | `otpcrypto.xor_bytes`, `pad.read_segment` |
| Plaintext `otp_offset` in packet | `packet.seal` |
| First 32 segment bytes = MAC key over offset + ciphertext | `packet.seal` / `packet.open_` |
| Auto-correction: jump `rx_offset` forward; reject `otp_offset < rx_offset` | `State.accept_rx` |
| Relay node: take fee, decrypt layer, forward | `relay.Relay.handle` |
| 3-layer onion builder (AES-GCM, source-routed) | `onion.build_onion` |
| Phase 4: Alice :5001, Bob :5002, relays :8001–8003, fault test | `usb_kit/OTPNET/demo.py` |

### Deliberate choices beyond the spec

* **The default MAC is one-time Poly1305**, keyed by the same 32-byte segment
  allocation. It is a Carter–Wegman MAC with an unconditional forgery bound,
  which matches the "infinite compute" threat model. HMAC-SHA256 depends on
  SHA-256 holding up. HMAC-SHA256 is still available (`init --mac hmac-sha256`).
* **The pad is split by direction.** The initiator sends with `[0, size/2)` and
  the responder with `[size/2, size)`, so the two parties can never reuse each
  other's bytes.
* **The MAC is verified before `rx_offset` moves.** Otherwise a forged packet
  claiming a huge offset could burn the receiver's remaining pad: a cheap
  denial-of-service.
* **The recipient gets its own sealed envelope**, encrypted to a routing key
  exchanged at pairing time, so the exit relay can't read even the inner
  packet's `sender_id`.
* **Relays reject replayed onion layers**, keyed on the ephemeral key, for an
  hour.
* **Post-quantum KEM:** `onion.seal`/`unseal` are the only key-exchange touch
  points. ML-KEM (Kyber) or an X25519+ML-KEM hybrid can be swapped in there.

Known V1 limitations (central bootstrap, linkable ledger, no size padding,
synchronous circuits) are listed in the
[kit README](usb_kit/OTPNET/README.md#limitations-of-this-v1).

## Running the tests

```sh
cd usb_kit/OTPNET
python -m unittest discover -s tests -v    # primitives, tamper/replay/forgery, onion, ledger, pairing
python demo.py                             # Phase 4 integration over real local ports
```
