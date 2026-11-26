"""Money, stock and reports.

Stock: each dish has an ingredient list. Saving an order takes those ingredients out of the outlet's stock in the
same database write. Rejecting an order that was not made yet puts them back; rejecting one that was already
ready counts them as wasted. Stock is allowed to go below zero (a count can be wrong) and is then flagged:
it never blocks a sale.

Quantities are stored in thousandths as whole numbers, so adding and subtracting never drifts.
Costs are per one unit (g, ml or piece). A dish sold without a full ingredient list and costs has an
UNKNOWN cost: reports say so instead of counting it as free."""
import json
import os
import time

import db
import xlsx

UNITS = ("g", "ml", "pcs")
UNPAID_DAYS = 31


# ------------------------------------------------------------ stock
def stock_row(c, outlet_id, ingredient_id):
    c.execute("INSERT OR IGNORE INTO stock(outlet_id, ingredient_id) VALUES(?,?)", (outlet_id, ingredient_id))
    return c.execute("SELECT * FROM stock WHERE outlet_id=? AND ingredient_id=?", (outlet_id, ingredient_id)).fetchone()


def move(c, outlet_id, ingredient_id, delta, kind, cost, order_id=None, paid=None, actor="", note="", now=None):
    c.execute("UPDATE stock SET qty=qty+? WHERE outlet_id=? AND ingredient_id=?", (delta, outlet_id, ingredient_id))
    c.execute("INSERT INTO stock_moves(at,outlet_id,ingredient_id,delta,kind,order_id,cost,paid,actor,note) VALUES(?,?,?,?,?,?,?,?,?,?)",
              (now or time.time(), outlet_id, ingredient_id, delta, kind, order_id, cost, paid, actor, note))


def dish_cost(c, outlet_id, item_id):
    """Cost of one plate at this outlet now, or None if it cannot be known."""
    rows = c.execute("""SELECT r.qty, s.cost FROM recipes r LEFT JOIN stock s ON s.ingredient_id=r.ingredient_id AND s.outlet_id=?
                        WHERE r.item_id=?""", (outlet_id, item_id)).fetchall()
    if not rows or any(r["cost"] is None for r in rows):
        return None
    return sum(r["qty"] / 1000.0 * r["cost"] for r in rows)


def take_for_order(c, outlet_id, order_id, now):
    """Called inside the write that saves an order. Done in four whole-order statements: one command per ingredient
    made every other order wait during a rush."""
    p = {"outlet": outlet_id, "order": order_id, "now": now}
    # what one plate of each line costs right now; empty if it has no ingredient list or any cost is missing
    c.execute("""UPDATE order_lines SET cost = (
                   SELECT CASE WHEN COUNT(*)=0 OR COUNT(s.cost)<COUNT(*) THEN NULL ELSE SUM(r.qty/1000.0*s.cost) END
                   FROM recipes r LEFT JOIN stock s ON s.ingredient_id=r.ingredient_id AND s.outlet_id=:outlet
                   WHERE r.item_id=order_lines.item_id)
                 WHERE order_id=:order""", p)
    c.execute("""INSERT OR IGNORE INTO stock(outlet_id, ingredient_id)
                 SELECT :outlet, r.ingredient_id FROM order_lines l JOIN recipes r ON r.item_id=l.item_id WHERE l.order_id=:order""", p)
    used = c.execute("""INSERT INTO stock_moves(at,outlet_id,ingredient_id,delta,kind,order_id,cost,actor,note)
                        SELECT :now, :outlet, r.ingredient_id, -r.qty*l.qty, 'sale', :order, s.cost, '', ''
                        FROM order_lines l JOIN recipes r ON r.item_id=l.item_id
                        JOIN stock s ON s.outlet_id=:outlet AND s.ingredient_id=r.ingredient_id
                        WHERE l.order_id=:order ORDER BY l.id""", p).rowcount
    if used:
        c.execute("""UPDATE stock SET qty = qty + (SELECT SUM(delta) FROM stock_moves m
                       WHERE m.order_id=:order AND m.kind='sale' AND m.ingredient_id=stock.ingredient_id)
                     WHERE outlet_id=:outlet AND ingredient_id IN
                       (SELECT ingredient_id FROM stock_moves WHERE order_id=:order AND kind='sale')""", p)


