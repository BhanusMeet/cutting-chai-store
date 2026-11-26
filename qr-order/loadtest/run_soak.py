#!/usr/bin/env python3
"""Sustained-load (soak) test: every outlet is full and busy for a fixed time without a break.

Per outlet, all at once and non-stop:
  * every dine-in table is occupied: the guest orders, eats, and orders again,
  * a crowd of takeaway customers keeps arriving, ordering and collecting,
  * a kitchen with several cooks works the queue,
and across the chain, owner dashboards keep refreshing.
It reports each 30-second window separately so slow degradation, memory growth and thread leaks show up,
then checks the database for lost, duplicated or inconsistent orders.

    python run_soak.py --name soak10 --duration 600
Standard library only. Client and server share one computer, so treat the numbers as a conservative floor.
"""
import argparse
import asyncio
import collections
import json
import os
import random
import sqlite3
import statistics
import subprocess
import sys
import threading
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
import run_load as R  # noqa: E402  (reuses the tiny HTTP client, percentiles and the process sampler)

CITIES = R.CITIES
WIN = 30  # seconds per report window


class Soak:
    def __init__(self, t0):
        self.t0 = t0
        self.tl = collections.defaultdict(list)     # name -> [(seconds_since_start, value)]
        self.cnt = collections.Counter()
        self.err = collections.Counter()
        self.err_tl = []                            # [(seconds_since_start, label)]
        self.tap = {}
        self.acked = set()
        self.live = 0
        self.live_peak = 0
        self.live_tl = []                           # [(seconds_since_start, live connections)]
        self.kind_of = {}
        self.max_backlog = 0

    def add(self, name, v):
        self.tl[name].append((time.time() - self.t0, v))

    def fail(self, label):
        self.err[label] += 1
        self.err_tl.append((time.time() - self.t0, label))


async def stream(cfg, S, path, on_event, stop, opened=None):
    """Live stream that ends cleanly when `stop` is set (cancelling alone can be swallowed by Python)."""
    w = None
    try:
        r, w = await asyncio.wait_for(asyncio.open_connection(cfg.host, cfg.port), 30)
        w.write(("GET %s HTTP/1.0\r\nHost: %s\r\n\r\n" % (path, cfg.host)).encode())
        await w.drain()
        line = await asyncio.wait_for(r.readline(), 30)
        if b" 200" not in line:
            S.cnt["sse_refused"] += 1
            return False
        while True:
            hl = await asyncio.wait_for(r.readline(), 30)
            if hl in (b"\r\n", b""):
                break
        S.live += 1
        S.live_peak = max(S.live_peak, S.live)
        S.cnt["sse_opened"] += 1
        if opened is not None:
            opened.set()
        ev = None
        try:
            while not stop.is_set():
                line = await asyncio.wait_for(r.readline(), 60)
                if stop.is_set():
                    return True
                if not line:
                    S.cnt["sse_dropped"] += 1
                    return True
                line = line.decode().rstrip("\r\n")
                if line.startswith("event: "):
                    ev = line[7:]
                elif line.startswith("data: ") and ev:
                    on_event(ev, json.loads(line[6:]), time.time())
                    ev = None
            return True
        finally:
            S.live -= 1
            if opened is not None:
                opened.clear()
    except asyncio.CancelledError:
        raise
    except (asyncio.TimeoutError, ConnectionError, OSError):
        S.cnt["sse_failed"] += 1
        return False
    finally:
        if w is not None:
            try:
                w.close()
            except Exception:
                pass


