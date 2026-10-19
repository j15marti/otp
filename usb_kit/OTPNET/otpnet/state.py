"""Secrecy layer: offset state in a local SQLite database.

Per contact we keep ``tx_offset`` (next unused byte for sending) and
``rx_offset`` (next byte we expect to receive with). Both only ever move
forward — that is the burn rule. Each direction owns its own half of the pad
so the two parties can never encrypt with the same bytes::

    pad:  [ initiator -> responder  |  responder -> initiator ]
          0                       size/2                    size
"""

import sqlite3
import threading
import time
from contextlib import contextmanager

from .pad import PadExhausted

SCHEMA = """
CREATE TABLE IF NOT EXISTS contacts (
    contact_id   TEXT PRIMARY KEY,
    pad_file     TEXT    NOT NULL,      -- relative to the drive's data dir
    pad_sha256   TEXT    NOT NULL,      -- fingerprint at pairing time
    tx_offset    INTEGER NOT NULL,
    tx_end       INTEGER NOT NULL,
    rx_offset    INTEGER NOT NULL,
    rx_end       INTEGER NOT NULL,
    address      TEXT    NOT NULL,      -- host:port of their inbox
    routing_pub  TEXT    NOT NULL,      -- base64 X25519 key for the delivery envelope
    mac_alg      TEXT    NOT NULL,
    created_at   REAL    NOT NULL
);
CREATE TABLE IF NOT EXISTS burn_log (
    id          INTEGER PRIMARY KEY,
    contact_id  TEXT    NOT NULL,
    direction   TEXT    NOT NULL CHECK (direction IN ('tx', 'rx')),
    start       INTEGER NOT NULL,
    length      INTEGER NOT NULL,
    reason      TEXT    NOT NULL,
    ts          REAL    NOT NULL
);
CREATE TABLE IF NOT EXISTS messages (
    id              INTEGER PRIMARY KEY,
    contact_id      TEXT    NOT NULL,
    direction       TEXT    NOT NULL CHECK (direction IN ('out', 'in')),
    otp_offset      INTEGER NOT NULL,
    payload_length  INTEGER NOT NULL,
    subject         TEXT,
    body            TEXT,
    status          TEXT    NOT NULL,
    ts              REAL    NOT NULL
);
"""


class ReplayError(Exception):
    """otp_offset is behind rx_offset: those bytes are already burned."""


class UnknownContact(KeyError):
    pass