def put_back(c, order_id, now):
    """The order was rejected before it was made: its ingredients were never used."""
    for m in c.execute("SELECT * FROM stock_moves WHERE order_id=? AND kind='sale'", (order_id,)).fetchall():
        move(c, m["outlet_id"], m["ingredient_id"], -m["delta"], "cancel", m["cost"], order_id, now=now)


def stock_list(c, brand_id, outlet_id):
    rows = c.execute("""SELECT i.id, i.name, i.unit, s.qty, s.low, s.cost FROM ingredients i
                        LEFT JOIN stock s ON s.ingredient_id=i.id AND s.outlet_id=?
                        WHERE i.brand_id=? AND i.archived=0 ORDER BY i.name COLLATE NOCASE""", (outlet_id, brand_id)).fetchall()
    out = []
    for r in rows:
        qty, low = (r["qty"] or 0) / 1000.0, (r["low"] or 0) / 1000.0
        status = "OUT" if qty <= 0 else "LOW" if low > 0 and qty <= low else "OK"
        out.append({"id": r["id"], "name": r["name"], "unit": r["unit"], "quantity": qty, "low_at": low, "cost": r["cost"], "status": status,
                    "value": round(max(qty, 0) * r["cost"], 2) if r["cost"] is not None else None})
    return out


def low_stock(c, brand_id, outlet_id):
    """Ingredients that need buying. One that was never stocked or used is not an alarm."""
    used = {r[0] for r in c.execute("SELECT DISTINCT ingredient_id FROM stock_moves WHERE outlet_id=?", (outlet_id,))}
    return [s for s in stock_list(c, brand_id, outlet_id) if s["status"] != "OK" and (s["id"] in used or s["low_at"] > 0)]


# ------------------------------------------------------------ bills
def bill(o):
    return {"public_id": o["public_id"], "token": o["token"], "kind": o["kind"], "table": o["table_no"], "name": o["customer_name"] or "",
            "total": o["total"], "status": o["status"], "created_at": o["created_at"], "pay_method": o["pay_method"], "paid_at": o["paid_at"]}


def unpaid(c, outlet_id):
    rows = c.execute("""SELECT * FROM orders WHERE outlet_id=? AND paid_at IS NULL AND status!='cancelled' AND total>0 AND created_at>=?
                        ORDER BY created_at""", (outlet_id, time.time() - UNPAID_DAYS * 86400)).fetchall()
    return [bill(r) for r in rows]


def refunds_due(c, outlet_id):
    rows = c.execute("""SELECT * FROM orders WHERE outlet_id=? AND status='cancelled' AND paid_at IS NOT NULL AND refunded_at IS NULL
                        ORDER BY created_at""", (outlet_id,)).fetchall()
    return [bill(r) for r in rows]


# ------------------------------------------------------------ reports
def day_bounds(first, last):
    """'2026-01-05', '2026-01-05' -> the local midnight that starts it and the one that ends it."""
    a, b = time.strptime(first, "%Y-%m-%d"), time.strptime(last, "%Y-%m-%d")
    start = time.mktime((a.tm_year, a.tm_mon, a.tm_mday, 0, 0, 0, 0, 0, -1))
    end = time.mktime((b.tm_year, b.tm_mon, b.tm_mday + 1, 0, 0, 0, 0, 0, -1))
    return start, end


def money(v):
    return None if v is None else round(v + 0.0, 2)


