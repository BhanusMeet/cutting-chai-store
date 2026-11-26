#!/usr/bin/env python3
"""Peak test of the real store: many outlets, every seat full, non-stop.

  * dine-in guests open the table QR (page, scripts, menu, table check), order with the table code, wait,
    and their bill is then marked paid at the counter,
  * takeaway customers are rung up by signed-in counter staff, who record the payment,
  * each outlet has a kitchen screen (live feed, 3 s printer check) whose cooks only get food when its slip
    PRINTS on a simulated USB printer, a counter screen checking bills every 10 s, and a token board,
  * every dish has an ingredient list, so every order also moves stock,
  * owners refresh the overview, and one pulls the money report and the Excel sheet during the rush.

    python peak_test.py --name peak-gap5 --gap 5
    python peak_test.py --name trial --cities 1 --per-city 2 --duration 40
Standard library only. The test and the server share one computer. It uses its own database, never the real store's.
"""
import argparse
import asyncio
import collections
import json
import os
import random
import secrets
import shutil
import sqlite3
import statistics
import subprocess
import sys
import tempfile
import threading
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
import run_load as R  # noqa: E402  (tiny HTTP client, percentiles, process sampler)
import run_soak as K  # noqa: E402  (timeline recorder and live-stream reader)

BRAND = "peak-cafe"
PRINTER = "Load Sim"
OWNER_PW = "peak-owner-%s" % secrets.token_hex(6)
PIN = "7%07d1" % random.SystemRandom().randint(0, 9999999)
FILES = ["/css/base.css", "/css/theme-bombay.css", "/js/api.js", "/js/i18n.js", "/js/themes.js", "/js/customer.js"]
INGREDIENTS = [("Milk", "ml", 0.06), ("Tea leaf", "g", 0.5), ("Sugar", "g", 0.05), ("Bread", "pcs", 6), ("Butter", "g", 0.55), ("Potato", "g", 0.03)]


