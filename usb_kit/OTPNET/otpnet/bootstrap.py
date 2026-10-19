"""Bootstrap service: relay directory + token ledger.

V1 stand-in for the pieces a production network would decentralise (a DHT for
the directory, a blockchain or federated e-cash mint for the ledger). Any drive
can run one; a network is simply the set of drives that point at the same
bootstrap address.

Payments use hash-locked escrow, Lightning-style: the sender locks a relay's fee
to sha256(secret); only the next hop can reveal ``secret`` and it does so only
upon receiving the packet, so a relay gets paid exactly when it forwards.
"""

import hashlib
import hmac
import secrets as _secrets
import sqlite3
import threading
import time

UNITS = 1_000_000            # ledger stores integer micro-tokens
RELAY_TTL = 3600             # relays not heard from in this long drop out of the directory

SCHEMA = """
CREATE TABLE IF NOT EXISTS relays (
    node_id TEXT PRIMARY KEY, host TEXT, port INTEGER, pub TEXT, fee INTEGER, last_seen REAL);
CREATE TABLE IF NOT EXISTS accounts (
    account_id TEXT PRIMARY KEY, secret_hash TEXT NOT NULL, balance INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS escrows (
    escrow_id TEXT PRIMARY KEY, payer TEXT, payee TEXT, amount INTEGER, hashlock TEXT,
    expires REAL, status TEXT, created REAL);
CREATE TABLE IF NOT EXISTS ledger_log (
    id INTEGER PRIMARY KEY, ts REAL, account_id TEXT, delta INTEGER, kind TEXT,
    counterparty TEXT, memo TEXT);
"""


class LedgerError(Exception):
    pass


def tokens(units):
    return units / UNITS


def to_units(amount):
    u = int(round(float(amount) * UNITS))
    if u < 0:
        raise LedgerError("negative amount")
    return u


