"""Security rules in one place: sign-in sessions, lockouts, password rules, table QR keys,
browser security headers, the activity log, backups and deleting old phone numbers."""
import hashlib
import hmac
import json
import os
import secrets
import sqlite3
import threading
import time

import db
from core import ApiError

SESSION_TTL = 12 * 3600      # a staff sign-in lasts one shift
SESSION_IDLE = 4 * 3600      # and ends early if the screen is not used (live kitchen screens count as used)
PHONE_KEEP_DAYS = 30
BACKUPS_TO_KEEP = 14

# Content-Security-Policy: pages may only run our own scripts (plus the one QR drawing library).
HEADERS = [
    ("Content-Security-Policy",
     "default-src 'self'; script-src 'self' https://cdnjs.cloudflare.com; style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
     "font-src https://fonts.gstatic.com; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; "
     "form-action 'self'; object-src 'none'"),
    ("X-Content-Type-Options", "nosniff"),
    ("X-Frame-Options", "DENY"),
    ("Referrer-Policy", "no-referrer"),  # the table key in a QR link is never sent to other websites
    ("Permissions-Policy", "camera=(), microphone=(), geolocation=()"),
    ("Cross-Origin-Opener-Policy", "same-origin"),
]


# ------------------------------------------------------------ passwords
COMMON = {"password", "password1", "password12", "password123", "1234567890", "0123456789", "qwertyuiop", "iloveyou12",
          "cuttingchai", "cuttingchai1", "restaurant", "restaurant1", "admin12345", "welcome123"}


def check_new_password(pw):
    if not isinstance(pw, str) or not 10 <= len(pw) <= 128:
        raise ApiError(400, "The owner password must be 10 to 128 characters")
    if pw.lower() in COMMON or len(set(pw)) < 5:
        raise ApiError(400, "That password is too easy to guess. Try three unrelated words and a number.")
    return pw


def check_new_pin(pin):
    if not isinstance(pin, str) or not pin.isdigit() or not 6 <= len(pin) <= 12:
        raise ApiError(400, "The staff PIN must be 6 to 12 digits")
    steps = {(int(b) - int(a)) % 10 for a, b in zip(pin, pin[1:])}
    if len(set(pin)) < 3 or steps in ({1}, {9}):
        raise ApiError(400, "That PIN is too easy to guess (avoid repeats and 123456-style runs)")
    return pin


# ------------------------------------------------------------ sign-in lockout
class Throttle:
    """5 wrong tries a minute from one device, and 20 wrong tries in 15 minutes on one account from anywhere."""

    def __init__(self):
        self.lock = threading.Lock()
        self.fails = {}

    def _recent(self, key, window, now):
        v = [t for t in self.fails.get(key, []) if now - t < window]
        if v:
            self.fails[key] = v
        else:
            self.fails.pop(key, None)
        return len(v)

    def check(self, ip, account):
        now = time.time()
        with self.lock:
            if self._recent(("ip", ip, account), 60, now) >= 5:
                raise ApiError(429, "Too many wrong tries. Wait a minute.")
            if self._recent(("acct", account), 900, now) >= 20:
                raise ApiError(429, "This sign-in is locked for 15 minutes after too many wrong tries.")

    def failed(self, ip, account):
        now = time.time()
        with self.lock:
            self.fails.setdefault(("ip", ip, account), []).append(now)
            self.fails.setdefault(("acct", account), []).append(now)


class RateLimit:
    """At most `per_minute` actions from one network address."""

    def __init__(self, per_minute):
        self.per_minute, self.lock, self.hits = per_minute, threading.Lock(), {}

    def hit(self, key, message):
        now = time.time()
        with self.lock:
            v = [t for t in self.hits.get(key, []) if now - t < 60]
            if len(v) >= self.per_minute:
                self.hits[key] = v
                raise ApiError(429, message)
            v.append(now)
            self.hits[key] = v
            if len(self.hits) > 5000:
                self.hits = {k: x for k, x in self.hits.items() if x and now - x[-1] < 60}


