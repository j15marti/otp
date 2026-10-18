#!/usr/bin/env python3
"""Phase 4 integration test: the whole network on one machine.

  * two simulated USB drives (Alice :5001, Bob :5002) paired with one 10 MB pad
  * a bootstrap directory + ledger (:7000)
  * three relays (:8001, :8002, :8003), each charging 0.5 tokens per hop
  * Alice -> Bob through 3 onion hops, Bob -> Alice back
  * fault tolerance: Alice's tx_offset is bumped (a "lost" message) and Bob's
    client must jump its rx_offset forward and still decrypt

Every node is a separate process started from this kit's own otpnet.py,
exactly as it would run from a USB stick.

    python demo.py            # run in ./demo_run (wiped first)
    python demo.py --keep     # leave processes' data behind for inspection
"""

import argparse
import os
import shutil
import subprocess
import sys
import threading
import time

KIT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, KIT)
from otpnet import wire  # noqa: E402
from otpnet.client import Client, Drive  # noqa: E402
from otpnet.pad import read_segment  # noqa: E402

PY = sys.executable
CLI = os.path.join(KIT, "otpnet.py")
COLORS = {"bootstrap": 90, "relay1": 36, "relay2": 34, "relay3": 35, "alice": 32, "bob": 33}
results = []


def say(msg=""):
    print(msg, flush=True)


def step(title):
    say("\n\033[1m== %s ==\033[0m" % title)


def check(name, cond, detail=""):
    results.append((name, bool(cond)))
    say("  [%s] %s%s" % ("\033[32mPASS\033[0m" if cond else "\033[31mFAIL\033[0m", name,
                         ("  (%s)" % detail) if detail else ""))
    return cond


def cli(home, *args):
    out = subprocess.run([PY, CLI, "--home", home] + list(args), capture_output=True, text=True)
    if out.returncode:
        raise SystemExit("otpnet %s failed:\n%s%s" % (" ".join(args), out.stdout, out.stderr))
    return out.stdout


class Proc:
    def __init__(self, name, home, *args):
        self.name = name
        env = dict(os.environ, PYTHONUNBUFFERED="1")
        self.p = subprocess.Popen([PY, CLI, "--home", home] + list(args), stdout=subprocess.PIPE,
                                  stderr=subprocess.STDOUT, text=True, env=env)
        threading.Thread(target=self._pump, daemon=True).start()

    def _pump(self):
        c = COLORS.get(self.name, 37)
        for line in self.p.stdout:
            say("    \033[%dm%-9s|\033[0m %s" % (c, self.name, line.rstrip()))

    def stop(self):
        self.p.terminate()
        try:
            self.p.wait(5)
        except subprocess.TimeoutExpired:
            self.p.kill()


