"""Database layer for the QR ordering platform.

Structure (built multi-tenant from day one):
    brand -> outlets -> tables -> orders
    brand owns the master menu; each outlet can override price / availability.

SQLite keeps the install simple. Every query goes through this module, so
moving to Postgres / Supabase later means changing this file, not the app.
"""
import hashlib
import hmac
import json
import os
import secrets
import sqlite3

HERE = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.environ.get("QRO_DB", os.path.join(HERE, "data", "store.db"))
PIN_ROUNDS = 600_000

SCHEMA = """
CREATE TABLE IF NOT EXISTS brands (
  id INTEGER PRIMARY KEY, slug TEXT UNIQUE NOT NULL, name TEXT NOT NULL,
  theme TEXT NOT NULL, tagline TEXT, langs TEXT NOT NULL DEFAULT '["en"]',
  default_lang TEXT NOT NULL DEFAULT 'en', admin_pin_hash TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS outlets (
  id INTEGER PRIMARY KEY, brand_id INTEGER NOT NULL REFERENCES brands(id),
  slug TEXT UNIQUE NOT NULL, name TEXT NOT NULL, city TEXT, country TEXT,
  currency TEXT NOT NULL DEFAULT 'INR', tables_count INTEGER NOT NULL DEFAULT 10,
  kitchen_lang TEXT NOT NULL DEFAULT 'en', kitchen_pin_hash TEXT NOT NULL,
  accepting INTEGER NOT NULL DEFAULT 1
);
CREATE TABLE IF NOT EXISTS categories (
  id INTEGER PRIMARY KEY, brand_id INTEGER NOT NULL REFERENCES brands(id),
  slug TEXT NOT NULL, sort INTEGER NOT NULL DEFAULT 0, names TEXT NOT NULL,
  UNIQUE(brand_id, slug)
);
CREATE TABLE IF NOT EXISTS items (
  id INTEGER PRIMARY KEY, brand_id INTEGER NOT NULL REFERENCES brands(id),
  category_id INTEGER NOT NULL REFERENCES categories(id), slug TEXT NOT NULL,
  sort INTEGER NOT NULL DEFAULT 0, price INTEGER NOT NULL, veg INTEGER NOT NULL DEFAULT 1,
  tag TEXT, names TEXT NOT NULL, descs TEXT NOT NULL DEFAULT '{}',
  UNIQUE(brand_id, slug)
);
CREATE TABLE IF NOT EXISTS outlet_items (
  outlet_id INTEGER NOT NULL REFERENCES outlets(id),
  item_id INTEGER NOT NULL REFERENCES items(id),
  price INTEGER, available INTEGER NOT NULL DEFAULT 1,
  PRIMARY KEY (outlet_id, item_id)
);
CREATE TABLE IF NOT EXISTS orders (
  id INTEGER PRIMARY KEY, public_id TEXT UNIQUE NOT NULL,
  outlet_id INTEGER NOT NULL REFERENCES outlets(id), token INTEGER NOT NULL,
  table_no INTEGER NOT NULL, customer_name TEXT, prefs TEXT, note TEXT,
  kind TEXT NOT NULL DEFAULT 'dine_in', client_key TEXT,
  status TEXT NOT NULL DEFAULT 'new', total INTEGER NOT NULL,
  created_at REAL NOT NULL, updated_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_orders_outlet ON orders(outlet_id, created_at);
CREATE TABLE IF NOT EXISTS order_lines (
  id INTEGER PRIMARY KEY, order_id INTEGER NOT NULL REFERENCES orders(id),
  item_id INTEGER NOT NULL REFERENCES items(id), qty INTEGER NOT NULL, price INTEGER NOT NULL
);
"""


def connect(manual=False, shared=False):
    """manual=True gives a connection where the caller issues BEGIN / COMMIT itself (used for writes)."""
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH, timeout=15, isolation_level=None if manual else "", check_same_thread=not shared)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")  # safe in WAL mode: an app crash loses nothing, only a power cut can lose the last instant
    return conn


