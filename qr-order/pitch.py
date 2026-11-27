#!/usr/bin/env python3
"""The pitch store: Cutting Chai Co. with made-up sales, for showing the product to a possible client.

It uses its OWN database (data/pitch/store.db) and its own port, so your real store is never touched.
Passwords are made fresh on your computer and written to data/pitch/PITCH-LOGINS.txt (never uploaded).
Every staff screen is marked as sample data.

    python pitch.py             start it (creates it the first time)
    python pitch.py --lan       also reachable from phones on the same private Wi-Fi
    python pitch.py --reset     throw the pitch store away and make a fresh one
"""
import argparse
import json
import os
import random
import secrets
import shutil
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
FOLDER = os.path.join(HERE, "data", "pitch")
DB = os.path.join(FOLDER, "store.db")
LOGINS = os.path.join(FOLDER, "PITCH-LOGINS.txt")
BRAND, OUTLET = "cutting-chai-co", "cutting-chai-co-dadar"
TABLES = 12

# name, unit, made-up purchase price for 1000 g / 1000 ml / 1 piece, amount wanted on the shelf, low-stock warning
INGREDIENTS = {
    "milk": ("Milk", "ml", 62, 18000, 8000), "leaf": ("Tea leaf", "g", 420, 2600, 800), "sugar": ("Sugar", "g", 46, 7000, 2000),
    "ginger": ("Ginger", "g", 140, 150, 300), "masala": ("Chai masala", "g", 900, 400, 100), "bun": ("Bun", "pcs", 7, 45, 20),
    "pav": ("Pav", "pcs", 4, 90, 30), "butter": ("Butter", "g", 560, 1500, 600), "potato": ("Potato", "g", 32, 6000, 2000),
    "egg": ("Egg", "pcs", 7, 60, 24), "biscuit": ("Biscuits", "pcs", 4, 150, 40), "oil": ("Cooking oil", "ml", 140, 3000, 1000),
    "coffee": ("Coffee", "g", 800, 300, 100), "lemon": ("Lemon", "pcs", 5, 12, 20), "spice": ("Spice mix", "g", 500, 700, 200),
}
RECIPES = {
    "cutting-chai": {"milk": 40, "leaf": 2.5, "sugar": 6}, "full-chai": {"milk": 80, "leaf": 5, "sugar": 12},
    "masala-chai": {"milk": 60, "leaf": 4, "sugar": 8, "masala": 1}, "adrak-chai": {"milk": 60, "leaf": 4, "sugar": 8, "ginger": 3},
    "irani-chai": {"milk": 110, "leaf": 4, "sugar": 10}, "sulaimani": {"leaf": 3, "sugar": 6, "lemon": 0.25},
    "bun-maska": {"bun": 1, "butter": 15}, "maska-pav": {"pav": 2, "butter": 15}, "khari": {"biscuit": 2},
    "osmania": {"biscuit": 2}, "toast-butter": {"bun": 1, "butter": 20}, "bhaji-pav": {"pav": 2, "potato": 150, "butter": 15, "spice": 6},
    "vada-pav": {"pav": 1, "potato": 80, "oil": 15, "spice": 3}, "egg-bhurji-pav": {"pav": 2, "egg": 2, "oil": 10, "spice": 4},
    "omelette-pav": {"pav": 2, "egg": 2, "oil": 10, "spice": 2}, "cold-coffee": {"milk": 200, "coffee": 5, "sugar": 20},
    "nimbu-soda": {"lemon": 1, "sugar": 15},
    # garam-paani is free and has no ingredient list, so reports show how "unknown cost" looks
}
POPULAR = {"cutting-chai": 10, "masala-chai": 6, "adrak-chai": 5, "vada-pav": 7, "bun-maska": 6, "full-chai": 3, "irani-chai": 3,
           "maska-pav": 3, "bhaji-pav": 3, "cold-coffee": 3, "omelette-pav": 2, "egg-bhurji-pav": 2}
NAMES = ["", "", "", "Asha", "Ravi", "Meera", "Imran", "Neha", "Sameer", "Priya"]
NOTES = ["", "", "", "", "", "", "less spicy", "extra butter", "no onion"]


def passwords():
    words = ["kettle", "masala", "monsoon", "taxi", "cassette", "saucer", "ginger", "local", "marine", "sunset", "ticket", "radio"]
    rng = secrets.SystemRandom()
    owner = "-".join(rng.sample(words, 3)) + "-%d" % rng.randint(10, 99)
    while True:
        pin = "%06d" % rng.randint(0, 999999)
        if len(set(pin)) >= 4 and pin not in ("012345", "123456"):
            return owner, pin


