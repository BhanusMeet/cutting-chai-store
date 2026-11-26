"""Shared basics used by every part of the server: errors, safe input reading, one-writer-at-a-time database access."""
import contextlib
import threading

import db


class ApiError(Exception):
    def __init__(self, code, msg):
        super().__init__(msg)
        self.code, self.msg = code, msg


# SQLite allows one writer at a time. Writers queue here instead of fighting through SQLite's retry loop.
WRITE_LOCK = threading.Lock()


@contextlib.contextmanager
def write_lock_tx(c):
    """Hold the write lock and run the block inside one transaction on a manual-mode connection."""
    with WRITE_LOCK:
        c.execute("BEGIN IMMEDIATE")
        try:
            yield c
            c.execute("COMMIT")
        except BaseException:
            c.execute("ROLLBACK")
            raise


# Every write goes through this one connection, which stays open. Closing the last open connection makes SQLite
# tidy and flush the whole database; doing that after every write made each order about 16 times slower.
_shared = {"path": None, "conn": None}


@contextlib.contextmanager
def writer():
    with WRITE_LOCK:
        if _shared["conn"] is None or _shared["path"] != db.DB_PATH:
            _shared.update(path=db.DB_PATH, conn=db.connect(manual=True, shared=True))
        c = _shared["conn"]
        try:
            c.execute("BEGIN IMMEDIATE")
            yield c
            c.execute("COMMIT")
        except BaseException:
            try:
                if c.in_transaction:
                    c.execute("ROLLBACK")
            except Exception:  # the connection itself is broken: start a fresh one next time
                _shared["conn"] = None
                c.close()
            raise


def as_int(v, lo, hi, field):
    if isinstance(v, bool) or not isinstance(v, (int, float)) or v != v or v in (float("inf"), float("-inf")) or int(v) != v:
        raise ApiError(400, f"{field} must be a whole number")
    v = int(v)
    if not lo <= v <= hi:
        raise ApiError(400, f"{field} must be between {lo} and {hi}")
    return v


def text(v, maxlen, field, required=False):
    if v is None:
        v = ""
    if not isinstance(v, str):
        raise ApiError(400, f"{field} must be text")
    try:
        v.encode("utf-8")
    except UnicodeEncodeError:
        raise ApiError(400, f"{field} contains characters that cannot be saved")
    v = "".join(ch for ch in v if ch >= " " or ch == "\t").strip()  # no control characters
    if required and not v:
        raise ApiError(400, f"{field} is required")
    if len(v) > maxlen:
        raise ApiError(400, f"{field} is too long")
    return v


def get_outlet(c, slug):
    r = c.execute("""SELECT o.*, b.slug AS brand_slug, b.name AS brand_name, b.id AS bid FROM outlets o
                     JOIN brands b ON b.id=o.brand_id WHERE o.slug=?""", (slug,)).fetchone()
    if not r:
        raise ApiError(404, "Unknown outlet")
    return r


def get_brand(c, slug):
    r = c.execute("SELECT * FROM brands WHERE slug=?", (slug,)).fetchone()
    if not r:
        raise ApiError(404, "Unknown restaurant")
    return r
