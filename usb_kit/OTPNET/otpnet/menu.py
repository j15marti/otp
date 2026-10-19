"""Friendly text menu: what you get when you double-click a Start file.

Everything here is a thin layer over the same functions the command line uses.
While the menu is open, the inbox runs in the background, so messages arrive
while you read or write.
"""

import asyncio
import datetime
import os
import shutil
import sys
import threading

from . import KIT_ROOT
from .cli import human
from .client import Client, ClientError, Drive, pair
from .pad import describe_entropy, parse_size
from .state import UnknownContact
from .wallet import KIND_LABELS, Wallet, WalletError

LINE = "-" * 60
KIT_IGNORE = shutil.ignore_patterns("__pycache__", "*.pyc", "data", "vendor", "demo_run")


# -- small input helpers ----------------------------------------------------

def say(text=""):
    print(text, flush=True)


def ask(prompt, default=None):
    suffix = " [%s]" % default if default not in (None, "") else ""
    try:
        answer = input("%s%s: " % (prompt, suffix)).strip()
    except EOFError:
        raise KeyboardInterrupt
    return answer or (default if default is not None else "")


def ask_yes(prompt, default=True):
    a = ask(prompt + (" (Y/n)" if default else " (y/N)")).lower()
    return default if not a else a.startswith("y")


def choose(prompt, options):
    """options: list of labels. Returns index, or None for 'back'."""
    for i, label in enumerate(options, 1):
        say("  %d) %s" % (i, label))
    say("  0) Back")
    while True:
        a = ask(prompt)
        if a in ("", "0"):
            return None
        if a.isdigit() and 1 <= int(a) <= len(options):
            return int(a) - 1
        say("  Please type a number from the list.")


def clean_path(text):
    """Accept paths dragged into a terminal window ('quoted' or with escaped spaces)."""
    text = text.strip().strip("'\"")
    if os.sep == "/":
        text = text.replace("\\ ", " ")
    return os.path.expanduser(text)


def pause():
    ask("\nPress Enter to go back to the menu")


# -- background inbox ---------------------------------------------------------

class Inbox:
    def __init__(self, drive):
        self.error = None
        self.client = Client(drive, log=self._log)
        threading.Thread(target=self._run, daemon=True).start()

    def _log(self, line):
        if "message #" in line and " from " in line:
            who = line.split(" from ", 1)[1].split(" @", 1)[0]
            subject = line.rsplit(": ", 1)[-1].strip("'\"")
            say("\n  *** New message from %s: %s  (choose 'Read my messages') ***" % (who, subject))
        elif "REJECTED" in line:
            say("\n  (A message arrived but failed its security check and was thrown away.)")

    def _run(self):
        try:
            asyncio.run(self.client.serve())
        except OSError as e:
            self.error = ("couldn't open your inbox on %s (%s). Is OTPNET already running in "
                          "another window?" % (self.client.drive.config["listen"], e.strerror or e))


# -- screens ------------------------------------------------------------------

def first_time_setup(home):
    say(LINE)
    say("Welcome to OTPNET! Let's set up this drive. You only do this once.")
    say(LINE)
    name = ""
    while not name or not name.replace("-", "").replace("_", "").isalnum():
        name = ask("Pick a name your friends will see (letters/numbers, e.g. alice)").lower()
    say("\nThe *network address* comes from whoever runs your OTPNET network.")
    say("Just trying it out on this computer? Press Enter to use the default.")
    bootstrap = ask("Network address", "127.0.0.1:7000")
    listen, advertise = _ask_inbox_address("127.0.0.1:5001")
    d = Drive.init(home, name, listen, advertise, bootstrap)
    say("\nAll set, %s! Next step: add a contact (option 4) with a friend's drive." % d.user_id)
    return d


def _ask_inbox_address(default):
    if not ask_yes("\nWill friends on OTHER computers send to this drive?", default=False):
        return default, default
    say("Enter the address other computers use to reach this one, as IP:port")
    say("(your network organiser can help; e.g. 203.0.113.7:5001).")
    advertise = ask("Address", "")
    port = advertise.rpartition(":")[2] or "5001"
    return "0.0.0.0:%s" % port, advertise


