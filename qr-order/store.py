"""Running a real store: first-time setup, staff sign-in, owner security tools, table QR links, activity and backups.
These are request handlers mixed into the server's Handler class."""
import hmac
import json
import os
import re
import secrets
import socket

import db
import security
from core import ApiError, as_int, get_brand, get_outlet, text, writer

SESSIONS = security.Sessions()
THROTTLE = security.Throttle()
LOGIN_RATE = security.RateLimit(int(os.environ.get("QRO_LOGIN_RATE", "30")))
SETUP = {"code": None}  # printed in the server window while the store has not been set up
THEMES = ("bombay", "darbar")
LANGS = ("en", "hi", "mr")
_DUMMY_HASH = db.hash_pin(secrets.token_hex(16))  # checked for unknown accounts, so timing does not reveal which exist


def get_session(tok):
    return SESSIONS.get(tok)


def setup_needed(c):
    return c.execute("SELECT COUNT(*) FROM brands").fetchone()[0] == 0


def slugify(s, fallback):
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")[:30].strip("-") or fallback


def lan_ip():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("10.255.255.255", 1))  # no packet is sent
        return s.getsockname()[0]
    except OSError:
        return "127.0.0.1"
    finally:
        s.close()


class StoreRoutes:
    def ip(self):
        return self.client_address[0]

    def owned_outlet(self, c, brand, slug):
        o = get_outlet(c, slug)
        if o["brand_slug"] != brand:
            raise ApiError(403, "Outlet belongs to another restaurant")
        return o

    # ------------------------------------------------------------ public
    def r_health(self):
        self.send_json({"ok": True})

    def r_store(self):
        """Just enough for the staff home page. Nothing about settings or sales."""
        with db.connect() as c:
            if setup_needed(c):
                return self.send_json({"setup_needed": True})
            b = c.execute("SELECT * FROM brands ORDER BY id LIMIT 1").fetchone()
            outlets = [{"slug": o["slug"], "name": o["name"], "takeaway": bool(o["takeaway"])}
                       for o in c.execute("SELECT slug,name,takeaway FROM outlets WHERE brand_id=? ORDER BY id", (b["id"],))]
            sample = c.execute("SELECT 1 FROM meta WHERE key='sample_data'").fetchone() is not None
        self.send_json({"setup_needed": False, "name": b["name"], "brand": b["slug"], "outlets": outlets, "sample": sample})

    def r_table_check(self, slug, table):
        with db.connect() as c:
            o = get_outlet(c, slug)
            ok = 1 <= int(table) <= o["tables_count"] and security.table_key_ok(c, o, int(table), self.q.get("k", ""))
        self.send_json({"valid": bool(ok)})

    # ------------------------------------------------------------ first-time setup
    def r_setup(self):
        d = self.body()
        LOGIN_RATE.hit(self.ip(), "Too many tries. Wait a minute.")
        with db.connect() as c:
            if not setup_needed(c):
                raise ApiError(409, "This store is already set up")
        THROTTLE.check(self.ip(), "setup")
        code = text(d.get("code"), 40, "setup code", True).upper().replace("-", "").replace(" ", "")
        if not SETUP["code"] or not hmac.compare_digest(code.encode(), SETUP["code"].encode()):
            THROTTLE.failed(self.ip(), "setup")
            raise ApiError(401, "Wrong setup code. It is shown in the window where the server was started.")
        name = text(d.get("restaurant"), 60, "restaurant name", True)
        theme = d.get("theme")
        if theme not in THEMES:
            raise ApiError(400, "Choose a look for the menu")
        area = text(d.get("outlet"), 40, "outlet name", True)
        city = text(d.get("city"), 40, "city", True)
        tables = as_int(d.get("tables"), 1, 200, "number of tables")
        langs = d.get("langs") or ["en"]
        if not isinstance(langs, list) or "en" not in langs or any(x not in LANGS for x in langs):
            raise ApiError(400, "English must be one of the languages")
        password = security.check_new_password(d.get("owner_password"))
        pin = security.check_new_pin(d.get("staff_pin"))
        password_hash, pin_hash = db.hash_pin(password), db.hash_pin(pin)
        brand_slug = slugify(name, "store")
        outlet_slug = "%s-%s" % (brand_slug, slugify(area, "main"))
        j = lambda v: json.dumps(v, ensure_ascii=False)
        with writer() as c:
            if not setup_needed(c):
                raise ApiError(409, "This store is already set up")
            bid = c.execute("INSERT INTO brands(slug,name,theme,tagline,langs,default_lang,admin_pin_hash) VALUES(?,?,?,?,?,?,?)",
                            (brand_slug, name, theme, text(d.get("tagline"), 80, "tagline"), j(list(dict.fromkeys(langs))), "en", password_hash)).lastrowid
            c.execute("INSERT INTO outlets(brand_id,slug,name,city,country,currency,tables_count,kitchen_lang,kitchen_pin_hash,takeaway) VALUES(?,?,?,?,?,?,?,?,?,?)",
                      (bid, outlet_slug, "%s - %s" % (name, area), city, "India", "INR", tables, "en", pin_hash, 0 if d.get("takeaway") is False else 1))
            c.execute("INSERT OR REPLACE INTO meta(key,value) VALUES('store_secret',?)", (secrets.token_hex(32),))
            if d.get("starter_menu") is True:
                db.starter_menu(c, bid, langs)
            security.log_activity(c, "owner", self.ip(), "store set up", name)
        SETUP["code"] = None
        self.send_json({"brand": brand_slug, "outlet": outlet_slug}, 201)

    # ------------------------------------------------------------ sign in and out
    def r_login(self):
        d = self.body()
        LOGIN_RATE.hit(self.ip(), "Too many sign-in tries. Wait a minute.")
        scope, slug = d.get("scope"), text(d.get("slug"), 80, "slug", True)
        pin = d.get("pin")
        if scope not in ("kitchen", "admin") or not isinstance(pin, str) or not 1 <= len(pin) <= 128:
            raise ApiError(400, "Bad sign-in request")
        account = "%s:%s" % (scope, slug)
        THROTTLE.check(self.ip(), account)
        sql = "SELECT kitchen_pin_hash AS h FROM outlets WHERE slug=?" if scope == "kitchen" else "SELECT admin_pin_hash AS h FROM brands WHERE slug=?"
        with db.connect() as c:
            r = c.execute(sql, (slug,)).fetchone()
        ok = db.check_pin(pin, r["h"] if r else _DUMMY_HASH) and bool(r)
        if r:
            with writer() as c:
                security.log_activity(c, account, self.ip(), "signed in" if ok else "WRONG sign-in")
        if not ok:
            THROTTLE.failed(self.ip(), account)
            raise ApiError(401, "Wrong PIN or password")
        token, key = SESSIONS.create(scope, slug)
        self.send_json({"token": token, "stream_key": key})

    def r_logout(self):
        s = SESSIONS.get(self.token())
        SESSIONS.revoke(self.token())
        if s:
            with writer() as c:
                security.log_activity(c, "%s:%s" % (s["scope"], s["slug"]), self.ip(), "signed out")
        self.send_json({"ok": True})

    # ------------------------------------------------------------ owner security
    def confirm_owner(self, brand, password):
        """Sensitive actions ask for the owner password again, with the same lockout as signing in."""
        account = "admin:" + brand
        THROTTLE.check(self.ip(), account)
        with db.connect() as c:
            b = get_brand(c, brand)
        if not isinstance(password, str) or len(password) > 128 or not db.check_pin(password, b["admin_pin_hash"]):
            THROTTLE.failed(self.ip(), account)
            raise ApiError(403, "Your current owner password is wrong")

    def r_admin_password(self, brand):
        self.need("admin", brand)
        d = self.body()
        self.confirm_owner(brand, d.get("current"))
        new_hash = db.hash_pin(security.check_new_password(d.get("new")))
        with writer() as c:
            c.execute("UPDATE brands SET admin_pin_hash=? WHERE slug=?", (new_hash, brand))
            security.log_activity(c, "admin:" + brand, self.ip(), "owner password changed")
        SESSIONS.revoke_account("admin", brand)  # every owner screen has to sign in again
        self.send_json({"ok": True})

    def r_admin_staff_pin(self, brand, slug):
        self.need("admin", brand)
        d = self.body()
        self.confirm_owner(brand, d.get("current_password"))
        new_hash = db.hash_pin(security.check_new_pin(d.get("pin")))
        with writer() as c:
            o = self.owned_outlet(c, brand, slug)
            c.execute("UPDATE outlets SET kitchen_pin_hash=? WHERE id=?", (new_hash, o["id"]))
            security.log_activity(c, "admin:" + brand, self.ip(), "staff PIN changed", slug)
        SESSIONS.revoke_account("kitchen", slug)  # old kitchen and counter screens are signed out
        self.send_json({"ok": True})

    def r_admin_qr(self, brand):
        self.need("admin", brand)
        with db.connect() as c:
            o = self.owned_outlet(c, brand, self.q.get("outlet", ""))
            secret = security.store_secret(c)
        self.send_json({"tables": [{"table": n, "path": "/r/%s/%d?k=%s" % (o["slug"], n, security.table_key(secret, o["slug"], n, o["qr_version"]))}
                                   for n in range(1, o["tables_count"] + 1)],
                        "lan_ip": lan_ip(), "port": self.server.server_port, "https": self.server.is_https})

    def r_admin_new_qr(self, brand, slug):
        self.need("admin", brand)
        self.body()
        with writer() as c:
            o = self.owned_outlet(c, brand, slug)
            c.execute("UPDATE outlets SET qr_version=qr_version+1 WHERE id=?", (o["id"],))
            security.log_activity(c, "admin:" + brand, self.ip(), "new table QR codes", slug)
        self.send_json({"ok": True})

    def r_admin_activity(self, brand):
        self.need("admin", brand)
        with db.connect() as c:
            rows = c.execute("SELECT at, actor, ip, action, detail FROM activity ORDER BY id DESC LIMIT 200").fetchall()
        self.send_json({"activity": [dict(r) for r in rows]})

    def r_admin_backup(self, brand):
        self.need("admin", brand)
        self.body()
        name = security.make_backup()
        with writer() as c:
            security.log_activity(c, "admin:" + brand, self.ip(), "backup made", name)
        self.send_json({"name": name})

    def r_admin_backup_download(self, brand):
        """The file holds customer data and password fingerprints, so the owner password is asked again."""
        self.need("admin", brand)
        d = self.body()
        self.confirm_owner(brand, d.get("password"))
        name = security.make_backup()
        with open(os.path.join(security.backup_dir(), name), "rb") as f:
            data = f.read()
        with writer() as c:
            security.log_activity(c, "admin:" + brand, self.ip(), "backup DOWNLOADED", name)
        self.send_response(200)
        self.send_header("Content-Type", "application/octet-stream")
        self.send_header("Content-Disposition", 'attachment; filename="%s"' % name)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    # ------------------------------------------------------------ menu sections
    def r_admin_category_create(self, brand):
        self.need("admin", brand)
        d = self.body()
        with writer() as c:
            b = get_brand(c, brand)
            names = self.clean_names(b, d.get("names"), True)
            base = slugify(names.get("en", "section"), "section")
            slug, n = base, 2
            while slug == "all" or c.execute("SELECT 1 FROM categories WHERE brand_id=? AND slug=?", (b["id"], slug)).fetchone():
                slug, n = "%s-%d" % (base, n), n + 1
            sort = c.execute("SELECT COALESCE(MAX(sort),-1)+1 FROM categories WHERE brand_id=?", (b["id"],)).fetchone()[0]
            if sort >= 60:
                raise ApiError(400, "Too many menu sections")
            c.execute("INSERT INTO categories(brand_id,slug,sort,names) VALUES(?,?,?,?)", (b["id"], slug, sort, json.dumps(names, ensure_ascii=False)))
            security.log_activity(c, "admin:" + brand, self.ip(), "menu section added", names.get("en", slug))
        self.send_json({"slug": slug}, 201)