def report(c, brand, outlets, first, last):
    """brand: brands row; outlets: outlet rows; first/last: 'YYYY-MM-DD' (both included). Money is by order date."""
    start, end = day_bounds(first, last)
    ids = [o["id"] for o in outlets]
    marks = ",".join("?" * len(ids))
    name_of = {o["id"]: o["name"] for o in outlets}
    orders = c.execute("SELECT * FROM orders WHERE outlet_id IN (%s) AND created_at>=? AND created_at<? ORDER BY created_at, id" % marks,
                       ids + [start, end]).fetchall()
    lines = c.execute("""SELECT l.order_id, l.item_id, l.qty, l.price, l.cost, i.names FROM order_lines l JOIN items i ON i.id=l.item_id
                         JOIN orders o ON o.id=l.order_id WHERE o.outlet_id IN (%s) AND o.created_at>=? AND o.created_at<? ORDER BY l.id""" % marks,
                      ids + [start, end]).fetchall()
    by_order = {}
    for l in lines:
        by_order.setdefault(l["order_id"], []).append(l)

    def dish_name(raw):
        names = json.loads(raw)
        return names.get("en") or next(iter(names.values()), "?")

    totals = dict.fromkeys(("sales", "paid_cash", "paid_upi", "paid_card", "paid_online", "unpaid", "costed_sales", "cost"), 0.0)
    counts = {"orders": 0, "cancelled": 0}
    refunds = 0.0
    dishes, order_rows, line_rows = {}, [], []
    for o in orders:
        cancelled = o["status"] == "cancelled"
        stamp = time.localtime(o["created_at"])
        if cancelled:
            counts["cancelled"] += 1
            if o["paid_at"] is not None and o["refunded_at"] is None:
                refunds += o["total"]
            payment = "refund due" if o["paid_at"] is not None and o["refunded_at"] is None else "returned" if o["refunded_at"] else ""
        else:
            counts["orders"] += 1
            totals["sales"] += o["total"]
            if o["paid_at"] is None:
                totals["unpaid"] += o["total"]
                payment = "unpaid" if o["total"] else "free"
            else:
                key = "paid_" + (o["pay_method"] or "cash")
                totals[key if key in totals else "paid_cash"] += o["total"]
                payment = o["pay_method"] or "paid"
        mine = by_order.get(o["id"], [])
        common = {"date": time.strftime("%d-%m-%Y", stamp), "time": time.strftime("%H:%M", stamp), "token": o["token"],
                  "outlet": name_of[o["outlet_id"]], "type": "Takeaway" if o["kind"] == "takeaway" else "Dine-in",
                  "table": o["table_no"] if o["kind"] != "takeaway" else None, "customer": o["customer_name"] or "",
                  "payment": payment, "status": o["status"]}
        order_rows.append(dict(common, items=", ".join("%d x %s" % (l["qty"], dish_name(l["names"])) for l in mine), total=o["total"]))
        for l in mine:
            amount = l["price"] * l["qty"]
            cost = None if l["cost"] is None else l["cost"] * l["qty"]
            line_rows.append(dict(common, item=dish_name(l["names"]), qty=l["qty"], price=l["price"], amount=amount, cost=money(cost),
                                  margin=money(None if cost is None else amount - cost)))
            if cancelled:
                continue
            d = dishes.setdefault(l["item_id"], {"name": dish_name(l["names"]), "qty": 0, "sales": 0, "costed_sales": 0, "cost": 0.0, "unknown": 0})
            d["qty"] += l["qty"]
            d["sales"] += amount
            if cost is None:
                d["unknown"] += l["qty"]
            else:
                d["costed_sales"] += amount
                d["cost"] += cost
                totals["costed_sales"] += amount
                totals["cost"] += cost

    dish_rows = []
    for d in sorted(dishes.values(), key=lambda d: -d["sales"]):
        complete = d["unknown"] == 0
        margin = d["costed_sales"] - d["cost"] if complete else None
        dish_rows.append({"name": d["name"], "qty": d["qty"], "sales": d["sales"], "cost": money(d["cost"]) if complete else None,
                          "margin": money(margin), "margin_percent": round(margin / d["sales"], 4) if complete and d["sales"] else None,
                          "note": "" if complete else "cost unknown for %d of %d sold" % (d["unknown"], d["qty"])})

    # stock movements in the period
    moves = c.execute("SELECT * FROM stock_moves WHERE outlet_id IN (%s) AND at>=? AND at<?" % marks, ids + [start, end]).fetchall()
    use = {}
    purchases = wasted_value = count_value = 0.0
    for m in moves:
        u = use.setdefault((m["outlet_id"], m["ingredient_id"]), {"used": 0, "added": 0, "wasted": 0})
        value = abs(m["delta"]) / 1000.0 * (m["cost"] or 0)
        if m["kind"] in ("sale", "cancel"):
            u["used"] -= m["delta"]
        elif m["kind"] == "purchase":
            u["added"] += m["delta"]
            purchases += m["paid"] or 0
        elif m["kind"] == "waste":
            u["wasted"] -= m["delta"]
            wasted_value += value
        elif m["kind"] == "count":
            count_value += m["delta"] / 1000.0 * (m["cost"] or 0)
    # food that was made and then rejected was used up but never sold
    thrown = c.execute("""SELECT COALESCE(SUM(-m.delta/1000.0*COALESCE(m.cost,0)),0) FROM stock_moves m JOIN orders o ON o.id=m.order_id
                          WHERE o.outlet_id IN (%s) AND o.created_at>=? AND o.created_at<? AND o.status='cancelled' AND m.kind='sale'
                          AND NOT EXISTS (SELECT 1 FROM stock_moves x WHERE x.order_id=m.order_id AND x.kind='cancel')""" % marks,
                       ids + [start, end]).fetchone()[0]
    stock_rows = []
    for o in outlets:
        for s in stock_list(c, brand["id"], o["id"]):
            u = use.get((o["id"], s["id"]), {"used": 0, "added": 0, "wasted": 0})
            stock_rows.append({"outlet": o["name"], "name": s["name"], "unit": s["unit"], "quantity": s["quantity"], "low_at": s["low_at"],
                               "cost_per_unit": s["cost"], "value": s["value"], "used": u["used"] / 1000.0, "added": u["added"] / 1000.0,
                               "wasted": u["wasted"] / 1000.0, "status": s["status"]})

    margin = totals["costed_sales"] - totals["cost"]
    summary = {"restaurant": brand["name"], "outlet": outlets[0]["name"] if len(outlets) == 1 else "All outlets",
               "currency": outlets[0]["currency"], "from": time.strftime("%d-%m-%Y", time.localtime(start)),
               "to": time.strftime("%d-%m-%Y", time.localtime(end - 3600)), "made_at": time.strftime("%d-%m-%Y %H:%M"),
               "orders": counts["orders"], "cancelled": counts["cancelled"], "sales": money(totals["sales"]),
               "paid_cash": money(totals["paid_cash"]), "paid_upi": money(totals["paid_upi"]), "paid_card": money(totals["paid_card"]),
               "paid_online": money(totals["paid_online"]), "unpaid": money(totals["unpaid"]), "refunds_due": money(refunds),
               "costed_sales": money(totals["costed_sales"]), "uncosted_sales": money(totals["sales"] - totals["costed_sales"]),
               "cost": money(totals["cost"]) if totals["costed_sales"] or totals["cost"] else None,
               "margin": money(margin) if totals["costed_sales"] or totals["cost"] else None,
               "margin_percent": round(margin / totals["costed_sales"], 4) if totals["costed_sales"] else None,
               "waste_cost": money(wasted_value + thrown), "count_difference": money(count_value), "purchases": money(purchases)}
    summary["period"] = summary["from"] if summary["from"] == summary["to"] else "%s to %s" % (summary["from"], summary["to"])
    return {"summary": summary, "orders": order_rows, "lines": line_rows, "dishes": dish_rows, "stock": stock_rows}


