"""Handlers for money (unpaid bills, refunds), stock and recipes, reports and Excel order sheets.
Staff may take payments at their own outlet. Everything about costs, margins and sheets is owner only."""
import json
import re
import time
from urllib.parse import quote, unquote

import db
import ledger
import security
import xlsx
from core import ApiError, as_int, get_brand, get_outlet, text, writer

METHODS = ("cash", "upi", "card")
MAX_INGREDIENTS = 300
DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def number(v, low, high, field):
    """A quantity or amount of money: a real number inside the limits (up to 3 decimals are kept)."""
    if isinstance(v, bool) or not isinstance(v, (int, float)) or not low <= v <= high:  # also refuses NaN and infinity
        raise ApiError(400, "%s must be a number from %s to %s" % (field, low, high))
    return v


def thousandths(v, field, low=0):
    return int(round(number(v, low, 10_000_000, field) * 1000))


def period(q):
    first, last = q.get("from", ""), q.get("to", "")
    if not DATE.match(first) or not DATE.match(last):
        raise ApiError(400, "from and to must be dates like 2026-01-31")
    try:
        start, end = ledger.day_bounds(first, last)
    except (ValueError, OverflowError):
        raise ApiError(400, "That is not a real date")
    if end <= start:
        raise ApiError(400, "The first date is after the last date")
    if end - start > 367 * 86400:
        raise ApiError(400, "Choose at most one year at a time")
    return first, last


