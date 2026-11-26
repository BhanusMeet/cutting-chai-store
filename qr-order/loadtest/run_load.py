#!/usr/bin/env python3
"""Peak-traffic simulation for the QR ordering platform.

Simulates, against a real server process and a separate database:
  * every table of every outlet occupied by a guest who loads the menu, places an
    order, and watches the live tracker (one live connection per guest),
  * a kitchen per outlet (live board, a few cooks moving tickets along),
  * owner dashboards polling the head-office overview.
Then it checks the database for lost, duplicated or stuck orders.

    python run_load.py --name peak --burst 20
    python run_load.py --name spike --burst 3
Standard library only. Client and server share this one computer, so numbers are a
conservative floor compared with a real server on its own hardware.
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
CITIES = ["mumbai", "delhi", "bengaluru", "chennai", "kolkata", "hyderabad", "pune", "ahmedabad"]


class Metrics:
    def __init__(self):
        self.lat = collections.defaultdict(list)
        self.cnt = collections.Counter()
        self.err = collections.Counter()
        self.sse_now = 0
        self.sse_peak = 0
        self.tap = {}          # (public_id, status) -> time the kitchen pressed the button
        self.acked = set()     # public ids the guests were told succeeded


def pct(xs, p):
    if not xs:
        return None
    xs = sorted(xs)
    return xs[min(len(xs) - 1, int(round(p / 100.0 * (len(xs) - 1))))]


# ------------------------------------------------------------------ tiny async HTTP client
async def request(host, port, method, path, body=None, token=None, timeout=30):
    t0 = time.perf_counter()
    try:
        r, w = await asyncio.wait_for(asyncio.open_connection(host, port), 20)
        payload = json.dumps(body).encode() if body is not None else b""
        head = "%s %s HTTP/1.0\r\nHost: %s\r\nConnection: close\r\nContent-Length: %d\r\n" % (method, path, host, len(payload))
        if body is not None:
            head += "Content-Type: application/json\r\n"
        if token:
            head += "Authorization: Bearer %s\r\n" % token
        w.write(head.encode() + b"\r\n" + payload)
        await w.drain()
        raw = await asyncio.wait_for(r.read(-1), timeout)
        w.close()
        h, _, rest = raw.partition(b"\r\n\r\n")
        status = int(h.split(b" ", 2)[1])
        return status, (json.loads(rest) if rest else None), time.perf_counter() - t0, None
    except asyncio.TimeoutError:
        return 0, None, time.perf_counter() - t0, "timeout"
    except (ConnectionError, OSError) as e:
        return 0, None, time.perf_counter() - t0, type(e).__name__
    except (ValueError, IndexError):
        return 0, None, time.perf_counter() - t0, "bad_response"


async def sse(host, port, path, on_event, M, stop=None):
    """Open a live stream and feed events to on_event(name, data, wall_time). Returns False if it never opened.
    `stop` ends the stream cleanly. (Cancelling alone is not enough: Python can swallow a cancel that lands while a
    line is arriving, which left connections open in an earlier version of this test.)"""
    w = None
    try:
        r, w = await asyncio.wait_for(asyncio.open_connection(host, port), 20)
        w.write(("GET %s HTTP/1.0\r\nHost: %s\r\n\r\n" % (path, host)).encode())
        await w.drain()
        line = await asyncio.wait_for(r.readline(), 20)
        if b" 200" not in line:
            M.cnt["sse_refused"] += 1
            return False
        while True:
            hl = await asyncio.wait_for(r.readline(), 20)
            if hl in (b"\r\n", b""):
                break
        M.sse_now += 1
        M.sse_peak = max(M.sse_peak, M.sse_now)
        M.cnt["sse_opened"] += 1
        ev = None
        try:
            while True:
                line = await asyncio.wait_for(r.readline(), 60)  # server sends a keepalive every 15 s
                if stop is not None and stop.is_set():
                    return True
                if not line:
                    M.cnt["sse_dropped"] += 1
                    return True
                line = line.decode().rstrip("\r\n")
                if line.startswith("event: "):
                    ev = line[7:]
                elif line.startswith("data: ") and ev:
                    on_event(ev, json.loads(line[6:]), time.time())
                    ev = None
        finally:
            M.sse_now -= 1
    except asyncio.CancelledError:
        raise
    except (asyncio.TimeoutError, ConnectionError, OSError):
        M.cnt["sse_failed"] += 1
        return False
    finally:
        if w is not None:
            try:
                w.close()
            except Exception:
                pass


# ------------------------------------------------------------------ simulated people
async def guest(cfg, M, slug, table, delay):
    await asyncio.sleep(delay)
    for rnd in range(cfg.waves):
        if rnd > 0:
            if random.random() > cfg.reorder:
                return
            await asyncio.sleep(random.uniform(2, 10) / cfg.speed)
        menu = None
        for attempt in range(3):  # a guest whose page fails to load just refreshes
            (s1, _, l1, e1), (s2, menu, l2, e2) = await asyncio.gather(
                request(cfg.host, cfg.port, "GET", "/api/outlet/" + slug), request(cfg.host, cfg.port, "GET", "/api/menu/" + slug))
            if s1 == 200 and s2 == 200:
                M.lat["page_load"].append(max(l1, l2))
                break
            M.err["page_load_%s" % (s1 or e1 or s2 or e2)] += 1
            menu = None
            await asyncio.sleep(1)
        if not menu:
            M.cnt["guests_gave_up"] += 1
            return
        items = [i for c in menu["categories"] for i in c["items"] if i["available"]]
        picks = random.sample(items, random.randint(1, 4))
        body = {"outlet": slug, "table": table, "name": "", "lines": [{"item_id": i["id"], "qty": random.randint(1, 3)} for i in picks]}
        s, d, lat, e = await request(cfg.host, cfg.port, "POST", "/api/orders", body)
        M.cnt["order_attempts"] += 1
        if s != 201:
            M.err["order_%s" % (s or e)] += 1
            continue
        M.lat["order_post"].append(lat)
        M.cnt["orders_ok"] += 1
        pid = d["public_id"]
        M.acked.add(pid)
        await track(cfg, M, slug, pid)


async def track(cfg, M, slug, pid):
    done = asyncio.Event()
    last = ["new"]

    def on_ev(name, data, now):
        if name == "snapshot":  # the server tells a newly connected tracker where its order already is
            last[0] = data["status"]
            if last[0] in ("served", "cancelled"):
                done.set()
            return
        if name != "status":
            return
        st = data["status"]
        t0 = M.tap.get((pid, st))
        if t0:
            M.lat["status_propagation"].append(now - t0)
        last[0] = st
        if st in ("served", "cancelled"):
            done.set()

    stream = asyncio.create_task(sse(cfg.host, cfg.port, "/api/stream?order=" + pid, on_ev, M, done))

    async def poller():  # the real app also polls every 10 s as a safety net
        while not done.is_set():
            await asyncio.sleep(10)
            s, d, _, _ = await request(cfg.host, cfg.port, "GET", "/api/orders/" + pid)
            if s == 200 and d["status"] != last[0]:
                M.cnt["poll_rescued_missed_event"] += 1
                last[0] = d["status"]
                if last[0] in ("served", "cancelled"):
                    done.set()

    poll = asyncio.create_task(poller())
    try:
        await asyncio.wait_for(done.wait(), cfg.track_timeout)
        M.cnt["orders_completed"] += 1
    except asyncio.TimeoutError:
        M.cnt["orders_stuck"] += 1
    finally:
        stream.cancel()
        poll.cancel()


async def kitchen(cfg, M, slug, stop):
    s, d, _, e = await request(cfg.host, cfg.port, "POST", "/api/login", {"scope": "kitchen", "slug": slug, "pin": "1111"})
    if s != 200:
        M.err["kitchen_login_%s" % (s or e)] += 1
        return
    token = d["token"]
    q = asyncio.Queue()
    seen = set()

    def enqueue(o):
        if o["public_id"] not in seen:
            seen.add(o["public_id"])
            q.put_nowait(o)

    def on_ev(name, data, now):
        if name == "order_new":
            M.lat["kitchen_delivery"].append(now - data["created_at"])
            enqueue(data)

    async def tap(o, status):
        # Like a real cook: if the screen shows an error, press the button again (up to 3 tries).
        # Every failed attempt is still counted as an error.
        for attempt in range(3):
            M.tap[(o["public_id"], status)] = time.time()
            s2, _, lat, e2 = await request(cfg.host, cfg.port, "POST", "/api/kitchen/%s/orders/%s/status" % (slug, o["public_id"]), {"status": status}, token)
            if s2 == 200:
                M.lat["kitchen_tap"].append(lat)
                return True
            M.err["kitchen_tap_%s" % (s2 or e2)] += 1
            await asyncio.sleep(1)
        return False

    async def cook():
        while True:
            o = await q.get()
            if not await tap(o, "preparing"):
                continue
            await asyncio.sleep(random.uniform(*cfg.cook_time) / cfg.speed)
            if not await tap(o, "ready"):
                continue
            await asyncio.sleep(random.uniform(0.5, 1.5) / cfg.speed)
            await tap(o, "served")

    async def reconcile():  # a real cook refreshes the screen now and then; also catches any missed live event
        while True:
            await asyncio.sleep(20)
            s2, d2, _, _ = await request(cfg.host, cfg.port, "GET", "/api/kitchen/%s/orders" % slug, None, token)
            if s2 == 200:
                for o in d2["orders"]:
                    if o["status"] == "new" and o["public_id"] not in seen:
                        M.cnt["kitchen_reconcile_found_missed_order"] += 1
                        enqueue(o)

    tasks = [asyncio.create_task(sse(cfg.host, cfg.port, "/api/stream?outlet=%s&t=%s" % (slug, token), on_ev, M, stop)),
             asyncio.create_task(reconcile())] + [asyncio.create_task(cook()) for _ in range(cfg.cooks)]
    await stop.wait()
    for t in tasks:
        t.cancel()


async def owner(cfg, M, brand, stop):
    s, d, _, e = await request(cfg.host, cfg.port, "POST", "/api/login", {"scope": "admin", "slug": brand, "pin": "1111"})
    if s != 200:
        M.err["owner_login_%s" % (s or e)] += 1
        return
    while not stop.is_set():
        s, _, lat, e = await request(cfg.host, cfg.port, "GET", "/api/admin/%s/overview" % brand, None, d["token"])
        if s == 200:
            M.lat["owner_overview"].append(lat)
        else:
            M.err["owner_overview_%s" % (s or e)] += 1
        try:
            await asyncio.wait_for(stop.wait(), 3)
        except asyncio.TimeoutError:
            pass


# ------------------------------------------------------------------ server process + resource sampling
def sampler(pid, out, stop):
    while not stop.is_set():
        try:
            r = subprocess.run(["powershell", "-NoProfile", "-Command",
                                "$p=Get-Process -Id %d -ErrorAction Stop; '{0} {1} {2} {3}' -f $p.CPU,$p.WorkingSet64,$p.Threads.Count,$p.HandleCount" % pid],
                               capture_output=True, text=True, timeout=10)
            cpu, ws, th, hd = r.stdout.split()
            out.append((time.time(), float(cpu), int(ws), int(th), int(hd)))
        except Exception:
            pass
        stop.wait(2)


def verify_db(db_path, acked):
    c = sqlite3.connect(db_path)
    res = {}
    res["orders_in_db"] = c.execute("SELECT COUNT(*) FROM orders").fetchone()[0]
    res["orders_acked_to_guests"] = len(acked)
    ids = {r[0] for r in c.execute("SELECT public_id FROM orders")}
    res["in_db_but_never_acked (possible duplicates/lost replies)"] = len(ids - acked)
    res["acked_but_missing_from_db (LOST ORDERS)"] = len(acked - ids)
    res["duplicate_token_numbers"] = c.execute("SELECT COUNT(*) FROM (SELECT outlet_id, token FROM orders GROUP BY outlet_id, token HAVING COUNT(*)>1)").fetchone()[0]
    res["status_counts"] = dict(c.execute("SELECT status, COUNT(*) FROM orders GROUP BY status").fetchall())
    res["orders_with_wrong_total"] = c.execute("""SELECT COUNT(*) FROM orders o WHERE o.total != (SELECT COALESCE(SUM(qty*price),0) FROM order_lines l WHERE l.order_id=o.id)""").fetchone()[0]
    res["orders_without_lines"] = c.execute("SELECT COUNT(*) FROM orders o WHERE NOT EXISTS (SELECT 1 FROM order_lines l WHERE l.order_id=o.id)").fetchone()[0]
    res["table_out_of_range"] = c.execute("SELECT COUNT(*) FROM orders o JOIN outlets u ON u.id=o.outlet_id WHERE o.table_no<1 OR o.table_no>u.tables_count").fetchone()[0]
    c.close()
    return res


async def wait_ready(host, port, tries=60):
    for _ in range(tries):
        s, *_ = await request(host, port, "GET", "/api/health", None, None, 2)
        if s == 200:
            return True
        await asyncio.sleep(0.5)
    return False


async def run(cfg):
    os.makedirs(os.path.join(HERE, "results"), exist_ok=True)
    db_path = os.path.join(HERE, "results", "%s.db" % cfg.name)
    subprocess.run([sys.executable, os.path.join(HERE, "seed_scale.py"), "--db", db_path, "--cities", str(cfg.cities),
                    "--per-city", str(cfg.per_city), "--tables", str(cfg.tables)], check=True)
    env = dict(os.environ, QRO_DB=db_path)
    log = open(os.path.join(HERE, "results", "%s.server.log" % cfg.name), "w")
    srv = subprocess.Popen([sys.executable, os.path.join(ROOT, cfg.server), "--port", str(cfg.port), "--no-demo"], env=env, stdout=log, stderr=log)
    M = Metrics()
    samples, sstop = [], threading.Event()
    try:
        if not await wait_ready(cfg.host, cfg.port):
            print("server did not start; see results/%s.server.log" % cfg.name)
            return None
        threading.Thread(target=sampler, args=(srv.pid, samples, sstop), daemon=True).start()
        outlets = ["scale-%s-%d" % (c, k) for c in CITIES[:cfg.cities] for k in range(1, cfg.per_city + 1)]
        tables = len(outlets) * cfg.tables
        print("scenario %s: %d outlets x %d tables = %d tables, %d wave(s), burst %ss, %d cooks/outlet, %d owner dashboards"
              % (cfg.name, len(outlets), cfg.tables, tables, cfg.waves, cfg.burst, cfg.cooks, cfg.owners))
        stop = asyncio.Event()
        bg = [asyncio.create_task(kitchen(cfg, M, o, stop)) for o in outlets]
        bg += [asyncio.create_task(owner(cfg, M, "scale-cafe", stop)) for _ in range(cfg.owners)]
        await asyncio.sleep(3)  # kitchens log in and connect before the rush
        t0 = time.time()
        guests = [asyncio.create_task(guest(cfg, M, o, t, random.uniform(0, cfg.burst))) for o in outlets for t in range(1, cfg.tables + 1)]
        monitor_stop = asyncio.Event()

        async def monitor():
            while not monitor_stop.is_set():
                await asyncio.sleep(10)
                print("  t+%3ds  orders ok %4d  completed %4d  errors %d  live connections %d"
                      % (time.time() - t0, M.cnt["orders_ok"], M.cnt["orders_completed"], sum(M.err.values()), M.sse_now), flush=True)
        mon = asyncio.create_task(monitor())
        await asyncio.gather(*guests)
        wall = time.time() - t0
        await asyncio.sleep(2)
        M.guest_conns_open_at_end = M.sse_now - len(outlets)  # kitchens keep one stream each; guests should hold none
        monitor_stop.set(); mon.cancel()
        stop.set()
        await asyncio.sleep(1)
        for t in bg:
            t.cancel()
        sstop.set()
        return M, samples, wall, db_path, tables
    finally:
        sstop.set()
        srv.terminate()
        try:
            srv.wait(10)
        except subprocess.TimeoutExpired:
            srv.kill()
        log.close()


def report(cfg, M, samples, wall, db_path, tables):
    L = M.lat
    def row(name, key, slo):
        xs = L.get(key, [])
        if not xs:
            return "  %-34s no data" % name, False
        p95 = pct(xs, 95)
        ok = p95 <= slo
        return "  %-34s n=%-5d p50 %5.0f ms  p95 %6.0f ms  p99 %6.0f ms  max %6.0f ms   target p95<=%d ms  %s" % (
            name, len(xs), pct(xs, 50) * 1000, p95 * 1000, pct(xs, 99) * 1000, max(xs) * 1000, slo * 1000, "PASS" if ok else "FAIL"), ok

    rows = [row("menu page load (2 requests)", "page_load", 2.0), row("place order", "order_post", 1.0),
            row("order -> visible on kitchen screen", "kitchen_delivery", 1.0), row("kitchen tap -> guest phone updates", "status_propagation", 1.0),
            row("kitchen status tap (API)", "kitchen_tap", 1.0), row("owner overview refresh", "owner_overview", 2.0)]
    v = verify_db(db_path, M.acked)
    errors = sum(M.err.values())
    integrity_ok = (v["acked_but_missing_from_db (LOST ORDERS)"] == 0 and v["duplicate_token_numbers"] == 0 and v["orders_with_wrong_total"] == 0
                    and v["orders_without_lines"] == 0 and v["table_out_of_range"] == 0)
    out = []
    out.append("=" * 100)
    out.append("RESULT: %s" % cfg.name)
    out.append("=" * 100)
    out.append("Load: %d tables ordering, %d order attempts, %d accepted, finished in %.0f s (%.1f orders/s over the whole run)"
               % (tables, M.cnt["order_attempts"], M.cnt["orders_ok"], wall, M.cnt["orders_ok"] / wall))
    out.append("Peak live connections held open at once: %d   (guest connections still open after everyone finished: %d, should be 0)"
               % (M.sse_peak, getattr(M, "guest_conns_open_at_end", -1)))
    out.append("")
    out.append("Delays (client-side, includes queueing inside the server):")
    for text, _ in rows:
        out.append(text)
    out.append("")
    out.append("Failures: %d total %s" % (errors, dict(M.err) if M.err else ""))
    out.append("Orders completed end to end: %d / %d   stuck (never reached 'served'): %d" % (M.cnt["orders_completed"], M.cnt["orders_ok"], M.cnt["orders_stuck"]))
    out.append("Live-update trouble: dropped %d, failed to open %d, refused %d, guests who needed the 10 s fallback poll %d, orders a kitchen only found by refreshing %d"
               % (M.cnt["sse_dropped"], M.cnt["sse_failed"], M.cnt["sse_refused"], M.cnt["poll_rescued_missed_event"], M.cnt["kitchen_reconcile_found_missed_order"]))
    out.append("")
    out.append("Database check:")
    for k, val in v.items():
        out.append("  %-62s %s" % (k, val))
    if len(samples) > 2:
        cpu = [(b[0] - a[0], b[1] - a[1]) for a, b in zip(samples, samples[1:]) if b[0] > a[0]]
        util = [dc / dt * 100 for dt, dc in cpu]
        out.append("")
        out.append("Server process: peak threads %d (at end %d), peak memory %.0f MB, peak handles %d, CPU avg %.0f%% / peak %.0f%% of one core"
                   % (max(s[3] for s in samples), samples[-1][3], max(s[2] for s in samples) / 1e6, max(s[4] for s in samples), statistics.mean(util), max(util)))
    passed = all(ok for _, ok in rows) and errors == 0 and integrity_ok and M.cnt["orders_stuck"] == 0
    out.append("")
    out.append("OVERALL: %s" % ("PASS" if passed else "FAIL"))
    text = "\n".join(out)
    print(text)
    with open(os.path.join(HERE, "results", "%s.txt" % cfg.name), "w", encoding="utf-8") as f:
        f.write(text + "\n")
    return passed


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--name", default="peak")
    ap.add_argument("--server", default="server.py", help="server file relative to qr-order/")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8100)
    ap.add_argument("--cities", type=int, default=5)
    ap.add_argument("--per-city", type=int, default=5)
    ap.add_argument("--tables", type=int, default=50)
    ap.add_argument("--waves", type=int, default=2, help="rounds of ordering per table")
    ap.add_argument("--reorder", type=float, default=0.6, help="chance a table orders again after being served")
    ap.add_argument("--burst", type=float, default=20, help="seconds over which the first wave of orders arrives")
    ap.add_argument("--cooks", type=int, default=6)
    ap.add_argument("--cook-time", type=float, nargs=2, default=[2.0, 4.0], metavar=("MIN", "MAX"))
    ap.add_argument("--owners", type=int, default=10)
    ap.add_argument("--speed", type=float, default=1.0, help="divides all human delays")
    ap.add_argument("--track-timeout", type=float, default=120)
    cfg = ap.parse_args()
    random.seed(7)
    result = asyncio.run(run(cfg))
    if result is None:
        sys.exit(2)
    sys.exit(0 if report(cfg, *result) else 1)


if __name__ == "__main__":
    main()