class Bootstrap:
    def __init__(self, db_path, faucet=100.0, log=print):
        self.db = sqlite3.connect(db_path, isolation_level=None, check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self.db.executescript(SCHEMA)
        self.faucet = to_units(faucet)
        self.log = log
        self._lock = threading.Lock()

    async def handle(self, req):
        op = req.get("type")
        fn = getattr(self, "op_" + str(op), None)
        if fn is None:
            return {"ok": False, "error": "unknown request type %r" % op}
        with self._lock:
            self._expire()
            try:
                self.db.execute("BEGIN IMMEDIATE")
                resp = fn(req)
                self.db.execute("COMMIT")
            except LedgerError as e:
                self.db.execute("ROLLBACK")
                return {"ok": False, "error": str(e)}
            except Exception:
                self.db.execute("ROLLBACK")
                raise
        resp.setdefault("ok", True)
        return resp

    # -- helpers ------------------------------------------------------------

    def _auth(self, account_id, secret):
        row = self.db.execute("SELECT * FROM accounts WHERE account_id=?", (account_id,)).fetchone()
        if row is None:
            raise LedgerError("no such account %r" % account_id)
        if not hmac.compare_digest(row["secret_hash"], hashlib.sha256(secret.encode()).hexdigest()):
            raise LedgerError("bad account secret")
        return row

    def _log(self, account_id, delta, kind, counterparty="", memo=""):
        self.db.execute("INSERT INTO ledger_log (ts, account_id, delta, kind, counterparty, memo)"
                        " VALUES (?,?,?,?,?,?)", (time.time(), account_id, delta, kind, counterparty, memo))

    def _locked(self, account_id):
        return self.db.execute("SELECT COALESCE(SUM(amount), 0) FROM escrows WHERE payer=? AND status='locked'",
                               (account_id,)).fetchone()[0]

    def _open(self, account_id, secret):
        h = hashlib.sha256(secret.encode()).hexdigest()
        row = self.db.execute("SELECT * FROM accounts WHERE account_id=?", (account_id,)).fetchone()
        if row is None:
            self.db.execute("INSERT INTO accounts VALUES (?,?,?)", (account_id, h, self.faucet))
            self._log(account_id, self.faucet, "faucet", "network", "welcome tokens")
            self.log("[bootstrap] opened account %s with %.2f faucet tokens"
                     % (account_id, tokens(self.faucet)))
            return self.faucet
        if not hmac.compare_digest(row["secret_hash"], h):
            raise LedgerError("account %r exists and the secret does not match" % account_id)
        return row["balance"]

    def _expire(self):
        """Refund escrows whose relay never produced the receipt in time."""
        now = time.time()
        for e in self.db.execute("SELECT * FROM escrows WHERE status='locked' AND expires<?", (now,)).fetchall():
            self.db.execute("UPDATE escrows SET status='refunded' WHERE escrow_id=?", (e["escrow_id"],))
            self.db.execute("UPDATE accounts SET balance=balance+? WHERE account_id=?",
                            (e["amount"], e["payer"]))
            self._log(e["payer"], e["amount"], "fee_refund", e["payee"], "relay did not deliver in time")

    # -- directory ----------------------------------------------------------

    def op_ping(self, req):
        return {"service": "otpnet-bootstrap"}

    def op_register_relay(self, req):
        node_id = req["node_id"]
        self._open(node_id, req["secret"])
        self.db.execute("INSERT OR REPLACE INTO relays VALUES (?,?,?,?,?,?)",
                        (node_id, req["host"], int(req["port"]), req["pub"], to_units(req["fee"]),
                         time.time()))
        self.log("[bootstrap] relay %s registered at %s:%s fee %s"
                 % (node_id, req["host"], req["port"], req["fee"]))
        return {}

    def op_list_relays(self, req):
        rows = self.db.execute("SELECT * FROM relays WHERE last_seen>? ORDER BY node_id",
                               (time.time() - RELAY_TTL,)).fetchall()
        return {"relays": [{"node_id": r["node_id"], "host": r["host"], "port": r["port"],
                            "pub": r["pub"], "fee": tokens(r["fee"])} for r in rows]}

    # -- ledger -------------------------------------------------------------

    def op_open_account(self, req):
        return {"balance": tokens(self._open(req["account_id"], req["secret"]))}

    def op_balance(self, req):
        acct = self._auth(req["account_id"], req["secret"])
        return {"balance": tokens(acct["balance"]), "locked": tokens(self._locked(acct["account_id"]))}

    def op_transfer(self, req):
        acct = self._auth(req["account_id"], req["secret"])
        to, amount = req["to"], to_units(req["amount"])
        memo = str(req.get("memo", ""))[:200]
        if amount <= 0:
            raise LedgerError("amount must be positive")
        if to == acct["account_id"]:
            raise LedgerError("can't send tokens to yourself")
        if self.db.execute("SELECT 1 FROM accounts WHERE account_id=?", (to,)).fetchone() is None:
            raise LedgerError("no wallet called %r on this network" % to)
        if acct["balance"] < amount:
            raise LedgerError("not enough tokens: you have %.6g, tried to send %.6g"
                              % (tokens(acct["balance"]), tokens(amount)))
        self.db.execute("UPDATE accounts SET balance=balance-? WHERE account_id=?", (amount, acct["account_id"]))
        self.db.execute("UPDATE accounts SET balance=balance+? WHERE account_id=?", (amount, to))
        self._log(acct["account_id"], -amount, "transfer_out", to, memo)
        self._log(to, amount, "transfer_in", acct["account_id"], memo)
        return {"balance": tokens(acct["balance"] - amount)}

    def op_history(self, req):
        acct = self._auth(req["account_id"], req["secret"])
        limit = max(1, min(int(req.get("limit", 20)), 500))
        rows = self.db.execute("SELECT * FROM ledger_log WHERE account_id=? ORDER BY id DESC LIMIT ?",
                               (acct["account_id"], limit)).fetchall()
        return {"balance": tokens(acct["balance"]), "locked": tokens(self._locked(acct["account_id"])),
                "entries": [{"ts": r["ts"], "amount": tokens(r["delta"]), "kind": r["kind"],
                             "counterparty": r["counterparty"], "memo": r["memo"]} for r in rows]}

    def op_escrow_create(self, req):
        acct = self._auth(req["account_id"], req["secret"])
        amount = to_units(req["amount"])
        if acct["balance"] < amount:
            raise LedgerError("insufficient balance: have %.6f, need %.6f"
                              % (tokens(acct["balance"]), tokens(amount)))
        if self.db.execute("SELECT 1 FROM accounts WHERE account_id=?", (req["payee"],)).fetchone() is None:
            raise LedgerError("payee %r has no account" % req["payee"])
        escrow_id = _secrets.token_hex(16)
        self.db.execute("UPDATE accounts SET balance=balance-? WHERE account_id=?",
                        (amount, acct["account_id"]))
        self.db.execute("INSERT INTO escrows VALUES (?,?,?,?,?,?,?,?)",
                        (escrow_id, acct["account_id"], req["payee"], amount, req["hashlock"],
                         time.time() + float(req.get("ttl", 300)), "locked", time.time()))
        self._log(acct["account_id"], -amount, "fee_paid", req["payee"], "relay fee (held until delivery)")
        return {"escrow_id": escrow_id}

    def op_escrow_info(self, req):
        e = self.db.execute("SELECT * FROM escrows WHERE escrow_id=?", (req["escrow_id"],)).fetchone()
        if e is None:
            raise LedgerError("no such escrow")
        return {"payee": e["payee"], "amount": tokens(e["amount"]), "hashlock": e["hashlock"],
                "expires": e["expires"], "status": e["status"]}

    def op_escrow_claim(self, req):
        e = self.db.execute("SELECT * FROM escrows WHERE escrow_id=?", (req["escrow_id"],)).fetchone()
        if e is None:
            raise LedgerError("no such escrow")
        if e["status"] != "locked":
            raise LedgerError("escrow is %s" % e["status"])
        preimage = bytes.fromhex(req["preimage"])
        if not hmac.compare_digest(hashlib.sha256(preimage).hexdigest(), e["hashlock"]):
            raise LedgerError("preimage does not match hashlock")
        self.db.execute("UPDATE escrows SET status='claimed' WHERE escrow_id=?", (e["escrow_id"],))
        self.db.execute("UPDATE accounts SET balance=balance+? WHERE account_id=?",
                        (e["amount"], e["payee"]))
        # deliberately no counterparty: a relay must not learn who funded the packet
        self._log(e["payee"], e["amount"], "fee_earned", "", "forwarded a packet")
        return {"amount": tokens(e["amount"])}