async def customer(cfg, S, slug, kind, table, name, t_end, first_delay):
    """One seat (dine-in table or takeaway slot): order, wait, think, repeat until the clock runs out."""
    await asyncio.sleep(first_delay)
    think = cfg.dine_think if kind == "dine_in" else cfg.takeaway_think
    while time.time() < t_end:
        menu = None
        for _ in range(3):
            (s1, _, l1, e1), (s2, menu, l2, e2) = await asyncio.gather(
                R.request(cfg.host, cfg.port, "GET", "/api/outlet/" + slug), R.request(cfg.host, cfg.port, "GET", "/api/menu/" + slug))
            if s1 == 200 and s2 == 200:
                S.add("page_load", max(l1, l2))
                break
            S.fail("page_load_%s" % (s1 or e1 or s2 or e2))
            menu = None
            await asyncio.sleep(1)
        if not menu:
            S.cnt["gave_up"] += 1
            await asyncio.sleep(2)
            continue
        items = [i for c in menu["categories"] for i in c["items"] if i["available"]]
        picks = random.sample(items, random.randint(1, 4 if kind == "dine_in" else 3))
        body = {"outlet": slug, "lines": [{"item_id": i["id"], "qty": random.randint(1, 3)} for i in picks], "name": name}
        if kind == "dine_in":
            body["table"] = table
        else:
            body["kind"] = "takeaway"
        t_send = time.time()
        s, d, lat, e = await R.request(cfg.host, cfg.port, "POST", "/api/orders", body)
        S.cnt["order_attempts"] += 1
        if s != 201:
            S.fail("order_%s" % (s or e))
            await asyncio.sleep(2)
            continue
        S.add("order_post", lat)
        S.cnt["orders_ok"] += 1
        S.cnt["orders_" + kind] += 1
        pid = d["public_id"]
        S.acked.add(pid)
        S.kind_of[pid] = kind
        ok = await track(cfg, S, pid, t_send)
        if not ok:
            S.cnt["orders_stuck"] += 1
        await asyncio.sleep(random.uniform(*think) / cfg.speed)


async def track(cfg, S, pid, t_send):
    done = asyncio.Event()
    opened = asyncio.Event()
    last = ["new"]

    def on_ev(name, data, now):
        if name == "snapshot":
            last[0] = data["status"]
        elif name == "status":
            st = data["status"]
            t0 = S.tap.pop((pid, st), None)
            if t0:
                S.add("status_propagation", now - t0)
            last[0] = st
        else:
            return
        if last[0] in ("served", "cancelled"):
            done.set()

    st_task = asyncio.create_task(stream(cfg, S, "/api/stream?order=" + pid, on_ev, done, opened))

    async def fallback_poll():  # only needed when the live stream is not up (the app does the same)
        while not done.is_set():
            await asyncio.sleep(10)
            if opened.is_set() or done.is_set():
                continue
            s, d, _, _ = await R.request(cfg.host, cfg.port, "GET", "/api/orders/" + pid)
            S.cnt["fallback_polls"] += 1
            if s == 200 and d["status"] != last[0]:
                S.cnt["poll_rescued_missed_event"] += 1
                last[0] = d["status"]
                if last[0] in ("served", "cancelled"):
                    done.set()

    poll = asyncio.create_task(fallback_poll())
    try:
        await asyncio.wait_for(done.wait(), cfg.track_timeout)
        S.add("order_to_served", time.time() - t_send)
        S.cnt["orders_completed"] += 1
        return True
    except asyncio.TimeoutError:
        return False
    finally:
        done.set()  # tells the stream loop to end; cancel is only a backstop
        poll.cancel()
        st_task.cancel()


async def kitchen(cfg, S, slug, stop):
    s, d, _, e = await R.request(cfg.host, cfg.port, "POST", "/api/login", {"scope": "kitchen", "slug": slug, "pin": "1111"})
    if s != 200:
        S.fail("kitchen_login_%s" % (s or e))
        return
    token = d["token"]
    q = asyncio.Queue()
    seen = set()

    def enqueue(o):
        if o["public_id"] not in seen:
            seen.add(o["public_id"])
            q.put_nowait(o)
            S.max_backlog = max(S.max_backlog, q.qsize())

    def on_ev(name, data, now):
        if name == "order_new":
            S.add("kitchen_delivery", now - data["created_at"])
            enqueue(data)

    async def tap(o, status):
        for _ in range(3):
            S.tap[(o["public_id"], status)] = time.time()
            s2, _, lat, e2 = await R.request(cfg.host, cfg.port, "POST", "/api/kitchen/%s/orders/%s/status" % (slug, o["public_id"]), {"status": status}, token)
            if s2 == 200:
                S.add("kitchen_tap", lat)
                return True
            S.fail("kitchen_tap_%s" % (s2 or e2))
            await asyncio.sleep(1)
        return False

    async def hand_over(o, kind):  # a waiter carries it out / the takeaway customer collects it; the cook is not blocked
        await asyncio.sleep((random.uniform(0.5, 1.5) if kind == "dine_in" else random.uniform(3, 10)) / cfg.speed)
        await tap(o, "served")

    async def cook():
        while True:
            o = await q.get()
            if not await tap(o, "preparing"):
                continue
            await asyncio.sleep(random.uniform(*cfg.cook_time) / cfg.speed)
            if await tap(o, "ready"):
                asyncio.create_task(hand_over(o, S.kind_of.get(o["public_id"], "dine_in")))

    async def reconcile():
        while True:
            await asyncio.sleep(20)
            s2, d2, _, _ = await R.request(cfg.host, cfg.port, "GET", "/api/kitchen/%s/orders" % slug, None, token)
            if s2 == 200:
                for o in d2["orders"]:
                    if o["status"] == "new" and o["public_id"] not in seen:
                        S.cnt["kitchen_reconcile_found_missed_order"] += 1
                        enqueue(o)

    tasks = [asyncio.create_task(stream(cfg, S, "/api/stream?outlet=%s&t=%s" % (slug, token), on_ev, stop)),
             asyncio.create_task(reconcile())] + [asyncio.create_task(cook()) for _ in range(cfg.cooks)]
    await stop.wait()
    for t in tasks:
        t.cancel()