# ------------------------------------------------------------ order sheets
SUMMARY_LAYOUT = [  # label, placeholder, style
    ("Orders", "orders", 0), ("Rejected orders", "cancelled", 0), ("Sales", "sales", 2), ("Paid in cash", "paid_cash", 2),
    ("Paid by UPI", "paid_upi", 2), ("Paid by card", "paid_card", 2), ("Paid online", "paid_online", 2), ("Not paid yet", "unpaid", 2),
    ("Money still to return (rejected after payment)", "refunds_due", 2), (None, None, 0),
    ("Sales with a known cost", "costed_sales", 2), ("Ingredient cost of those sales", "cost", 2), ("Gross margin on those sales", "margin", 2),
    ("Margin %", "margin_percent", 4), ("Sales with UNKNOWN cost (not in the margin)", "uncosted_sales", 2),
    ("Cost of wasted and rejected food", "waste_cost", 2), ("Stock count difference (minus = missing)", "count_difference", 2),
    ("Money spent buying stock", "purchases", 2)]
TABLES = [  # sheet name, list name, [(heading, field, width, style)]
    ("Orders", "order", [("Date", "date", 12, 0), ("Time", "time", 7, 0), ("Outlet", "outlet", 22, 0), ("Token", "token", 7, 0), ("Type", "type", 10, 0),
                         ("Table", "table", 6, 0), ("Customer", "customer", 18, 0), ("Items", "items", 48, 0), ("Total", "total", 11, 2),
                         ("Payment", "payment", 11, 0), ("Status", "status", 10, 0)]),
    ("Items", "line", [("Date", "date", 12, 0), ("Time", "time", 7, 0), ("Token", "token", 7, 0), ("Item", "item", 28, 0), ("Qty", "qty", 6, 0),
                       ("Price", "price", 10, 2), ("Amount", "amount", 11, 2), ("Cost", "cost", 10, 2), ("Margin", "margin", 10, 2),
                       ("Payment", "payment", 11, 0), ("Status", "status", 10, 0)]),
    ("Dishes", "dish", [("Dish", "name", 28, 0), ("Sold", "qty", 7, 0), ("Sales", "sales", 12, 2), ("Cost", "cost", 12, 2),
                        ("Margin", "margin", 12, 2), ("Margin %", "margin_percent", 10, 4), ("Note", "note", 34, 0)]),
    ("Stock", "stock", [("Outlet", "outlet", 22, 0), ("Ingredient", "name", 24, 0), ("Unit", "unit", 6, 0), ("In stock now", "quantity", 13, 5),
                        ("Warn at", "low_at", 10, 5), ("Cost per unit", "cost_per_unit", 13, 0), ("Stock value", "value", 12, 2),
                        ("Used", "used", 10, 5), ("Added", "added", 10, 5), ("Wasted", "wasted", 10, 5), ("Status", "status", 8, 0)])]
