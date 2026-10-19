"""Token wallet: balance, history and transfers against the network ledger.

A wallet is an account on the bootstrap ledger, identified by your user id
(or a relay's node id) and unlocked by the secret stored on your drive. Losing
the drive's identity.json (or a relay's relay.json) means losing the wallet,
so back it up with ``otpnet wallet backup``.
"""

import json
import os
import shutil

from . import wire

KIND_LABELS = {
    "faucet": "Welcome tokens",
    "fee_paid": "Paid relay fee",
    "fee_refund": "Fee refunded",
    "fee_earned": "Earned forwarding",
    "transfer_out": "Sent",
    "transfer_in": "Received",
}


class WalletError(Exception):
    pass


class Wallet:
    def __init__(self, account_id, secret, bootstrap, key_file=None):
        self.account_id = account_id
        self.secret = secret
        self.bootstrap = wire.parse_addr(bootstrap) if isinstance(bootstrap, str) else bootstrap
        self.key_file = key_file

    @classmethod
    def for_drive(cls, drive):
        return cls(drive.user_id, drive.identity["ledger_secret"], drive.config["bootstrap"],
                   os.path.join(drive.home, "identity.json"))

    @classmethod
    def for_relay(cls, home, relay_id, bootstrap=None):
        path = os.path.join(home, "relays", relay_id, "relay.json")
        if not os.path.exists(path):
            raise WalletError("no relay %r has been run from %s" % (relay_id, home))
        with open(path) as f:
            k = json.load(f)
        return cls(relay_id, k["ledger_secret"], bootstrap or k.get("bootstrap", "127.0.0.1:7000"), path)

    def _call(self, req):
        req.update(account_id=self.account_id, secret=self.secret)
        try:
            resp = wire.request_sync(*self.bootstrap, req, timeout=15)
        except wire.WireError:
            raise WalletError("can't reach the network at %s:%d" % self.bootstrap)
        if not resp.get("ok"):
            raise WalletError(resp.get("error"))
        return resp

    def open(self) -> float:
        """Create the account if needed (new accounts get the network's welcome tokens)."""
        return self._call({"type": "open_account"})["balance"]

    def balance(self) -> dict:
        self.open()
        return self._call({"type": "balance"})

    def history(self, limit=20) -> dict:
        self.open()
        return self._call({"type": "history", "limit": limit})

    def send(self, to, amount, memo="") -> float:
        self.open()
        return self._call({"type": "transfer", "to": to, "amount": float(amount), "memo": memo})["balance"]

    def backup(self, dest) -> str:
        """Copy the wallet key file somewhere safe (another drive, a printed QR, ...)."""
        if os.path.isdir(dest):
            dest = os.path.join(dest, "otpnet-wallet-%s.json" % self.account_id)
        shutil.copyfile(self.key_file, dest)
        return dest