async def owner(cfg, S, brand, stop):
    s, d, _, e = await R.request(cfg.host, cfg.port, "POST", "/api/login", {"scope": "admin", "slug": brand, "pin": "1111"})
    if s != 200:
        S.fail("owner_login_%s" % (s or e))
        return
    while not stop.is_set():
        s, _, lat, e = await R.request(cfg.host, cfg.port, "GET", "/api/admin/%s/overview" % brand, None, d["token"])
        if s == 200:
            S.add("owner_overview", lat)
        else:
            S.fail("owner_overview_%s" % (s or e))
        try:
            await asyncio.wait_for(stop.wait(), 3)
        except asyncio.TimeoutError:
            pass


def verify(db_path, acked, takeaway_expected):
    c = sqlite3.connect(db_path)
    res = {}
    res["orders_in_db"] = c.execute("SELECT COUNT(*) FROM orders").fetchone()[0]
    res["orders_acked_to_customers"] = len(acked)
    ids = {r[0] for r in c.execute("SELECT public_id FROM orders")}
    res["acked_but_missing_from_db (LOST ORDERS)"] = len(acked - ids)
    res["in_db_but_never_acked (possible duplicates)"] = len(ids - acked)
    res["duplicate_token_numbers_within_an_outlet"] = c.execute("SELECT COUNT(*) FROM (SELECT outlet_id, token FROM orders GROUP BY outlet_id, token HAVING COUNT(*)>1)").fetchone()[0]
    res["status_counts"] = dict(c.execute("SELECT status, COUNT(*) FROM orders GROUP BY status").fetchall())
    res["orders_with_wrong_total"] = c.execute("SELECT COUNT(*) FROM orders o WHERE o.total != (SELECT COALESCE(SUM(qty*price),0) FROM order_lines l WHERE l.order_id=o.id)").fetchone()[0]
    res["orders_without_lines"] = c.execute("SELECT COUNT(*) FROM orders o WHERE NOT EXISTS (SELECT 1 FROM order_lines l WHERE l.order_id=o.id)").fetchone()[0]
    try:
        res["takeaway_orders_in_db"] = c.execute("SELECT COUNT(*) FROM orders WHERE kind='takeaway'").fetchone()[0]
        res["takeaway_without_name"] = c.execute("SELECT COUNT(*) FROM orders WHERE kind='takeaway' AND (customer_name IS NULL OR customer_name='')").fetchone()[0]
        res["dine_in_table_out_of_range"] = c.execute("SELECT COUNT(*) FROM orders o JOIN outlets u ON u.id=o.outlet_id WHERE o.kind='dine_in' AND (o.table_no<1 OR o.table_no>u.tables_count)").fetchone()[0]
        res["takeaway_with_a_table_number"] = c.execute("SELECT COUNT(*) FROM orders WHERE kind='takeaway' AND table_no!=0").fetchone()[0]
    except sqlite3.OperationalError:
        res["takeaway_orders_in_db"] = "n/a (server has no takeaway column)"
    res["sqlite_integrity_check"] = c.execute("PRAGMA integrity_check").fetchone()[0]
    res["database_size_mb"] = round(os.path.getsize(db_path) / 1e6, 1)
    c.close()
    return res