def seed(path, cfg):
    os.environ["QRO_DB"] = path
    for ext in ("", "-wal", "-shm"):
        if os.path.exists(path + ext):
            os.remove(path + ext)
    sys.path.insert(0, ROOT)
    import db
    db.DB_PATH = path
    db.init()
    outlets = []
    pin_hash = db.hash_pin(PIN)
    with db.connect() as c:
        bid = c.execute("INSERT INTO brands(slug,name,theme,tagline,langs,default_lang,admin_pin_hash) VALUES(?,?,?,?,?,?,?)",
                        (BRAND, "Peak Cafe", "bombay", "load test", json.dumps(["en", "hi", "mr"]), "en", db.hash_pin(OWNER_PW))).lastrowid
        db.starter_menu(c, bid, ["en", "hi", "mr"])
        c.execute("INSERT OR REPLACE INTO meta(key,value) VALUES('store_secret',?)", (secrets.token_hex(32),))  # as first-time setup does
        ing = [(c.execute("INSERT INTO ingredients(brand_id,name,unit) VALUES(?,?,?)", (bid, n, u)).lastrowid, cost) for n, u, cost in INGREDIENTS]
        rng = random.Random(3)
        for item in c.execute("SELECT id FROM items").fetchall():
            for iid, _ in rng.sample(ing, rng.randint(2, 4)):
                c.execute("INSERT INTO recipes(item_id,ingredient_id,qty) VALUES(?,?,?)", (item["id"], iid, rng.randint(1, 80) * 1000))
        for city in R.CITIES[:cfg.cities]:
            for k in range(1, cfg.per_city + 1):
                slug = "peak-%s-%d" % (city, k)
                oid = c.execute("""INSERT INTO outlets(brand_id,slug,name,city,country,currency,tables_count,kitchen_lang,kitchen_pin_hash,
                                   print_gap,print_mode,printer_name,paper_width) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                                (bid, slug, "Peak Cafe - %s %d" % (city.title(), k), city.title(), "India", "INR", cfg.tables, "en", pin_hash,
                                 cfg.gap, "usb", PRINTER, 80)).lastrowid
                for iid, cost in ing:  # plenty of stock, so the starting figure is known
                    c.execute("INSERT INTO stock(outlet_id,ingredient_id,qty,low,cost) VALUES(?,?,?,?,?)", (oid, iid, 10 ** 12, 10 ** 6, cost))
                outlets.append(slug)
    return outlets


class World:
    def __init__(self):
        self.delivered = collections.defaultdict(asyncio.Event)
        self.sent = collections.Counter()
        self.paid = set()
        self.printer = {}
        self.t_end = time.time() + 10 ** 6


async def req(cfg, S, W, label, method, path, body=None, token=None, ok=(200, 201)):
    W.sent[label] += 1
    s, d, lat, e = await R.request(cfg.host, cfg.port, method, path, body, token, timeout=60)
    if s in ok:
        S.add(label, lat)
    else:
        S.fail("%s_%s" % (label, s or e))
    return s, d


async def raw(cfg, path, token=None):
    """A request whose answer is a file, not data. Returns (status, size)."""
    try:
        r, w = await asyncio.wait_for(asyncio.open_connection(cfg.host, cfg.port), 20)
        auth = "Authorization: Bearer %s\r\n" % token if token else ""
        w.write(("GET %s HTTP/1.0\r\nHost: %s\r\n%s\r\n" % (path, cfg.host, auth)).encode())
        await w.drain()
        data = await asyncio.wait_for(r.read(-1), 120)
        w.close()
        return int(data.split(b" ", 2)[1]), len(data)
    except (asyncio.TimeoutError, ConnectionError, OSError, ValueError, IndexError):
        return 0, 0


async def wait_for(event, deadline):
    try:
        await asyncio.wait_for(event.wait(), max(0.01, deadline - time.time()))
        return True
    except asyncio.TimeoutError:
        return False


async def guest(cfg, S, W, slug, table, key, items, staff, t_end, hard_end, delay):
    await asyncio.sleep(delay)
    while time.time() < t_end:
        t0 = time.perf_counter()
        got = await asyncio.gather(raw(cfg, "/r/%s/%d?k=%s" % (slug, table, key)), *[raw(cfg, f) for f in FILES])
        got += [(s, 0) for s, _, _, _ in await asyncio.gather(R.request(cfg.host, cfg.port, "GET", "/api/outlet/" + slug),
                                                             R.request(cfg.host, cfg.port, "GET", "/api/menu/" + slug),
                                                             R.request(cfg.host, cfg.port, "GET", "/api/table/%s/%d?k=%s" % (slug, table, key)))]
        W.sent["page_requests"] += len(got)
        if any(s != 200 for s, _ in got):
            S.fail("page_open_%s" % next(s for s, _ in got if s != 200))
            await asyncio.sleep(2)
            continue
        S.add("page_open", time.perf_counter() - t0)
        body = {"outlet": slug, "table": table, "key": key, "client_key": secrets.token_hex(12),
                "lines": [{"item_id": i, "qty": random.randint(1, 3)} for i in random.sample(items, random.randint(1, 4))]}
        s, d = await req(cfg, S, W, "order_dine_in", "POST", "/api/orders", body)
        if s not in (200, 201):
            await asyncio.sleep(2)
            continue
        pid = d["public_id"]
        S.acked.add(pid)
        S.cnt["orders_ok"] += 1
        S.cnt["orders_dine_in"] += 1
        placed = time.time()
        if not await wait_for(W.delivered[pid], hard_end):
            S.cnt["still_waiting_dine_in"] += 1
            return
        S.add("food_dine_in", time.time() - placed)
        S.cnt["completed"] += 1
        await asyncio.sleep(random.uniform(*cfg.dine_think))
        s, _ = await req(cfg, S, W, "mark_paid", "POST", "/api/kitchen/%s/orders/%s/pay" % (slug, pid), {"method": random.choice(["cash", "upi", "card"])}, staff)
        if s == 200:
            W.paid.add(pid)


async def takeaway(cfg, S, W, slug, number, items, staff, t_end, hard_end, delay):
    await asyncio.sleep(delay)
    while time.time() < t_end:
        body = {"outlet": slug, "kind": "takeaway", "name": "Guest %03d" % number, "client_key": secrets.token_hex(12),
                "pay_method": random.choice(["cash", "upi", "card"]),
                "lines": [{"item_id": i, "qty": random.randint(1, 3)} for i in random.sample(items, random.randint(1, 3))]}
        s, d = await req(cfg, S, W, "order_counter", "POST", "/api/orders", body, staff)
        if s not in (200, 201):
            await asyncio.sleep(2)
            continue
        pid = d["public_id"]
        S.acked.add(pid)
        S.cnt["orders_ok"] += 1
        S.cnt["orders_takeaway"] += 1
        placed = time.time()
        if not await wait_for(W.delivered[pid], hard_end):
            S.cnt["still_waiting_takeaway"] += 1
            return
        S.add("food_takeaway", time.time() - placed)
        S.cnt["completed"] += 1
        await asyncio.sleep(random.uniform(*cfg.takeaway_think))


async def kitchen(cfg, S, W, slug, staff, key, stop):
    cooking = asyncio.Queue()
    side = set()

    async def tap(pid, status):
        s, _ = await req(cfg, S, W, "kitchen_tap", "POST", "/api/kitchen/%s/orders/%s/status" % (slug, pid), {"status": status}, staff)
        return s == 200

    async def hand_over(pid):
        await asyncio.sleep(random.uniform(0.5, 2))
        if await tap(pid, "served"):
            W.delivered[pid].set()

    def later(coro):
        task = asyncio.create_task(coro)
        side.add(task)
        task.add_done_callback(side.discard)

    def on_event(name, data, now):
        if name == "order_new":
            S.add("order_to_screen", now - data["created_at"])
            if data["status"] == "ready":  # tea only: nothing to cook
                later(hand_over(data["public_id"]))
        elif name == "slip" and data["status"] == "printed":
            S.add("print_to_screen", now - data["printed_at"])
            if data["station"] == "kitchen":
                cooking.put_nowait(data["public_id"])
        elif name == "slip" and data["status"] == "failed":
            S.fail("slip_failed")

    async def cook():
        while True:
            pid = await cooking.get()
            await asyncio.sleep(random.uniform(*cfg.cook_time))
            if await tap(pid, "ready"):
                later(hand_over(pid))

    async def printer_check():
        while True:
            await asyncio.sleep(3)
            s, st = await req(cfg, S, W, "printer_check", "GET", "/api/kitchen/%s/printer" % slug, None, staff)
            if s == 200 and time.time() < W.t_end:
                W.printer[slug] = st
                S.tl["queue_waiting"].append((time.time() - S.t0, st["waiting"]))
                S.tl["queue_oldest"].append((time.time() - S.t0, st["oldest_wait"]))

    async def counter_screen():
        while True:
            await asyncio.sleep(10)
            await req(cfg, S, W, "counter_bills", "GET", "/api/kitchen/%s/bills" % slug, None, staff)

    tasks = [asyncio.create_task(K.stream(cfg, S, "/api/stream?outlet=%s&key=%s" % (slug, key), on_event, stop)),
             asyncio.create_task(K.stream(cfg, S, "/api/stream?board=" + slug, lambda *a: S.cnt.update(["board_events"]), stop)),
             asyncio.create_task(printer_check()), asyncio.create_task(counter_screen())] + [asyncio.create_task(cook()) for _ in range(cfg.cooks)]
    await stop.wait()
    for t in tasks + list(side):
        t.cancel()


async def owners(cfg, S, W, token, outlets, stop):
    async def overview():
        await asyncio.sleep(random.uniform(0, 5))
        while not stop.is_set():
            await req(cfg, S, W, "owner_overview", "GET", "/api/admin/%s/overview" % BRAND, None, token)
            await asyncio.sleep(5)

    async def reporter():  # one owner looking at the money while the shop is at its busiest
        n = 0
        while not stop.is_set():
            await asyncio.sleep(cfg.report_every)
            if stop.is_set():
                break
            today = time.strftime("%Y-%m-%d")
            query = "?from=%s&to=%s&outlet=%s" % (today, today, outlets[n % len(outlets)] if n % 3 else "all")
            await req(cfg, S, W, "owner_report", "GET", "/api/admin/%s/report%s" % (BRAND, query), None, token)
            t0 = time.perf_counter()
            status, size = await raw(cfg, "/api/admin/%s/sheet%s" % (BRAND, query), token)
            S.tl["sheet_log"].append((time.time() - S.t0, (query.endswith("all"), status, round(time.perf_counter() - t0, 2), size)))
            n += 1

    tasks = [asyncio.create_task(overview()) for _ in range(cfg.owners)] + [asyncio.create_task(reporter())]
    await stop.wait()
    for t in tasks:
        t.cancel()


def verify(path, S, W, gap):
    c = sqlite3.connect(path)
    one = lambda sql: c.execute(sql).fetchone()[0]
    res = collections.OrderedDict()
    ids = {r[0] for r in c.execute("SELECT public_id FROM orders")}
    res["orders in database"] = len(ids)
    res["orders confirmed to customers"] = len(S.acked)
    res["confirmed but missing (LOST ORDERS)"] = len(S.acked - ids)
    res["saved but never confirmed"] = len(ids - S.acked)
    res["duplicate token numbers within a store"] = one("SELECT COUNT(*) FROM (SELECT outlet_id,token FROM orders GROUP BY outlet_id,token HAVING COUNT(*)>1)")
    res["orders with a wrong total"] = one("SELECT COUNT(*) FROM orders o WHERE o.total != (SELECT COALESCE(SUM(qty*price),0) FROM order_lines l WHERE l.order_id=o.id)")
    res["counter sales without a payment record"] = one("SELECT COUNT(*) FROM orders WHERE kind='takeaway' AND (paid_at IS NULL OR pay_method IS NULL)")
    paid = {r[0] for r in c.execute("SELECT public_id FROM orders WHERE kind='dine_in' AND paid_at IS NOT NULL")}
    res["table bills marked paid but not saved"] = len(W.paid - paid)
    res["sold lines without a recorded cost"] = one("SELECT COUNT(*) FROM order_lines WHERE cost IS NULL")
    res["stock figures that do not match their history"] = one(
        """SELECT COUNT(*) FROM stock s WHERE s.qty != %d + COALESCE((SELECT SUM(delta) FROM stock_moves m
           WHERE m.outlet_id=s.outlet_id AND m.ingredient_id=s.ingredient_id),0)""" % 10 ** 12)
    sold = one("SELECT COALESCE(SUM(r.qty*l.qty),0) FROM order_lines l JOIN recipes r ON r.item_id=l.item_id")
    taken = one("SELECT COALESCE(-SUM(delta),0) FROM stock_moves WHERE kind IN ('sale','cancel')")
    res["stock taken minus what the sales needed"] = taken - sold
    res["database integrity check"] = one("PRAGMA integrity_check")
    per = collections.defaultdict(list)
    for oid, at in c.execute("SELECT outlet_id, printed_at FROM slips WHERE station='kitchen' AND status='printed' ORDER BY outlet_id, printed_at"):
        per[oid].append(at)
    gaps = [b - a for v in per.values() for a, b in zip(v, v[1:])]
    slips = dict(c.execute("SELECT station||' '||status, COUNT(*) FROM slips GROUP BY 1").fetchall())
    waits = sorted(r[0] for r in c.execute("SELECT printed_at-queued_at FROM slips WHERE station='kitchen' AND status='printed'"))
    counter_waits = sorted(r[0] for r in c.execute("SELECT printed_at-queued_at FROM slips WHERE station='counter' AND status='printed'"))
    busiest = c.execute("SELECT COUNT(*) FROM orders WHERE kind='dine_in' GROUP BY outlet_id, CAST((created_at-?)/60 AS INT) ORDER BY 1 DESC LIMIT 1", (S.t0,)).fetchone()
    c.close()
    pace = {"gaps": gaps, "slips": slips, "waits": waits, "counter_waits": counter_waits, "too_close": sum(1 for g in gaps if g < gap - 0.15),
            "busiest_guest_minute": busiest[0] if busiest else 0}
    return res, pace


async def run(cfg):
    os.makedirs(os.path.join(HERE, "results"), exist_ok=True)
    path = os.path.join(HERE, "results", "%s.db" % cfg.name)
    outlets = seed(path, cfg)
    sim = tempfile.mkdtemp(prefix="qro-sim-")  # the pretend printer's paper
    with open(os.path.join(sim, "printers.json"), "w") as f:
        json.dump([{"name": PRINTER, "port": "USB001"}], f)
    logp = os.path.join(HERE, "results", "%s.server.log" % cfg.name)
    log = open(logp, "w")
    # Every simulated phone shares one network address here, so the per-address limits are lifted for the test.
    env = dict(os.environ, QRO_DB=path, QRO_PRINT_SIM=sim, QRO_ORDER_RATE="1000000000", QRO_LOGIN_RATE="100000")
    env.pop("QRO_PAY_SECRET", None)
    srv = subprocess.Popen([sys.executable, os.path.join(ROOT, "server.py"), "--port", str(cfg.port)], env=env, stdout=log, stderr=log)
    samples, sstop = [], threading.Event()
    try:
        if not await R.wait_ready(cfg.host, cfg.port):
            print("server did not start")
            return None
        threading.Thread(target=R.sampler, args=(srv.pid, samples, sstop), daemon=True).start()
        S, W = K.Soak(time.time()), World()

        async def login(scope, slug, secret):
            s, d, _, e = await R.request(cfg.host, cfg.port, "POST", "/api/login", {"scope": scope, "slug": slug, "pin": secret}, timeout=120)
            if s != 200:
                raise RuntimeError("sign-in failed: %s %s %s" % (s, e, d))
            return d

        owner = (await login("admin", BRAND, OWNER_PW))["token"]
        staff, keys = {}, {}
        for o in outlets:
            d = await login("kitchen", o, PIN)
            staff[o] = d
            s, q, _, _ = await R.request(cfg.host, cfg.port, "GET", "/api/admin/%s/qr?outlet=%s" % (BRAND, o), None, owner)
            if s != 200:
                raise RuntimeError("QR codes failed for %s: %s %s" % (o, s, q))
            keys[o] = {t["table"]: t["path"].split("k=")[1] for t in q["tables"]}
        s, menu, _, _ = await R.request(cfg.host, cfg.port, "GET", "/api/menu/" + outlets[0])
        items = [i["id"] for c in menu["categories"] for i in c["items"] if i["available"] and i["price"] > 0]
        print("%s: %d outlets x (%d tables + %d takeaway), %d s non-stop, 1 kitchen slip every %s s per outlet"
              % (cfg.name, len(outlets), cfg.tables, cfg.takeaway, cfg.duration, cfg.gap), flush=True)
        stop = asyncio.Event()
        bg = [asyncio.create_task(kitchen(cfg, S, W, o, staff[o]["token"], staff[o]["stream_key"], stop)) for o in outlets]
        await asyncio.sleep(3)
        t0 = time.time()
        S.t0 = t0
        W.t_end = t0 + cfg.duration
        hard_end = W.t_end + cfg.grace
        bg.append(asyncio.create_task(owners(cfg, S, W, owner, outlets, stop)))
        people = []
        for o in outlets:
            people += [asyncio.create_task(guest(cfg, S, W, o, n, keys[o][n], items, staff[o]["token"], W.t_end, hard_end, random.uniform(0, cfg.ramp)))
                       for n in range(1, cfg.tables + 1)]
            people += [asyncio.create_task(takeaway(cfg, S, W, o, n, items, staff[o]["token"], W.t_end, hard_end, random.uniform(0, cfg.ramp)))
                       for n in range(1, cfg.takeaway + 1)]

        async def monitor():
            last = 0
            while True:
                await asyncio.sleep(30)
                ok = S.cnt["orders_ok"]
                print("  t+%3ds  orders %6d (+%.1f/s)  delivered %6d  errors %d  slips waiting %d" % (
                    time.time() - t0, ok, (ok - last) / 30, S.cnt["completed"], sum(S.err.values()), sum(v["waiting"] for v in W.printer.values())), flush=True)
                if S.err:
                    waiting_ports = subprocess.run(["netstat", "-an", "-p", "TCP"], capture_output=True, text=True).stdout.count("TIME_WAIT")
                    print("         top errors %s | network ports in TIME_WAIT: %d" % (S.err.most_common(4), waiting_ports), flush=True)
                last = ok
        mon = asyncio.create_task(monitor())
        await asyncio.gather(*people)
        mon.cancel()
        stop.set()
        await asyncio.sleep(2)
        for t in bg:
            t.cancel()
        sstop.set()
        return S, W, samples, path, logp, len(outlets)
    finally:
        sstop.set()
        srv.terminate()
        try:
            srv.wait(20)
        except subprocess.TimeoutExpired:
            srv.kill()
        log.close()
        shutil.rmtree(sim, ignore_errors=True)


def report(cfg, S, W, samples, path, logp, n):
    checks, pace = verify(path, S, W, cfg.gap)
    vals = lambda name: [x for _, x in S.tl.get(name, [])]
    out = ["=" * 112, "PEAK TEST: %s" % cfg.name, "=" * 112]
    out.append("%d outlets x (%d tables + %d takeaway), %d s non-stop, 1 kitchen slip every %s s per outlet" % (n, cfg.tables, cfg.takeaway, cfg.duration, cfg.gap))
    out.append("Orders: %d (dine-in %d, counter %d) = %.1f a second. Delivered %d. Still waiting at the end: dine-in %d, takeaway %d. Table bills marked paid: %d"
               % (S.cnt["orders_ok"], S.cnt["orders_dine_in"], S.cnt["orders_takeaway"], S.cnt["orders_ok"] / cfg.duration, S.cnt["completed"],
                  S.cnt["still_waiting_dine_in"], S.cnt["still_waiting_takeaway"], len(W.paid)))
    out.append("Requests: %d. Peak live connections: %d" % (sum(W.sent.values()), S.live_peak))
    out.append("")
    ok_speed = True
    for label, name, target in [("guest opens table page (9 requests)", "page_open", 3.0), ("guest places order", "order_dine_in", 1.0),
                                ("counter rings up a sale", "order_counter", 1.0), ("counter marks a bill paid", "mark_paid", 1.0),
                                ("kitchen tap", "kitchen_tap", 1.0), ("new order -> kitchen screen", "order_to_screen", 1.0),
                                ("slip printed -> kitchen screen", "print_to_screen", 1.0), ("kitchen printer check", "printer_check", 1.0),
                                ("counter bills check", "counter_bills", 1.0), ("owner overview", "owner_overview", 2.0), ("owner money report", "owner_report", 5.0)]:
        x = vals(name)
        if not x:
            out.append("  %-38s no data" % label)
            ok_speed = False
            continue
        p95 = R.pct(x, 95)
        ok_speed = ok_speed and p95 <= target
        out.append("  %-38s n=%-6d p50 %6.0f ms  p95 %6.0f ms  p99 %6.0f ms  max %6.0f ms  target p95<=%d  %s"
                   % (label, len(x), R.pct(x, 50) * 1000, p95 * 1000, R.pct(x, 99) * 1000, max(x) * 1000, target * 1000, "PASS" if p95 <= target else "FAIL"))
    sheets = vals("sheet_log")
    if sheets:
        out.append("  Excel sheet during the rush: " + "; ".join("%s -> %s in %.1f s (%d KB)" % ("all outlets" if a else "one outlet", s, t, size / 1024) for a, s, t, size in sheets))
    out.append("")
    out.append("Minute by minute:   orders/s   errors   guest order p95 ms   counter sale p95 ms   slips waiting per outlet   oldest slip s")
    for m in range(int(cfg.duration // 60)):
        win = lambda name: [x for t, x in S.tl.get(name, []) if m * 60 <= t < (m + 1) * 60]
        a, b, qw, qo = win("order_dine_in"), win("order_counter"), win("queue_waiting"), win("queue_oldest")
        out.append("  %6d %16.1f %8d %20s %21s %26s %15s" % (
            m + 1, (len(a) + len(b)) / 60, sum(1 for t, _ in S.err_tl if m * 60 <= t < (m + 1) * 60),
            "-" if not a else "%.0f" % (R.pct(a, 95) * 1000), "-" if not b else "%.0f" % (R.pct(b, 95) * 1000),
            "-" if not qw else "%.0f" % statistics.mean(qw), "-" if not qo else "%d" % max(qo)))
    out.append("")
    w = pace["waits"]
    if w:
        out.append("Kitchen slip wait to print: median %.0f s, p95 %.0f s, longest %.0f s" % (R.pct(w, 50), R.pct(w, 95), w[-1]))
    if pace["counter_waits"]:
        out.append("Counter (tea) slip wait to print: median %.2f s, p95 %.2f s, longest %.2f s" % (
            R.pct(pace["counter_waits"], 50), R.pct(pace["counter_waits"], 95), pace["counter_waits"][-1]))
    if pace["gaps"]:
        out.append("Gap between kitchen slips at one printer: shortest %.2f s, median %.2f s, closer than the setting: %d" % (
            min(pace["gaps"]), statistics.median(pace["gaps"]), pace["too_close"]))
    out.append("Slips: %s" % ", ".join("%s %d" % kv for kv in sorted(pace["slips"].items())))
    for label, name in [("dine-in order -> food", "food_dine_in"), ("takeaway order -> food", "food_takeaway")]:
        x = vals(name)
        if x:
            out.append("%s (delivered only): median %.0f s, p95 %.0f s, longest %.0f s" % (label, R.pct(x, 50), R.pct(x, 95), max(x)))
    out.append("Busiest minute of guest orders at one outlet: %d (the real server allows 120 a minute from one network address)" % pace["busiest_guest_minute"])
    out.append("")
    out.append("Failed requests: %d %s" % (sum(S.err.values()), dict(S.err) if S.err else ""))
    out.append("Database check:")
    out += ["  %-48s %s" % kv for kv in checks.items()]
    size = sum(os.path.getsize(path + e) for e in ("", "-wal") if os.path.exists(path + e))
    out.append("Database size after the run: %.0f MB" % (size / 1e6))
    if len(samples) > 6:
        cpu = [(b[1] - a[1]) / (b[0] - a[0]) * 100 for a, b in zip(samples, samples[1:]) if b[0] > a[0]]
        out.append("Server process: peak threads %d, peak memory %.0f MB, CPU average %.0f%% / peak %.0f%% of one core"
                   % (max(s[3] for s in samples), max(s[2] for s in samples) / 1e6, statistics.mean(cpu), max(cpu)))
    tracebacks = open(logp, errors="replace").read().count("Traceback")
    zero = ["confirmed but missing (LOST ORDERS)", "saved but never confirmed", "duplicate token numbers within a store", "orders with a wrong total",
            "counter sales without a payment record", "table bills marked paid but not saved", "sold lines without a recorded cost",
            "stock figures that do not match their history", "stock taken minus what the sales needed"]
    consistent = all(checks[k] == 0 for k in zero) and checks["database integrity check"] == "ok"
    sheets_ok = all(s == 200 for _, s, _, _ in sheets)
    errors = sum(S.err.values())
    out.append("Server tracebacks: %d" % tracebacks)
    verdict = ok_speed and consistent and sheets_ok and errors == 0 and tracebacks == 0 and pace["too_close"] == 0
    out.append("Checks: speed %s | no failed requests %s | money, orders and stock consistent %s | printer pacing %s | sheets %s" % tuple(
        "PASS" if x else "FAIL" for x in (ok_speed, errors == 0, consistent, pace["too_close"] == 0, sheets_ok)))
    out.append("VERDICT: %s  (server only; how long guests wait for food depends on the print gap and the cooks)" % ("PASS" if verdict else "FAIL"))
    text = "\n".join(out)
    print(text)
    with open(os.path.join(HERE, "results", "%s.txt" % cfg.name), "w", encoding="utf-8") as fh:
        fh.write(text + "\n")
    return verdict


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--name", default="peak-gap5")
    ap.add_argument("--gap", type=float, default=5)
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8100)
    ap.add_argument("--cities", type=int, default=5)
    ap.add_argument("--per-city", type=int, default=5)
    ap.add_argument("--tables", type=int, default=50)
    ap.add_argument("--takeaway", type=int, default=100)
    ap.add_argument("--duration", type=float, default=600)
    ap.add_argument("--grace", type=float, default=60)
    ap.add_argument("--ramp", type=float, default=20)
    ap.add_argument("--cooks", type=int, default=12)
    ap.add_argument("--cook-time", type=float, nargs=2, default=[2.0, 4.0])
    ap.add_argument("--dine-think", type=float, nargs=2, default=[15, 45])
    ap.add_argument("--takeaway-think", type=float, nargs=2, default=[8, 25])
    ap.add_argument("--owners", type=int, default=10)
    ap.add_argument("--report-every", type=float, default=90)
    cfg = ap.parse_args()
    random.seed(11)
    result = asyncio.run(run(cfg))
    if result is None:
        sys.exit(2)
    sys.exit(0 if report(cfg, *result) else 1)


if __name__ == "__main__":
    main()
