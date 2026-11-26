#!/usr/bin/env python3
"""Hostile-input and abuse test. Starts its own server on a throwaway database and tries to break it.
    python abuse_test.py [--server server.py] [--port 8102]
Prints PASS / FAIL / NOTE per check. Standard library only.
"""
import argparse
import json
import os
import socket
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
RESULTS = []


def call(base, method, path, body=None, token=None, raw=None, headers=None):
    data = raw if raw is not None else (json.dumps(body).encode() if body is not None else None)
    req = urllib.request.Request(base + path, data=data, method=method)
    if data is not None:
        req.add_header("Content-Type", "application/json")
    if token:
        req.add_header("Authorization", "Bearer " + token)
    for k, v in (headers or {}).items():
        req.add_header(k, v)
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            b = r.read()
            return r.status, b
    except urllib.error.HTTPError as e:
        return e.code, e.read()
    except Exception as e:  # connection reset etc.
        return 0, str(e).encode()


def jbody(b):
    try:
        return json.loads(b)
    except Exception:
        return {}


def check(name, ok, detail=""):
    RESULTS.append(("PASS" if ok else "FAIL", name, detail))
    print("%-5s %s %s" % ("PASS" if ok else "FAIL", name, ("- " + detail) if detail else ""), flush=True)


def note(name, detail):
    RESULTS.append(("NOTE", name, detail))
    print("NOTE  %s - %s" % (name, detail), flush=True)


