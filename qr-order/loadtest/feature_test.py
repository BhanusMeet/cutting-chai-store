#!/usr/bin/env python3
"""Checks paid takeaway (including attempts to cheat it), auto-accept, per-store print pacing, instant items,
manual accept, rejection and the token board. Starts its own server on a throwaway database.
    python feature_test.py
"""
import hashlib
import hmac
import json
import os
import sqlite3
import subprocess
import sys
import time
import urllib.error
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
PORT = 8110
BASE = "http://127.0.0.1:%d" % PORT
SECRET = "feature-test-secret"
A, B = "scale-mumbai-1", "scale-mumbai-2"
results = []


def call(method, path, body=None, token=None, raw=None, headers=None):
    data = raw if raw is not None else (json.dumps(body).encode() if body is not None else None)
    req = urllib.request.Request(BASE + path, data=data, method=method)
    if token:
        req.add_header("Authorization", "Bearer " + token)
    for k, v in (headers or {}).items():
        req.add_header(k, v)
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            return r.status, json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read() or b"{}")


def check(name, ok, detail=""):
    results.append(ok)
    print("%-4s %s %s" % ("PASS" if ok else "FAIL", name, ("- " + str(detail)) if detail != "" else ""), flush=True)


def main():
    os.makedirs(os.path.join(HERE, "results"), exist_ok=True)
    dbp = os.path.join(HERE, "results", "feature.db")
    subprocess.run([sys.executable, os.path.join(HERE, "seed_scale.py"), "--db", dbp, "--cities", "1", "--per-city", "2", "--tables", "20", "--print-gap", "1"], check=True, capture_output=True)
    log = open(os.path.join(HERE, "results", "feature.server.log"), "w")
    srv = subprocess.Popen([sys.executable, os.path.join(ROOT, "server.py"), "--port", str(PORT), "--no-demo", "--test-pay"],
                           env=dict(os.environ, QRO_DB=dbp, QRO_PAY_SECRET=SECRET), stdout=log, stderr=log)
    db = None
    try:
        for _ in range(60):
            try:
                if call("GET", "/api/info")[0] == 200:
                    break
            except Exception:
                time.sleep(0.25)
        db = sqlite3.connect(dbp)
        q = lambda sql, *a: db.execute(sql, a).fetchall()
        menu = {i["slug"]: i for c in call("GET", "/api/menu/" + A)[1]["categories"] for i in c["items"]}
        iid = lambda s: menu[s]["id"]
        line = lambda s, n=1: {"item_id": iid(s), "qty": n}
        kt = call("POST", "/api/login", {"scope": "kitchen", "slug": A, "pin": "1111"})[1]["token"]
        at = call("POST", "/api/login", {"scope": "admin", "slug": "scale-cafe", "pin": "1111"})[1]["token"]
        orders = lambda: q("SELECT COUNT(*) FROM orders")[0][0]

        print("-- paid takeaway")
        base = {"outlet": A, "name": "Ravi", "lines": [line("vada-pav", 2)]}
        s, d = call("POST", "/api/orders", dict(base, kind="takeaway"))
        check("a phone cannot send unpaid takeaway to the kitchen", s == 402 and orders() == 0, s)
        s, d = call("POST", "/api/pay/start", base)
        check("payment needs a phone number", s == 400, d.get("error"))
        s, d = call("POST", "/api/pay/start", dict(base, phone="12345"))
        check("a bad phone number is refused", s == 400, d.get("error"))
        pay = dict(base, phone="+91 98765 43210", client_key="try-1")
        s, p = call("POST", "/api/pay/start", pay)
        check("payment starts with the price worked out by the server", s == 201 and p["amount"] == 30, p.get("amount"))
        check("starting payment sends nothing to the kitchen", orders() == 0)
        check("pressing pay twice reuses the same payment", call("POST", "/api/pay/start", pay)[1]["payment_ref"] == p["payment_ref"])
        ev = json.dumps({"payment_ref": p["payment_ref"], "status": "paid", "amount": p["amount"]}).encode()
        sign = lambda b, key=SECRET: {"X-Pay-Signature": hmac.new(key.encode(), b, hashlib.sha256).hexdigest()}
        s, _ = call("POST", "/api/pay/webhook", raw=ev)
        check("'payment done' without a signature is refused", s == 401 and orders() == 0, s)
        s, _ = call("POST", "/api/pay/webhook", raw=ev, headers=sign(ev, "wrong-secret"))
        check("a forged signature is refused", s == 401 and orders() == 0, s)
        low = json.dumps({"payment_ref": p["payment_ref"], "status": "paid", "amount": 1}).encode()
        s, d = call("POST", "/api/pay/webhook", raw=low, headers=sign(low))
        check("paying less than the price is refused", s == 400 and orders() == 0, d.get("error"))
        s, d = call("POST", "/api/pay/webhook", raw=ev, headers=sign(ev))
        check("a correctly signed confirmation creates the order", s == 200 and d["status"] == "paid" and orders() == 1, d)
        first = d["order"]
        s, d = call("POST", "/api/pay/webhook", raw=ev, headers=sign(ev))
        check("a repeated confirmation does not create a second order", d.get("order") == first and orders() == 1)
        s, od = call("GET", "/api/orders/" + first)
        check("the phone number is not in the public order", "98765" not in json.dumps(od) and od["paid"] is True and od["eta_seconds"] > 0, od.get("eta_seconds"))
        s, p2 = call("POST", "/api/pay/start", dict(base, phone="9876543210", name="Sana"))
        s, d = call("POST", "/api/pay/test-complete", {"payment_ref": p2["payment_ref"], "outcome": "fail"})
        check("a failed payment creates no order", d["status"] == "failed" and orders() == 1)
        s, d = call("POST", "/api/orders", dict(base, kind="takeaway", name="Counter"), token=kt)
        check("counter staff can type in a takeaway sale", s == 201, s)

        print("-- auto-accept and instant items")
        s, d = call("POST", "/api/orders", {"outlet": A, "table": 1, "lines": [line("cutting-chai", 2), line("masala-chai")]})
        sl = q("SELECT station,status FROM slips WHERE order_id=(SELECT id FROM orders WHERE public_id=?)", d["public_id"])
        check("tea-only order is accepted as Ready and printed at once", d["status"] == "ready" and sl == [("counter", "printed")], sl)
        time.sleep(1.5)
        s, d = call("POST", "/api/orders", {"outlet": A, "table": 2, "lines": [line("cutting-chai"), line("bhaji-pav")]})
        time.sleep(1.2)  # a kitchen slip may have to wait one full gap behind the previous one
        sl = sorted(q("SELECT station,status FROM slips WHERE order_id=(SELECT id FROM orders WHERE public_id=?)", d["public_id"]))
        check("tea + food: two slips, accepted by the server as Preparing", d["status"] == "preparing" and sl == [("counter", "printed"), ("kitchen", "printed")], sl)

        print("-- print pacing, per store")
        time.sleep(3)

        def food(outlet, table, qty=1, slug="vada-pav"):
            return call("POST", "/api/orders", {"outlet": outlet, "table": table, "lines": [line(slug, qty)]})[1]["public_id"]

        def printed_times(ids):
            out = []
            for pid in ids:
                r = q("SELECT s.printed_at FROM slips s JOIN orders o ON o.id=s.order_id WHERE o.public_id=? AND s.station='kitchen'", pid)
                out.append(r[0][0] if r else None)
            return out
        t0 = time.time()
        a_ids = [food(A, t) for t in range(3, 8)]
        b_id = food(B, 3)
        time.sleep(0.4)
        check("another store does not wait behind a busy store", printed_times([b_id])[0] is not None and printed_times([b_id])[0] - t0 < 1.0)
        time.sleep(5)
        ts = printed_times(a_ids)
        gaps = [round(b - a, 2) for a, b in zip(ts, ts[1:])] if all(ts) else None
        check("slips come out about 1 s apart (gap set to 1 s)", gaps is not None and all(0.85 <= g <= 1.4 for g in gaps), gaps)
        check("first in, first out", all(ts) and ts == sorted(ts))

        s, _ = call("PUT", "/api/admin/scale-cafe/outlets/" + A, {"print_gap": 2, "print_order": "small_first"}, token=at)
        time.sleep(2.2)
        ids = [food(A, 8, 1), food(A, 9, 6), food(A, 10, 1)]
        time.sleep(7)
        ts = printed_times(ids)
        check("owner can change gap and order; small orders can go first", s == 200 and all(ts) and ts[2] < ts[1], [round(x - min(ts), 1) for x in ts] if all(ts) else ts)
        check("gap of 2 s is respected", all(ts) and min(b - a for a, b in zip(sorted(ts), sorted(ts)[1:])) >= 1.85)

        print("-- manual accept, rejection, token board")
        s, d = call("PUT", "/api/kitchen/%s/settings" % A, {"auto_accept": False}, token=kt)
        s, d = call("POST", "/api/orders", {"outlet": A, "table": 11, "lines": [line("vada-pav")]})
        n = q("SELECT COUNT(*) FROM slips WHERE order_id=(SELECT id FROM orders WHERE public_id=?)", d["public_id"])[0][0]
        check("auto-accept off: order stays New and nothing prints", d["status"] == "new" and n == 0)
        s, od = call("POST", "/api/kitchen/%s/orders/%s/status" % (A, d["public_id"]), {"status": "preparing"}, token=kt)
        n = q("SELECT COUNT(*) FROM slips WHERE order_id=(SELECT id FROM orders WHERE public_id=?)", d["public_id"])[0][0]
        check("pressing Accept creates the slip", s == 200 and n == 1)
        check("a phone cannot flip the auto-accept switch", call("PUT", "/api/kitchen/%s/settings" % A, {"auto_accept": True})[0] == 401)
        call("PUT", "/api/kitchen/%s/settings" % A, {"auto_accept": True}, token=kt)
        queued = [food(A, t) for t in range(12, 16)]
        s, od = call("POST", "/api/kitchen/%s/orders/%s/status" % (A, queued[-1]), {"status": "cancelled"}, token=kt)
        time.sleep(9)
        st = q("SELECT status FROM slips WHERE order_id=(SELECT id FROM orders WHERE public_id=?)", queued[-1])
        check("a rejected order's waiting slip is never printed", st == [("skipped",)], st)
        s, od = call("POST", "/api/kitchen/%s/orders/%s/status" % (A, first), {"status": "cancelled"}, token=kt)
        st = q("SELECT status FROM payments WHERE order_public_id=?", first)
        check("rejecting a paid takeaway marks a refund as due", od.get("refund_due") is True and st == [("refund_due",)], st)
        s, bd = call("GET", "/api/board/" + A)
        flat = json.dumps(bd)
        check("token board shows token numbers only (no names or phones)", s == 200 and all(set(o) == {"token", "status"} for o in bd["orders"]) and "Counter" not in flat and "98765" not in flat, bd["orders"])
        s, k = call("GET", "/api/kitchen/%s/orders" % A, token=kt)
        check("kitchen sees printer status and recent slips", "waiting" in k["printer"] and len(k["recent_slips"]) > 0, k["printer"])
        check("settings out of range are refused", call("PUT", "/api/admin/scale-cafe/outlets/" + A, {"print_gap": -1}, token=at)[0] == 400)
    finally:
        if db:
            db.close()
        srv.terminate()
        try:
            srv.wait(10)
        except subprocess.TimeoutExpired:
            srv.kill()
        log.close()
    errs = open(os.path.join(HERE, "results", "feature.server.log")).read().count("Traceback")
    check("no server errors in the log", errs == 0, "%d tracebacks" % errs)
    print("\n%d checks, %d FAIL" % (len(results), results.count(False)))
    sys.exit(0 if all(results) else 1)


if __name__ == "__main__":
    main()