# ------------------------------------------------------------ sessions
class Sessions:
    """Sign-in tokens live only in memory (a restart signs everyone out). The live-update stream gets its own
    key that can do nothing but open that stream, because stream addresses can end up in logs."""

    def __init__(self):
        self.lock = threading.Lock()
        self.by_token = {}
        self.by_stream_key = {}

    def create(self, scope, slug):
        token, key, now = secrets.token_urlsafe(32), secrets.token_urlsafe(24), time.time()
        with self.lock:
            for t in [t for t, s in self.by_token.items() if not self._alive(s, now)]:
                self.by_stream_key.pop(self.by_token.pop(t)["stream_key"], None)
            self.by_token[token] = {"scope": scope, "slug": slug, "created": now, "seen": now, "stream_key": key}
            self.by_stream_key[key] = token
        return token, key

    @staticmethod
    def _alive(s, now):
        return now - s["created"] < SESSION_TTL and now - s["seen"] < SESSION_IDLE

    def get(self, token):
        now = time.time()
        with self.lock:
            s = self.by_token.get(token or "")
            if not s or not self._alive(s, now):
                return None
            s["seen"] = now
            return s

    def from_stream_key(self, key):
        return self.get(self.by_stream_key.get(key or ""))

    def revoke(self, token):
        with self.lock:
            s = self.by_token.pop(token or "", None)
            if s:
                self.by_stream_key.pop(s["stream_key"], None)

    def revoke_account(self, scope, slug):
        with self.lock:
            gone = [t for t, s in self.by_token.items() if s["scope"] == scope and s["slug"] == slug]
            for t in gone:
                self.by_stream_key.pop(self.by_token.pop(t)["stream_key"], None)


# ------------------------------------------------------------ table QR keys
def store_secret(c):
    r = c.execute("SELECT value FROM meta WHERE key='store_secret'").fetchone()
    return r[0] if r else None


def table_key(secret, outlet_slug, table, version):
    """The code inside a table's QR link. Without it, nobody can send an order for that table."""
    return hmac.new(secret.encode(), ("%s:%d:%d" % (outlet_slug, table, version)).encode(), hashlib.sha256).hexdigest()[:20]


def table_key_ok(c, outlet, table, key):
    secret = store_secret(c)
    return bool(secret) and isinstance(key, str) and hmac.compare_digest(
        table_key(secret, outlet["slug"], table, outlet["qr_version"]).encode(), key.encode("utf-8", "replace"))


# ------------------------------------------------------------ activity log
def log_activity(c, actor, ip, action, detail=""):
    c.execute("INSERT INTO activity(at,actor,ip,action,detail) VALUES(?,?,?,?,?)", (time.time(), actor[:80], ip[:60], action[:60], detail[:300]))


# ------------------------------------------------------------ backups and privacy
def backup_dir():
    return os.path.join(os.path.dirname(os.path.abspath(db.DB_PATH)), "backups")


def make_backup():
    """A consistent copy of the whole database, safe to take while orders are coming in."""
    os.makedirs(backup_dir(), exist_ok=True)
    name = "store-%s-%s.db" % (time.strftime("%Y%m%d-%H%M%S"), secrets.token_hex(2))
    src, dst = db.connect(), sqlite3.connect(os.path.join(backup_dir(), name))
    try:
        src.backup(dst)
    finally:
        dst.close()
        src.close()
    old = sorted(f for f in os.listdir(backup_dir()) if f.startswith("store-") and f.endswith(".db"))
    for f in old[:-BACKUPS_TO_KEEP]:
        os.remove(os.path.join(backup_dir(), f))
    return name


def purge_old_phones(c, now=None):
    """Customers' phone numbers are deleted after PHONE_KEEP_DAYS days. Sales records stay."""
    cutoff = (now or time.time()) - PHONE_KEEP_DAYS * 86400
    n = c.execute("UPDATE orders SET phone=NULL WHERE phone IS NOT NULL AND created_at<?", (cutoff,)).rowcount
    for p in c.execute("SELECT id, spec FROM payments WHERE created_at<?", (cutoff,)).fetchall():
        spec = json.loads(p["spec"])
        if spec.get("phone"):
            spec["phone"] = None
            c.execute("UPDATE payments SET spec=? WHERE id=?", (json.dumps(spec, ensure_ascii=False), p["id"]))
    return n
