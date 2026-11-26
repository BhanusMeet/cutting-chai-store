#!/usr/bin/env python3
"""Table ordering for a restaurant: API, live updates (Server-Sent Events) and pages.

Run:  python server.py                          (this computer only)
      python server.py --lan                    (phones and tablets on the store Wi-Fi)
      python server.py --lan --cert c.pem --key k.pem   (the same, encrypted with HTTPS)
On the first start the window shows a one-time SETUP CODE for creating your store.
Only the Python standard library is used.
"""
import argparse
import hashlib
import hmac
import json
import math
import os
import queue
import re
import secrets
import select
import socket
import ssl
import sys
import threading
import time
import traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

import db
import ledger
from business_routes import BUSINESS_ROUTES, BusinessRoutes
import security
import store
from core import ApiError, as_int, get_brand, get_outlet, text, write_lock_tx, writer
import printing
import print_routes
from print_routes import PRINT_ROUTES, PrintRoutes
from printer import PrintQueue
from store import SESSIONS, STORE_ROUTES, StoreRoutes, get_session

WEB = os.path.join(os.path.dirname(os.path.abspath(__file__)), "web")
# Online payment stays OFF until a real payment company is connected: set QRO_PAY_SECRET to the shared secret
# it signs its confirmations with. Without it, takeaway is paid at the counter.
PAY_SECRET = os.environ.get("QRO_PAY_SECRET", "").encode()
ORDER_RATE = security.RateLimit(int(os.environ.get("QRO_ORDER_RATE", "120")))  # a whole restaurant can share one Wi-Fi address
MAX_PUBLIC_STREAMS, MAX_PUBLIC_STREAMS_PER_IP = 600, 60
STREAMS = {}
STREAM_LOCK = threading.Lock()
PREP_SECONDS = 480          # typical cooking time used in the takeaway estimate
INSTANT_ETA_SECONDS = 120   # estimate when everything on the order is always ready
MAX_BODY = 64 * 1024
# A fixed list on purpose. Python's mimetypes module reads the Windows registry on first use, and when thousands of
# requests did that at once the server stopped answering (found by the load test).
FILE_TYPES = {".html": "text/html", ".css": "text/css", ".js": "text/javascript", ".json": "application/json",
              ".svg": "image/svg+xml", ".png": "image/png", ".jpg": "image/jpeg", ".ico": "image/x-icon", ".woff2": "font/woff2"}
STALE_SLIP = 2 * 3600       # a printer that comes back hours later must not pour out old slips
FLOW = {"new": ["preparing", "cancelled"], "preparing": ["ready", "cancelled"], "ready": ["served", "cancelled"], "served": [], "cancelled": []}
STRENGTH = ("Halka", "Normal", "Kadak")
SUGAR = ("Kam", "Normal", "Zyada")


MAX_OPEN_PER_TABLE = 4      # orders a table can have in progress at once (stops one phone flooding the kitchen)
MAX_PER_TABLE_HOUR = 20
MAX_OPEN_TAKEAWAY_PER_NAME = 5


# ------------------------------------------------------------ live updates
class Hub:
    def __init__(self):
        self.lock = threading.Lock()
        self.chans = {}

    def subscribe(self, ch):
        q = queue.Queue(maxsize=200)
        with self.lock:
            self.chans.setdefault(ch, set()).add(q)
        return q

    def unsubscribe(self, ch, q):
        with self.lock:
            self.chans.get(ch, set()).discard(q)

    def publish(self, ch, event, data):
        payload = (event, json.dumps(data, ensure_ascii=False))
        with self.lock:
            targets = list(self.chans.get(ch, ()))
        for q in targets:
            try:
                q.put_nowait(payload)
            except queue.Full:
                pass


HUB = Hub()

# ------------------------------------------------------------ helpers
def day_start():
    t = time.localtime()
    return time.mktime((t.tm_year, t.tm_mon, t.tm_mday, 0, 0, 0, 0, 0, -1))


def brand_public(r):
    return {"slug": r["slug"], "name": r["name"], "theme": r["theme"], "tagline": r["tagline"],
            "langs": json.loads(r["langs"]), "default_lang": r["default_lang"]}


def outlet_public(r):
    """What anyone may know about an outlet."""
    return {"slug": r["slug"], "name": r["name"], "city": r["city"], "country": r["country"], "currency": r["currency"],
            "tables": r["tables_count"], "accepting": bool(r["accepting"]), "online_payment": bool(PAY_SECRET)}


def outlet_staff(r):
    """Settings only signed-in staff see."""
    return dict(outlet_public(r), kitchen_lang=r["kitchen_lang"], auto_accept=bool(r["auto_accept"]),
                print_gap=r["print_gap"], print_order=r["print_order"], print_mode=r["print_mode"],
                printer_name=r["printer_name"] or "", paper_width=r["paper_width"])


def order_dict(c, o, outlet):
    lines = c.execute("""SELECT l.item_id, l.qty, l.price, i.names FROM order_lines l JOIN items i ON i.id=l.item_id
                         WHERE l.order_id=? ORDER BY l.id""", (o["id"],)).fetchall()
    kl = outlet["kitchen_lang"]
    out = []
    for l in lines:
        names = json.loads(l["names"])
        out.append({"item_id": l["item_id"], "qty": l["qty"], "price": l["price"], "names": names,
                    "kitchen_name": names.get(kl) or names.get("en") or next(iter(names.values()), "?")})
    return {"public_id": o["public_id"], "token": o["token"], "table": o["table_no"], "kind": o["kind"], "status": o["status"],
            "total": o["total"], "name": o["customer_name"] or "", "prefs": json.loads(o["prefs"] or "null"),
            "note": o["note"] or "", "created_at": o["created_at"], "updated_at": o["updated_at"],
            "paid": bool(o["payment_ref"]), "eta_seconds": o["eta_seconds"], "server_time": time.time(),
            "currency": outlet["currency"], "outlet": outlet["slug"], "lines": out}  # the phone number is never included


def staff_order(c, o, outlet):
    """order_dict plus what only staff may see: print state and the last digits of the phone number."""
    od = order_dict(c, o, outlet)
    slips = c.execute("SELECT status FROM slips WHERE order_id=?", (o["id"],)).fetchall()
    od["slips_waiting"] = sum(1 for s in slips if s["status"] == "queued")
    od["phone_last4"] = (o["phone"] or "")[-4:]
    od["pay_method"], od["paid_at"] = o["pay_method"], o["paid_at"]
    return od


# ------------------------------------------------------------ slips and printing
def slip_dict(r, o):
    return {"id": r["id"], "station": r["station"], "items": json.loads(r["items"]), "queued_at": r["queued_at"],
            "printed_at": r["printed_at"], "public_id": o["public_id"], "token": o["token"], "table": o["table_no"],
            "kind": o["kind"], "name": o["customer_name"] or "", "status": r["status"], "error": r["error"] or ""}