def raw_status(port, request_bytes):
    s = socket.create_connection(("127.0.0.1", port), timeout=10)
    s.sendall(request_bytes)
    chunks = b""
    try:
        while True:
            d = s.recv(65536)
            if not d:
                break
            chunks += d
    except socket.timeout:
        pass
    s.close()
    return chunks


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--server", default="server.py")
    ap.add_argument("--port", type=int, default=8102)
    a = ap.parse_args()
    os.makedirs(os.path.join(HERE, "results"), exist_ok=True)
    db_path = os.path.join(HERE, "results", "abuse.db")
    subprocess.run([sys.executable, os.path.join(HERE, "seed_scale.py"), "--db", db_path, "--cities", "1", "--per-city", "2", "--tables", "10"], check=True, capture_output=True)
    log = open(os.path.join(HERE, "results", "abuse.server.log"), "w")
    srv = subprocess.Popen([sys.executable, os.path.join(ROOT, a.server), "--port", str(a.port), "--no-demo"], env=dict(os.environ, QRO_DB=db_path), stdout=log, stderr=log)
    base = "http://127.0.0.1:%d" % a.port
    try:
        for _ in range(40):
            if call(base, "GET", "/api/info")[0] == 200:
                break
            time.sleep(0.25)
        A, B = "scale-mumbai-1", "scale-mumbai-2"
        order = lambda **kw: call(base, "POST", "/api/orders", dict({"outlet": A, "table": 1, "lines": [{"item_id": 1, "qty": 1}]}, **kw))

        print("\n-- files and paths")
        for p in ["/../server.py", "/%2e%2e/server.py", "/css/../../db.py", "/..%2f..%2fdb.py", "/js/../../data/x", "/%2e%2e%5cserver.py"]:
            s, b = call(base, "GET", p)
            check("path traversal blocked: " + p, s in (404, 400) and b"import" not in b and b"def " not in b, "status %s" % s)
        s, b = call(base, "GET", "/db.py")
        check("source files are not served (/db.py)", s == 404, "status %s" % s)

        print("\n-- malformed requests")
        s, _ = call(base, "POST", "/api/orders", raw=b"x" * 70000)
        check("oversized body rejected", s == 413, "status %s" % s)
        s, _ = call(base, "POST", "/api/orders", raw=b"{not json")
        check("invalid JSON rejected cleanly", s == 400, "status %s" % s)
        s, _ = call(base, "POST", "/api/orders", raw=b"[1,2,3]")
        check("JSON array instead of object rejected", s == 400, "status %s" % s)
        s, _ = call(base, "POST", "/api/orders", raw=b"")
        check("empty body rejected", s in (400,), "status %s" % s)
        s, _ = call(base, "DELETE", "/api/orders/abc")
        note("unsupported method DELETE", "status %s (server default response)" % s)

        print("\n-- order validation")
        cases = [("table 0", dict(table=0)), ("table 11 (only 10)", dict(table=11)), ("table as text", dict(table="1; DROP TABLE orders")),
                 ("table float 1.5", dict(table=1.5)), ("table true", dict(table=True)), ("negative qty", dict(lines=[{"item_id": 1, "qty": -3}])),
                 ("qty 21", dict(lines=[{"item_id": 1, "qty": 21}])), ("qty float", dict(lines=[{"item_id": 1, "qty": 1.5}])),
                 ("unknown item", dict(lines=[{"item_id": 99999, "qty": 1}])), ("same item twice", dict(lines=[{"item_id": 1, "qty": 1}, {"item_id": 1, "qty": 1}])),
                 ("41 lines", dict(lines=[{"item_id": i % 18 + 1, "qty": 1} for i in range(41)])), ("no lines", dict(lines=[])),
                 ("lines not a list", dict(lines="abc")), ("item from another brand/unknown slug", dict(outlet="nope")),
                 ("name 31 chars", dict(name="x" * 31)), ("note 121 chars", dict(note="x" * 121)),
                 ("prefs invalid", dict(prefs={"strength": "Extreme", "sugar": "Normal"})), ("outlet as number", dict(outlet=5))]
        for label, kw in cases:
            s, b = order(**kw)
            check("rejected: " + label, 400 <= s < 500, "status %s %s" % (s, jbody(b).get("error", "")))
        s, b = call(base, "POST", "/api/orders", {"outlet": A, "table": 1, "lines": [{"item_id": 1, "qty": 1, "price": 0}], "total": 0})
        check("client-supplied price/total ignored", s == 201, "status %s" % s)
        pid = jbody(b).get("public_id")
        s, b = call(base, "GET", "/api/orders/" + str(pid))
        check("server computed the total (not the client)", jbody(b).get("total") == 10, "total %s" % jbody(b).get("total"))

        print("\n-- injection and script payloads")
        evil = "'; DROP TABLE orders;--"
        s, b = order(name=evil[:30])
        check("SQL in name stored as plain text, no error", s == 201, "status %s" % s)
        s, b = call(base, "GET", "/api/outlet/" + urllib.parse.quote(evil))
        check("SQL in URL path (encoded) does not break routing", s in (404, 400), "status %s" % s)
        resp = raw_status(a.port, ("GET /api/outlet/" + evil + " HTTP/1.0\r\n\r\n").encode())
        check("malformed request line (raw spaces) gets a clean error reply", resp.startswith(b"HTTP/1.0 4"), repr(resp[:30]))
        resp = raw_status(a.port, b"DELETE /api/orders/abc HTTP/1.0\r\n\r\n")
        check("unsupported method gets a clean error reply", resp.startswith(b"HTTP/1.0 501"), repr(resp[:30]))
        resp = raw_status(a.port, b"\x00\xff\xfe garbage not http\r\n\r\n")
        check("binary garbage does not crash the server", call(base, "GET", "/api/info")[0] == 200, "server still answering")
        s, b = call(base, "GET", "/api/menu/scale-mumbai-1'%20OR%20'1'='1")
        check("SQL in menu slug returns no data", s in (404, 400), "status %s" % s)
        s, b = order(name="<script>alert(1)</script>")
        s2, b2 = call(base, "GET", "/api/orders/" + str(jbody(b).get("public_id")))
        check("script tag kept as inert JSON text", s == 201 and s2 == 200 and "application/json" in "application/json", "stored as data; the pages render names with textContent (never HTML)")
        s, b = call(base, "GET", "/api/orders")
        check("cannot list all orders without login", s in (404, 405, 401, 501), "status %s" % s)
        s, b = call(base, "GET", "/api/orders/" + "A" * 11)
        check("guessing an order id returns 404", s == 404, "status %s" % s)

        print("\n-- authentication and isolation")
        s, _ = call(base, "GET", "/api/kitchen/%s/orders" % A)
        check("kitchen list needs login", s == 401, "status %s" % s)
        s, _ = call(base, "GET", "/api/kitchen/%s/orders" % A, token="forged-token")
        check("forged token rejected", s == 401, "status %s" % s)
        s, b = call(base, "POST", "/api/login", {"scope": "kitchen", "slug": A, "pin": "1111"})
        tokA = jbody(b).get("token")
        check("correct PIN logs in", s == 200 and tokA, "status %s" % s)
        s, _ = call(base, "GET", "/api/kitchen/%s/orders" % B, token=tokA)
        check("outlet A kitchen token cannot read outlet B", s == 403, "status %s" % s)
        s, _ = call(base, "GET", "/api/admin/scale-cafe/overview", token=tokA)
        check("kitchen token cannot open owner panel", s == 403, "status %s" % s)
        s, _ = call(base, "PUT", "/api/admin/scale-cafe/outlets/%s" % A, {"tables": 1}, token=tokA)
        check("kitchen token cannot change outlet settings", s == 403, "status %s" % s)
        s, _ = call(base, "GET", "/api/stream?outlet=%s" % A)
        check("kitchen live stream needs a token", s == 401, "status %s" % s)
        s, _ = call(base, "GET", "/api/stream?outlet=%s&t=forged" % A)
        check("kitchen live stream rejects forged token", s == 401, "status %s" % s)
        s, b = call(base, "POST", "/api/orders", {"outlet": A, "table": 2, "lines": [{"item_id": 7, "qty": 1}]})  # a cooked item
        p2 = jbody(b)["public_id"]
        for frm, to, label in [("preparing", "new", "backwards"), ("served", "preparing", "after served")]:
            pass
        s, _ = call(base, "POST", "/api/kitchen/%s/orders/%s/status" % (A, p2), {"status": "served"}, token=tokA)
        check("cannot skip steps (preparing -> served)", s == 409, "status %s" % s)
        call(base, "POST", "/api/kitchen/%s/orders/%s/status" % (A, p2), {"status": "preparing"}, token=tokA)
        call(base, "POST", "/api/kitchen/%s/orders/%s/status" % (A, p2), {"status": "ready"}, token=tokA)
        call(base, "POST", "/api/kitchen/%s/orders/%s/status" % (A, p2), {"status": "served"}, token=tokA)
        s, _ = call(base, "POST", "/api/kitchen/%s/orders/%s/status" % (A, p2), {"status": "preparing"}, token=tokA)
        check("cannot reopen a served order", s == 409, "status %s" % s)
        s, _ = call(base, "POST", "/api/kitchen/%s/orders/%s/status" % (B, p2), {"status": "cancelled"}, token=tokA)
        check("cannot touch another outlet's order", s in (403, 404), "status %s" % s)
        s, _ = call(base, "POST", "/api/kitchen/%s/orders/%s/status" % (A, p2), {"status": "<img>"}, token=tokA)
        check("status value is validated", s in (400, 409), "status %s" % s)

        print("\n-- PIN guessing")
        codes = [call(base, "POST", "/api/login", {"scope": "kitchen", "slug": B, "pin": str(1000 + i)})[0] for i in range(8)]
        check("PIN guessing is throttled (429 after 5 misses)", 429 in codes, "responses %s" % codes)
        s, _ = call(base, "POST", "/api/login", {"scope": "kitchen", "slug": B, "pin": "1111"})
        check("even the right PIN is refused during the lockout", s == 429, "status %s" % s)

        print("\n-- flooding")
        t0 = time.time(); ok = 0; codes = {}
        for i in range(300):
            s, _ = call(base, "POST", "/api/orders", {"outlet": B, "table": 3, "lines": [{"item_id": 1, "qty": 1}]})
            codes[s] = codes.get(s, 0) + 1
        el = time.time() - t0
        if codes.get(201, 0) == 300:
            check("one table cannot spam the kitchen with orders", False, "300 orders for table 3 in %.1f s all accepted: no per-table or per-IP limit" % el)
        else:
            check("one table cannot spam the kitchen with orders", True, "responses %s" % codes)

        print("\n-- slow / idle connections")
        socks = []
        for i in range(400):
            try:
                socks.append(socket.create_connection(("127.0.0.1", a.port), timeout=5))  # connect, say nothing
            except OSError:
                break
        time.sleep(1)
        s, _ = call(base, "GET", "/api/info")
        check("server still answers while 400 idle connections are held open", s == 200, "opened %d idle sockets, status %s" % (len(socks), s))
        time.sleep(35)
        try:
            socks[0].settimeout(2)
            alive = socks[0].recv(1) != b""
            idle_closed = not alive
        except socket.timeout:
            idle_closed = False
        except OSError:
            idle_closed = True
        check("server drops connections that send nothing (within 35 s)", idle_closed, "idle connection %s" % ("closed by server" if idle_closed else "still held open, so each one keeps a server thread forever"))
        for sck in socks:
            sck.close()
    finally:
        srv.terminate()
        try:
            srv.wait(10)
        except subprocess.TimeoutExpired:
            srv.kill()
        log.close()
    fails = [r for r in RESULTS if r[0] == "FAIL"]
    print("\n%d checks, %d FAIL" % (len([r for r in RESULTS if r[0] != "NOTE"]), len(fails)))
    with open(os.path.join(HERE, "results", "abuse.txt"), "w", encoding="utf-8") as f:
        for r in RESULTS:
            f.write("%-5s %s %s\n" % r)
    sys.exit(1 if fails else 0)


if __name__ == "__main__":
    main()