STORE_ROUTES = [
    ("GET", r"^/api/health$", "r_health"),
    ("GET", r"^/api/store$", "r_store"),
    ("GET", r"^/api/table/([a-z0-9-]+)/(\d{1,4})$", "r_table_check"),
    ("POST", r"^/api/setup$", "r_setup"),
    ("POST", r"^/api/login$", "r_login"),
    ("POST", r"^/api/logout$", "r_logout"),
    ("POST", r"^/api/admin/([a-z0-9-]+)/password$", "r_admin_password"),
    ("POST", r"^/api/admin/([a-z0-9-]+)/outlets/([a-z0-9-]+)/staff-pin$", "r_admin_staff_pin"),
    ("GET", r"^/api/admin/([a-z0-9-]+)/qr$", "r_admin_qr"),
    ("POST", r"^/api/admin/([a-z0-9-]+)/outlets/([a-z0-9-]+)/new-qr$", "r_admin_new_qr"),
    ("GET", r"^/api/admin/([a-z0-9-]+)/activity$", "r_admin_activity"),
    ("POST", r"^/api/admin/([a-z0-9-]+)/backup$", "r_admin_backup"),
    ("POST", r"^/api/admin/([a-z0-9-]+)/backup/download$", "r_admin_backup_download"),
    ("POST", r"^/api/admin/([a-z0-9-]+)/categories$", "r_admin_category_create"),
]