class State:
    def __init__(self, path):
        self.path = path
        self._lock = threading.Lock()
        db = self._connect()
        try:
            db.executescript(SCHEMA)
        finally:
            db.close()

    def _connect(self):
        db = sqlite3.connect(self.path, timeout=30, isolation_level=None)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA synchronous=FULL")
        return db

    @contextmanager
    def _tx(self):
        # BEGIN IMMEDIATE takes the write lock up front so two senders (or two
        # processes sharing a drive) can never reserve the same bytes.
        with self._lock:
            db = self._connect()
            try:
                db.execute("BEGIN IMMEDIATE")
                yield db
                db.execute("COMMIT")
            except BaseException:
                db.execute("ROLLBACK")
                raise
            finally:
                db.close()

    # -- contacts -----------------------------------------------------------

    def add_contact(self, contact_id, pad_file, pad_sha256, tx_range, rx_range, address,
                    routing_pub, mac_alg):
        with self._tx() as db:
            db.execute(
                "INSERT INTO contacts VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (contact_id, pad_file, pad_sha256, tx_range[0], tx_range[1], rx_range[0],
                 rx_range[1], address, routing_pub, mac_alg, time.time()))

    def get_contact(self, contact_id) -> dict:
        with self._tx() as db:
            row = db.execute("SELECT * FROM contacts WHERE contact_id=?", (contact_id,)).fetchone()
        if row is None:
            raise UnknownContact(contact_id)
        return dict(row)

    def has_contact(self, contact_id) -> bool:
        try:
            self.get_contact(contact_id)
            return True
        except UnknownContact:
            return False

    def list_contacts(self):
        with self._tx() as db:
            return [dict(r) for r in db.execute("SELECT * FROM contacts ORDER BY contact_id")]

    def set_address(self, contact_id, address):
        with self._tx() as db:
            if db.execute("UPDATE contacts SET address=? WHERE contact_id=?",
                          (address, contact_id)).rowcount == 0:
                raise UnknownContact(contact_id)

    # -- offsets ------------------------------------------------------------

    def reserve_tx(self, contact_id, length) -> int:
        """Claim ``length`` sending bytes and advance tx_offset *before* use.

        Returns the starting offset. The bytes are burned from this moment on,
        whether or not the message is ever delivered.
        """
        with self._tx() as db:
            row = db.execute("SELECT tx_offset, tx_end FROM contacts WHERE contact_id=?",
                             (contact_id,)).fetchone()
            if row is None:
                raise UnknownContact(contact_id)
            start = row["tx_offset"]
            if start + length > row["tx_end"]:
                raise PadExhausted("only %d sending bytes left for %s; need %d"
                                   % (row["tx_end"] - start, contact_id, length))
            db.execute("UPDATE contacts SET tx_offset=? WHERE contact_id=?",
                       (start + length, contact_id))
            return start

    def accept_rx(self, contact_id, otp_offset, length, verify):
        """Receive-side burn rule and offset auto-correction.

        * ``otp_offset < rx_offset``  -> ReplayError (bytes already burned).
        * ``otp_offset > rx_offset``  -> earlier message(s) were lost; skip
          (permanently burn) the gap and jump forward.
        * ``verify()`` must check the MAC and return the plaintext. It runs inside
          the transaction and *before* rx_offset moves, so a forged packet with a
          huge offset can't make us burn the rest of the pad.

        Returns ``(plaintext, previous_rx_offset, skipped_bytes)``.
        """
        with self._tx() as db:
            row = db.execute("SELECT rx_offset, rx_end FROM contacts WHERE contact_id=?",
                             (contact_id,)).fetchone()
            if row is None:
                raise UnknownContact(contact_id)
            rx = row["rx_offset"]
            if otp_offset < rx:
                raise ReplayError("otp_offset %d < rx_offset %d: replayed or stale packet"
                                  % (otp_offset, rx))
            if otp_offset + length > row["rx_end"]:
                raise PadExhausted("packet claims bytes beyond %s's sending region" % contact_id)
            plaintext = verify()
            skipped = otp_offset - rx
            if skipped:
                db.execute("INSERT INTO burn_log (contact_id, direction, start, length, reason, ts)"
                           " VALUES (?, 'rx', ?, ?, 'gap: lost or delayed packet', ?)",
                           (contact_id, rx, skipped, time.time()))
            db.execute("UPDATE contacts SET rx_offset=? WHERE contact_id=?",
                       (otp_offset + length, contact_id))
            return plaintext, rx, skipped

    def burn(self, contact_id, direction, nbytes, reason="manual"):
        """Advance tx/rx offset without using the bytes (e.g. to simulate loss)."""
        col = {"tx": "tx_offset", "rx": "rx_offset"}[direction]
        end = {"tx": "tx_end", "rx": "rx_end"}[direction]
        with self._tx() as db:
            row = db.execute("SELECT %s AS o, %s AS e FROM contacts WHERE contact_id=?" % (col, end),
                             (contact_id,)).fetchone()
            if row is None:
                raise UnknownContact(contact_id)
            new = min(row["o"] + nbytes, row["e"])
            db.execute("UPDATE contacts SET %s=? WHERE contact_id=?" % col, (new, contact_id))
            db.execute("INSERT INTO burn_log (contact_id, direction, start, length, reason, ts)"
                       " VALUES (?,?,?,?,?,?)",
                       (contact_id, direction, row["o"], new - row["o"], reason, time.time()))
            return row["o"], new

    def burn_log(self, contact_id=None):
        with self._tx() as db:
            q = "SELECT * FROM burn_log" + (" WHERE contact_id=?" if contact_id else "") + " ORDER BY id"
            return [dict(r) for r in db.execute(q, (contact_id,) if contact_id else ())]

    # -- mailbox ------------------------------------------------------------

    def log_message(self, contact_id, direction, otp_offset, payload_length, subject, body,
                    status) -> int:
        with self._tx() as db:
            cur = db.execute(
                "INSERT INTO messages (contact_id, direction, otp_offset, payload_length, subject,"
                " body, status, ts) VALUES (?,?,?,?,?,?,?,?)",
                (contact_id, direction, otp_offset, payload_length, subject, body, status,
                 time.time()))
            return cur.lastrowid

    def set_message_status(self, msg_id, status):
        with self._tx() as db:
            db.execute("UPDATE messages SET status=? WHERE id=?", (status, msg_id))

    def list_messages(self, direction=None):
        with self._tx() as db:
            q = "SELECT * FROM messages" + (" WHERE direction=?" if direction else "") + " ORDER BY id"
            return [dict(r) for r in db.execute(q, (direction,) if direction else ())]

    def get_message(self, msg_id):
        with self._tx() as db:
            row = db.execute("SELECT * FROM messages WHERE id=?", (msg_id,)).fetchone()
        return dict(row) if row else None