LIST_FIELDS = {key: [f for _, f, _, _ in cols] for _, key, cols in TABLES}
LIST_FIELDS["line"] += ["outlet", "type", "table", "customer"]
LIST_DATA = {"order": "orders", "line": "lines", "dish": "dishes", "stock": "stock"}
SUMMARY_KEYS = ("restaurant", "outlet", "currency", "from", "to", "period", "made_at", "orders", "cancelled", "sales", "paid_cash", "paid_upi",
                "paid_card", "paid_online", "unpaid", "refunds_due", "costed_sales", "uncosted_sales", "cost", "margin", "margin_percent",
                "waste_cost", "count_difference", "purchases")


def default_layout():
    """The sheet the owner can download, rearrange in Excel and upload again."""
    rows = [[("{{restaurant}} - {{outlet}}", 3)], ["Order sheet for {{period}} (made {{made_at}}, amounts in {{currency}})"], []]
    for label, key, style in SUMMARY_LAYOUT:
        rows.append([] if label is None else [(label, 1), ("{{%s}}" % key, style)])
    rows += [[], ["Gross margin = sales minus ingredient cost. It is not profit: rent, wages, gas, power and taxes are not taken out."]]
    sheets = [("Summary", [46, 18], rows)]
    for title, key, cols in TABLES:
        sheets.append((title, [w for _, _, w, _ in cols],
                       [[(h, 1) for h, _, _, _ in cols], [("{{%s.%s}}" % (key, f), s) for _, f, _, s in cols]]))
    help_rows = [[("How to make your own layout", 3)], ["Move, rename, colour or delete anything, then save as .xlsx and upload it in the owner panel."],
                 ["A row with list placeholders (order. line. dish. stock.) is repeated for every entry. Use one list per row."],
                 ["Keep placeholders exactly as written. This sheet can be deleted."], [], [("Single values", 1)]]
    help_rows += [["{ {%s} }" % k] for k in SUMMARY_KEYS]
    for key, fields in LIST_FIELDS.items():
        help_rows += [[], [("List: %s" % key, 1)]] + [["{ {%s.%s} }" % (key, f)] for f in fields]
    help_rows.insert(1, ["Below, a space is shown inside the brackets so this page is not filled in: write them without spaces."])
    sheets.append(("Placeholders", [110], help_rows))
    return xlsx.build(sheets)