def hash_pin(pin):
    """Passwords and PINs are never stored: only a slow, salted fingerprint of them."""
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", pin.encode("utf-8", "replace"), salt.encode(), PIN_ROUNDS).hex()
    return "%d$%s$%s" % (PIN_ROUNDS, salt, digest)


def check_pin(pin, stored):
    try:
        rounds, salt, digest = stored.split("$")
        test = hashlib.pbkdf2_hmac("sha256", pin.encode("utf-8", "replace"), salt.encode(), int(rounds)).hex()
    except (ValueError, AttributeError):
        return False
    return hmac.compare_digest(test, digest)


def migrate(c):
    """Bring an older database up to date (adds takeaway and retry-safety columns) and create the indexes that need them."""
    cols = {r[1] for r in c.execute("PRAGMA table_info(orders)")}
    if "kind" not in cols:
        c.execute("ALTER TABLE orders ADD COLUMN kind TEXT NOT NULL DEFAULT 'dine_in'")
    if "client_key" not in cols:
        c.execute("ALTER TABLE orders ADD COLUMN client_key TEXT")
    # one order per (outlet, client_key): a retried request can never create a second order
    c.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_orders_client_key ON orders(outlet_id, client_key) WHERE client_key IS NOT NULL")

    def add(table, column, ddl):
        if column not in {r[1] for r in c.execute("PRAGMA table_info(%s)" % table)}:
            c.execute("ALTER TABLE %s ADD COLUMN %s %s" % (table, column, ddl))
            return True
        return False

    # paid takeaway
    add("orders", "phone", "TEXT")
    add("orders", "payment_ref", "TEXT")
    add("orders", "eta_seconds", "INTEGER")
    c.execute("""CREATE TABLE IF NOT EXISTS payments (
        id INTEGER PRIMARY KEY, ref TEXT UNIQUE NOT NULL, outlet_id INTEGER NOT NULL, spec TEXT NOT NULL,
        amount INTEGER NOT NULL, status TEXT NOT NULL DEFAULT 'pending', client_key TEXT, order_public_id TEXT,
        created_at REAL NOT NULL, paid_at REAL)""")
    c.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_payments_client_key ON payments(outlet_id, client_key) WHERE client_key IS NOT NULL")
    # per-store kitchen settings
    add("outlets", "auto_accept", "INTEGER NOT NULL DEFAULT 1")
    add("outlets", "print_gap", "REAL NOT NULL DEFAULT 5")
    add("outlets", "print_order", "TEXT NOT NULL DEFAULT 'fifo'")
    if add("items", "instant", "INTEGER NOT NULL DEFAULT 0"):
        instant_defaults(c)
    c.execute("""CREATE TABLE IF NOT EXISTS slips (
        id INTEGER PRIMARY KEY, order_id INTEGER NOT NULL, outlet_id INTEGER NOT NULL, station TEXT NOT NULL,
        status TEXT NOT NULL DEFAULT 'queued', items TEXT NOT NULL, queued_at REAL NOT NULL, printed_at REAL)""")
    c.execute("CREATE INDEX IF NOT EXISTS idx_slips_order ON slips(order_id)")
    # real-store security
    c.execute("CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
    c.execute("""CREATE TABLE IF NOT EXISTS activity (id INTEGER PRIMARY KEY, at REAL NOT NULL, actor TEXT NOT NULL,
        ip TEXT, action TEXT NOT NULL, detail TEXT)""")
    add("outlets", "qr_version", "INTEGER NOT NULL DEFAULT 1")
    add("items", "archived", "INTEGER NOT NULL DEFAULT 0")
    add("orders", "pay_method", "TEXT")
    # real printing: 'ask' = no printer chosen yet, 'none' = the owner does not print, 'usb' = print on printer_name
    add("outlets", "print_mode", "TEXT NOT NULL DEFAULT 'ask'")
    add("outlets", "printer_name", "TEXT")
    add("outlets", "paper_width", "INTEGER NOT NULL DEFAULT 80")
    add("slips", "error", "TEXT")
    add("slips", "reprint", "INTEGER NOT NULL DEFAULT 0")
    c.execute("CREATE INDEX IF NOT EXISTS idx_slips_outlet ON slips(outlet_id, status)")
    # money: when and how each order was paid, and whether money for a rejected order was given back
    if add("orders", "paid_at", "REAL"):
        c.execute("UPDATE orders SET pay_method='online' WHERE payment_ref IS NOT NULL AND pay_method IS NULL")
        c.execute("UPDATE orders SET paid_at=created_at WHERE pay_method IS NOT NULL")
    add("orders", "refunded_at", "REAL")
    # stock. Quantities are whole thousandths of a unit; costs are money for one unit.
    add("order_lines", "cost", "REAL")  # ingredient cost of one plate when it was sold; empty = not known
    c.execute("""CREATE TABLE IF NOT EXISTS ingredients (id INTEGER PRIMARY KEY, brand_id INTEGER NOT NULL, name TEXT NOT NULL,
        unit TEXT NOT NULL, archived INTEGER NOT NULL DEFAULT 0)""")
    c.execute("""CREATE TABLE IF NOT EXISTS stock (outlet_id INTEGER NOT NULL, ingredient_id INTEGER NOT NULL,
        qty INTEGER NOT NULL DEFAULT 0, low INTEGER NOT NULL DEFAULT 0, cost REAL, PRIMARY KEY (outlet_id, ingredient_id))""")
    c.execute("""CREATE TABLE IF NOT EXISTS recipes (item_id INTEGER NOT NULL, ingredient_id INTEGER NOT NULL, qty INTEGER NOT NULL,
        PRIMARY KEY (item_id, ingredient_id))""")
    c.execute("""CREATE TABLE IF NOT EXISTS stock_moves (id INTEGER PRIMARY KEY, at REAL NOT NULL, outlet_id INTEGER NOT NULL,
        ingredient_id INTEGER NOT NULL, delta INTEGER NOT NULL, kind TEXT NOT NULL, order_id INTEGER, cost REAL, paid REAL,
        actor TEXT, note TEXT)""")
    c.execute("CREATE INDEX IF NOT EXISTS idx_moves_time ON stock_moves(outlet_id, at)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_moves_order ON stock_moves(order_id)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_lines_order ON order_lines(order_id)")
    c.execute("CREATE TABLE IF NOT EXISTS sheet_templates (brand_id INTEGER PRIMARY KEY, name TEXT NOT NULL, data BLOB NOT NULL, uploaded_at REAL NOT NULL)")


# Items that are always ready (poured, not cooked). Owners change this per item in the owner panel.
INSTANT_SLUGS = ("cutting-chai", "full-chai", "masala-chai", "adrak-chai", "irani-chai", "sulaimani",
                 "garam-paani", "masala-chaas", "jaljeera")


def instant_defaults(c):
    c.execute("UPDATE items SET instant=1 WHERE slug IN (%s)" % ",".join("?" * len(INSTANT_SLUGS)), INSTANT_SLUGS)


def init():
    """Creates an EMPTY store. There is no sample restaurant and no sample password: the owner sets up their own."""
    with connect() as c:
        c.executescript(SCHEMA)
        migrate(c)


# ---------------------------------------------------------------- optional starter menu
# A starting point the owner can choose at setup. The prices are placeholders to be checked.
# Hindi / Marathi names are first drafts: have a native speaker review them.

CHAI_CATEGORIES = [
    ("chai", {"en": "Chai", "hi": "चाय", "mr": "चहा"}),
    ("saath", {"en": "Chai ke Saath", "hi": "चाय के साथ", "mr": "चहा सोबत"}),
    ("more", {"en": "Aur Kuch", "hi": "और कुछ", "mr": "आणखी काही"}),
]
# slug, category, en, hi, mr, price(INR), veg, tag, description(en), dubai price (AED)
CHAI_ITEMS = [
    ("cutting-chai", "chai", "Cutting Chai", "कटिंग चाय", "कटिंग चहा", 10, 1, "Bestseller", "Half a glass, a full kick.", 4),
    ("full-chai", "chai", "Full Chai", "फुल चाय", "फुल चहा", 18, 1, None, "The whole glass, no sharing.", 7),
    ("masala-chai", "chai", "Masala Chai", "मसाला चाय", "मसाला चहा", 15, 1, None, "Crushed elaichi and a pinch of the house masala.", 6),
    ("adrak-chai", "chai", "Adrak Chai", "अदरक चाय", "आले चहा", 15, 1, None, "Fresh ginger, strong leaf.", 6),
    ("irani-chai", "chai", "Irani Chai", "इरानी चाय", "इराणी चहा", 20, 1, None, "Mawa-rich, slow simmered, Irani cafe style.", 8),
    ("sulaimani", "chai", "Sulaimani", "सुलेमानी", "सुलेमानी", 15, 1, None, "Black tea, lemon and a hint of spice.", 6),
    ("bun-maska", "saath", "Bun Maska", "बन मस्का", "बन मस्का", 18, 1, "Dunk it", "Soft bun, thick slab of butter.", 8),
    ("maska-pav", "saath", "Maska Pav", "मस्का पाव", "मस्का पाव", 20, 1, None, "Toasted pav, butter melting in.", 8),
    ("khari", "saath", "Khari Biscuit", "खारी बिस्किट", "खारी बिस्किट", 12, 1, None, "Flaky and made for dipping.", 5),
    ("osmania", "saath", "Osmania Biscuit", "उस्मानिया बिस्किट", "उस्मानिया बिस्किट", 12, 1, None, "Salty-sweet Hyderabadi classic.", 5),
    ("toast-butter", "saath", "Toast & Butter", "टोस्ट और बटर", "टोस्ट आणि बटर", 25, 1, None, "Two slices, golden and crisp.", 10),
    ("bhaji-pav", "saath", "Bhaji Pav", "भाजी पाव", "भाजी पाव", 45, 1, None, "Buttery mashed bhaji with pav.", 18),
    ("vada-pav", "more", "Vada Pav", "वडा पाव", "वडा पाव", 15, 1, "Bombay classic", "The city's own, with dry garlic chutney.", 8),
    ("egg-bhurji-pav", "more", "Egg Bhurji Pav", "अंडा भुर्जी पाव", "अंडा भुर्जी पाव", 40, 0, None, "Spiced scrambled eggs, buttered pav.", 16),
    ("omelette-pav", "more", "Masala Omelette Pav", "मसाला ऑमलेट पाव", "मसाला ऑम्लेट पाव", 40, 0, None, "Onion, chilli and coriander.", 16),
    ("cold-coffee", "more", "Cold Coffee", "कोल्ड कॉफ़ी", "कोल्ड कॉफी", 35, 1, None, "Thick, cold, sweet.", 14),
    ("nimbu-soda", "more", "Nimbu Soda", "नींबू सोडा", "लिंबू सोडा", 20, 1, None, "Sweet, salty or both.", 8),
    ("garam-paani", "more", "Garam Paani", "गरम पानी", "गरम पाणी", 0, 1, None, "Warm water, on the house.", 0),
]

def starter_menu(c, brand_id, langs):
    j = lambda v: json.dumps({k: x for k, x in v.items() if k in langs}, ensure_ascii=False)
    cats = {}
    for i, (slug, names) in enumerate(CHAI_CATEGORIES):
        cats[slug] = c.execute("INSERT INTO categories(brand_id,slug,sort,names) VALUES(?,?,?,?)", (brand_id, slug, i, j(names))).lastrowid
    for i, (slug, cat, en, hi, mr, price, veg, tag, desc, _aed) in enumerate(CHAI_ITEMS):
        c.execute("INSERT INTO items(brand_id,category_id,slug,sort,price,veg,tag,names,descs) VALUES(?,?,?,?,?,?,?,?,?)",
                  (brand_id, cats[cat], slug, i, price, veg, None, j({"en": en, "hi": hi, "mr": mr}), j({"en": desc})))
    instant_defaults(c)


if __name__ == "__main__":
    init()
    print("database ready at", DB_PATH)