def resolve_drive(path):
    """Find the OTPNET data folder from a drive root, OTPNET folder or data folder."""
    for cand in (path, os.path.join(path, "data"), os.path.join(path, "OTPNET", "data")):
        if os.path.exists(os.path.join(cand, "config.json")):
            return cand, True
    for kit in (path, os.path.join(path, "OTPNET")):
        if os.path.exists(os.path.join(kit, "otpnet.py")):
            return os.path.join(kit, "data"), False
    return None, False


def add_contact(drive):
    say(LINE)
    say("ADD A CONTACT\n")
    say("You and your friend need to be together, with BOTH USB drives plugged")
    say("into this computer. OTPNET will create a secret key (a 'pad') and put an")
    say("identical copy on each drive. Nobody else will ever have it.\n")
    path = clean_path(ask("Drag your friend's USB drive (or its OTPNET folder) here, then press Enter"))
    if not path or not os.path.isdir(path):
        say("That folder doesn't exist.")
        return pause()
    other_home, ready = resolve_drive(path)
    if other_home and os.path.abspath(other_home) == drive.home:
        say("That's your own drive! Plug in your friend's drive instead.")
        return pause()
    if other_home is None:
        if not ask_yes("That drive doesn't have OTPNET yet. Copy OTPNET onto it now?"):
            return pause()
        dest = os.path.join(path, "OTPNET")
        say("Copying OTPNET to %s ..." % dest)
        shutil.copytree(KIT_ROOT, dest, ignore=KIT_IGNORE, dirs_exist_ok=True)
        other_home = os.path.join(dest, "data")
    if not ready:
        say("\nNow let's set up your friend's drive.")
        fname = ask("Your friend's name (letters/numbers)").lower()
        listen, advertise = _ask_inbox_address("127.0.0.1:5002")
        Drive.init(other_home, fname, listen, advertise, drive.config["bootstrap"])
    other = Drive(other_home)

    say("\nHow big should the pad be? Every message uses up its own size from the pad.")
    sizes = [("100 MB", "about 20,000 short emails each way"), ("1 GB", "about 200,000 each way"),
             ("10 GB", "years of email plus photos"), ("Custom", "")]
    i = choose("Pick a size", ["%-7s %s" % s for s in sizes])
    if i is None:
        return
    size = parse_size(ask("Size (e.g. 500M, 64G)") if i == 3 else sizes[i][0].replace(" ", ""))
    for d in (drive, other):
        free = shutil.disk_usage(d.home).free
        if free < size * 1.05:
            say("Not enough space on %s's drive: %s free, %s needed." % (d.user_id, human(free), human(size)))
            return pause()
    say("\nRandomness source: %s" % describe_entropy())
    say("Creating the pad. Keep both drives plugged in ...")

    def progress(stage, done, total):
        label = "Creating" if stage == "generate" else "Copying "
        sys.stdout.write("\r  %s %3d%%" % (label, 100 * done // max(total, 1)))
        sys.stdout.flush()
        if done >= total:
            sys.stdout.write("\n")

    try:
        pair(drive, other, size, progress=progress)
    except ClientError as e:
        say("Couldn't pair: %s" % e)
        return pause()
    say("\nDone! %s and %s can now send each other private messages." % (drive.user_id, other.user_id))
    say("Your friend can unplug their drive now.")
    pause()


def pick_contact(drive, prompt="Who?"):
    contacts = drive.state.list_contacts()
    if not contacts:
        say("You don't have any contacts yet. Add one first (option 4).")
        return None
    i = choose(prompt, [c["contact_id"] for c in contacts])
    return None if i is None else contacts[i]


def send_message(drive):
    say(LINE)
    say("SEND A MESSAGE\n")
    c = pick_contact(drive, "Send to")
    if not c:
        return pause()
    subject = ask("Subject")
    say("Type your message. When you're done, type a single dot (.) on its own line.")
    lines = []
    while True:
        try:
            line = input()
        except EOFError:
            break
        if line.strip() == ".":
            break
        lines.append(line)
    attachments = []
    while ask_yes("Attach a file?", default=False):
        p = clean_path(ask("Drag the file here, then press Enter"))
        if os.path.isfile(p):
            with open(p, "rb") as f:
                attachments.append((os.path.basename(p), f.read()))
            say("  attached %s" % os.path.basename(p))
        else:
            say("  can't find that file")
    say("\nSending ...")
    try:
        r = Client(drive, log=lambda *_: None).send(c["contact_id"], subject, "\n".join(lines), attachments)
    except (ClientError, WalletError, OSError) as e:
        say("Couldn't send: %s" % e)
        say("Nothing was used up. Check that you're connected to the network and try again.")
        return pause()
    if r["delivered"]:
        say("Delivered to %s privately. Network fee: %.2f tokens." % (c["contact_id"], r["fees"]))
    else:
        say("NOT delivered: %s" % r["status"])
        say("Your friend's OTPNET is probably closed. Ask them to open it, then send again.")
        say("(For safety, the part of the pad used for this attempt is never reused.)")
    pause()


def read_messages(drive):
    while True:
        say(LINE)
        say("MY MESSAGES\n")
        msgs = list(reversed(drive.state.list_messages("in")))[:30]
        if not msgs:
            say("No messages yet. Messages arrive while OTPNET is open.")
            return pause()
        labels = ["%s  from %-10s %s" % (datetime.datetime.fromtimestamp(m["ts"]).strftime("%b %d %H:%M"),
                                          m["contact_id"], m["subject"] or "(no subject)") for m in msgs]
        i = choose("Open message", labels)
        if i is None:
            return
        m = msgs[i]
        say(LINE)
        say("From:    %s\nSubject: %s\n" % (m["contact_id"], m["subject"]))
        say(m["body"])
        att = os.path.join(drive.home, "inbox", str(m["id"]))
        if os.path.isdir(att):
            say("\nAttachments saved in: %s" % att)
            for name in os.listdir(att):
                say("  - %s" % name)
        pause()


def wallet_screen(drive):
    w = Wallet.for_drive(drive)
    while True:
        say(LINE)
        say("WALLET\n")
        try:
            h = w.history(8)
        except WalletError as e:
            say("Can't open your wallet right now: %s" % e)
            return pause()
        say("Your wallet name: %s" % w.account_id)
        say("Balance:          %.2f tokens%s" % (h["balance"],
            ("   (%.2f held for messages on their way)" % h["locked"]) if h["locked"] else ""))
        say("\nRecent activity:")
        for e in h["entries"]:
            ts = datetime.datetime.fromtimestamp(e["ts"]).strftime("%b %d %H:%M")
            who = (" (%s)" % e["counterparty"]) if e["counterparty"] else ""
            say("  %s  %+8.2f  %s%s" % (ts, e["amount"], KIND_LABELS.get(e["kind"], e["kind"]), who))
        relays = _my_relays(drive)
        for rw, bal in relays:
            say("Relay %-11s %.2f tokens earned/held" % (rw.account_id + ":", bal))
        say("\nTokens pay the volunteers whose computers carry your messages (about")
        say("1.5 tokens per message). You can also earn tokens by running a relay.\n")
        options = ["Send tokens to someone", "Back up my wallet key"]
        if relays:
            options.append("Move my relay earnings into this wallet")
        i = choose("What next?", options)
        if i is None:
            return
        if i == 2:
            for rw, bal in relays:
                if bal > 0:
                    rw.send(w.account_id, bal, "relay earnings")
                    say("Moved %.2f tokens from relay %s." % (bal, rw.account_id))
            pause()
        elif i == 0:
            to = ask("Send to (their wallet name)")
            try:
                amount = float(ask("How many tokens"))
                memo = ask("Note (optional)")
                if ask_yes("Send %.2f tokens to %s?" % (amount, to)):
                    say("Sent. New balance: %.2f" % w.send(to, amount, memo))
                else:
                    say("Cancelled; nothing was sent.")
            except ValueError:
                say("That's not a number.")
            except WalletError as e:
                say("Couldn't send: %s" % e)
            pause()
        else:
            say("Your wallet key lives on this drive. If the drive is lost, so are the tokens.")
            dest = clean_path(ask("Drag a folder here (e.g. on another USB drive) to save a copy"))
            if os.path.isdir(dest):
                say("Saved to %s. Keep it private: anyone with it can spend your tokens." % w.backup(dest))
            else:
                say("That folder doesn't exist.")
            pause()


def _my_relays(drive):
    """Wallets of relays run from this drive, with their balances (skips unreachable ones)."""
    out = []
    root = os.path.join(drive.home, "relays")
    for rid in sorted(os.listdir(root)) if os.path.isdir(root) else []:
        try:
            rw = Wallet.for_relay(drive.home, rid)
            out.append((rw, rw.balance()["balance"]))
        except WalletError:
            pass
    return out


def contacts_screen(drive):
    say(LINE)
    say("CONTACTS\n")
    contacts = drive.state.list_contacts()
    if not contacts:
        say("No contacts yet.")
    for c in contacts:
        left = c["tx_end"] - c["tx_offset"]
        say("  %-12s you can still send %s (about %s short emails)"
            % (c["contact_id"], human(left), "{:,}".format(left // 2500)))
    say("\nWhen a pad runs low, meet up again and add the contact again with a new pad.")
    pause()


def relay_screen(drive):
    from .relay import Relay
    from .wire import parse_addr
    say(LINE)
    say("RUN A RELAY (earn tokens)\n")
    say("A relay passes other people's sealed messages along. It can't read them")
    say("or tell who is talking to whom. You earn a fee for every message passed on.")
    say("Leave this running as long as you like; press Ctrl+C to stop.\n")
    rid = ask("Relay name", "%s-relay" % drive.user_id)
    port = int(ask("Port", "8001"))
    public = ask("Address other computers use to reach this one (Enter = this computer only)", "127.0.0.1")
    fee = float(ask("Fee per message, in tokens", "0.5"))
    host = "127.0.0.1" if public == "127.0.0.1" else "0.0.0.0"
    relay = Relay(rid, host, port, fee, os.path.join(drive.home, "relays", rid),
                  parse_addr(drive.config["bootstrap"]), public, say)
    try:
        asyncio.run(relay.run())
    except KeyboardInterrupt:
        say("\nRelay stopped. Earnings are in its wallet: otpnet wallet --relay %s" % rid)
    except Exception as e:
        say("Relay stopped: %s" % e)
    pause()


def check_screen(drive):
    say(LINE)
    say("CHECK MY SETUP\n")
    say("  Name:        %s" % drive.user_id)
    say("  Inbox:       %s" % drive.config["advertise"])
    say("  Network:     %s" % drive.config["bootstrap"])
    say("  Randomness:  %s" % describe_entropy())
    try:
        relays = Client(drive).relays()
        say("  Network is reachable; %d relays online%s." % (len(relays), "" if len(relays) >= 3 else
                                                              " (need at least 3 to send)"))
    except Exception as e:
        say("  Network NOT reachable: %s" % e)
    pause()


# -- main loop ------------------------------------------------------------------

def run(home):
    say("\nOTPNET - unbreakable private messages\n")
    try:
        drive = Drive(home) if os.path.exists(os.path.join(home, "config.json")) else first_time_setup(home)
        inbox = Inbox(drive)
        screens = [("Send a message", send_message), ("Read my messages", read_messages),
                   ("Wallet (tokens)", wallet_screen), ("Add a contact (with a friend's drive)", add_contact),
                   ("My contacts", contacts_screen), ("Run a relay to earn tokens", relay_screen),
                   ("Check my setup", check_screen)]
        while True:
            say(LINE)
            new = len(drive.state.list_messages("in"))
            say("Signed in as %s   |   %d message(s) in your inbox" % (drive.user_id, new))
            if inbox.error:
                say("Note: %s" % inbox.error)
            else:
                say("Your inbox is open while this window is open.")
            say(LINE)
            for i, (label, _) in enumerate(screens, 1):
                say("  %d) %s" % (i, label))
            say("  0) Quit")
            a = ask("Choose")
            if a == "0":
                break
            if a.isdigit() and 1 <= int(a) <= len(screens):
                try:
                    screens[int(a) - 1][1](drive)
                except KeyboardInterrupt:
                    say("")
                except (ClientError, WalletError, UnknownContact, OSError, ValueError) as e:
                    say("Something went wrong: %s" % e)
                    pause()
    except KeyboardInterrupt:
        pass
    say("\nGoodbye. Messages only arrive while OTPNET is open.")
    return 0