async def run(cfg):
    os.makedirs(os.path.join(HERE, "results"), exist_ok=True)
    db_path = os.path.join(HERE, "results", "%s.db" % cfg.name)
    subprocess.run([sys.executable, os.path.join(HERE, "seed_scale.py"), "--db", db_path, "--cities", str(cfg.cities),
                    "--per-city", str(cfg.per_city), "--tables", str(cfg.tables)], check=True)
    env = dict(os.environ, QRO_DB=db_path)
    log = open(os.path.join(HERE, "results", "%s.server.log" % cfg.name), "w")
    srv = subprocess.Popen([sys.executable, os.path.join(ROOT, cfg.server), "--port", str(cfg.port), "--no-demo"], env=env, stdout=log, stderr=log)
    samples, sstop = [], threading.Event()
    try:
        if not await R.wait_ready(cfg.host, cfg.port):
            print("server did not start; see results/%s.server.log" % cfg.name)
            return None
        threading.Thread(target=R.sampler, args=(srv.pid, samples, sstop), daemon=True).start()
        outlets = ["scale-%s-%d" % (c, k) for c in CITIES[:cfg.cities] for k in range(1, cfg.per_city + 1)]
        seats = len(outlets) * (cfg.tables + cfg.takeaway)
        print("soak %s: %d outlets, each with %d full tables + %d takeaway customers = %d customers at once, running %d s non-stop, %d cooks/outlet"
              % (cfg.name, len(outlets), cfg.tables, cfg.takeaway, seats, cfg.duration, cfg.cooks), flush=True)
        stop = asyncio.Event()
        warm = time.time()
        S = Soak(warm)
        bg = [asyncio.create_task(kitchen(cfg, S, o, stop)) for o in outlets]
        bg += [asyncio.create_task(owner(cfg, S, "scale-cafe", stop)) for _ in range(cfg.owners)]
        await asyncio.sleep(4)
        t0 = time.time()
        S.t0 = t0
        t_end = t0 + cfg.duration
        people = []
        for o in outlets:
            for t in range(1, cfg.tables + 1):
                people.append(asyncio.create_task(customer(cfg, S, o, "dine_in", t, "", t_end, random.uniform(0, cfg.ramp))))
            for k in range(1, cfg.takeaway + 1):
                people.append(asyncio.create_task(customer(cfg, S, o, "takeaway", 0, "Guest%03d" % k, t_end, random.uniform(0, cfg.ramp))))
        mon_stop = asyncio.Event()

        async def monitor():
            last_ok = 0
            while not mon_stop.is_set():
                await asyncio.sleep(WIN)
                S.live_tl.append((time.time() - t0, S.live))
                ok = S.cnt["orders_ok"]
                print("  t+%3ds  orders %6d (+%d/s)  completed %6d  errors %d  live connections %d  max kitchen backlog %d"
                      % (time.time() - t0, ok, (ok - last_ok) / WIN, S.cnt["orders_completed"], sum(S.err.values()), S.live, S.max_backlog), flush=True)
                last_ok = ok
        mon = asyncio.create_task(monitor())
        await asyncio.gather(*people)
        wall = time.time() - t0
        mon_stop.set(); mon.cancel()
        await asyncio.sleep(2)
        S.open_at_end = S.live - len(outlets)
        stop.set()
        await asyncio.sleep(1)
        for t in bg:
            t.cancel()
        sstop.set()
        return S, samples, wall, db_path, len(outlets), seats
    finally:
        sstop.set()
        srv.terminate()
        try:
            srv.wait(15)
        except subprocess.TimeoutExpired:
            srv.kill()
        log.close()