def make_slips(c, order_id, outlet, now):
    """Split an order into a counter slip (always-ready items, released at once) and a kitchen slip (paced).
    Call inside a write transaction. Returns (slips to release now, slips to queue). 'No print' makes none."""
    if outlet["print_mode"] == "none":
        return [], []
    rows = c.execute("""SELECT l.qty, i.instant, i.names FROM order_lines l JOIN items i ON i.id=l.item_id
                        WHERE l.order_id=? ORDER BY l.id""", (order_id,)).fetchall()
    kl = outlet["kitchen_lang"]
    groups = {"counter": [], "kitchen": []}
    for r in rows:
        names = json.loads(r["names"])
        groups["counter" if r["instant"] else "kitchen"].append({"qty": r["qty"], "name": names.get(kl) or names.get("en")})
    now_list, queued = [], []
    for station, items in groups.items():
        if not items:
            continue
        at_once = station == "counter" or outlet["print_gap"] <= 0
        cur = c.execute("INSERT INTO slips(order_id,outlet_id,station,status,items,queued_at,printed_at) VALUES(?,?,?,?,?,?,?)",
                        (order_id, outlet["id"], station, "queued", json.dumps(items, ensure_ascii=False), now, None))
        entry = {"id": cur.lastrowid, "order_id": order_id, "queued_at": now, "size": sum(i["qty"] for i in items)}
        entry["station"] = station
        (now_list if at_once else queued).append(entry)
    return now_list, queued


def announce_slips(slip_ids):
    """Tell each store's kitchen screen about slips that have just printed."""
    with db.connect() as c:
        for sid in slip_ids:
            r = c.execute("""SELECT s.*, o.public_id, o.token, o.table_no, o.kind, o.customer_name, u.slug FROM slips s
                             JOIN orders o ON o.id=s.order_id JOIN outlets u ON u.id=s.outlet_id WHERE s.id=?""", (sid,)).fetchone()
            if r and r["status"] != "skipped":
                HUB.publish("outlet:" + r["slug"], "slip", slip_dict(r, r))


def release(slips):
    """Slips whose turn has come: send them to the store's USB printer, or just show them on screen."""
    to_send, on_screen, shown = [], [], []
    if not slips:
        return
    with db.connect() as c:  # only a look: slips going to a printer need no write here
        for s in slips:
            r = c.execute("""SELECT s.station, s.outlet_id, u.print_mode FROM slips s JOIN outlets u ON u.id=s.outlet_id
                             WHERE s.id=? AND s.status='queued'""", (s["id"],)).fetchone()
            if not r:
                continue
            if r["print_mode"] == "usb":
                to_send.append((r["outlet_id"], s["id"], r["station"]))
            else:
                on_screen.append(s)
    if on_screen:
        with writer() as c:
            for s in on_screen:
                c.execute("UPDATE slips SET status='screen', printed_at=? WHERE id=? AND status='queued'",
                          (s.get("printed_at", time.time()), s["id"]))
                shown.append(s["id"])
    for outlet_id, slip_id, station in to_send:
        DISPATCH.add(outlet_id, slip_id, station)
    announce_slips(shown)


def printer_config(outlet_id):
    with db.connect() as c:
        return c.execute("SELECT * FROM outlets WHERE id=?", (outlet_id,)).fetchone()


def load_slip(slip_id):
    """The slip as it should print now, or None if it no longer should."""
    with db.connect() as c:
        r = c.execute("""SELECT s.*, o.public_id, o.token, o.table_no, o.kind, o.customer_name, o.prefs, o.note FROM slips s
                         JOIN orders o ON o.id=s.order_id WHERE s.id=? AND s.status='queued'""", (slip_id,)).fetchone()
    if not r:
        return None
    if not r["reprint"] and time.time() - r["queued_at"] > STALE_SLIP:
        mark_slip(slip_id, "failed", "this slip waited over 2 hours: reprint it only if it is still needed")
        return None
    return dict(slip_dict(r, r), reprint=bool(r["reprint"]), prefs=json.loads(r["prefs"] or "null"), note=r["note"] or "")


def mark_slip(slip_id, status, error, at=None):
    """Save what happened to a slip and tell that store's kitchen screen."""
    with writer() as c:
        c.execute("UPDATE slips SET status=?, error=?, printed_at=COALESCE(?, printed_at) WHERE id=? AND status!='skipped'",
                  (status, error, (at or time.time()) if status == "printed" else None, slip_id))
    announce_slips([slip_id])


PRINTER = PrintQueue(release)
DISPATCH = printing.Dispatcher(printer_config, load_slip, mark_slip)


def queue_entry(s):
    return {"id": s["id"], "order_id": s["order_id"], "queued_at": s["queued_at"], "size": sum(i["qty"] for i in json.loads(s["items"]))}


def load_printer():
    with writer() as c:
        c.execute("""UPDATE slips SET status='failed', error='the server restarted while this slip was printing: check the paper'
                     WHERE status='sending'""")
    with db.connect() as c:
        for o in c.execute("SELECT id, print_gap, print_order FROM outlets"):
            PRINTER.configure(o["id"], o["print_gap"], o["print_order"])
        waiting = c.execute("SELECT * FROM slips WHERE status='queued' ORDER BY queued_at").fetchall()
    for s in waiting:
        if s["station"] == "counter":
            release([queue_entry(s)])
        else:
            PRINTER.add(s["outlet_id"], queue_entry(s))
    PRINTER.start()


def printer_info(c, o):
    """Everything the kitchen screen shows about printing at this store."""
    return print_routes.info(c, o, PRINTER, DISPATCH)


# ------------------------------------------------------------ orders
def clean_phone(v):
    v = text(v, 20, "phone", True)
    digits = re.sub(r"[\s\-()]", "", v)
    if not re.fullmatch(r"\+?\d{10,15}", digits):
        raise ApiError(400, "Please enter a valid phone number")
    return digits