def fill(layout, data):
    lists = {key: {"fields": fields, "rows": data[LIST_DATA[key]]} for key, fields in LIST_FIELDS.items()}
    return xlsx.fill_layout(layout, data["summary"], lists)


def check_layout(layout):
    """Try the layout with made-up figures, so mistakes show up at upload time rather than at closing time."""
    row = {key: [dict.fromkeys(fields, 1)] * 2 for key, fields in LIST_FIELDS.items()}
    fill(layout, dict({LIST_DATA[key]: rows for key, rows in row.items()}, summary=dict.fromkeys(SUMMARY_KEYS, 1)))


def saved_layout(c, brand_id):
    return c.execute("SELECT name, data, uploaded_at FROM sheet_templates WHERE brand_id=?", (brand_id,)).fetchone()


def auto_save(folder):
    """Writes yesterday's sheet, and last month's, for every outlet if they are not there yet. Safe to call often."""
    today = time.localtime()
    yesterday = time.strftime("%Y-%m-%d", time.localtime(time.mktime((today.tm_year, today.tm_mon, today.tm_mday - 1, 12, 0, 0, 0, 0, -1))))
    month_end = time.localtime(time.mktime((today.tm_year, today.tm_mon, 0, 12, 0, 0, 0, 0, -1)))
    periods = [(yesterday, yesterday, yesterday), (time.strftime("%Y-%m-01", month_end), time.strftime("%Y-%m-%d", month_end), time.strftime("%Y-%m", month_end))]
    made = []
    with db.connect() as c:
        for brand in c.execute("SELECT * FROM brands").fetchall():
            own = saved_layout(c, brand["id"])
            for o in c.execute("SELECT * FROM outlets WHERE brand_id=?", (brand["id"],)).fetchall():
                for first, last, label in periods:
                    path = os.path.join(folder, "%s-%s.xlsx" % (o["slug"], label))
                    if os.path.exists(path):
                        continue
                    start, end = day_bounds(first, last)
                    if not c.execute("SELECT 1 FROM orders WHERE outlet_id=? AND created_at>=? AND created_at<? LIMIT 1", (o["id"], start, end)).fetchone():
                        continue
                    data = report(c, brand, [o], first, last)
                    try:
                        blob = fill(own["data"] if own else default_layout(), data)
                    except xlsx.LayoutError:
                        blob = fill(default_layout(), data)
                    os.makedirs(folder, exist_ok=True)
                    with open(path, "wb") as f:
                        f.write(blob)
                    made.append(path)
    return made