def add_order(c, db_ledger, day_token, menu, outlet_id, when, status, paid, rng):
    items = rng.choices(menu, weights=[POPULAR.get(m["slug"], 1) for m in menu], k=rng.randint(1, 4))
    lines = {}
    for m in items:
        lines[m["id"]] = [lines.get(m["id"], [0])[0] + rng.choice([1, 1, 1, 2, 2, 3]), m["price"]]
    total = sum(q * p for q, p in lines.values())
    method = rng.choice(["upi", "upi", "upi", "cash", "cash", "card"]) if paid and total else None
    note = rng.choice(NOTES)
    cur = c.execute("""INSERT INTO orders(public_id,outlet_id,token,table_no,customer_name,note,kind,status,total,created_at,updated_at,
                       eta_seconds,pay_method,paid_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (secrets.token_urlsafe(16), outlet_id, day_token, rng.randint(1, TABLES), rng.choice(NAMES), note, "dine_in", status, total,
                     when, when + 300, 480, method, when + 1500 if method else None))
    for item_id, (qty, price) in lines.items():
        c.execute("INSERT INTO order_lines(order_id,item_id,qty,price) VALUES(?,?,?,?)", (cur.lastrowid, item_id, qty, price))
    db_ledger.take_for_order(c, outlet_id, cur.lastrowid, when)


def midnight(days_ago=0):
    t = time.localtime()
    return time.mktime((t.tm_year, t.tm_mon, t.tm_mday - days_ago, 0, 0, 0, 0, 0, -1))


def today_orders(c, ledger, menu, outlet_id, rng):
    """A believable 'right now': earlier orders served, two bills waiting to be paid, three still in the kitchen."""
    now = time.time()
    start = max(midnight() + 60, now - 10 * 3600)
    first = c.execute("SELECT COALESCE(MAX(token),0)+1 FROM orders WHERE outlet_id=? AND created_at>=?", (outlet_id, midnight())).fetchone()[0]
    times = sorted(rng.uniform(start, max(start + 1, now - 1800)) for _ in range(26))
    token = first
    for n, when in enumerate(times):
        add_order(c, ledger, token, menu, outlet_id, when, "served", n < 24, rng)
        token += 1
    for minutes, status in ((7, "ready"), (4, "preparing"), (1, "preparing")):
        add_order(c, ledger, token, menu, outlet_id, max(midnight() + 30, now - minutes * 60), status, False, rng)
        token += 1


def create():
    import db
    import ledger
    import security  # noqa: F401  (checked here so a broken install fails before anything is written)
    os.makedirs(FOLDER, exist_ok=True)
    db.init()
    owner, pin = passwords()
    rng = random.Random()
    j = lambda v: json.dumps(v, ensure_ascii=False)
    owner_hash, pin_hash = db.hash_pin(owner), db.hash_pin(pin)
    with db.connect() as c:
        bid = c.execute("INSERT INTO brands(slug,name,theme,tagline,langs,default_lang,admin_pin_hash) VALUES(?,?,?,?,?,?,?)",
                        (BRAND, "Cutting Chai Co.", "bombay", "Ek Cutting, Ek Yaadein", j(["en", "hi", "mr"]), "en", owner_hash)).lastrowid
        oid = c.execute("""INSERT INTO outlets(brand_id,slug,name,city,country,currency,tables_count,kitchen_lang,kitchen_pin_hash,takeaway)
                           VALUES(?,?,?,?,?,?,?,?,?,0)""",
                        (bid, OUTLET, "Cutting Chai Co. - Dadar", "Mumbai", "India", "INR", TABLES, "en", pin_hash)).lastrowid
        c.execute("INSERT INTO meta(key,value) VALUES('store_secret',?)", (secrets.token_hex(32),))
        c.execute("INSERT INTO meta(key,value) VALUES('sample_data','1')")
        db.starter_menu(c, bid, ["en", "hi", "mr"])
        menu = [dict(r) for r in c.execute("SELECT id, slug, price FROM items WHERE brand_id=? AND price>0 ORDER BY id", (bid,))]
        ids = {}
        for key, (name, unit, price, _have, low) in INGREDIENTS.items():
            ids[key] = c.execute("INSERT INTO ingredients(brand_id,name,unit) VALUES(?,?,?)", (bid, name, unit)).lastrowid
            per_unit = price if unit == "pcs" else price / 1000.0
            c.execute("INSERT INTO stock(outlet_id,ingredient_id,qty,low,cost) VALUES(?,?,0,?,?)", (oid, ids[key], low * 1000, per_unit))
        for slug, parts in RECIPES.items():
            item = c.execute("SELECT id FROM items WHERE brand_id=? AND slug=?", (bid, slug)).fetchone()
            for key, qty in parts.items():
                c.execute("INSERT INTO recipes(item_id,ingredient_id,qty) VALUES(?,?,?)", (item["id"], ids[key], int(round(qty * 1000))))
        for days_ago in range(29, 0, -1):
            weekend = time.localtime(midnight(days_ago) + 43200).tm_wday >= 5
            count = rng.randint(55, 75) if weekend else rng.randint(35, 55)
            times = sorted(midnight(days_ago) + rng.uniform(8 * 3600, 22 * 3600) for _ in range(count))
            for token, when in enumerate(times, 1):
                add_order(c, ledger, token, menu, oid, when, "served", True, rng)
        today_orders(c, ledger, menu, oid, rng)
        # buy stock in five weekly lots so that today's shelf shows the wanted amounts (ginger and lemon run low)
        for key, (_name, unit, price, have, _low) in INGREDIENTS.items():
            used = -c.execute("SELECT COALESCE(SUM(delta),0) FROM stock_moves WHERE outlet_id=? AND ingredient_id=?", (oid, ids[key])).fetchone()[0]
            need = used + have * 1000
            per_unit = price if unit == "pcs" else price / 1000.0
            left = need
            for week in range(5):
                part = left // (5 - week)
                left -= part
                c.execute("""INSERT INTO stock_moves(at,outlet_id,ingredient_id,delta,kind,cost,paid,actor,note)
                             VALUES(?,?,?,?,'purchase',?,?,'owner','weekly stock')""",
                          (midnight(29 - week * 7) + 7 * 3600, oid, ids[key], part, per_unit, round(part / 1000.0 * per_unit, 2)))
            c.execute("UPDATE stock SET qty=qty+? WHERE outlet_id=? AND ingredient_id=?", (need, oid, ids[key]))
    with open(LOGINS, "w", encoding="utf-8") as f:
        f.write("PITCH STORE sign-ins (sample data only; do not use these for a real store)\n\n"
                "Owner panel password : %s\nStaff PIN (kitchen and counter) : %s\n" % (owner, pin))


def top_up():
    """On a later day, add today's sample orders so the screens are not empty. Nothing you changed is reset."""
    import db
    import ledger
    with db.connect() as c:
        o = c.execute("SELECT id, brand_id FROM outlets WHERE slug=?", (OUTLET,)).fetchone()
        if not o or c.execute("SELECT 1 FROM orders WHERE outlet_id=? AND created_at>=? LIMIT 1", (o["id"], midnight())).fetchone():
            return False
        menu = [dict(r) for r in c.execute("SELECT id, slug, price FROM items WHERE brand_id=? AND price>0 AND archived=0", (o["brand_id"],))]
        today_orders(c, ledger, menu, o["id"], random.Random())
    return True


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--port", type=int, default=8010)
    ap.add_argument("--lan", action="store_true", help="let phones on the same Wi-Fi open it")
    ap.add_argument("--reset", action="store_true", help="delete the pitch store and make a new one")
    ap.add_argument("--create-only", action="store_true", help=argparse.SUPPRESS)
    a = ap.parse_args()
    if a.reset and os.path.isdir(FOLDER):
        shutil.rmtree(FOLDER)  # only ever the pitch folder
    os.environ["QRO_DB"] = DB  # must be set before the store code is loaded
    sys.path.insert(0, HERE)
    if not os.path.exists(DB):
        print("Making the pitch store (30 days of sample sales)...", flush=True)
        create()
    else:
        import db
        db.init()
        if top_up():
            print("Added today's sample orders.")
    if a.create_only:
        return
    base = "http://localhost:%d" % a.port
    print("\nPITCH STORE - sample data, separate from your real store")
    print("  start here      : %s/" % base)
    print("  guest website   : %s/r/%s" % (base, OUTLET))
    print("  sign-ins are in : %s" % LOGINS)
    print("  to order as a table: Owner panel -> Tables & QR -> 'Open as this table'\n", flush=True)
    import server
    sys.argv = ["server.py", "--port", str(a.port)] + (["--lan"] if a.lan else [])
    server.main()


if __name__ == "__main__":
    main()