def validate_order(c, o, d, kind):
    """Check a request against this store's menu and work out the price on the server."""
    table = 0 if kind == "takeaway" else as_int(d.get("table"), 1, o["tables_count"], "table")
    raw = d.get("lines")
    if not isinstance(raw, list) or not 1 <= len(raw) <= 40:
        raise ApiError(400, "Add at least one item")
    menu = {it["id"]: it for cat in menu_rows(c, o) for it in cat["items"]}
    lines, total, seen = [], 0, set()
    for ln in raw:
        if not isinstance(ln, dict):
            raise ApiError(400, "Bad item")
        iid = as_int(ln.get("item_id"), 1, 10**9, "item")
        qty = as_int(ln.get("qty"), 1, 20, "quantity")
        it = menu.get(iid)
        if not it or iid in seen:
            raise ApiError(400, "Unknown item")
        if not it["available"]:
            raise ApiError(409, "%s is not available right now" % it["names"].get("en", "An item"))
        seen.add(iid)
        lines.append([iid, qty, it["price"]])
        total += qty * it["price"]
    prefs = d.get("prefs")
    if prefs is not None:
        if not isinstance(prefs, dict) or prefs.get("strength") not in STRENGTH or prefs.get("sugar") not in SUGAR:
            raise ApiError(400, "Bad preferences")
        prefs = {"strength": prefs["strength"], "sugar": prefs["sugar"]}
    return {"kind": kind, "table": table, "lines": lines, "total": total, "prefs": prefs,
            "name": text(d.get("name"), 30, "name", required=(kind == "takeaway")),  # takeaway needs a name to call out
            "note": text(d.get("note"), 120, "note"), "client_key": text(d.get("client_key"), 40, "client_key") or None}


def check_limits(c, o, spec, now):
    if spec["kind"] == "dine_in":
        open_n = c.execute("SELECT COUNT(*) FROM orders WHERE outlet_id=? AND table_no=? AND kind='dine_in' AND status IN ('new','preparing','ready')", (o["id"], spec["table"])).fetchone()[0]
        if open_n >= MAX_OPEN_PER_TABLE:
            raise ApiError(429, "This table already has %d orders in progress. Please ask a waiter." % open_n)
        if c.execute("SELECT COUNT(*) FROM orders WHERE outlet_id=? AND table_no=? AND kind='dine_in' AND created_at>=?", (o["id"], spec["table"], now - 3600)).fetchone()[0] >= MAX_PER_TABLE_HOUR:
            raise ApiError(429, "Too many orders from this table in the last hour. Please ask a waiter.")
    elif c.execute("SELECT COUNT(*) FROM orders WHERE outlet_id=? AND kind='takeaway' AND customer_name=? AND status IN ('new','preparing','ready')", (o["id"], spec["name"])).fetchone()[0] >= MAX_OPEN_TAKEAWAY_PER_NAME:
        raise ApiError(429, "There are already %d takeaway orders under this name. Please ask at the counter." % MAX_OPEN_TAKEAWAY_PER_NAME)


