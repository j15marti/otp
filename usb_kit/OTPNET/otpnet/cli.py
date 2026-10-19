"""Command-line interface: ``python otpnet.py <command> ...``"""

import argparse
import asyncio
import datetime
import os
import sys

from . import KIT_ROOT, PROTOCOL, __version__
from .wire import parse_addr

DEFAULT_HOME = os.environ.get("OTPNET_HOME") or os.path.join(KIT_ROOT, "data")


def log(msg):
    print(msg, flush=True)


def human(n):
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if abs(n) < 1024 or unit == "TB":
            return ("%d %s" % (n, unit)) if unit == "B" else ("%.1f %s" % (n, unit))
        n /= 1024


def _drive(args):
    from .client import Drive
    return Drive(args.home)


def _progress(stage, done, total):
    pct = 100 * done // max(total, 1)
    sys.stdout.write("\r  %-8s %3d%%  %s / %s   " % (stage, pct, human(done), human(total)))
    if done >= total:
        sys.stdout.write("\n")
    sys.stdout.flush()


# -- commands ---------------------------------------------------------------

def cmd_init(args):
    from .client import Drive
    d = Drive.init(args.home, args.name, args.listen, args.advertise, args.bootstrap,
                   args.mac, not args.keep_used_pad)
    log("Initialised OTPNET drive for %r at %s" % (d.user_id, d.home))
    log("  inbox address : %s (listen %s)" % (d.config["advertise"], d.config["listen"]))
    log("  bootstrap     : %s" % d.config["bootstrap"])
    log("  MAC           : %s" % d.config["mac_alg"])
    log("Next: meet your contact, plug in both drives and run `otpnet pair --other <their data dir>`.")


