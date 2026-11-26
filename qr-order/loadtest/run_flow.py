#!/usr/bin/env python3
"""10-minute test of the NEW ordering flow. Every store, non-stop:
  * 50 dine-in tables: order, see a confirmation (no live connection, no checking), wait for the waiter,
  * 100 takeaway customers: start payment, spend a few seconds paying, payment confirmed, then ask "is it ready?"
    every 30 s (no live connection), collect at the counter,
  * a kitchen screen (auto-accept on, done by the server) whose cooks only get food when ITS slip prints,
  * a counter token board (one live connection), plus owner dashboards.
Each store prints one kitchen slip every --gap seconds; always-ready items print at once.

    python run_flow.py --name flow-gap5 --gap 5
    python run_flow.py --name flow-gap2 --gap 2
Standard library only. Client and server share one computer.
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
import run_load as R  # noqa: E402
import run_soak as K  # noqa: E402

CHECK_EVERY = 30  # same as the app


class World:
    """Things that happen in the room, not over the network."""
    def __init__(self):
        self.delivered = collections.defaultdict(asyncio.Event)  # the food reached the guest
        self.at_counter = collections.defaultdict(asyncio.Event)  # a takeaway guest saw "ready" and walked up
        self.sent = collections.Counter()                         # requests by type
        self.end_stats = {}


async def req(cfg, S, W, label, method, path, body=None, token=None):
    W.sent[label] += 1
    s, d, lat, e = await R.request(cfg.host, cfg.port, method, path, body, token)
    if 200 <= s < 300:
        S.add(label, lat)
    else:
        S.fail("%s_%s" % (label, s or e))
    return s, d


async def wait_for(event, deadline):
    try:
        await asyncio.wait_for(event.wait(), max(0.01, deadline - time.time()))
        return True
    except asyncio.TimeoutError:
        return False


async def customer(cfg, S, W, slug, kind, seat, t_end, hard_end, delay):
    await asyncio.sleep(delay)
    while time.time() < t_end:
        menu = None
        for _ in range(3):
            t0 = time.perf_counter()
            (s1, _, _, e1), (s2, menu, _, e2) = await asyncio.gather(
                R.request(cfg.host, cfg.port, "GET", "/api/outlet/" + slug), R.request(cfg.host, cfg.port, "GET", "/api/menu/" + slug))
            W.sent["page_load"] += 2
            if s1 == 200 and s2 == 200:
                S.add("page_load", time.perf_counter() - t0)
                break
            S.fail("page_load_%s" % (e1 or e2 or (s1 if s1 != 200 else s2)))
            menu = None
            await asyncio.sleep(1)
        if not menu:
            await asyncio.sleep(2)
            continue
        items = [i for c in menu["categories"] for i in c["items"] if i["available"] and i["price"] > 0]
        picks = random.sample(items, random.randint(1, 4 if kind == "dine_in" else 3))
        body = {"outlet": slug, "lines": [{"item_id": i["id"], "qty": random.randint(1, 3)} for i in picks],
                "client_key": "%x" % random.getrandbits(64)}
        if kind == "dine_in":
            body["table"] = seat
            s, d = await req(cfg, S, W, "order_post", "POST", "/api/orders", body)
            if s not in (200, 201):
                await asyncio.sleep(2)
                continue
            pid = d["public_id"]
        else:
            body.update(name="Guest%03d" % seat, phone="9%09d" % random.randint(0, 999999999))
            s, d = await req(cfg, S, W, "pay_start", "POST", "/api/pay/start", body)
            if s != 201:
                await asyncio.sleep(2)
                continue
            await asyncio.sleep(random.uniform(*cfg.paying))  # typing card / UPI details
            s, d2 = await req(cfg, S, W, "pay_confirm", "POST", "/api/pay/test-complete", {"payment_ref": d["payment_ref"], "outcome": "success"})
            if s != 200 or not d2.get("order"):
                await asyncio.sleep(2)
                continue
            pid = d2["order"]
        S.acked.add(pid)
        S.cnt["orders_ok"] += 1
        S.cnt["orders_" + kind] += 1
        placed = time.time()
        if kind == "takeaway":
            await req(cfg, S, W, "takeaway_check", "GET", "/api/orders/" + pid)  # first screen after paying
            while not W.delivered[pid].is_set() and time.time() < hard_end:
                if await wait_for(W.delivered[pid], min(hard_end, time.time() + CHECK_EVERY)):
                    break
                if time.time() >= hard_end:
                    break
                s, od = await req(cfg, S, W, "takeaway_check", "GET", "/api/orders/" + pid)
                if s == 200 and od["status"] in ("ready", "served"):
                    W.at_counter[pid].set()
                    await wait_for(W.delivered[pid], min(hard_end, time.time() + 30))
                    break
        else:
            await wait_for(W.delivered[pid], hard_end)  # sits and waits; the phone does nothing
        if not W.delivered[pid].is_set():
            S.cnt["still_waiting_" + kind] += 1
            return
        S.add("order_to_food_" + kind, time.time() - placed)
        S.cnt["completed"] += 1
        await asyncio.sleep(random.uniform(*(cfg.dine_think if kind == "dine_in" else cfg.takeaway_think)))


async def kitchen(cfg, S, W, slug, stop):
    s, d, _, e = await R.request(cfg.host, cfg.port, "POST", "/api/login", {"scope": "kitchen", "slug": slug, "pin": "1111"})
    if s != 200:
        S.fail("kitchen_login_%s" % (s or e))
        return
    token = d["token"]
    cooking = asyncio.Queue()
    side = set()

    async def tap(pid, status):
        for _ in range(3):
            s2, _d = await req(cfg, S, W, "kitchen_tap", "POST", "/api/kitchen/%s/orders/%s/status" % (slug, pid), {"status": status}, token)
            if s2 == 200:
                return True
            if s2 == 409:
                return False
            await asyncio.sleep(1)
        return False

    async def hand_over(pid, kind):
        if kind == "takeaway":  # waits at the counter until the guest comes up (or the counter calls them out)
            await wait_for(W.at_counter[pid], time.time() + 60)
            await asyncio.sleep(2)
        else:
            await asyncio.sleep(random.uniform(0.5, 1.5))
        if await tap(pid, "served"):
            W.delivered[pid].set()

    def later(coro):
        task = asyncio.create_task(coro)
        side.add(task)
        task.add_done_callback(side.discard)

    def on_ev(name, data, now):
        if name == "order_new":
            S.add("order_to_screen", now - data["created_at"])
            if data["status"] == "ready":  # tea only: nothing to cook
                S.cnt["instant_only_orders"] += 1
                later(hand_over(data["public_id"], data["kind"]))
        elif name == "slip":
            S.add("slip_to_screen", now - data["printed_at"])
            if data["station"] == "kitchen":
                cooking.put_nowait((data["public_id"], data["kind"]))
                S.max_backlog = max(S.max_backlog, cooking.qsize())

    async def cook():
        while True:
            pid, kind = await cooking.get()
            await asyncio.sleep(random.uniform(*cfg.cook_time))
            if await tap(pid, "ready"):
                later(hand_over(pid, kind))

    async def watch_printer():  # the kitchen screen asks how long its queue is every 3 s
        while True:
            await asyncio.sleep(3)
            s2, st = await req(cfg, S, W, "printer_status", "GET", "/api/kitchen/%s/printer" % slug, None, token)
            if s2 == 200 and time.time() < W.t_end:
                W.end_stats[slug] = st
                S.tl["queue_waiting"].append((time.time() - S.t0, st["waiting"]))
                S.tl["queue_oldest"].append((time.time() - S.t0, st["oldest_wait"]))

    tasks = [asyncio.create_task(K.stream(cfg, S, "/api/stream?outlet=%s&t=%s" % (slug, token), on_ev, stop)),
             asyncio.create_task(K.stream(cfg, S, "/api/stream?board=" + slug, lambda *a: S.cnt.update(["board_events"]), stop)),
             asyncio.create_task(watch_printer())] + [asyncio.create_task(cook()) for _ in range(cfg.cooks)]
    await stop.wait()
    for t in tasks + list(side):
        t.cancel()


def verify(db_path, acked, gap):
    c = sqlite3.connect(db_path)
    one = lambda sql: c.execute(sql).fetchone()[0]
    res = collections.OrderedDict()
    res["orders_in_db"] = one("SELECT COUNT(*) FROM orders")
    ids = {r[0] for r in c.execute("SELECT public_id FROM orders")}
    res["orders_confirmed_to_customers"] = len(acked)
    res["confirmed_but_missing (LOST ORDERS)"] = len(acked - ids)
    res["saved_but_never_confirmed"] = len(ids - acked)
    res["duplicate_token_numbers_within_a_store"] = one("SELECT COUNT(*) FROM (SELECT outlet_id,token FROM orders GROUP BY outlet_id,token HAVING COUNT(*)>1)")
    res["orders_with_wrong_total"] = one("SELECT COUNT(*) FROM orders o WHERE o.total != (SELECT COALESCE(SUM(qty*price),0) FROM order_lines l WHERE l.order_id=o.id)")
    res["takeaway_orders_WITHOUT_a_paid_payment"] = one("SELECT COUNT(*) FROM orders o WHERE kind='takeaway' AND NOT EXISTS (SELECT 1 FROM payments p WHERE p.ref=o.payment_ref AND p.status='paid' AND p.amount=o.total)")
    res["paid_payments_WITHOUT_an_order"] = one("SELECT COUNT(*) FROM payments p WHERE status='paid' AND NOT EXISTS (SELECT 1 FROM orders o WHERE o.payment_ref=p.ref)")
    res["payments_that_made_two_orders"] = one("SELECT COUNT(*) FROM (SELECT payment_ref FROM orders WHERE payment_ref IS NOT NULL GROUP BY payment_ref HAVING COUNT(*)>1)")
    res["payments_started_but_not_finished"] = one("SELECT COUNT(*) FROM payments WHERE status='pending'")
    res["sqlite_integrity_check"] = one("PRAGMA integrity_check")
    per = collections.defaultdict(list)
    for oid, at in c.execute("SELECT outlet_id, printed_at FROM slips WHERE station='kitchen' AND status='printed' ORDER BY outlet_id, printed_at"):
        per[oid].append(at)
    gaps = [b - a for v in per.values() for a, b in zip(v, v[1:])]
    waits = sorted(r[0] for r in c.execute("SELECT printed_at-queued_at FROM slips WHERE station='kitchen' AND status='printed'"))
    pace = {"stores": len(per), "kitchen_printed": sum(len(v) for v in per.values()),
            "counter_printed": one("SELECT COUNT(*) FROM slips WHERE station='counter' AND status='printed'"),
            "still_queued": one("SELECT COUNT(*) FROM slips WHERE status='queued'"),
            "min_gap": min(gaps) if gaps else None, "median_gap": statistics.median(gaps) if gaps else None,
            "too_close": sum(1 for g in gaps if gap > 0 and g < gap - 0.15), "waits": waits}
    c.close()
    return res, pace


async def run(cfg):
    os.makedirs(os.path.join(HERE, "results"), exist_ok=True)
    db_path = os.path.join(HERE, "results", "%s.db" % cfg.name)
    subprocess.run([sys.executable, os.path.join(HERE, "seed_scale.py"), "--db", db_path, "--cities", str(cfg.cities), "--per-city", str(cfg.per_city),
                    "--tables", str(cfg.tables), "--print-gap", str(cfg.gap)], check=True)
    log = open(os.path.join(HERE, "results", "%s.server.log" % cfg.name), "w")
    srv = subprocess.Popen([sys.executable, os.path.join(ROOT, "server.py"), "--port", str(cfg.port), "--no-demo", "--test-pay"],
                           env=dict(os.environ, QRO_DB=db_path), stdout=log, stderr=log)
    samples, sstop = [], threading.Event()
    try:
        if not await R.wait_ready(cfg.host, cfg.port):
            print("server did not start")
            return None
        threading.Thread(target=R.sampler, args=(srv.pid, samples, sstop), daemon=True).start()
        outlets = ["scale-%s-%d" % (c, k) for c in R.CITIES[:cfg.cities] for k in range(1, cfg.per_city + 1)]
        print("%s: %d stores x (%d tables + %d takeaway), %d s non-stop, each store prints 1 kitchen slip every %s s"
              % (cfg.name, len(outlets), cfg.tables, cfg.takeaway, cfg.duration, cfg.gap), flush=True)
        stop = asyncio.Event()
        S, W = K.Soak(time.time()), World()
        W.t_end = time.time() + 10 ** 6
        bg = [asyncio.create_task(kitchen(cfg, S, W, o, stop)) for o in outlets]
        bg += [asyncio.create_task(K.owner(cfg, S, "scale-cafe", stop)) for _ in range(cfg.owners)]
        await asyncio.sleep(4)
        t0 = time.time()
        S.t0 = t0
        W.t_end = t0 + cfg.duration
        hard_end = W.t_end + cfg.grace
        people = []
        for o in outlets:
            people += [asyncio.create_task(customer(cfg, S, W, o, "dine_in", n, W.t_end, hard_end, random.uniform(0, cfg.ramp))) for n in range(1, cfg.tables + 1)]
            people += [asyncio.create_task(customer(cfg, S, W, o, "takeaway", n, W.t_end, hard_end, random.uniform(0, cfg.ramp))) for n in range(1, cfg.takeaway + 1)]

        async def monitor():
            last = 0
            while True:
                await asyncio.sleep(30)
                ok = S.cnt["orders_ok"]
                waiting = sum(v["waiting"] for v in W.end_stats.values())
                oldest = max((v["oldest_wait"] for v in W.end_stats.values()), default=0)
                print("  t+%3ds  orders %6d (+%.1f/s)  food delivered %6d  errors %d  live connections %d  slips waiting %d  longest wait %ds"
                      % (time.time() - t0, ok, (ok - last) / 30, S.cnt["completed"], sum(S.err.values()), S.live, waiting, oldest), flush=True)
                last = ok
        mon = asyncio.create_task(monitor())
        await asyncio.gather(*people)
        wall = time.time() - t0
        mon.cancel()
        stop.set()
        await asyncio.sleep(1)
        for t in bg:
            t.cancel()
        sstop.set()
        return S, W, samples, wall, db_path, len(outlets)
    finally:
        sstop.set()
        srv.terminate()
        try:
            srv.wait(15)
        except subprocess.TimeoutExpired:
            srv.kill()
        log.close()


def report(cfg, S, W, samples, wall, db_path, n):
    v, pace = verify(db_path, S.acked, cfg.gap)
    errors = sum(S.err.values())
    vals = lambda name: [x for _, x in S.tl.get(name, [])]
    out = ["=" * 118, "NEW-FLOW RESULT: %s   (1 kitchen slip every %s s per store)" % (cfg.name, cfg.gap), "=" * 118]
    out.append("%d stores x (%d tables + %d takeaway), %d s of non-stop ordering" % (n, cfg.tables, cfg.takeaway, cfg.duration))
    out.append("Orders placed: %d (dine-in %d, takeaway %d) = %.1f a second, %.1f a minute per store. Food delivered: %d. Still waiting at the end: dine-in %d, takeaway %d"
               % (S.cnt["orders_ok"], S.cnt["orders_dine_in"], S.cnt["orders_takeaway"], S.cnt["orders_ok"] / cfg.duration, S.cnt["orders_ok"] / (cfg.duration / 60) / n,
                  S.cnt["completed"], S.cnt["still_waiting_dine_in"], S.cnt["still_waiting_takeaway"]))
    out.append("Peak live connections: %d (kitchen screens + token boards only)" % S.live_peak)
    out.append("Requests sent: %d total %s" % (sum(W.sent.values()), dict(W.sent)))
    out.append("")
    out.append("Server speed (what a phone or tablet feels):")
    ok_all = True
    for label, name, target in [("menu page load (2 requests)", "page_load", 2.0), ("dine-in: place order", "order_post", 1.0), ("takeaway: start payment", "pay_start", 1.0),
                                ("takeaway: payment confirmed -> order", "pay_confirm", 1.0), ("takeaway: 'is it ready?'", "takeaway_check", 1.0),
                                ("kitchen tap", "kitchen_tap", 1.0), ("order -> kitchen screen", "order_to_screen", 1.0), ("printed slip -> kitchen screen", "slip_to_screen", 1.0),
                                ("owner overview", "owner_overview", 2.0)]:
        x = vals(name)
        if not x:
            out.append("  %-38s no data" % label)
            ok_all = False
            continue
        p95 = R.pct(x, 95)
        ok_all = ok_all and p95 <= target
        out.append("  %-38s n=%-6d p50 %6.0f ms  p95 %6.0f ms  p99 %6.0f ms  max %6.0f ms  target p95<=%d ms  %s"
                   % (label, len(x), R.pct(x, 50) * 1000, p95 * 1000, R.pct(x, 99) * 1000, max(x) * 1000, target * 1000, "PASS" if p95 <= target else "FAIL"))
    out.append("")
    out.append("The print queue and the wait for food (per store):")
    w = pace["waits"]
    if w:
        out.append("  kitchen slips printed %d, always-ready slips printed at once %d, still in a queue at the end %d" % (pace["kitchen_printed"], pace["counter_printed"], pace["still_queued"]))
        out.append("  time a kitchen slip waited to print: median %.0f s, p95 %.0f s, longest %.0f s" % (R.pct(w, 50), R.pct(w, 95), w[-1]))
        out.append("  pacing check: shortest gap between two slips at one store %.2f s, median %.2f s, slips closer than the setting: %d" % (pace["min_gap"], pace["median_gap"], pace["too_close"]))
    ends = list(W.end_stats.values())
    if ends:
        out.append("  at the 10-minute mark: slips waiting per store average %.0f, worst %d; oldest waiting slip up to %d s"
                   % (statistics.mean(e["waiting"] for e in ends), max(e["waiting"] for e in ends), max(e["oldest_wait"] for e in ends)))
    for label, name in [("dine-in: order -> food on table", "order_to_food_dine_in"), ("takeaway: paid -> collected", "order_to_food_takeaway")]:
        x = vals(name)
        if x:
            out.append("  %-34s (delivered ones only) median %.0f s, p95 %.0f s, longest %.0f s" % (label, R.pct(x, 50), R.pct(x, 95), max(x)))
    out.append("")
    out.append("Minute by minute:")
    out.append("  %-7s %9s %10s %14s %14s %14s" % ("minute", "orders/s", "errors", "order p95 ms", "slips waiting", "oldest wait s"))
    for m in range(int(cfg.duration // 60)):
        lo, hi = m * 60, (m + 1) * 60
        win = lambda name: [x for t, x in S.tl.get(name, []) if lo <= t < hi]
        placed = len(win("order_post")) + len(win("pay_confirm"))
        op = win("order_post")
        qw, qo = win("queue_waiting"), win("queue_oldest")
        out.append("  %-7d %9.1f %10d %14s %14s %14s" % (m + 1, placed / 60, sum(1 for t, _ in S.err_tl if lo <= t < hi),
                                                       "-" if not op else "%.0f" % (R.pct(op, 95) * 1000),
                                                       "-" if not qw else "%.0f avg" % statistics.mean(qw), "-" if not qo else "%d" % max(qo)))
    out.append("")
    out.append("Failures: %d total %s" % (errors, dict(S.err) if S.err else ""))
    out.append("")
    out.append("Database check:")
    for k, val in v.items():
        out.append("  %-48s %s" % (k, val))
    if len(samples) > 6:
        cpu = [(b[1] - a[1]) / (b[0] - a[0]) * 100 for a, b in zip(samples, samples[1:]) if b[0] > a[0]]
        out.append("")
        out.append("Server process: peak threads %d, peak memory %.0f MB, CPU average %.0f%% / peak %.0f%% of one core"
                   % (max(s[3] for s in samples), max(s[2] for s in samples) / 1e6, statistics.mean(cpu), max(cpu)))
    tracebacks = open(os.path.join(HERE, "results", "%s.server.log" % cfg.name)).read().count("Traceback")
    integrity = (v["confirmed_but_missing (LOST ORDERS)"] == 0 and v["duplicate_token_numbers_within_a_store"] == 0 and v["orders_with_wrong_total"] == 0
                 and v["takeaway_orders_WITHOUT_a_paid_payment"] == 0 and v["paid_payments_WITHOUT_an_order"] == 0 and v["payments_that_made_two_orders"] == 0
                 and v["sqlite_integrity_check"] == "ok")
    passed = ok_all and errors == 0 and integrity and pace["too_close"] == 0 and tracebacks == 0
    out.append("")
    out.append("Server tracebacks: %d" % tracebacks)
    out.append("Checks: server speed %s | no failed requests %s | orders and payments consistent %s | print pacing respected %s"
               % ("PASS" if ok_all else "FAIL", "PASS" if errors == 0 else "FAIL", "PASS" if integrity else "FAIL", "PASS" if pace["too_close"] == 0 else "FAIL"))
    out.append("SERVER VERDICT: %s   (this does not judge how long guests wait for food: see the print queue above)" % ("PASS" if passed else "FAIL"))
    text = "\n".join(out)
    print(text)
    with open(os.path.join(HERE, "results", "%s.txt" % cfg.name), "w", encoding="utf-8") as fh:
        fh.write(text + "\n")
    return passed


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--name", default="flow-gap5")
    ap.add_argument("--gap", type=float, default=5)
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8100)
    ap.add_argument("--cities", type=int, default=5)
    ap.add_argument("--per-city", type=int, default=5)
    ap.add_argument("--tables", type=int, default=50)
    ap.add_argument("--takeaway", type=int, default=100)
    ap.add_argument("--duration", type=float, default=600)
    ap.add_argument("--grace", type=float, default=60, help="seconds after the last order to finish what is in progress")
    ap.add_argument("--ramp", type=float, default=20)
    ap.add_argument("--cooks", type=int, default=12)
    ap.add_argument("--cook-time", type=float, nargs=2, default=[2.0, 4.0])
    ap.add_argument("--paying", type=float, nargs=2, default=[5, 15])
    ap.add_argument("--dine-think", type=float, nargs=2, default=[15, 45])
    ap.add_argument("--takeaway-think", type=float, nargs=2, default=[8, 25])
    ap.add_argument("--owners", type=int, default=10)
    ap.add_argument("--speed", type=float, default=1.0)
    cfg = ap.parse_args()
    random.seed(11)
    result = asyncio.run(run(cfg))
    if result is None:
        sys.exit(2)
    sys.exit(0 if report(cfg, *result) else 1)


if __name__ == "__main__":
    main()