def insert_order(c, o, spec, now, payment_ref=None, phone=None, pay_method=None):
    """Save an order inside a write transaction. With auto-accept on, the SERVER accepts it here, in the same write,
    so the kitchen sends no extra request. Returns (row id, slips printed now, slips to queue)."""
    auto = bool(o["auto_accept"])
    status = "new"
    all_instant = False
    if auto:
        ids = [l[0] for l in spec["lines"]]
        n_instant = c.execute("SELECT COUNT(*) FROM items WHERE instant=1 AND id IN (%s)" % ",".join("?" * len(ids)), ids).fetchone()[0]
        all_instant = n_instant == len(ids)
        status = "ready" if all_instant else "preparing"
    token = c.execute("SELECT COALESCE(MAX(token),0)+1 FROM orders WHERE outlet_id=? AND created_at>=?", (o["id"], day_start())).fetchone()[0]
    eta = INSTANT_ETA_SECONDS if all_instant else int(PREP_SECONDS + PRINTER.ahead(o["id"]) * max(o["print_gap"], 0))
    if payment_ref:
        pay_method = "online"
    cur = c.execute("""INSERT INTO orders(public_id,outlet_id,token,table_no,customer_name,prefs,note,kind,client_key,status,total,
                       created_at,updated_at,phone,payment_ref,eta_seconds,pay_method,paid_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (secrets.token_urlsafe(16), o["id"], token, spec["table"], spec["name"],
                     json.dumps(spec["prefs"]) if spec["prefs"] else None, spec["note"], spec["kind"], spec["client_key"], status,
                     spec["total"], now, now, phone, payment_ref, eta, pay_method, now if pay_method else None))
    oid = cur.lastrowid
    for iid, qty, price in spec["lines"]:
        c.execute("INSERT INTO order_lines(order_id,item_id,qty,price) VALUES(?,?,?,?)", (oid, iid, qty, price))
    ledger.take_for_order(c, o["id"], oid, now)
    printed, queued = make_slips(c, oid, o, now) if auto else ([], [])
    return oid, printed, queued


def after_create(o, od, printed, queued):
    """Everything that happens once a new order is safely saved."""
    HUB.publish("outlet:" + o["slug"], "order_new", dict(od, slips_waiting=len(queued)))  # the kitchen learns of the order first
    for s in queued:
        PRINTER.add(o["id"], s)
    if printed:
        release(printed)
    if od["kind"] == "takeaway":
        HUB.publish("board:" + o["slug"], "board", {"token": od["token"], "status": od["status"]})


def process_payment_event(raw, signature):
    """The ONLY way a paid takeaway order is created. `raw` must carry a valid signature from the payment side."""
    if not PAY_SECRET:
        raise ApiError(404, "Online payment is not connected")
    good = hmac.new(PAY_SECRET, raw, hashlib.sha256).hexdigest()
    if not signature or not hmac.compare_digest(good.encode(), signature.encode("utf-8", "replace")):
        raise ApiError(401, "Bad payment signature")
    try:
        ev = json.loads(raw)
        ref, status, amount = ev["payment_ref"], ev["status"], ev["amount"]
    except (ValueError, KeyError, TypeError):
        raise ApiError(400, "Bad payment event")
    if not isinstance(ref, str) or not isinstance(status, str):
        raise ApiError(400, "Bad payment event")
    created = None
    with writer() as c:
        p = c.execute("SELECT * FROM payments WHERE ref=?", (ref,)).fetchone()
        if not p:
            raise ApiError(404, "Unknown payment")
        if p["status"] in ("paid", "refund_due"):  # providers repeat their messages: never create a second order
            return {"status": p["status"], "order": p["order_public_id"], "duplicate": True}
        if status != "paid":
            c.execute("UPDATE payments SET status='failed' WHERE id=?", (p["id"],))
            return {"status": "failed", "order": None}
        if amount != p["amount"]:
            raise ApiError(400, "Paid amount does not match the order")
        o = c.execute("""SELECT o.*, b.slug AS brand_slug, b.id AS bid FROM outlets o JOIN brands b ON b.id=o.brand_id
                         WHERE o.id=?""", (p["outlet_id"],)).fetchone()
        stored = json.loads(p["spec"])
        spec = stored["spec"]
        now = time.time()
        oid, printed, queued = insert_order(c, o, spec, now, payment_ref=ref, phone=stored["phone"])
        row = c.execute("SELECT * FROM orders WHERE id=?", (oid,)).fetchone()
        c.execute("UPDATE payments SET status='paid', order_public_id=?, paid_at=? WHERE id=?", (row["public_id"], now, p["id"]))
        created = (o, row, printed, queued)
    o, row, printed, queued = created
    with db.connect() as c:
        od = order_dict(c, row, o)
    after_create(o, od, printed, queued)
    return {"status": "paid", "order": od["public_id"]}


def menu_rows(c, outlet, admin=False):
    cats = c.execute("SELECT * FROM categories WHERE brand_id=? ORDER BY sort, id", (outlet["bid"],)).fetchall()
    rows = c.execute("""SELECT i.*, oi.price AS o_price, oi.available AS o_avail FROM items i
                        LEFT JOIN outlet_items oi ON oi.item_id=i.id AND oi.outlet_id=?
                        WHERE i.brand_id=? AND i.archived=0 ORDER BY i.sort, i.id""", (outlet["id"], outlet["bid"])).fetchall()
    out = []
    for cat in cats:
        items = []
        for r in rows:
            if r["category_id"] != cat["id"]:
                continue
            avail = 1 if r["o_avail"] is None else r["o_avail"]
            eff = r["o_price"] if r["o_price"] is not None else r["price"]
            it = {"id": r["id"], "slug": r["slug"], "names": json.loads(r["names"]), "descs": json.loads(r["descs"]),
                  "price": eff, "veg": bool(r["veg"]), "tag": r["tag"], "available": bool(avail), "instant": bool(r["instant"])}
            if admin:
                it.update({"base_price": r["price"], "override": r["o_price"]})
            items.append(it)
        out.append({"slug": cat["slug"], "names": json.loads(cat["names"]), "items": items})
    return out


# ------------------------------------------------------------ HTTP handler
class Handler(BusinessRoutes, PrintRoutes, StoreRoutes, BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.0"
    server_version = "store"   # do not advertise software names or versions
    sys_version = ""
    timeout = 30  # drop connections that connect and then say nothing, so they cannot pile up and hold threads

    def log_message(self, fmt, *args):
        # Python also calls this for its own error replies (unsupported method, bad request line) where the
        # first argument is a number, so build the full line before inspecting it.
        line = (fmt % args) if args else fmt
        line = re.sub(r"([?&](?:k|key|order|t)=)[^ &]+", r"\g<1>***", line)  # secrets in addresses never reach the log
        if "/api/stream" not in line:
            sys.stderr.write("%s - %s\n" % (self.address_string(), line))

    def end_headers(self):
        for name, value in security.HEADERS:  # on every reply, including error replies
            self.send_header(name, value)
        if getattr(self.server, "is_https", False):
            self.send_header("Strict-Transport-Security", "max-age=15552000")
        super().end_headers()

    do_GET = lambda self: self.route("GET")
    do_POST = lambda self: self.route("POST")
    do_PUT = lambda self: self.route("PUT")

    # --- plumbing
    def send_json(self, obj, code=200):
        body = json.dumps(obj, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def length(self, limit=MAX_BODY):
        raw = (self.headers.get("Content-Length") or "0").strip()
        if not raw.isdigit() or len(raw) > 10:  # also refuses negative sizes, which would make the server read forever
            raise ApiError(400, "Bad request size")
        if int(raw) > limit:
            raise ApiError(413, "Request too large")
        return int(raw)

    def body(self):
        n = self.length()
        try:
            data = json.loads(self.rfile.read(n) or b"{}")
        except (ValueError, RecursionError):
            raise ApiError(400, "Invalid JSON")
        if not isinstance(data, dict):
            raise ApiError(400, "JSON object expected")
        return data

    def token(self):
        """Sign-in tokens are accepted only in a request header, never in a web address."""
        h = self.headers.get("Authorization", "")
        return h[7:] if h.startswith("Bearer ") else None

    def need(self, scope, slug):
        s = get_session(self.token())
        if not s:
            raise ApiError(401, "Please sign in")
        if not (s["scope"] == scope and s["slug"] == slug):
            raise ApiError(403, "Not allowed for this restaurant")
        return s

    @staticmethod
    def check_kitchen(s, outlet):
        if not s:
            raise ApiError(401, "Please sign in")
        ok = (s["scope"] == "kitchen" and s["slug"] == outlet["slug"]) or (s["scope"] == "admin" and s["slug"] == outlet["brand_slug"])
        if not ok:
            raise ApiError(403, "Not allowed for this outlet")
        return s

    def need_kitchen(self, c, outlet):
        return self.check_kitchen(get_session(self.token()), outlet)

    def route(self, method):
        u = urlparse(self.path)
        self.q = {k: v[0] for k, v in parse_qs(u.query).items()}
        try:
            for meth, rx, fn in ROUTES:
                if meth == method:
                    m = re.match(rx, u.path)
                    if m:
                        return getattr(self, fn)(*m.groups())
            if method == "GET":
                return self.static(u.path)
            raise ApiError(404, "Not found")
        except ApiError as e:
            try:
                self.send_json({"error": e.msg}, e.code)
            except OSError:
                pass
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
            pass
        except OverflowError:
            try:
                self.send_json({"error": "A number in the request is too large"}, 400)
            except OSError:
                pass
        except Exception:
            traceback.print_exc()
            try:
                self.send_json({"error": "Something went wrong"}, 500)
            except OSError:
                pass

    def static(self, path):
        if path.startswith("/api/"):
            raise ApiError(404, "Not found")
        if re.match(r"^/r/[a-z0-9-]+(/\d+)?/?$", path):
            path = "/customer.html"
        elif path == "/":
            path = "/index.html"
        if "\x00" in path or "/." in path:
            raise ApiError(404, "Not found")
        full = os.path.realpath(os.path.join(WEB, path.lstrip("/")))
        if not full.startswith(os.path.realpath(WEB) + os.sep) or not os.path.isfile(full):
            raise ApiError(404, "Not found")
        ctype = FILE_TYPES.get(os.path.splitext(full)[1].lower(), "application/octet-stream")
        if ctype.startswith("text/") or ctype in ("application/json", "image/svg+xml"):
            ctype += "; charset=utf-8"
        with open(full, "rb") as f:
            data = f.read()
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        self.wfile.write(data)

    # --- public API
    def r_outlet(self, slug):
        with db.connect() as c:
            o = get_outlet(c, slug)
            b = get_brand(c, o["brand_slug"])
            self.send_json({"brand": brand_public(b), "outlet": outlet_public(o)})

    def r_menu(self, slug):
        with db.connect() as c:
            o = get_outlet(c, slug)
            self.send_json({"categories": menu_rows(c, o)})

    def r_order_create(self):
        """Dine-in orders from a table QR, and counter sales typed in by signed-in staff."""
        d = self.body()
        slug = text(d.get("outlet"), 80, "outlet", True)
        kind = d.get("kind", "dine_in")
        if kind not in ("dine_in", "takeaway"):
            raise ApiError(400, "kind must be dine_in or takeaway")
        c = db.connect(manual=True)
        try:
            o = get_outlet(c, slug)
            staff = None
            if self.token() is not None:  # a signed-in counter or kitchen screen
                staff = self.need_kitchen(c, o)
            elif kind == "takeaway":  # unpaid takeaway may only come from the counter
                raise ApiError(402, "Please order takeaway at the counter.")
            else:
                ORDER_RATE.hit(self.ip(), "Too many orders from this network. Please ask a waiter.")
            if not o["accepting"]:
                raise ApiError(409, "This restaurant is not taking orders right now")
            spec = validate_order(c, o, d, kind)
            if not staff and not security.table_key_ok(c, o, spec["table"], d.get("key")):
                raise ApiError(403, "Please scan the QR code on your table to order.")
            pay_method = None
            if staff:
                pay_method = d.get("pay_method")
                if pay_method not in (None, "cash", "upi", "card"):
                    raise ApiError(400, "Payment must be cash, UPI or card")
                if kind == "takeaway" and pay_method is None:
                    raise ApiError(400, "Choose how the customer paid")
            now = time.time()
            dup, printed, queued = None, [], []
            with writer() as w:
                if spec["client_key"]:
                    # A retried request (flaky mobile signal, double tap) carries the same key: return the order
                    # that already exists instead of creating a second one.
                    dup = w.execute("SELECT * FROM orders WHERE outlet_id=? AND client_key=?", (o["id"], spec["client_key"])).fetchone()
                if not dup:
                    if not staff:
                        check_limits(w, o, spec, now)
                    oid, printed, queued = insert_order(w, o, spec, now, pay_method=pay_method)
                    if staff:
                        security.log_activity(w, "%s:%s" % (staff["scope"], staff["slug"]), self.ip(), "counter order",
                                              "%s %s total %d %s" % (o["slug"], kind, spec["total"], pay_method or "pay later"))
            row = dup or c.execute("SELECT * FROM orders WHERE id=?", (oid,)).fetchone()
            od = order_dict(c, row, o)
        finally:
            c.close()
        reply = {"public_id": od["public_id"], "token": od["token"], "total": od["total"], "status": od["status"], "eta_seconds": od["eta_seconds"]}
        if dup:  # the retry of an order we already have: same answer, and the kitchen is not told twice
            reply["duplicate"] = True
            return self.send_json(reply, 200)
        after_create(o, od, printed, queued)
        self.send_json(reply, 201)

    # --- takeaway payment: the order is created only after a signed confirmation
    def r_pay_start(self):
        if not PAY_SECRET:
            raise ApiError(404, "Online payment is not connected")
        d = self.body()
        ORDER_RATE.hit(self.ip(), "Too many orders from this network. Please order at the counter.")
        slug = text(d.get("outlet"), 80, "outlet", True)
        c = db.connect(manual=True)
        try:
            o = get_outlet(c, slug)
            if not o["accepting"]:
                raise ApiError(409, "This restaurant is not taking orders right now")
            spec = validate_order(c, o, d, "takeaway")
            phone = clean_phone(d.get("phone"))
            if spec["total"] <= 0:
                raise ApiError(400, "There is nothing to pay for. Please order this at the counter.")
            now = time.time()
            with write_lock_tx(c):
                p = None
                if spec["client_key"]:
                    p = c.execute("SELECT * FROM payments WHERE outlet_id=? AND client_key=?", (o["id"], spec["client_key"])).fetchone()
                if not p:
                    check_limits(c, o, spec, now)
                    ref = "pay_" + secrets.token_urlsafe(12)
                    c.execute("INSERT INTO payments(ref,outlet_id,spec,amount,client_key,created_at) VALUES(?,?,?,?,?,?)",
                              (ref, o["id"], json.dumps({"spec": spec, "phone": phone}, ensure_ascii=False), spec["total"], spec["client_key"], now))
                    p = c.execute("SELECT * FROM payments WHERE ref=?", (ref,)).fetchone()
        finally:
            c.close()
        self.send_json({"payment_ref": p["ref"], "amount": p["amount"], "currency": o["currency"], "status": p["status"],
                        "order": p["order_public_id"]}, 201)

    def r_pay_webhook(self):
        n = self.length()
        self.send_json(process_payment_event(self.rfile.read(n), self.headers.get("X-Pay-Signature", "")))

    def r_pay_status(self, ref):
        with db.connect() as c:
            p = c.execute("SELECT status, amount, order_public_id FROM payments WHERE ref=?", (ref,)).fetchone()
        if not p:
            raise ApiError(404, "Unknown payment")
        self.send_json({"status": p["status"], "amount": p["amount"], "order": p["order_public_id"]})

    # --- token board at the counter (public: token numbers only, no names or phones)
    def r_board(self, slug):
        with db.connect() as c:
            o = get_outlet(c, slug)
            rows = c.execute("""SELECT token, status FROM orders WHERE outlet_id=? AND kind='takeaway' AND status IN ('new','preparing','ready')
                                AND created_at>=? ORDER BY created_at""", (o["id"], day_start())).fetchall()
        self.send_json({"name": o["name"], "orders": [{"token": r["token"], "status": r["status"]} for r in rows]})

    def r_order_get(self, pid):
        with db.connect() as c:
            row = c.execute("SELECT * FROM orders WHERE public_id=?", (pid,)).fetchone()
            if not row:
                raise ApiError(404, "Order not found")
            o = c.execute("""SELECT o.*, b.slug AS brand_slug, b.id AS bid FROM outlets o JOIN brands b ON b.id=o.brand_id
                             WHERE o.id=?""", (row["outlet_id"],)).fetchone()
            self.send_json(order_dict(c, row, o))

    def r_stream(self):
        key = None
        with db.connect() as c:
            if "outlet" in self.q:
                o = get_outlet(c, self.q["outlet"])
                key = self.q.get("key", "")
                self.check_kitchen(SESSIONS.from_stream_key(key), o)
                ch = "outlet:" + o["slug"]
            elif "board" in self.q:
                ch = "board:" + get_outlet(c, self.q["board"])["slug"]
            elif "order" in self.q:
                if not c.execute("SELECT 1 FROM orders WHERE public_id=?", (self.q["order"],)).fetchone():
                    raise ApiError(404, "Order not found")
                ch = "order:" + self.q["order"]
            else:
                raise ApiError(400, "outlet, order or board required")
        if key is None:  # public streams are capped so nobody can tie up the server by opening thousands
            ip = self.ip()
            with STREAM_LOCK:
                if STREAMS.get(ip, 0) >= MAX_PUBLIC_STREAMS_PER_IP or sum(STREAMS.values()) >= MAX_PUBLIC_STREAMS:
                    raise ApiError(429, "Too many live screens open")
                STREAMS[ip] = STREAMS.get(ip, 0) + 1
            try:
                return self.run_stream(ch, None)
            finally:
                with STREAM_LOCK:
                    STREAMS[ip] -= 1
                    if not STREAMS[ip]:
                        del STREAMS[ip]
        return self.run_stream(ch, key)

    def run_stream(self, ch, key):
        q = HUB.subscribe(ch)
        snap = None
        if ch.startswith("order:"):
            # Read the current status AFTER subscribing so nothing that happens in between can be missed.
            with db.connect() as c2:
                row = c2.execute("SELECT status FROM orders WHERE public_id=?", (ch[6:],)).fetchone()
                snap = row["status"] if row else None
        try:
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Accel-Buffering", "no")
            self.end_headers()
            self.wfile.write(b": connected\n\n")
            if snap:
                self.wfile.write(("event: snapshot\ndata: %s\n\n" % json.dumps({"status": snap})).encode())
            self.wfile.flush()
            if snap in ("served", "cancelled"):
                return
            idle = 0
            while True:
                if key is not None and not SESSIONS.from_stream_key(key):
                    break  # signed out, password changed or shift over: stop sending orders to this screen
                try:
                    ev, data = q.get(timeout=5)
                    if key is not None and not SESSIONS.from_stream_key(key):
                        break
                    self.wfile.write(("event: %s\ndata: %s\n\n" % (ev, data)).encode())
                    self.wfile.flush()
                    idle = 0
                    if ch.startswith("order:") and ev == "status" and ('"served"' in data or '"cancelled"' in data):
                        break  # the order is finished: closing here frees this connection's thread straight away
                except queue.Empty:
                    if self.client_gone():  # a closed phone is noticed within 5 s instead of lingering
                        break
                    idle += 1
                    if idle % 3 == 0:
                        self.wfile.write(b": keepalive\n\n")
                        self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError, OSError):
            pass
        finally:
            HUB.unsubscribe(ch, q)

    def client_gone(self):
        try:
            readable, _, _ = select.select([self.connection], [], [], 0)
            return bool(readable) and self.connection.recv(1, socket.MSG_PEEK) == b""
        except (OSError, ValueError):
            return True

    # --- kitchen
    def r_kitchen_orders(self, slug):
        with db.connect() as c:
            o = get_outlet(c, slug)
            self.need_kitchen(c, o)
            rows = c.execute("""SELECT * FROM orders WHERE outlet_id=? AND status IN ('new','preparing','ready')
                                AND created_at>=? ORDER BY created_at""", (o["id"], time.time() - 24 * 3600)).fetchall()
            done = c.execute("SELECT COUNT(*) FROM orders WHERE outlet_id=? AND status='served' AND created_at>=?", (o["id"], day_start())).fetchone()[0]
            slips = c.execute("""SELECT s.*, o.public_id, o.token, o.table_no, o.kind, o.customer_name FROM slips s
                                 JOIN orders o ON o.id=s.order_id WHERE s.outlet_id=? AND s.status IN ('screen','sending','printed','failed')
                                 ORDER BY s.id DESC LIMIT 8""", (o["id"],)).fetchall()
            self.send_json({"orders": [staff_order(c, r, o) for r in rows], "served_today": done, "outlet": outlet_staff(o),
                            "printer": printer_info(c, o), "recent_slips": [slip_dict(s, s) for s in slips]})

    def r_kitchen_settings(self, slug):
        """The auto-accept switch on the kitchen screen."""
        d = self.body()
        if not isinstance(d.get("auto_accept"), bool):
            raise ApiError(400, "auto_accept must be true or false")
        with writer() as c:
            o = get_outlet(c, slug)
            self.need_kitchen(c, o)
            c.execute("UPDATE outlets SET auto_accept=? WHERE id=?", (1 if d["auto_accept"] else 0, o["id"]))
            security.log_activity(c, "staff:" + slug, self.ip(), "auto-accept " + ("on" if d["auto_accept"] else "off"))
        self.send_json({"auto_accept": d["auto_accept"]})

    def r_kitchen_status(self, slug, pid):
        d = self.body()
        new = d.get("status")
        printed, queued = [], []
        refund = False
        with writer() as c:
            o = get_outlet(c, slug)
            self.need_kitchen(c, o)
            r = c.execute("SELECT * FROM orders WHERE public_id=? AND outlet_id=?", (pid, o["id"])).fetchone()
            if not r:
                raise ApiError(404, "Order not found")
            if new not in FLOW.get(r["status"], []):
                raise ApiError(409, "Cannot move from %s to %s" % (r["status"], new))
            now = time.time()
            c.execute("UPDATE orders SET status=?, updated_at=? WHERE id=?", (new, now, r["id"]))
            if new == "preparing":  # accepted by hand (auto-accept off): print now or join the queue
                printed, queued = make_slips(c, r["id"], o, now)
            elif new in ("ready", "cancelled"):  # no point printing a slip for finished or rejected food
                c.execute("UPDATE slips SET status='skipped' WHERE order_id=? AND status='queued'", (r["id"],))
            if new in ("served", "cancelled"):
                c.execute("UPDATE slips SET status='skipped' WHERE order_id=? AND status IN ('queued','failed')", (r["id"],))
            if new == "cancelled":
                if r["status"] in ("new", "preparing"):  # not made yet: the ingredients go back
                    ledger.put_back(c, r["id"], now)
                if r["payment_ref"]:
                    c.execute("UPDATE payments SET status='refund_due' WHERE ref=?", (r["payment_ref"],))
                refund = r["paid_at"] is not None and r["total"] > 0
            order_id, kind, token = r["id"], r["kind"], r["token"]
            if new == "cancelled":
                security.log_activity(c, "staff:" + slug, self.ip(), "order rejected",
                                      "token %d, total %d%s" % (token, r["total"], ", REFUND DUE" if refund else ""))
            r = c.execute("SELECT * FROM orders WHERE id=?", (order_id,)).fetchone()
            od = staff_order(c, r, o)
        if new in ("ready", "cancelled"):
            PRINTER.drop_order(o["id"], order_id)
        for s in queued:
            PRINTER.add(o["id"], s)
        od["refund_due"] = refund
        HUB.publish("outlet:" + slug, "order_update", od)
        if printed:
            release(printed)
        if kind == "takeaway":
            HUB.publish("board:" + slug, "board", {"token": token, "status": new})
        self.send_json(od)

    # --- owner admin (brand level)
    def r_admin_overview(self, brand):
        self.need("admin", brand)
        with db.connect() as c:
            b = get_brand(c, brand)
            start = day_start()
            outlets = []
            for o in c.execute("SELECT * FROM outlets WHERE brand_id=? ORDER BY id", (b["id"],)):
                n, s = c.execute("SELECT COUNT(*), COALESCE(SUM(total),0) FROM orders WHERE outlet_id=? AND created_at>=? AND status!='cancelled'",
                                 (o["id"], start)).fetchone()
                live = c.execute("SELECT COUNT(*) FROM orders WHERE outlet_id=? AND status IN ('new','preparing','ready')", (o["id"],)).fetchone()[0]
                d = outlet_staff(o)
                d.update({"orders_today": n, "sales_today": s, "live": live, "unpaid_total": sum(x["total"] for x in ledger.unpaid(c, o["id"])),
                          "low_stock": [x["name"] for x in ledger.low_stock(c, b["id"], o["id"])]})
                outlets.append(d)
            top = c.execute("""SELECT i.names, SUM(l.qty) AS q FROM order_lines l JOIN orders o ON o.id=l.order_id
                               JOIN items i ON i.id=l.item_id JOIN outlets ou ON ou.id=o.outlet_id
                               WHERE ou.brand_id=? AND o.created_at>=? AND o.status!='cancelled'
                               GROUP BY i.id ORDER BY q DESC LIMIT 5""", (b["id"], start)).fetchall()
            self.send_json({"brand": brand_public(b), "outlets": outlets,
                            "top_items": [{"names": json.loads(t["names"]), "qty": t["q"]} for t in top]})

    def r_admin_menu(self, brand):
        self.need("admin", brand)
        with db.connect() as c:
            o = get_outlet(c, self.q.get("outlet", ""))
            if o["brand_slug"] != brand:
                raise ApiError(403, "Outlet belongs to another brand")
            self.send_json({"categories": menu_rows(c, o, admin=True), "outlet": outlet_staff(o)})

    def clean_names(self, brand_row, names, required):
        langs = json.loads(brand_row["langs"])
        if not isinstance(names, dict):
            raise ApiError(400, "names must be an object")
        out = {}
        for k, v in names.items():
            if k not in langs:
                raise ApiError(400, "Language not enabled: %s" % k)
            v = text(v, 120, "name")
            if v:
                out[k] = v
        if required and brand_row["default_lang"] not in out:
            raise ApiError(400, "A name in %s is required" % brand_row["default_lang"])
        return out

    def r_admin_item_create(self, brand):
        self.need("admin", brand)
        d = self.body()
        with writer() as c:
            b = get_brand(c, brand)
            cat = c.execute("SELECT id FROM categories WHERE brand_id=? AND slug=?", (b["id"], text(d.get("category"), 60, "category", True))).fetchone()
            if not cat:
                raise ApiError(400, "Unknown category")
            names = self.clean_names(b, d.get("names"), True)
            descs = self.clean_names(b, d.get("descs") or {}, False)
            price = as_int(d.get("price"), 0, 100000, "price")
            base = re.sub(r"[^a-z0-9]+", "-", (names.get("en") or next(iter(names.values()))).lower()).strip("-") or "item"
            slug, n = base, 2
            while c.execute("SELECT 1 FROM items WHERE brand_id=? AND slug=?", (b["id"], slug)).fetchone():
                slug, n = "%s-%d" % (base, n), n + 1
            sort = c.execute("SELECT COALESCE(MAX(sort),0)+1 FROM items WHERE brand_id=?", (b["id"],)).fetchone()[0]
            cur = c.execute("INSERT INTO items(brand_id,category_id,slug,sort,price,veg,tag,names,descs) VALUES(?,?,?,?,?,?,?,?,?)",
                            (b["id"], cat["id"], slug, sort, price, 1 if d.get("veg", True) else 0,
                             text(d.get("tag"), 30, "tag") or None, json.dumps(names, ensure_ascii=False), json.dumps(descs, ensure_ascii=False)))
            security.log_activity(c, "admin:" + brand, self.ip(), "dish added", "%s, price %d" % (names.get("en", slug), price))
        self.send_json({"id": cur.lastrowid}, 201)

    def r_admin_item_update(self, brand, iid):
        self.need("admin", brand)
        d = self.body()
        with writer() as c:
            b = get_brand(c, brand)
            r = c.execute("SELECT * FROM items WHERE id=? AND brand_id=?", (int(iid), b["id"])).fetchone()
            if not r:
                raise ApiError(404, "Item not found")
            names = json.loads(r["names"])
            descs = json.loads(r["descs"])
            if "names" in d:
                names = self.clean_names(b, d["names"], True)
            if "descs" in d:
                descs = self.clean_names(b, d["descs"], False)
            price = as_int(d["price"], 0, 100000, "price") if "price" in d else r["price"]
            veg = (1 if d["veg"] else 0) if "veg" in d else r["veg"]
            tag = (text(d["tag"], 30, "tag") or None) if "tag" in d else r["tag"]
            if "instant" in d:
                c.execute("UPDATE items SET instant=? WHERE id=?", (1 if d["instant"] else 0, r["id"]))
            if "archived" in d:  # "remove dish": hidden from the menu, kept for old sales records
                c.execute("UPDATE items SET archived=? WHERE id=?", (1 if d["archived"] else 0, r["id"]))
            security.log_activity(c, "admin:" + brand, self.ip(), "dish removed" if d.get("archived") else "dish changed",
                                  "%s, price %d -> %d" % (names.get("en", "?"), r["price"], price))
            c.execute("UPDATE items SET names=?, descs=?, price=?, veg=?, tag=? WHERE id=?",
                      (json.dumps(names, ensure_ascii=False), json.dumps(descs, ensure_ascii=False), price, veg, tag, r["id"]))
        self.send_json({"ok": True})

    def r_admin_outlet_item(self, brand):
        self.need("admin", brand)
        d = self.body()
        with writer() as c:
            o = get_outlet(c, self.q.get("outlet", ""))
            if o["brand_slug"] != brand:
                raise ApiError(403, "Outlet belongs to another brand")
            iid = as_int(d.get("item_id"), 1, 10**9, "item")
            if not c.execute("SELECT 1 FROM items WHERE id=? AND brand_id=?", (iid, o["bid"])).fetchone():
                raise ApiError(404, "Item not found")
            price = d.get("price")
            price = None if price is None else as_int(price, 0, 100000, "price")
            avail = 1 if d.get("available", True) else 0
            c.execute("""INSERT INTO outlet_items(outlet_id,item_id,price,available) VALUES(?,?,?,?)
                         ON CONFLICT(outlet_id,item_id) DO UPDATE SET price=excluded.price, available=excluded.available""",
                      (o["id"], iid, price, avail))
            security.log_activity(c, "admin:" + brand, self.ip(), "outlet price/stock", "item %d price %s %s" % (iid, price, "in stock" if avail else "OUT"))
        self.send_json({"ok": True})

    def r_admin_outlet(self, brand, slug):
        self.need("admin", brand)
        d = self.body()
        with writer() as c:
            o = get_outlet(c, slug)
            if o["brand_slug"] != brand:
                raise ApiError(403, "Outlet belongs to another brand")
            b = get_brand(c, brand)
            tables = as_int(d["tables"], 1, 200, "tables") if "tables" in d else o["tables_count"]
            accepting = (1 if d["accepting"] else 0) if "accepting" in d else o["accepting"]
            kl = d.get("kitchen_lang", o["kitchen_lang"])
            if kl not in json.loads(b["langs"]):
                raise ApiError(400, "Language not enabled")
            auto = (1 if d["auto_accept"] else 0) if "auto_accept" in d else o["auto_accept"]
            gap = d.get("print_gap", o["print_gap"])
            if isinstance(gap, bool) or not isinstance(gap, (int, float)) or not 0 <= gap <= 120:
                raise ApiError(400, "print_gap must be between 0 and 120 seconds")
            mode = d.get("print_order", o["print_order"])
            if mode not in ("fifo", "small_first"):
                raise ApiError(400, "print_order must be fifo or small_first")
            c.execute("UPDATE outlets SET tables_count=?, accepting=?, kitchen_lang=?, auto_accept=?, print_gap=?, print_order=? WHERE id=?",
                      (tables, accepting, kl, auto, gap, mode, o["id"]))
            security.log_activity(c, "admin:" + brand, self.ip(), "outlet settings",
                                  "tables %d, taking orders %d, auto-accept %d, gap %s" % (tables, accepting, auto, gap))
        PRINTER.configure(o["id"], gap, mode)
        self.send_json({"ok": True})


class Server(ThreadingHTTPServer):
    # The default waiting line for new connections is only 5 deep, so a rush of guests scanning at once had
    # connections dropped and retried 1 to 3 seconds later. 2048 lets a whole restaurant chain arrive together.
    # On Windows a plain number is quietly capped far lower; SOMAXCONN asks for the largest queue the system allows.
    request_queue_size = socket.SOMAXCONN if sys.platform == "win32" else 2048
    daemon_threads = True


S = r"([a-z0-9-]+)"
ROUTES = STORE_ROUTES + PRINT_ROUTES + BUSINESS_ROUTES + [
    ("GET", r"^/api/outlet/" + S + "$", "r_outlet"),
    ("GET", r"^/api/menu/" + S + "$", "r_menu"),
    ("POST", r"^/api/orders$", "r_order_create"),
    ("GET", r"^/api/orders/([A-Za-z0-9_-]+)$", "r_order_get"),
    ("GET", r"^/api/stream$", "r_stream"),
    ("POST", r"^/api/pay/start$", "r_pay_start"),
    ("POST", r"^/api/pay/webhook$", "r_pay_webhook"),
    ("GET", r"^/api/pay/(pay_[A-Za-z0-9_-]+)$", "r_pay_status"),
    ("GET", r"^/api/board/([a-z0-9-]+)$", "r_board"),
    ("PUT", r"^/api/kitchen/([a-z0-9-]+)/settings$", "r_kitchen_settings"),
    ("GET", r"^/api/kitchen/" + S + "/orders$", "r_kitchen_orders"),
    ("POST", r"^/api/kitchen/" + S + r"/orders/([A-Za-z0-9_-]+)/status$", "r_kitchen_status"),
    ("GET", r"^/api/admin/" + S + "/overview$", "r_admin_overview"),
    ("GET", r"^/api/admin/" + S + "/menu$", "r_admin_menu"),
    ("POST", r"^/api/admin/" + S + "/items$", "r_admin_item_create"),
    ("PUT", r"^/api/admin/" + S + r"/items/(\d{1,9})$", "r_admin_item_update"),
    ("PUT", r"^/api/admin/" + S + "/outlet-items$", "r_admin_outlet_item"),
    ("PUT", r"^/api/admin/" + S + "/outlets/" + S + "$", "r_admin_outlet"),
]


def sheet_saver():
    """Saves yesterday's order sheet, and last month's, into data/reports. Checks every hour, so a computer
    that was switched off at midnight catches up when it starts."""
    while True:
        try:
            for path in ledger.auto_save(reports_dir()):
                print("order sheet saved: %s" % path)
        except Exception:
            traceback.print_exc()
        time.sleep(3600)


def reports_dir():
    return os.path.join(os.path.dirname(os.path.abspath(db.DB_PATH)), "reports")


def maintenance():
    """Once a day: back up the store and delete old customer phone numbers."""
    while True:
        try:
            with db.connect() as c:
                empty = store.setup_needed(c)
            if not empty:
                with writer() as c:
                    security.purge_old_phones(c)
                security.make_backup()
        except Exception:
            traceback.print_exc()
        time.sleep(24 * 3600)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--port", type=int, default=8000)
    ap.add_argument("--lan", action="store_true", help="listen on all network interfaces (phones and tablets on your Wi-Fi)")
    ap.add_argument("--cert", help="HTTPS certificate file (PEM)")
    ap.add_argument("--key", help="HTTPS private key file (PEM)")
    a = ap.parse_args()
    if bool(a.cert) != bool(a.key):
        ap.error("--cert and --key go together")
    db.init()
    load_printer()
    PrintRoutes.pacer, PrintRoutes.dispatch = PRINTER, DISPATCH
    host = "0.0.0.0" if a.lan else "127.0.0.1"
    srv = Server((host, a.port), Handler)
    srv.is_https = bool(a.cert)
    if a.cert:
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        ctx.minimum_version = ssl.TLSVersion.TLSv1_2
        ctx.load_cert_chain(a.cert, a.key)
        srv.socket = ctx.wrap_socket(srv.socket, server_side=True, do_handshake_on_connect=False)
    scheme = "https" if a.cert else "http"
    print("Store server running")
    print("  this computer : %s://localhost:%d" % (scheme, a.port))
    if a.lan:
        print("  store Wi-Fi   : %s://%s:%d" % (scheme, store.lan_ip(), a.port))
        if not a.cert:
            print("  NOTE: without HTTPS, passwords can be read by someone else on the same Wi-Fi. Use a private staff network or --cert/--key.")
    with db.connect() as c:
        if store.setup_needed(c):
            code = "".join(secrets.choice("ABCDEFGHJKLMNPQRSTUVWXYZ23456789") for _ in range(10))
            store.SETUP["code"] = code
            print("  FIRST-TIME SETUP: open %s://localhost:%d/setup.html and enter the code %s-%s" % (scheme, a.port, code[:5], code[5:]))
    print("  online payment: %s" % ("connected (signed confirmations only)" if PAY_SECRET else "off - takeaway is paid at the counter"))
    sys.stdout.flush()
    threading.Thread(target=maintenance, daemon=True).start()
    threading.Thread(target=sheet_saver, daemon=True).start()
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\nbye")


if __name__ == "__main__":
    main()