def cmd_pair(args):
    from .client import Drive, pair
    from .pad import describe_entropy, parse_size
    a, b = _drive(args), Drive(args.other)
    size = parse_size(args.size)
    log("Pairing %s <-> %s with a %s pad" % (a.user_id, b.user_id, human(size)))
    log("  entropy: %s" % describe_entropy(args.entropy))
    info = pair(a, b, size, args.entropy, _progress)
    log("Done. Each direction has %s of pad (%s fingerprint %s...)."
        % (human(info["size"] // 2), "sha256", info["sha256"][:16]))
    log("Compare the fingerprint on both screens, then separate the drives.")


def cmd_contacts(args):
    d = _drive(args)
    if args.set_address:
        d.state.set_address(args.set_address[0], args.set_address[1])
        log("address for %s set to %s" % tuple(args.set_address))
        return
    rows = d.state.list_contacts()
    if not rows:
        log("no contacts yet; pair a drive first")
    for c in rows:
        log("%-14s addr %-21s tx %d/%d (%s left)  rx %d/%d (%s left)  %s"
            % (c["contact_id"], c["address"], c["tx_offset"], c["tx_end"],
               human(c["tx_end"] - c["tx_offset"]), c["rx_offset"], c["rx_end"],
               human(c["rx_end"] - c["rx_offset"]), c["mac_alg"]))


def cmd_serve(args):
    from .client import Client
    c = Client(_drive(args), log)
    try:
        log("[%s] wallet balance: %.2f tokens" % (c.drive.user_id, c.wallet()))
    except Exception as e:
        log("[%s] bootstrap not reachable yet (%s); receiving still works" % (c.drive.user_id, e))
    asyncio.run(c.serve())


def cmd_send(args):
    from .client import Client
    body = args.body
    if args.body_file:
        with open(args.body_file, encoding="utf-8") as f:
            body = f.read()
    if body is None:
        body = sys.stdin.read()
    attachments = []
    for p in args.attach or []:
        with open(p, "rb") as f:
            attachments.append((os.path.basename(p), f.read()))
    c = Client(_drive(args), log)
    r = c.send(args.to, args.subject, body, attachments, args.hops)
    log("message #%d -> %s via %s" % (r["msg_id"], args.to, " -> ".join(r["route"])))
    log("  otp_offset %d, %d pad bytes burned, %.2f tokens in fees" % (r["otp_offset"], r["pad_bytes_used"], r["fees"]))
    log("  status: %s" % r["status"])
    return 0 if r["delivered"] else 1


def cmd_inbox(args):
    d = _drive(args)
    for m in d.state.list_messages(None if args.all else "in"):
        ts = datetime.datetime.fromtimestamp(m["ts"]).strftime("%Y-%m-%d %H:%M")
        arrow = "from" if m["direction"] == "in" else "to  "
        log("#%-4d %s %s %-12s @%-10d %-10s %s"
            % (m["id"], ts, arrow, m["contact_id"], m["otp_offset"], m["status"][:10], m["subject"]))


def cmd_read(args):
    m = _drive(args).state.get_message(args.id)
    if not m:
        log("no message #%d" % args.id)
        return 1
    log("%s: %s\nSubject: %s\nOTP offset: %d (%d bytes)\nStatus: %s\n\n%s"
        % ("From" if m["direction"] == "in" else "To", m["contact_id"], m["subject"],
           m["otp_offset"], m["payload_length"], m["status"], m["body"]))


def _wallet(args):
    from .wallet import Wallet
    if args.relay:
        return Wallet.for_relay(args.home, args.relay, args.bootstrap)
    w = Wallet.for_drive(_drive(args))
    if args.bootstrap:
        w.bootstrap = parse_addr(args.bootstrap)
    return w


def print_history(entries):
    from .wallet import KIND_LABELS
    if not entries:
        log("  (no transactions yet)")
    for e in entries:
        ts = datetime.datetime.fromtimestamp(e["ts"]).strftime("%Y-%m-%d %H:%M")
        who = (" " + ("to " if e["amount"] < 0 else "from ") + e["counterparty"]) if e["counterparty"] else ""
        memo = ("  \"%s\"" % e["memo"]) if e["memo"] and e["kind"].startswith("transfer") else ""
        log("  %s  %+10.2f  %s%s%s" % (ts, e["amount"], KIND_LABELS.get(e["kind"], e["kind"]), who, memo))


def cmd_wallet(args):
    w = _wallet(args)
    action = args.action or "show"
    if action == "show":
        h = w.history(10)
        log("Wallet %r: %.2f tokens%s" % (w.account_id, h["balance"],
            ("  (%.2f held for messages in flight)" % h["locked"]) if h["locked"] else ""))
        log("Recent activity:")
        print_history(h["entries"])
    elif action == "history":
        print_history(w.history(args.limit)["entries"])
    elif action == "send":
        bal = w.send(args.to, args.amount, args.memo or "")
        log("Sent %.2f tokens to %s. New balance: %.2f" % (args.amount, args.to, bal))
    elif action == "address":
        log("Your wallet name is: %s   (others send you tokens with: otpnet wallet send --to %s --amount N)"
            % (w.account_id, w.account_id))
    elif action == "backup":
        log("Wallet key copied to %s. Keep it somewhere safe and private." % w.backup(args.dest))


def cmd_relays(args):
    from .client import Client
    for r in Client(_drive(args)).relays():
        log("%-10s %s:%-6d fee %-6s pub %s..." % (r["node_id"], r["host"], r["port"], r["fee"], r["pub"][:16]))


def cmd_relay(args):
    from .relay import Relay
    from .wire import parse_addr
    key_dir = os.path.join(args.home, "relays", args.id)
    r = Relay(args.id, args.host, args.port, args.fee, key_dir, parse_addr(args.bootstrap),
              args.advertise_host, log)
    asyncio.run(r.run())


def cmd_bootstrap(args):
    from .bootstrap import Bootstrap
    from .wire import serve
    d = os.path.join(args.home, "bootstrap")
    os.makedirs(d, exist_ok=True)
    b = Bootstrap(os.path.join(d, "network.db"), args.faucet, log)
    log("[bootstrap] directory + ledger on %s:%d (faucet %.2f tokens per new account)"
        % (args.host, args.port, args.faucet))
    asyncio.run(serve(b.handle, args.host, args.port))


def cmd_burn(args):
    d = _drive(args)
    old, new = d.state.burn(args.contact, args.direction, args.bytes, args.reason)
    log("contact %s: %s_offset %d -> %d (%d bytes burned, never to be used)"
        % (args.contact, args.direction, old, new, new - old))


def cmd_doctor(args):
    from .pad import describe_entropy
    log("OTPNET %s (%s), Python %s on %s" % (__version__, PROTOCOL, sys.version.split()[0], sys.platform))
    try:
        import cryptography
        log("  cryptography %s: OK" % cryptography.__version__)
    except ImportError:
        log("  cryptography: MISSING - run setup.sh / setup.bat")
    log("  entropy: %s" % describe_entropy())
    log("  data dir: %s (%s)" % (args.home, "initialised" if os.path.exists(os.path.join(args.home, "config.json")) else "not initialised"))


def build_parser():
    p = argparse.ArgumentParser(prog="otpnet", description="TRNG one-time-pad messaging over a token-incentivized onion relay network.")
    p.add_argument("--home", default=DEFAULT_HOME, help="drive data directory (default: %(default)s)")
    sub = p.add_subparsers(dest="cmd", metavar="command",
                         help="run with no command for the friendly menu")

    s = sub.add_parser("init", help="set up this drive's identity")
    s.add_argument("--name", required=True, help="your user id on the network")
    s.add_argument("--listen", default="127.0.0.1:5001", help="inbox bind address")
    s.add_argument("--advertise", help="inbox address contacts should deliver to (default: --listen)")
    s.add_argument("--bootstrap", default="127.0.0.1:7000", help="bootstrap (directory+ledger) address")
    s.add_argument("--mac", default="poly1305-otp", choices=["poly1305-otp", "hmac-sha256"])
    s.add_argument("--keep-used-pad", action="store_true", help="don't zero pad bytes after use")
    s.set_defaults(fn=cmd_init)

    s = sub.add_parser("pair", help="generate a pad and share it with another drive (in person)")
    s.add_argument("--other", required=True, help="the other drive's data directory")
    s.add_argument("--size", default="10M", help="pad size, e.g. 10M, 256G (default %(default)s)")
    s.add_argument("--entropy", help="TRNG device or captured TRNG file; \"os\" for os.urandom only (default: /dev/hwrng if fast enough)")
    s.set_defaults(fn=cmd_pair)

    s = sub.add_parser("contacts", help="list contacts and remaining pad")
    s.add_argument("--set-address", nargs=2, metavar=("CONTACT", "HOST:PORT"))
    s.set_defaults(fn=cmd_contacts)

    s = sub.add_parser("serve", help="run your inbox (receive messages)")
    s.set_defaults(fn=cmd_serve)

    s = sub.add_parser("send", help="send a message")
    s.add_argument("--to", required=True)
    s.add_argument("--subject", default="")
    g = s.add_mutually_exclusive_group()
    g.add_argument("--body")
    g.add_argument("--body-file")
    s.add_argument("--attach", action="append", help="file to attach (repeatable)")
    s.add_argument("--hops", type=int, help="relay hops (default from config: 3)")
    s.set_defaults(fn=cmd_send)

    s = sub.add_parser("inbox", help="list received messages")
    s.add_argument("--all", action="store_true", help="include sent messages")
    s.set_defaults(fn=cmd_inbox)

    s = sub.add_parser("read", help="show one message")
    s.add_argument("id", type=int)
    s.set_defaults(fn=cmd_read)

    s = sub.add_parser("wallet", help="tokens: balance, history, send, backup")
    s.add_argument("--relay", metavar="ID", help="use the wallet of a relay you run from this drive")
    s.add_argument("--bootstrap", help="network address (default: from config)")
    ws = s.add_subparsers(dest="action")
    ws.add_parser("show", help="balance and recent activity (default)")
    w = ws.add_parser("history", help="full transaction history")
    w.add_argument("--limit", type=int, default=50)
    w = ws.add_parser("send", help="send tokens to another user or relay")
    w.add_argument("--to", required=True)
    w.add_argument("--amount", type=float, required=True)
    w.add_argument("--memo")
    ws.add_parser("address", help="show the name others use to pay you")
    w = ws.add_parser("backup", help="copy your wallet key to a safe place")
    w.add_argument("dest", help="file or folder to copy to")
    s.set_defaults(fn=cmd_wallet)
    sub.add_parser("relays", help="list relays in the directory").set_defaults(fn=cmd_relays)

    s = sub.add_parser("relay", help="run a relay node and earn tokens")
    s.add_argument("--id", required=True)
    s.add_argument("--host", default="127.0.0.1")
    s.add_argument("--port", type=int, required=True)
    s.add_argument("--advertise-host", help="address other nodes should use to reach this relay")
    s.add_argument("--fee", type=float, default=0.5, help="tokens per forwarded packet")
    s.add_argument("--bootstrap", default="127.0.0.1:7000")
    s.set_defaults(fn=cmd_relay)

    s = sub.add_parser("bootstrap", help="run a directory + ledger service")
    s.add_argument("--host", default="127.0.0.1")
    s.add_argument("--port", type=int, default=7000)
    s.add_argument("--faucet", type=float, default=100.0, help="tokens granted to each new account")
    s.set_defaults(fn=cmd_bootstrap)

    s = sub.add_parser("burn", help="advance an offset without using the bytes (testing)")
    s.add_argument("--contact", required=True)
    s.add_argument("--direction", choices=["tx", "rx"], default="tx")
    s.add_argument("--bytes", type=int, required=True)
    s.add_argument("--reason", default="manual burn")
    s.set_defaults(fn=cmd_burn)

    sub.add_parser("doctor", help="check dependencies and entropy source").set_defaults(fn=cmd_doctor)
    return p


def main(argv=None):
    from .state import UnknownContact
    args = build_parser().parse_args(argv)
    try:
        if args.cmd is None:
            from .menu import run
            return run(args.home)
        return args.fn(args) or 0
    except KeyboardInterrupt:
        return 130
    except UnknownContact as e:
        if os.environ.get("OTPNET_DEBUG"):
            raise
        print("error: no contact %s on this drive; `otpnet pair` with them first" % e, file=sys.stderr)
        return 1
    except Exception as e:
        if os.environ.get("OTPNET_DEBUG"):
            raise
        print("error: %s: %s" % (type(e).__name__, e), file=sys.stderr)
        return 1