def wait_up(port, timeout=15):
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            if wire.request_sync("127.0.0.1", port, {"type": "ping"}, timeout=2).get("ok"):
                return
        except wire.WireError:
            time.sleep(0.2)
    raise SystemExit("nothing answering on port %d" % port)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dir", default=os.path.join(KIT, "demo_run"))
    ap.add_argument("--keep", action="store_true", help="don't delete the run directory afterwards")
    args = ap.parse_args()

    root = os.path.abspath(args.dir)
    shutil.rmtree(root, ignore_errors=True)
    alice_home = os.path.join(root, "alice_usb", "OTPNET", "data")
    bob_home = os.path.join(root, "bob_usb", "OTPNET", "data")
    net_home = os.path.join(root, "network")
    procs = []
    try:
        step("Phase 1: initialise two USB drives and exchange a 10 MB pad")
        say(cli(alice_home, "init", "--name", "alice", "--listen", "127.0.0.1:5001").rstrip())
        say(cli(bob_home, "init", "--name", "bob", "--listen", "127.0.0.1:5002").rstrip())
        say(cli(alice_home, "pair", "--other", bob_home, "--size", "10M").rstrip())
        alice, bob = Drive(alice_home), Drive(bob_home)
        pa = os.path.join(alice_home, "pads", "bob.bin")
        pb = os.path.join(bob_home, "pads", "alice.bin")
        with open(pa, "rb") as f1, open(pb, "rb") as f2:
            check("pad files are identical on both drives", f1.read() == f2.read())
        ca, cb = alice.state.get_contact("bob"), bob.state.get_contact("alice")
        check("Alice's tx region is Bob's rx region",
              (ca["tx_offset"], ca["tx_end"]) == (cb["rx_offset"], cb["rx_end"]),
              "[%d, %d)" % (ca["tx_offset"], ca["tx_end"]))

        step("Phase 3: start bootstrap, 3 relays and both inboxes")
        procs.append(Proc("bootstrap", net_home, "bootstrap", "--port", "7000"))
        wait_up(7000)
        for i, port in enumerate((8001, 8002, 8003), 1):
            procs.append(Proc("relay%d" % i, net_home, "relay", "--id", "relay%d" % i,
                              "--port", str(port), "--fee", "0.5"))
        procs.append(Proc("alice", alice_home, "serve"))
        procs.append(Proc("bob", bob_home, "serve"))
        for port in (8001, 8002, 8003, 5001, 5002):
            wait_up(port)
        time.sleep(0.5)

        step("Phase 4a: Alice sends a 5 KB email to Bob through 3 relays")
        body = "Meet at the usual place.\n" + ("This line pads the email out to about five kilobytes. " * 90)
        r1 = Client(alice).send("bob", "Hello Bob", body)
        say("  route: Alice -> %s -> Bob   otp_offset=%d   pad bytes used=%d"
            % (" -> ".join(r1["route"]), r1["otp_offset"], r1["pad_bytes_used"]))
        check("delivered through 3 distinct relays", r1["delivered"] and len(set(r1["route"])) == 3,
              r1["status"])
        got = bob.state.list_messages("in")
        check("Bob decrypted the exact plaintext", got and got[-1]["body"] == body and got[-1]["subject"] == "Hello Bob")
        cb = bob.state.get_contact("alice")
        check("Bob's rx_offset == Alice's tx_offset", cb["rx_offset"] == alice.state.get_contact("bob")["tx_offset"],
              "both at %d" % cb["rx_offset"])
        check("used pad bytes wiped on both drives",
              read_segment(pa, r1["otp_offset"], r1["pad_bytes_used"]).count(0) == r1["pad_bytes_used"]
              and read_segment(pb, r1["otp_offset"], r1["pad_bytes_used"]).count(0) == r1["pad_bytes_used"])

        step("Phase 4b: fault tolerance - Alice's tx_offset jumps (a lost message)")
        say("  " + cli(alice_home, "burn", "--contact", "bob", "--bytes", "4096",
                       "--reason", "simulated lost message").strip())
        before = bob.state.get_contact("alice")["rx_offset"]
        r2 = Client(alice).send("bob", "Did you get my last one?", "If not, no harm: offsets self-heal.")
        after = bob.state.get_contact("alice")
        check("message after the gap still delivered", r2["delivered"], r2["status"])
        check("Bob's rx_offset jumped forward over the gap",
              after["rx_offset"] == r2["otp_offset"] + r2["pad_bytes_used"] and r2["otp_offset"] == before + 4096,
              "rx %d -> skip to %d -> %d" % (before, r2["otp_offset"], after["rx_offset"]))
        burns = bob.state.burn_log("alice")
        check("Bob logged the 4096 skipped bytes as burned", burns and burns[-1]["length"] == 4096)
        check("Bob read the post-gap message", bob.state.list_messages("in")[-1]["subject"] == "Did you get my last one?")

        step("Phase 4c: Bob replies (uses the other half of the pad)")
        r3 = Client(bob).send("alice", "Re: Hello Bob", "Got both. See you there.")
        check("reply delivered to Alice", r3["delivered"], "otp_offset %d" % r3["otp_offset"])
        check("Alice decrypted the reply", alice.state.list_messages("in")[-1]["body"] == "Got both. See you there.")

        step("Phase 4d: near-limit message (700 KB attachment, ~0.95 MB serialised)")
        blob = os.urandom(700 * 1024)
        att = os.path.join(root, "photo.bin")
        with open(att, "wb") as f:
            f.write(blob)
        t0 = time.time()
        r4 = Client(alice).send("bob", "Photo", "see attachment", [("photo.bin", blob)])
        check("large message delivered", r4["delivered"], "%d pad bytes, %.1fs" % (r4["pad_bytes_used"], time.time() - t0))
        saved = os.path.join(bob_home, "inbox", str(bob.state.list_messages("in")[-1]["id"]), "photo.bin")
        with open(saved, "rb") as f:
            check("attachment byte-identical on Bob's drive", f.read() == blob)

        step("Token accounting")
        a_bal, b_bal = Client(alice).wallet(), Client(bob).wallet()
        earned = 0.0
        for port in (8001, 8002, 8003):
            info = wire.request_sync("127.0.0.1", port, {"type": "ping"})
            say("  %s forwarded %d packets, earned %.2f tokens" % (info["node_id"], info["forwarded"], info["earned"]))
            earned += info["earned"]
        say("  alice balance %.2f, bob balance %.2f" % (a_bal, b_bal))
        check("Alice paid 3 msgs x 3 hops x 0.5", abs(a_bal - 95.5) < 1e-6, "%.2f" % a_bal)
        check("relays earned exactly what senders paid", abs(earned - 6.0) < 1e-6, "%.2f" % earned)
    finally:
        for p in procs:
            p.stop()
        if not args.keep:
            shutil.rmtree(root, ignore_errors=True)

    passed = sum(ok for _, ok in results)
    step("Result: %d/%d checks passed" % (passed, len(results)))
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())