def window_rows(S, samples, wall):
    n = int(wall // WIN) + 1
    rows = []
    for w in range(n):
        lo, hi = w * WIN, (w + 1) * WIN
        pick = lambda name: [v for (t, v) in S.tl.get(name, []) if lo <= t < hi]
        orders = len(pick("order_post"))
        post, prop, deliv = pick("order_post"), pick("status_propagation"), pick("kitchen_delivery")
        errs = sum(1 for (t, _) in S.err_tl if lo <= t < hi)
        sm = [s for s in samples if S.t0 + lo <= s[0] < S.t0 + hi]
        rows.append({"start": lo, "orders_per_s": orders / WIN, "post_p95": R.pct(post, 95), "post_max": max(post) if post else None,
                     "deliv_p95": R.pct(deliv, 95), "prop_p95": R.pct(prop, 95), "errors": errs,
                     "threads": max((s[3] for s in sm), default=None), "mem_mb": max((s[2] for s in sm), default=0) / 1e6 if sm else None,
                     "cpu_core_pct": None})
    for i, r in enumerate(rows):
        a = [s for s in samples if S.t0 + r["start"] <= s[0] < S.t0 + r["start"] + WIN]
        if len(a) >= 2 and a[-1][0] > a[0][0]:
            r["cpu_core_pct"] = (a[-1][1] - a[0][1]) / (a[-1][0] - a[0][0]) * 100
    return [r for r in rows if r["orders_per_s"] > 0 or r["start"] < wall - 1]


def report(cfg, S, samples, wall, db_path, n_outlets, seats):
    def total(name, slo):
        xs = [v for (_, v) in S.tl.get(name, [])]
        if not xs:
            return "  %-36s no data" % name, False
        p95 = R.pct(xs, 95)
        return "  %-36s n=%-6d p50 %5.0f ms  p95 %6.0f ms  p99 %6.0f ms  max %6.0f ms   target p95<=%d ms  %s" % (
            name, len(xs), R.pct(xs, 50) * 1000, p95 * 1000, R.pct(xs, 99) * 1000, max(xs) * 1000, slo * 1000, "PASS" if p95 <= slo else "FAIL"), p95 <= slo
    spec = [("menu page load", "page_load", 2.0), ("place order", "order_post", 1.0), ("order -> visible on kitchen", "kitchen_delivery", 1.0),
            ("kitchen tap -> customer phone", "status_propagation", 1.0), ("kitchen status tap (API)", "kitchen_tap", 1.0), ("owner overview refresh", "owner_overview", 2.0)]
    rows_total = [total(n, s) for _, n, s in [(a, b, c) for a, b, c in spec]]
    v = verify(db_path, S.acked, cfg.takeaway)
    rows = window_rows(S, samples, wall)
    errors = sum(S.err.values())

    out = ["=" * 118, "SOAK RESULT: %s" % cfg.name, "=" * 118]
    out.append("%d outlets x (%d tables + %d takeaway) = %d customers at once, %d s non-stop; cooks per outlet %d" % (n_outlets, cfg.tables, cfg.takeaway, seats, cfg.duration, cfg.cooks))
    out.append("Orders accepted: %d (dine-in %d, takeaway %d) of %d attempts, completed %d, still waiting at the end %d  -> %.1f orders/s average"
               % (S.cnt["orders_ok"], S.cnt["orders_dine_in"], S.cnt["orders_takeaway"], S.cnt["order_attempts"], S.cnt["orders_completed"], S.cnt["orders_stuck"], S.cnt["orders_ok"] / wall))
    out.append("Peak live connections: %d (customer connections still open after everyone finished: %d, should be 0). Largest kitchen backlog: %d tickets"
               % (S.live_peak, getattr(S, "open_at_end", -1), S.max_backlog))
    otos = [v2 for (_, v2) in S.tl.get("order_to_served", [])]
    if otos:
        out.append("Order -> served (includes the kitchen's own cooking time and queue): median %.0f s, p95 %.0f s, max %.0f s" % (R.pct(otos, 50), R.pct(otos, 95), max(otos)))
    out.append("")
    out.append("Whole run:")
    out += [t for t, _ in rows_total]
    out.append("")
    out.append("Window by window (%d s each): is it degrading over time?" % WIN)
    out.append("  %-7s %9s %12s %12s %14s %7s %8s %8s %9s" % ("t+sec", "orders/s", "place p95 ms", "place max ms", "tap->phone p95", "errors", "threads", "mem MB", "CPU %core"))
    f = lambda x, m=1000.0, d=0: "-" if x is None else ("%.*f" % (d, x * m))
    for r in rows:
        out.append("  %-7d %9.1f %12s %12s %14s %7d %8s %8s %9s" % (r["start"], r["orders_per_s"], f(r["post_p95"]), f(r["post_max"]), f(r["prop_p95"]), r["errors"],
                                                                    "-" if r["threads"] is None else r["threads"], "-" if r["mem_mb"] is None else "%.0f" % r["mem_mb"],
                                                                    "-" if r["cpu_core_pct"] is None else "%.0f" % r["cpu_core_pct"]))
    out.append("")
    out.append("Failures: %d total %s" % (errors, dict(S.err) if S.err else ""))
    out.append("Live-update trouble: dropped %d, failed to open %d, refused %d; fallback polls %d; missed events rescued by polling %d; orders a kitchen only found by refreshing %d"
               % (S.cnt["sse_dropped"], S.cnt["sse_failed"], S.cnt["sse_refused"], S.cnt["fallback_polls"], S.cnt["poll_rescued_missed_event"], S.cnt["kitchen_reconcile_found_missed_order"]))
    out.append("")
    out.append("Database check:")
    for k, val in v.items():
        out.append("  %-58s %s" % (k, val))
    # resource trend
    mem_trend_ok, thread_ok = True, True
    if len(samples) > 6:
        third = max(1, len(samples) // 3)
        early = statistics.mean(s[2] for s in samples[third:2 * third]) / 1e6
        late = statistics.mean(s[2] for s in samples[-third:]) / 1e6
        growth = late / early if early else 1
        mem_trend_ok = growth < 1.5
        cpu = [(b[1] - a[1]) / (b[0] - a[0]) * 100 for a, b in zip(samples, samples[1:]) if b[0] > a[0]]
        out.append("")
        out.append("Server process: peak threads %d (at end %d), memory early %.0f MB -> late %.0f MB (x%.2f, %s), peak %.0f MB, CPU avg %.0f%% / peak %.0f%% of one core"
                   % (max(s[3] for s in samples), samples[-1][3], early, late, growth, "stable" if mem_trend_ok else "GROWING", max(s[2] for s in samples) / 1e6, statistics.mean(cpu), max(cpu)))
        thread_ok = samples[-1][3] < 200
    windows_ok = all(r["post_p95"] is None or r["post_p95"] <= 1.0 for r in rows) and all(r["prop_p95"] is None or r["prop_p95"] <= 1.0 for r in rows)
    integrity = (v["acked_but_missing_from_db (LOST ORDERS)"] == 0 and v["duplicate_token_numbers_within_an_outlet"] == 0 and v["orders_with_wrong_total"] == 0
                 and v["orders_without_lines"] == 0 and v["sqlite_integrity_check"] == "ok"
                 and v.get("takeaway_without_name", 0) == 0 and v.get("dine_in_table_out_of_range", 0) == 0 and v.get("takeaway_with_a_table_number", 0) == 0)
    passed = all(ok for _, ok in rows_total) and errors == 0 and integrity and windows_ok and S.cnt["orders_stuck"] == 0 and mem_trend_ok and thread_ok
    out.append("")
    out.append("Checks: every window p95<=1s %s | no errors %s | no lost/duplicate/inconsistent orders %s | memory stable %s | threads released %s"
               % ("PASS" if windows_ok else "FAIL", "PASS" if errors == 0 else "FAIL", "PASS" if integrity else "FAIL", "PASS" if mem_trend_ok else "FAIL", "PASS" if thread_ok else "FAIL"))
    out.append("OVERALL: %s" % ("PASS" if passed else "FAIL"))
    text = "\n".join(out)
    print(text)
    with open(os.path.join(HERE, "results", "%s.txt" % cfg.name), "w", encoding="utf-8") as fh:
        fh.write(text + "\n")
    return passed


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--name", default="soak10")
    ap.add_argument("--server", default="server.py")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8100)
    ap.add_argument("--cities", type=int, default=5)
    ap.add_argument("--per-city", type=int, default=5)
    ap.add_argument("--tables", type=int, default=50)
    ap.add_argument("--takeaway", type=int, default=100, help="takeaway customers per outlet at any moment")
    ap.add_argument("--duration", type=float, default=600, help="seconds of non-stop ordering")
    ap.add_argument("--ramp", type=float, default=20, help="seconds over which the seats first order")
    ap.add_argument("--cooks", type=int, default=12)
    ap.add_argument("--cook-time", type=float, nargs=2, default=[2.0, 4.0], metavar=("MIN", "MAX"))
    ap.add_argument("--dine-think", type=float, nargs=2, default=[15, 45], metavar=("MIN", "MAX"), help="seconds a table waits before reordering")
    ap.add_argument("--takeaway-think", type=float, nargs=2, default=[8, 25], metavar=("MIN", "MAX"))
    ap.add_argument("--owners", type=int, default=10)
    ap.add_argument("--speed", type=float, default=1.0)
    ap.add_argument("--track-timeout", type=float, default=180)
    cfg = ap.parse_args()
    random.seed(11)
    result = asyncio.run(run(cfg))
    if result is None:
        sys.exit(2)
    sys.exit(0 if report(cfg, *result) else 1)


if __name__ == "__main__":
    main()