class BusinessRoutes:
    # ------------------------------------------------------------ bills (staff)
    def bill_outlet(self, c, slug):
        o = get_outlet(c, slug)
        self.need_kitchen(c, o)
        return o

    def bill_order(self, c, o, pid):
        r = c.execute("SELECT * FROM orders WHERE public_id=? AND outlet_id=?", (pid, o["id"])).fetchone()
        if not r:
            raise ApiError(404, "Order not found")
        return r

    def r_bills(self, slug):
        with db.connect() as c:
            o = self.bill_outlet(c, slug)
            low = [{"name": s["name"], "unit": s["unit"], "quantity": s["quantity"], "status": s["status"]} for s in ledger.low_stock(c, o["bid"], o["id"])]
            self.send_json({"unpaid": ledger.unpaid(c, o["id"]), "refunds": ledger.refunds_due(c, o["id"]), "low_stock": low})

    def r_bill_pay(self, slug, pid):
        method = self.body().get("method")
        if method not in METHODS:
            raise ApiError(400, "method must be cash, upi or card")
        with writer() as c:
            o = self.bill_outlet(c, slug)
            r = self.bill_order(c, o, pid)
            if r["status"] == "cancelled":
                raise ApiError(409, "That order was rejected: do not take money for it")
            if r["paid_at"] is not None:
                raise ApiError(409, "That bill is already paid")
            c.execute("UPDATE orders SET paid_at=?, pay_method=? WHERE id=?", (time.time(), method, r["id"]))
            security.log_activity(c, "staff:" + slug, self.ip(), "bill paid", "token %d, %d, %s" % (r["token"], r["total"], method))
        self.send_json({"ok": True})

    def r_bill_refunded(self, slug, pid):
        self.body()
        with writer() as c:
            o = self.bill_outlet(c, slug)
            r = self.bill_order(c, o, pid)
            if r["status"] != "cancelled" or r["paid_at"] is None or r["refunded_at"] is not None:
                raise ApiError(409, "No money is waiting to be returned for that order")
            c.execute("UPDATE orders SET refunded_at=? WHERE id=?", (time.time(), r["id"]))
            security.log_activity(c, "staff:" + slug, self.ip(), "money returned", "token %d, %d" % (r["token"], r["total"]))
        self.send_json({"ok": True})

    # ------------------------------------------------------------ correcting a payment (owner only)
    def owner_outlet(self, c, brand):
        o = get_outlet(c, self.q.get("outlet", ""))
        if o["brand_slug"] != brand:
            raise ApiError(403, "Outlet belongs to another restaurant")
        return o

    def r_admin_payments(self, brand):
        self.need("admin", brand)
        with db.connect() as c:
            o = self.owner_outlet(c, brand)
            rows = c.execute("SELECT * FROM orders WHERE outlet_id=? AND paid_at IS NOT NULL ORDER BY paid_at DESC LIMIT 50", (o["id"],)).fetchall()
            self.send_json({"paid": [ledger.bill(r) for r in rows], "unpaid": ledger.unpaid(c, o["id"])})

    def r_admin_payment_undo(self, brand):
        """Staff cannot take a payment back (that would let cash disappear). The owner can, and it is logged."""
        self.need("admin", brand)
        d = self.body()
        with writer() as c:
            o = self.owner_outlet(c, brand)
            r = self.bill_order(c, o, text(d.get("order"), 40, "order", True))
            if r["paid_at"] is None or r["payment_ref"]:
                raise ApiError(409, "That payment cannot be undone here")
            c.execute("UPDATE orders SET paid_at=NULL, pay_method=NULL, refunded_at=NULL WHERE id=?", (r["id"],))
            security.log_activity(c, "admin:" + brand, self.ip(), "payment UNDONE", "token %d, %d, was %s" % (r["token"], r["total"], r["pay_method"]))
        self.send_json({"ok": True})

    # ------------------------------------------------------------ stock (owner only)
    def ingredient(self, c, brand_id, iid):
        iid = as_int(iid, 1, 10 ** 12, "ingredient")
        r = c.execute("SELECT * FROM ingredients WHERE id=? AND brand_id=? AND archived=0", (iid, brand_id)).fetchone()
        if not r:
            raise ApiError(404, "Ingredient not found")
        return r

    def r_admin_stock(self, brand):
        self.need("admin", brand)
        with db.connect() as c:
            o = self.owner_outlet(c, brand)
            dishes = []
            for i in c.execute("""SELECT i.id, i.names, i.price, oi.price AS here FROM items i LEFT JOIN outlet_items oi ON oi.item_id=i.id AND oi.outlet_id=?
                                  WHERE i.brand_id=? AND i.archived=0 ORDER BY i.category_id, i.sort, i.id""", (o["id"], o["bid"])).fetchall():
                recipe = [{"id": r["ingredient_id"], "qty": r["qty"] / 1000.0} for r in c.execute("SELECT * FROM recipes WHERE item_id=?", (i["id"],))]
                names = json.loads(i["names"])
                price = i["here"] if i["here"] is not None else i["price"]
                cost = ledger.dish_cost(c, o["id"], i["id"])
                dishes.append({"id": i["id"], "name": names.get("en") or next(iter(names.values()), "?"), "price": price, "recipe": recipe,
                               "cost": ledger.money(cost), "margin": ledger.money(None if cost is None else price - cost)})
            moves = c.execute("""SELECT m.at, m.delta, m.kind, m.paid, m.actor, m.note, i.name, i.unit, ord.token FROM stock_moves m
                                 JOIN ingredients i ON i.id=m.ingredient_id LEFT JOIN orders ord ON ord.id=m.order_id
                                 WHERE m.outlet_id=? ORDER BY m.id DESC LIMIT 60""", (o["id"],)).fetchall()
            self.send_json({"ingredients": ledger.stock_list(c, o["bid"], o["id"]), "dishes": dishes,
                            "moves": [{"at": m["at"], "name": m["name"], "unit": m["unit"], "change": m["delta"] / 1000.0, "kind": m["kind"],
                                       "paid": m["paid"], "token": m["token"], "note": m["note"] or ""} for m in moves]})

    def r_admin_ingredient_create(self, brand):
        self.need("admin", brand)
        d = self.body()
        name = text(d.get("name"), 60, "name", True)
        if d.get("unit") not in ledger.UNITS:
            raise ApiError(400, "unit must be g, ml or pcs")
        with writer() as c:
            b = get_brand(c, brand)
            if c.execute("SELECT COUNT(*) FROM ingredients WHERE brand_id=? AND archived=0", (b["id"],)).fetchone()[0] >= MAX_INGREDIENTS:
                raise ApiError(409, "Too many ingredients")
            if c.execute("SELECT 1 FROM ingredients WHERE brand_id=? AND archived=0 AND name=? COLLATE NOCASE", (b["id"], name)).fetchone():
                raise ApiError(409, "That ingredient is already in the list")
            iid = c.execute("INSERT INTO ingredients(brand_id,name,unit) VALUES(?,?,?)", (b["id"], name, d["unit"])).lastrowid
            security.log_activity(c, "admin:" + brand, self.ip(), "ingredient added", name)
        self.send_json({"id": iid}, 201)

    def r_admin_ingredient_update(self, brand, iid):
        """Rename or remove. The unit cannot change: that would silently change every recipe and quantity."""
        self.need("admin", brand)
        d = self.body()
        with writer() as c:
            b = get_brand(c, brand)
            r = self.ingredient(c, b["id"], int(iid))
            if d.get("archived") is True:
                used = c.execute("SELECT COUNT(*) FROM recipes rc JOIN items i ON i.id=rc.item_id WHERE rc.ingredient_id=? AND i.archived=0", (r["id"],)).fetchone()[0]
                if used:
                    raise ApiError(409, "%d dish(es) still use it. Take it out of those dishes first." % used)
                c.execute("UPDATE ingredients SET archived=1 WHERE id=?", (r["id"],))
                security.log_activity(c, "admin:" + brand, self.ip(), "ingredient removed", r["name"])
            else:
                name = text(d.get("name"), 60, "name", True)
                c.execute("UPDATE ingredients SET name=? WHERE id=?", (name, r["id"]))
        self.send_json({"ok": True})

    def r_admin_stock_move(self, brand):
        """{ingredient_id, action: purchase|waste|count, qty, paid?, note?}"""
        self.need("admin", brand)
        d = self.body()
        action = d.get("action")
        if action not in ("purchase", "waste", "count"):
            raise ApiError(400, "action must be purchase, waste or count")
        qty = thousandths(d.get("qty"), "qty")
        if qty == 0 and action != "count":
            raise ApiError(400, "qty must be more than zero")
        paid = None
        if action == "purchase" and d.get("paid") is not None:
            paid = number(d.get("paid"), 0, 100_000_000, "paid")
        note = text(d.get("note"), 120, "note")
        with writer() as c:
            o = self.owner_outlet(c, brand)
            ing = self.ingredient(c, o["bid"], d.get("ingredient_id"))
            s = ledger.stock_row(c, o["id"], ing["id"])
            cost = s["cost"]
            if action == "purchase":
                if paid is not None:  # average the new price with what is still on the shelf
                    unit_price = paid / (qty / 1000.0)
                    have = max(s["qty"], 0)
                    cost = unit_price if cost is None else (have * cost + qty * unit_price) / (have + qty)
                    c.execute("UPDATE stock SET cost=? WHERE outlet_id=? AND ingredient_id=?", (cost, o["id"], ing["id"]))
                delta = qty
            elif action == "waste":
                delta = -qty
            else:
                delta = qty - s["qty"]  # "I counted this much": record the difference
            ledger.move(c, o["id"], ing["id"], delta, action, cost, paid=paid, actor="owner", note=note)
            security.log_activity(c, "admin:" + brand, self.ip(), "stock " + action, "%s: %g %s%s" % (
                ing["name"], qty / 1000.0, ing["unit"], "" if paid is None else ", paid %g" % paid))
        self.send_json({"ok": True})

    def r_admin_stock_set(self, brand):
        """{ingredient_id, low_at?, price?, per?}  price paid for 'per' units sets the cost of one unit."""
        self.need("admin", brand)
        d = self.body()
        with writer() as c:
            o = self.owner_outlet(c, brand)
            ing = self.ingredient(c, o["bid"], d.get("ingredient_id"))
            ledger.stock_row(c, o["id"], ing["id"])
            if "low_at" in d:
                c.execute("UPDATE stock SET low=? WHERE outlet_id=? AND ingredient_id=?", (thousandths(d["low_at"], "low_at"), o["id"], ing["id"]))
            if "price" in d:
                price = number(d["price"], 0, 100_000_000, "price")
                per = number(d.get("per"), 0.001, 10_000_000, "per")
                c.execute("UPDATE stock SET cost=? WHERE outlet_id=? AND ingredient_id=?", (price / per, o["id"], ing["id"]))
                security.log_activity(c, "admin:" + brand, self.ip(), "ingredient cost", "%s: %g per %g %s" % (ing["name"], price, per, ing["unit"]))
        self.send_json({"ok": True})

    def r_admin_recipe(self, brand, item_id):
        """{ingredients: [{id, qty}]}: what one plate uses. An empty list removes it."""
        self.need("admin", brand)
        parts = self.body().get("ingredients")
        if not isinstance(parts, list) or len(parts) > 30:
            raise ApiError(400, "ingredients must be a list of up to 30")
        with writer() as c:
            b = get_brand(c, brand)
            item = c.execute("SELECT id, slug FROM items WHERE id=? AND brand_id=? AND archived=0", (int(item_id), b["id"])).fetchone()
            if not item:
                raise ApiError(404, "Dish not found")
            clean = {}
            for p in parts:
                if not isinstance(p, dict):
                    raise ApiError(400, "Each ingredient needs an id and a quantity")
                ing = self.ingredient(c, b["id"], p.get("id"))
                qty = thousandths(p.get("qty"), "qty")
                if qty <= 0 or ing["id"] in clean:
                    raise ApiError(400, "Each ingredient needs a quantity above zero, and may be listed once")
                clean[ing["id"]] = qty
            c.execute("DELETE FROM recipes WHERE item_id=?", (item["id"],))
            c.executemany("INSERT INTO recipes(item_id,ingredient_id,qty) VALUES(?,?,?)", [(item["id"], k, v) for k, v in clean.items()])
            security.log_activity(c, "admin:" + brand, self.ip(), "recipe changed", "%s: %d ingredients" % (item["slug"], len(clean)))
        self.send_json({"ok": True})

    # ------------------------------------------------------------ reports and sheets (owner only)
    def make_report(self, c, brand):
        b = get_brand(c, brand)
        first, last = period(self.q)
        if self.q.get("outlet", "all") == "all":
            outlets = c.execute("SELECT * FROM outlets WHERE brand_id=? ORDER BY id", (b["id"],)).fetchall()
        else:
            outlets = [self.owner_outlet(c, brand)]
        return b, ledger.report(c, b, outlets, first, last)

    def r_admin_report(self, brand):
        self.need("admin", brand)
        with db.connect() as c:
            _, data = self.make_report(c, brand)
        self.send_json({"summary": data["summary"], "dishes": data["dishes"]})

    def send_file(self, data, name):
        self.send_response(200)
        self.send_header("Content-Type", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
        self.send_header("Content-Disposition", 'attachment; filename="%s"' % name)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def r_admin_sheet(self, brand):
        self.need("admin", brand)
        with db.connect() as c:
            b, data = self.make_report(c, brand)
            own = ledger.saved_layout(c, b["id"]) if self.q.get("layout") == "mine" else None
        if self.q.get("layout") == "mine" and not own:
            raise ApiError(404, "You have not uploaded your own layout yet")
        try:
            blob = ledger.fill(own["data"] if own else ledger.default_layout(), data)
        except xlsx.LayoutError as e:
            raise ApiError(409, str(e))
        with writer() as c:
            security.log_activity(c, "admin:" + brand, self.ip(), "order sheet downloaded", "%s to %s" % (self.q["from"], self.q["to"]))
        self.send_file(blob, "orders-%s-to-%s.xlsx" % (self.q["from"], self.q["to"]))

    def r_admin_sheet_default(self, brand):
        self.need("admin", brand)
        self.send_file(ledger.default_layout(), "order-sheet-layout.xlsx")

    def r_admin_layout(self, brand):
        self.need("admin", brand)
        with db.connect() as c:
            own = ledger.saved_layout(c, get_brand(c, brand)["id"])
        self.send_json({"layout": {"name": own["name"], "uploaded_at": own["uploaded_at"]} if own else None})

    def r_admin_layout_upload(self, brand):
        """The request body is the .xlsx file itself."""
        self.need("admin", brand)  # checked first: a stranger's file is never even read
        n = self.length(xlsx.MAX_UPLOAD)
        data = self.rfile.read(n)
        name = re.sub(r"[^\w .()-]", "_", unquote(self.headers.get("X-File-Name", "")))[:80] or "my-layout.xlsx"
        try:
            ledger.check_layout(data)
        except xlsx.LayoutError as e:
            raise ApiError(400, str(e))
        except Exception:
            raise ApiError(400, "That file could not be used as a layout")
        with writer() as c:
            b = get_brand(c, brand)
            c.execute("INSERT OR REPLACE INTO sheet_templates(brand_id,name,data,uploaded_at) VALUES(?,?,?,?)", (b["id"], name, data, time.time()))
            security.log_activity(c, "admin:" + brand, self.ip(), "order sheet layout uploaded", name)
        self.send_json({"ok": True, "name": name}, 201)

    def r_admin_layout_remove(self, brand):
        self.need("admin", brand)
        self.body()
        with writer() as c:
            c.execute("DELETE FROM sheet_templates WHERE brand_id=?", (get_brand(c, brand)["id"],))
            security.log_activity(c, "admin:" + brand, self.ip(), "order sheet layout removed")
        self.send_json({"ok": True})


S = r"([a-z0-9-]+)"
PID = r"([A-Za-z0-9_-]+)"
BUSINESS_ROUTES = [
    ("GET", r"^/api/kitchen/" + S + "/bills$", "r_bills"),
    ("POST", r"^/api/kitchen/" + S + "/orders/" + PID + "/pay$", "r_bill_pay"),
    ("POST", r"^/api/kitchen/" + S + "/orders/" + PID + "/refunded$", "r_bill_refunded"),
    ("GET", r"^/api/admin/" + S + "/payments$", "r_admin_payments"),
    ("POST", r"^/api/admin/" + S + "/payments/undo$", "r_admin_payment_undo"),
    ("GET", r"^/api/admin/" + S + "/stock$", "r_admin_stock"),
    ("POST", r"^/api/admin/" + S + "/stock$", "r_admin_stock_move"),
    ("PUT", r"^/api/admin/" + S + "/stock$", "r_admin_stock_set"),
    ("POST", r"^/api/admin/" + S + "/ingredients$", "r_admin_ingredient_create"),
    ("PUT", r"^/api/admin/" + S + r"/ingredients/(\d{1,12})$", "r_admin_ingredient_update"),
    ("PUT", r"^/api/admin/" + S + r"/recipes/(\d{1,9})$", "r_admin_recipe"),
    ("GET", r"^/api/admin/" + S + "/report$", "r_admin_report"),
    ("GET", r"^/api/admin/" + S + "/sheet$", "r_admin_sheet"),
    ("GET", r"^/api/admin/" + S + "/sheet/default-layout$", "r_admin_sheet_default"),
    ("GET", r"^/api/admin/" + S + "/sheet/layout$", "r_admin_layout"),
    ("POST", r"^/api/admin/" + S + "/sheet/layout$", "r_admin_layout_upload"),
    ("POST", r"^/api/admin/" + S + "/sheet/layout/remove$", "r_admin_layout_remove"),
]
