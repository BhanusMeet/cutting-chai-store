"""Creates a separate database for load testing: one brand, N cities x M outlets, T tables each.
Never touches the demo database. Usage:
    python seed_scale.py --db path.db [--cities 5 --per-city 5 --tables 50]
"""
import argparse
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

CITIES = ["mumbai", "delhi", "bengaluru", "chennai", "kolkata", "hyderabad", "pune", "ahmedabad"]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", required=True)
    ap.add_argument("--cities", type=int, default=5)
    ap.add_argument("--per-city", type=int, default=5)
    ap.add_argument("--tables", type=int, default=50)
    ap.add_argument("--print-gap", type=float, default=5, help="seconds between kitchen slips at each store")
    a = ap.parse_args()
    os.environ["QRO_DB"] = os.path.abspath(a.db)
    for ext in ("", "-wal", "-shm"):
        if os.path.exists(os.environ["QRO_DB"] + ext):
            os.remove(os.environ["QRO_DB"] + ext)
    import db  # noqa: E402  (must import after QRO_DB is set)

    j = lambda d: json.dumps(d, ensure_ascii=False)
    pin_hash = db.hash_pin("1111")  # one hash reused for every outlet: hashing 25 PINs would just slow the seed
    with db.connect() as c:
        c.executescript(db.SCHEMA)
        db.migrate(c)
        c.execute("INSERT INTO brands(slug,name,theme,tagline,langs,default_lang,admin_pin_hash) VALUES(?,?,?,?,?,?,?)",
                  ("scale-cafe", "Scale Cafe", "bombay", "load test", j(["en", "hi", "mr"]), "en", pin_hash))
        bid = c.execute("SELECT id FROM brands").fetchone()[0]
        cats = {}
        for i, (slug, names) in enumerate(db.CHAI_CATEGORIES):
            cats[slug] = c.execute("INSERT INTO categories(brand_id,slug,sort,names) VALUES(?,?,?,?)", (bid, slug, i, j(names))).lastrowid
        for i, (slug, cat, en, hi, mr, price, veg, tag, desc, _aed) in enumerate(db.CHAI_ITEMS):
            c.execute("INSERT INTO items(brand_id,category_id,slug,sort,price,veg,tag,names,descs) VALUES(?,?,?,?,?,?,?,?,?)",
                      (bid, cats[cat], slug, i, price, veg, tag, j({"en": en, "hi": hi, "mr": mr}), j({"en": desc})))
        db.instant_defaults(c)
        n = 0
        for city in CITIES[:a.cities]:
            for k in range(1, a.per_city + 1):
                c.execute("INSERT INTO outlets(brand_id,slug,name,city,country,currency,tables_count,kitchen_lang,kitchen_pin_hash) VALUES(?,?,?,?,?,?,?,?,?)",
                          (bid, "scale-%s-%d" % (city, k), "Scale Cafe - %s %d" % (city.title(), k), city.title(), "India", "INR", a.tables, "en", pin_hash))
                n += 1
    with db.connect() as c:
        c.execute("UPDATE outlets SET print_gap=?", (a.print_gap,))
    print("seeded %d outlets x %d tables = %d tables at %s" % (n, a.tables, n * a.tables, os.environ["QRO_DB"]))


if __name__ == "__main__":
    main()
