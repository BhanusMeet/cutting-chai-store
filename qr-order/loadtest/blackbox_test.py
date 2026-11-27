#!/usr/bin/env python3
"""Black-box test of the whole store app: it only uses the network, like a guest, a staff member or an attacker.
Starts its own server on a new EMPTY database, sets the store up the way a real owner would, uses every feature
and then tries to break it. Test passwords are generated fresh on every run.
    python blackbox_test.py
"""
import hashlib
import hmac
import io
import json
import os
import random
import re
import secrets
import socket
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from xml.dom import minidom

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
PORT = 8112
BASE = "http://127.0.0.1:%d" % PORT
OWNER_PW = "mango-ladder-%s-river" % secrets.token_hex(3)
NEW_OWNER_PW = "copper-window-%s-train" % secrets.token_hex(3)
STAFF_PIN = "8%07d3" % random.randint(0, 9999999)
NEW_STAFF_PIN = "4%07d9" % random.randint(0, 9999999)
results, section_name = [], [""]
server_errors = []
SEEN_KEYS = []  # table codes used in this run


def section(name):
    section_name[0] = name
    print("\n-- %s" % name, flush=True)


def check(name, ok, detail=""):
    results.append((section_name[0], name, bool(ok)))
    print("%-4s %s %s" % ("PASS" if ok else "FAIL", name, ("- %s" % (detail,))[:150] if detail != "" and not ok else ""), flush=True)


def http(method, path, body=None, token=None, raw=None, headers=None, timeout=20):
    data = raw if raw is not None else (json.dumps(body).encode() if body is not None else None)
    req = urllib.request.Request(BASE + path, data=data, method=method)
    if token:
        req.add_header("Authorization", "Bearer " + token)
    for k, v in (headers or {}).items():
        req.add_header(k, v)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            status, hdrs, payload = r.status, r.headers, r.read()
    except urllib.error.HTTPError as e:
        status, hdrs, payload = e.code, e.headers, e.read()
    except Exception as e:
        return 0, {}, {"error": str(e)}, b""
    if status >= 500 and status != 501:
        server_errors.append((method, path, body, status))
    try:
        parsed = json.loads(payload)
    except Exception:
        parsed = {}
    return status, hdrs, parsed, payload


def call(method, path, body=None, token=None, **kw):
    s, _, d, _ = http(method, path, body, token, **kw)
    return s, d


def raw_exchange(data, timeout=8):
    s = socket.create_connection(("127.0.0.1", PORT), timeout=timeout)
    s.sendall(data)
    out = b""
    t0 = time.time()
    try:
        while True:
            chunk = s.recv(65536)
            if not chunk:
                break
            out += chunk
    except OSError:
        pass
    s.close()
    return out, time.time() - t0


def open_stream(path):
    """Returns (socket, status line)."""
    s = socket.create_connection(("127.0.0.1", PORT), timeout=10)
    s.sendall(("GET %s HTTP/1.0\r\n\r\n" % path).encode())
    head = b""
    while b"\r\n" not in head:
        chunk = s.recv(1)
        if not chunk:
            break
        head += chunk
    return s, head.decode(errors="replace").strip()


def stream_reads(s, needle, seconds):
    s.settimeout(1)
    buf, end = b"", time.time() + seconds
    while time.time() < end:
        try:
            chunk = s.recv(4096)
            if not chunk:
                return buf, True  # closed by the server
            buf += chunk
            if needle and needle in buf:
                return buf, False
        except socket.timeout:
            pass
        except OSError:
            return buf, True
    return buf, False


def printing_tests(ctx):
    """A simulated USB printer, controlled through files: plug and unplug it, run it out of paper, make it fail."""
    outlet, brand, owner, staff, tea, food, sim = (ctx[k] for k in ("outlet", "brand", "owner", "staff", "tea", "food", "sim"))
    base = "/api/kitchen/%s" % outlet
    outdir = os.path.join(sim, "out")

    def plug(**kw):
        with open(os.path.join(sim, "printers.json"), "w") as f:
            json.dump([dict({"name": "Test Thermal", "port": "USB001"}, **kw)], f)

    def sim_mode(m):
        with open(os.path.join(sim, "mode.txt"), "w") as f:
            f.write(m)

    def files():
        return sorted(os.listdir(outdir))

    def paper(name):
        with open(os.path.join(outdir, name), "rb") as f:
            return f.read()

    def until(fn, seconds=12):
        end = time.time() + seconds
        while time.time() < end:
            v = fn()
            if v:
                return v
            time.sleep(0.25)
        return fn()

    def state():
        return call("GET", base + "/printer", token=staff)[1]

    def sale(items, name="Asha", note=""):
        s, d = call("POST", "/api/orders", {"outlet": outlet, "kind": "takeaway", "name": name, "note": note, "pay_method": "cash",
                                            "lines": [{"item_id": i, "qty": 1} for i in items]}, staff)
        return d if s == 201 else None

    def slips(public_id=None):
        got = call("GET", base + "/orders", token=staff)[1].get("recent_slips", [])
        return [x for x in got if public_id in (None, x["public_id"])]

    section("printing: finding and choosing a printer")
    st = state()
    check("no printer chosen at first, none found", st.get("mode") == "ask" and st.get("detected") == [], st)
    plug()
    check("a printer that is plugged in is found by itself", until(lambda: [p["name"] for p in state()["detected"]] == ["Test Thermal"], 6))
    for method, path in [("GET", "/printer"), ("PUT", "/printer"), ("POST", "/printer/test"), ("POST", "/printer/retry"), ("POST", "/printer/clear"), ("POST", "/slips/1/reprint")]:
        check("outsiders cannot %s %s" % (method, path), call(method, base + path, None if method == "GET" else {"mode": "none"})[0] == 401)
    choose = lambda body: call("PUT", base + "/printer", body, staff)
    check("a printer that is not there cannot be chosen", choose({"mode": "usb", "name": "Ghost", "width": 80})[0] == 409)
    check("a nonsense paper width is refused", choose({"mode": "usb", "name": "Test Thermal", "width": 70})[0] == 400)
    check("a nonsense choice is refused", choose({"mode": "fax"})[0] == 400)
    check("reprint is refused while no printer is chosen", call("POST", base + "/printer/retry", {}, staff)[0] == 409)
    s, d = choose({"mode": "usb", "name": "Test Thermal", "width": 58})
    check("staff can say 'use this printer'", s == 200 and d.get("mode") == "usb", d)
    call("PUT", "/api/admin/%s/outlets/%s" % (brand, outlet), {"print_gap": 0}, owner)
    s, d = call("POST", base + "/printer/test", {}, staff)
    check("a test slip prints", d.get("ok") and len(files()) >= 1, d)

    section("printing: order slips")
    time.sleep(1)
    n = len(files())
    od = sale([tea, food], name="Ravi", note="less spicy")
    until(lambda: len(files()) >= n + 2)
    new = [paper(f) for f in files()[n:]]
    check("tea and food print as one counter slip and one kitchen slip", len(new) == 2 and sum(b"COUNTER" in x for x in new) == 1 and sum(b"KITCHEN" in x for x in new) == 1, len(new))
    check("slips are real printer commands, ending with a cut", all(x.startswith(b"\x1b@") and x.endswith(b"\x1dV\x42\x00") for x in new))
    check("the note reaches the paper", all(b"less spicy" in x for x in new))
    check("slips are marked printed only after the printer took them", until(lambda: len(slips(od["public_id"])) == 2 and all(x["status"] == "printed" for x in slips(od["public_id"]))))
    n = len(files())
    sale([food], name="Bad\x1bp\x00\x19\x19Guy", note="x\x1d\x56\x00y")
    until(lambda: len(files()) > n)
    body = paper(files()[-1]) if len(files()) > n else b""
    check("a guest cannot send commands to the printer", b"BadpGuy" in body.replace(b"\x19", b"") and b"\x1bp" not in body and body.count(b"\x1dV") == 1, body[:200])
    if sys.platform == "win32":
        n = len(files())
        sale([food], name="मीना")
        until(lambda: len(files()) > n)
        check("Hindi text is printed as an image", len(files()) > n and b"\x1dv0\x00" in paper(files()[-1]))
    call("PUT", "/api/admin/%s/outlets/%s" % (brand, outlet), {"print_gap": 2}, owner)
    time.sleep(2.5)
    n = len(files())
    for _ in range(3):
        sale([food])
    until(lambda: len(files()) >= n + 3, 15)
    times = [os.path.getmtime(os.path.join(outdir, f)) for f in files()[n:]]
    gaps = [round(b - a, 2) for a, b in zip(times, times[1:])]
    check("kitchen slips keep the 2 second gap at the real printer", len(times) == 3 and min(gaps) >= 1.8, gaps)
    call("PUT", "/api/admin/%s/outlets/%s" % (brand, outlet), {"print_gap": 0}, owner)

    section("printing: unplugged and out of paper (nothing sent, so it retries by itself)")
    for label, kw, words in [("unplugged", {"connected": False}, "unplugged"), ("out of paper", {"problem": "out of paper"}, "out of paper")]:
        time.sleep(2.2)
        plug(**kw)
        time.sleep(2.5)
        n = len(files())
        od = sale([food])
        st = until(lambda: (lambda s: s if words in s.get("problem", "") and s.get("waiting") else None)(state()))
        check("%s: staff are told why and the slip waits" % label, bool(st) and not st["stopped"] and len(files()) == n, st or state())
        plug()
        until(lambda: len(files()) > n)
        time.sleep(4)
        check("%s: when fixed it prints by itself, exactly once" % label, len(files()) == n + 1 and slips(od["public_id"])[0]["status"] == "printed", len(files()) - n)
        check("%s: the warning goes away" % label, until(lambda: state().get("problem") == ""), state())

    section("printing: unsure result (a person must decide)")
    sim_mode("unsure")
    n = len(files())
    first = sale([food])
    st = until(lambda: (lambda s: s if s.get("stopped") else None)(state()))
    check("the slip is marked failed and printing stops", bool(st) and st["failed"] == 1 and slips(first["public_id"])[0]["status"] == "failed", st)
    second = sale([food])
    sim_mode("ok")
    time.sleep(5)
    check("nothing prints until a person presses Try again", len(files()) == n and state()["waiting"] == 1, (len(files()) - n, state()))
    s, d = call("POST", base + "/printer/retry", {}, staff)
    until(lambda: len(files()) >= n + 2)
    new = [paper(f) for f in files()[n:]]
    check("Try again prints the failed slip first, marked REPRINT", s == 200 and len(new) == 2 and b"REPRINT" in new[0] and b"REPRINT" not in new[1], (d, len(new)))
    n = len(files())
    sid = slips(second["public_id"])[0]["id"]
    s = call("POST", base + "/slips/%d/reprint" % sid, {}, staff)[0]
    until(lambda: len(files()) > n)
    check("any printed slip can be reprinted, marked REPRINT", s == 200 and len(files()) == n + 1 and b"REPRINT" in paper(files()[-1]))
    check("a slip that does not exist cannot be reprinted", call("POST", base + "/slips/999999999/reprint", {}, staff)[0] == 404)
    sim_mode("unsure")
    third = sale([food])
    until(lambda: state().get("stopped"))
    sim_mode("ok")
    n = len(files())
    s, d = call("POST", base + "/printer/clear", {}, staff)
    time.sleep(2)
    check("'clear failed slips' drops them without printing", d.get("cleared") == 1 and len(files()) == n and not state()["stopped"], d)
    fourth = sale([food])
    check("printing carries on afterwards", until(lambda: len(files()) == n + 1))

    section("printing: server restart")
    plug(connected=False)
    time.sleep(2.5)
    n = len(files())
    od = sale([food])
    time.sleep(1)
    staff, owner = ctx["restart"]()
    ctx.update(staff=staff, owner=owner)
    check("a waiting slip survives a server restart", until(lambda: state().get("waiting") == 1), state())
    check("the printer choice survives a restart", state().get("mode") == "usb")
    plug()
    until(lambda: len(files()) > n)
    time.sleep(3)
    check("it then prints exactly once", len(files()) == n + 1, len(files()) - n)

    section("printing: 'No print'")
    plug(connected=False)
    time.sleep(2.5)
    sale([food])
    s, d = choose({"mode": "none"})
    check("owner or staff can choose 'No print'", s == 200 and d.get("mode") == "none", d)
    plug()
    time.sleep(3)
    n = len(files())
    od = sale([tea, food])
    time.sleep(2.5)
    st = state()
    check("nothing is printed, not even slips that were waiting", len(files()) == n and st["waiting"] == 0, st)
    check("no slips are made for new orders", slips(od["public_id"]) == [])
    check("the printer is not even looked for, so there is no prompt", st["detected"] == [] and st["without_driver"] == 0, st)
    kitchen = call("GET", base + "/orders", token=staff)[1]
    check("the order still shows on the kitchen screen", any(o["public_id"] == od["public_id"] for o in kitchen["orders"]))
    check("test print is refused with 'No print'", call("POST", base + "/printer/test", {}, staff)[0] == 409)
    s, d = call("GET", "/api/admin/%s/activity" % brand, token=owner)
    actions = {a["action"] for a in d.get("activity", [])}
    for want in ["printer setting", "printer retry", "slip reprinted", "failed slips cleared"]:
        check("activity log records: " + want, want in actions, sorted(actions))
    choose({"mode": "ask"})
    call("PUT", "/api/admin/%s/outlets/%s" % (brand, outlet), {"print_gap": 5}, owner)


def make_xlsx(rows_xml, extra=None, sheet_extra="", raw_sheet=None):
    """A tiny hand-made .xlsx, as an attacker (or an owner) might upload it."""
    ns = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
    sheet = raw_sheet if raw_sheet is not None else '<worksheet xmlns="%s"><sheetData>%s</sheetData>%s</worksheet>' % (ns, rows_xml, sheet_extra)
    parts = {"[Content_Types].xml": '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"/>',
             "xl/workbook.xml": '<workbook xmlns="%s"><sheets/></workbook>' % ns, "xl/worksheets/sheet1.xml": sheet}
    parts.update(extra or {})
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        for name, body in parts.items():
            z.writestr(name, body)
    return out.getvalue()


def cell(ref, text):
    return '<c r="%s" t="inlineStr"><is><t>%s</t></is></c>' % (ref, text)


def sheets_of(blob):
    with zipfile.ZipFile(io.BytesIO(blob)) as z:
        for name in z.namelist():
            if name.endswith(".xml") or name.endswith(".rels"):
                minidom.parseString(z.read(name))  # every part must be well formed
        return {n: z.read(n).decode() for n in z.namelist() if n.startswith("xl/worksheets/")}


def money_tests(ctx):
    outlet, brand, owner, staff, food = (ctx[k] for k in ("outlet", "brand", "owner", "staff", "food"))
    k, a = "/api/kitchen/%s" % outlet, "/api/admin/%s" % brand
    q = "?outlet=" + outlet
    today = time.strftime("%Y-%m-%d")
    dates = "?from=%s&to=%s&outlet=%s" % (today, today, outlet)

    def new_dish(name, price):
        return call("POST", a + "/items", {"category": ctx["category"], "names": {"en": name}, "price": price}, owner)[1].get("id")

    def sell(items, kind="takeaway", pay="cash", name="Asha", **extra):
        body = dict({"outlet": outlet, "kind": kind, "name": name, "lines": [{"item_id": i, "qty": n} for i, n in items]}, **extra)
        if kind == "dine_in":
            body.setdefault("table", 3)
        if pay:
            body["pay_method"] = pay
        return call("POST", "/api/orders", body, staff)

    bills = lambda: call("GET", k + "/bills", token=staff)[1]
    ids = lambda rows: {b["public_id"] for b in rows}
    step = lambda pid, status: call("POST", "%s/orders/%s/status" % (k, pid), {"status": status}, staff)
    ctx["category"] = call("POST", a + "/categories", {"names": {"en": "Money tests"}}, owner)[1].get("slug")
    dosa, lassi, plain = new_dish("Test Dosa", 100), new_dish("Test Lassi", 40), new_dish("Test Plain", 30)

    section("money: unpaid bills and mark as paid")
    for method, path in [("GET", k + "/bills"), ("POST", k + "/orders/abc/pay"), ("POST", k + "/orders/abc/refunded")]:
        check("outsiders cannot %s %s" % (method, path.split(outlet)[1]), call(method, path, None if method == "GET" else {"method": "cash"})[0] == 401)
    paid_pid = sell([(plain, 1)])[1]["public_id"]
    later = sell([(plain, 2)], kind="dine_in", pay=None)[1]["public_id"]
    check("a counter sale with payment is not on the unpaid list", paid_pid not in ids(bills()["unpaid"]))
    check("a 'pay later' table order is on the unpaid list", later in ids(bills()["unpaid"]))
    pay = lambda pid, m="cash", tok=None: call("POST", "%s/orders/%s/pay" % (k, pid), {"method": m}, tok or staff)[0]
    check("a made-up payment method is refused", pay(later, "iou") == 400)
    codes = []
    threads = [threading.Thread(target=lambda: codes.append(pay(later, "upi"))) for _ in range(8)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    check("eight taps at once pay the bill exactly once", sorted(codes) == [200] + [409] * 7, codes)
    check("it leaves the unpaid list", later not in ids(bills()["unpaid"]))
    check("staff cannot undo a payment", call("POST", a + "/payments/undo" + q, {"order": later}, staff)[0] in (401, 403))
    check("the owner can undo it", call("POST", a + "/payments/undo" + q, {"order": later}, owner)[0] == 200 and later in ids(bills()["unpaid"]))
    pay(later)
    s, d = step(paid_pid, "cancelled")
    check("rejecting a paid order warns that money must be returned", s == 200 and d.get("refund_due") is True, d)
    check("it appears under money to return", paid_pid in ids(bills()["refunds"]))
    check("a rejected order cannot be marked paid", pay(paid_pid) == 409)
    back = lambda: call("POST", "%s/orders/%s/refunded" % (k, paid_pid), {}, staff)[0]
    check("'money returned' works once only", back() == 200 and back() == 409 and paid_pid not in ids(bills()["refunds"]))

    section("stock: only the owner")
    for method, path in [("GET", "/stock" + q), ("POST", "/stock" + q), ("PUT", "/stock" + q), ("POST", "/ingredients"), ("PUT", "/ingredients/1"),
                         ("PUT", "/recipes/1"), ("GET", "/payments" + q), ("GET", "/report" + dates), ("GET", "/sheet" + dates),
                         ("GET", "/sheet/default-layout"), ("GET", "/sheet/layout"), ("POST", "/sheet/layout"), ("POST", "/sheet/layout/remove")]:
        got = [call(method, a + path, None if method == "GET" else {}, tok)[0] for tok in (None, staff)]
        check("outsiders and staff cannot %s %s" % (method, path.split("?")[0]), got[0] == 401 and got[1] in (401, 403), got)

    section("stock and margins")
    ing = lambda name, unit: call("POST", a + "/ingredients", {"name": name, "unit": unit}, owner)
    batter, curd = ing("Batter", "g")[1].get("id"), ing("Curd", "ml")[1].get("id")
    check("owner adds ingredients", bool(batter and curd))
    check("the same ingredient twice is refused", ing("batter", "g")[0] == 409)
    check("a made-up unit is refused", ing("Oil", "buckets")[0] == 400)
    move = lambda i, action, qty, **kw: call("POST", a + "/stock" + q, dict({"ingredient_id": i, "action": action, "qty": qty}, **kw), owner)
    check("a purchase is recorded", move(batter, "purchase", 1000, paid=80)[0] == 200)
    call("PUT", a + "/stock" + q, {"ingredient_id": curd, "price": 60, "per": 1000}, owner)
    call("PUT", a + "/stock" + q, {"ingredient_id": batter, "low_at": 700}, owner)
    recipe = lambda item, parts: call("PUT", "%s/recipes/%d" % (a, item), {"ingredients": parts}, owner)[0]
    check("owner sets what a plate uses", recipe(dosa, [{"id": batter, "qty": 200}]) == 200 and recipe(lassi, [{"id": curd, "qty": 250}]) == 200)
    view = lambda: call("GET", a + "/stock" + q, token=owner)[1]
    have = lambda i: next(x for x in view()["ingredients"] if x["id"] == i)
    dish = lambda i: next(x for x in view()["dishes"] if x["id"] == i)
    check("dish cost and margin are right", (dish(dosa)["cost"], dish(dosa)["margin"], dish(lassi)["cost"]) == (16, 84, 15), (dish(dosa), dish(lassi)))
    report = lambda: call("GET", a + "/report" + dates, token=owner)[1]["summary"]
    before = report()
    sale_body = {"client_key": "stock-test-key-0001"}
    sell([(dosa, 2), (lassi, 1)], **sale_body)
    sell([(dosa, 2), (lassi, 1)], **sale_body)  # the same order again, as a retry
    check("a sale takes its ingredients out of stock, and a retry does not take twice", (have(batter)["quantity"], have(curd)["quantity"]) == (600, -250), (have(batter), have(curd)))
    check("low and empty stock are flagged", have(batter)["status"] == "LOW" and have(curd)["status"] == "OUT")
    check("staff see low-stock names but no costs", {x["name"] for x in bills()["low_stock"]} >= {"Batter", "Curd"} and "cost" not in json.dumps(bills()["low_stock"]))
    after = report()
    delta = {x: round((after[x] or 0) - (before[x] or 0), 2) for x in ("sales", "costed_sales", "cost", "margin", "uncosted_sales", "paid_cash")}
    check("report: sales, cost and margin add up exactly", delta == {"sales": 240, "costed_sales": 240, "cost": 47, "margin": 193, "uncosted_sales": 0, "paid_cash": 240}, delta)
    sell([(plain, 1)])
    unknown = report()
    check("a dish with no ingredient list is reported as unknown cost, not free",
          round(unknown["uncosted_sales"] - after["uncosted_sales"], 2) == 30 and unknown["cost"] == after["cost"] and unknown["margin"] == after["margin"], (after, unknown))
    call("PUT", a + "/stock" + q, {"ingredient_id": curd, "price": 600, "per": 1000}, owner)
    check("changing a price later does not rewrite past sales", report()["cost"] == unknown["cost"])
    pid = sell([(dosa, 1)])[1]["public_id"]
    waste0 = report()["waste_cost"]
    step(pid, "cancelled")
    check("rejecting an order that was not made puts the stock back", have(batter)["quantity"] == 600 and report()["waste_cost"] == waste0, have(batter))
    pid = sell([(dosa, 1)])[1]["public_id"]
    step(pid, "ready")
    step(pid, "cancelled")
    check("rejecting a ready order counts it as wasted", have(batter)["quantity"] == 400 and round(report()["waste_cost"] - waste0, 2) == 16, (have(batter), report()["waste_cost"], waste0))
    move(batter, "purchase", 600, paid=96)
    check("buying at a new price averages the cost", abs(have(batter)["cost"] - 0.128) < 1e-9, have(batter))
    move(batter, "waste", 100)
    move(batter, "count", 5000)
    check("waste and shelf counts are recorded", have(batter)["quantity"] == 5000, have(batter))
    codes = []
    threads = [threading.Thread(target=lambda: codes.append(sell([(dosa, 1)])[0])) for _ in range(20)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    check("20 sales at the same moment take exactly 20 plates of stock", codes == [201] * 20 and have(batter)["quantity"] == 1000, (codes.count(201), have(batter)["quantity"]))
    for label, bad in [("negative", -5), ("true", True), ("text", "lots"), ("enormous", 1e300), ("nothing", None), ("zero purchase", 0)]:
        check("stock refuses a %s quantity" % label, move(batter, "purchase", bad)[0] == 400)
    s = http("POST", a + "/stock" + q, token=owner, raw=b'{"ingredient_id": %d, "action": "purchase", "qty": NaN}' % batter)[0]
    check("stock refuses a quantity that is not a number", s == 400, s)
    check("an ingredient still in a dish cannot be removed", call("PUT", "%s/ingredients/%d" % (a, batter), {"archived": True}, owner)[0] == 409)

    section("excel: order sheets")
    sell([(plain, 1)], name='=HYPERLINK("x")<&>')
    s, h, _, blob = http("GET", a + "/sheet" + dates, token=owner)
    parts = sheets_of(blob) if s == 200 else {}
    everything = "".join(parts.values())
    check("the standard order sheet downloads as a valid file", s == 200 and len(parts) == 6, (s, list(parts)))
    check("every placeholder is filled", "{{" not in "".join(v for n, v in parts.items() if not n.endswith("sheet6.xml")))
    check("a guest's name starting with '=' stays text, never a formula", "=HYPERLINK(" in everything and "<f>" not in everything and "<f " not in everything)
    check("the sheet's sales match the report", "<v>%r</v>" % report()["sales"] in parts.get("xl/worksheets/sheet1.xml", ""))
    for label, query in [("no dates", ""), ("a bad date", "?from=2026-13-45&to=2026-13-45"), ("dates backwards", "?from=2026-02-02&to=2026-01-01"),
                         ("ten years", "?from=2016-01-01&to=2026-01-01")]:
        check("sheet refuses " + label, call("GET", a + "/sheet" + query, token=owner)[0] == 400)
    check("asking for 'my layout' before uploading one says so", call("GET", a + "/sheet" + dates + "&layout=mine", token=owner)[0] == 404)

    def upload(data, tok=owner):
        s, _, d, _ = http("POST", a + "/sheet/layout", token=tok, raw=data, headers={"X-File-Name": "mine.xlsx"}, timeout=40)
        return s, d

    s, h, _, starter = http("GET", a + "/sheet/default-layout", token=owner)
    check("the starting layout can be downloaded and uploaded again", s == 200 and upload(starter)[0] == 201)
    rows = ('<row r="1">%s</row><row r="2">%s%s<c r="C2"><f>B2*2</f><v>99</v></c></row><row r="3"><c r="C3"><f>SUM(C2:C2)</f><v>99</v></c></row>'
            % (cell("A1", "Closing {{period}}"), cell("A2", "{{line.item}}"), cell("B2", "{{line.amount}}")))
    s, d = upload(make_xlsx(rows, sheet_extra='<mergeCells count="1"><mergeCell ref="D2:E2"/></mergeCells>'))
    check("an owner's own layout is accepted", s == 201, d)
    s, _, _, blob = http("GET", a + "/sheet" + dates + "&layout=mine", token=owner)
    sheet = sheets_of(blob)["xl/worksheets/sheet1.xml"] if s == 200 else ""
    n = sheet.count("Test ") + 0
    numbers = [int(x) for x in re.findall(r'<row r="(\d+)"', sheet)]
    last = len(numbers) - 1
    check("its rows repeat, one per item sold", s == 200 and len(numbers) > 10 and numbers == list(range(1, len(numbers) + 1)), (s, numbers[:5]))
    check("its total formula grows to cover them", "<f>SUM(C2:C%d)</f>" % last in sheet and "<f>B%d*2</f>" % last in sheet and "<v>99</v>" not in sheet, sheet[-300:])
    check("merged cells repeat with their row", 'ref="D%d:E%d"' % (last, last) in sheet)

    section("excel: hostile uploads")
    good = '<row r="1">%s</row>' % cell("A1", "{{sales}}")
    laughs = '<?xml version="1.0"?><!DOCTYPE x [<!ENTITY a "aaaaaaaaaa"><!ENTITY b "&a;&a;&a;&a;&a;&a;&a;&a;&a;&a;"><!ENTITY c "&b;&b;&b;&b;&b;&b;&b;&b;&b;&b;">]><x>&c;</x>'
    attacks = [
        ("something that is not an Excel file", b"hello" * 100, 400),
        ("a 3 MB file", os.urandom(3 * 1024 * 1024), 413),
        ("a zip bomb", make_xlsx(good, extra={"xl/media/big.bin": b"0" * (40 * 1024 * 1024)}), 400),
        ("macros", make_xlsx(good, extra={"xl/vbaProject.bin": b"x"}), 400),
        ("links to another file", make_xlsx(good, extra={"xl/externalLinks/externalLink1.xml": "<x/>"}), 400),
        ("an outside data link", make_xlsx(good, extra={"xl/_rels/workbook.xml.rels": '<Relationships><Relationship Id="r" Type="x/oleObject" Target="http://example.invalid/a" TargetMode="External"/></Relationships>'}), 400),
        ("an XML bomb", make_xlsx("", raw_sheet=laughs), 400),
        ("hidden-encoding XML", make_xlsx("", raw_sheet=laughs.encode("utf-16")), 400),
        ("damaged XML", make_xlsx("", raw_sheet="<worksheet><sheetData>"), 400),
        ("an unknown placeholder", make_xlsx('<row r="1">%s</row>' % cell("A1", "{{password}}")), 400),
        ("two lists on one row", make_xlsx('<row r="1">%s%s</row>' % (cell("A1", "{{order.token}}"), cell("B1", "{{dish.name}}"))), 400),
        ("no placeholders at all", make_xlsx('<row r="1">%s</row>' % cell("A1", "hi")), 400),
    ]
    for label, data, want in attacks:
        started = time.time()
        try:
            s = upload(data)[0]
        except Exception:
            s = 0
        ok = s == want or (want == 413 and s == 0)  # a too-large upload may be cut off before the reply arrives
        check("upload refuses " + label, ok and time.time() - started < 15, (s, round(time.time() - started, 1)))
    check("outsiders cannot upload a layout", upload(make_xlsx(good), None)[0] in (401, 0))
    check("refused files did not replace the saved layout", http("GET", a + "/sheet" + dates + "&layout=mine", token=owner)[0] == 200)
    check("the owner can remove their layout", call("POST", a + "/sheet/layout/remove", {}, owner)[0] == 200 and call("GET", a + "/sheet/layout", token=owner)[1] == {"layout": None})
    s, d = call("GET", a + "/activity", token=owner)
    actions = {x["action"] for x in d.get("activity", [])}
    for want in ["bill paid", "payment UNDONE", "money returned", "stock purchase", "stock count", "recipe changed", "order sheet layout uploaded", "order sheet downloaded"]:
        check("activity log records: " + want, want in actions, sorted(actions))
    ctx["ingredient"] = batter


def main():
    os.makedirs(os.path.join(HERE, "results"), exist_ok=True)
    dbp = os.path.join(HERE, "results", "blackbox-%s.db" % secrets.token_hex(4))  # always a brand-new, empty store
    logp = os.path.join(HERE, "results", "blackbox.server.log")
    log = open(logp, "w")
    sim = os.path.join(HERE, "results", "printsim-%s" % secrets.token_hex(4))
    os.makedirs(sim)
    env = dict(os.environ, QRO_DB=dbp, QRO_ORDER_RATE="150", QRO_LOGIN_RATE="200", QRO_PRINT_SIM=sim, QRO_PRINT_TIMEOUT="3")
    env.pop("QRO_PAY_SECRET", None)
    srv = subprocess.Popen([sys.executable, "-u", os.path.join(ROOT, "server.py"), "--port", str(PORT)], env=env, stdout=log, stderr=log)
    socks = []
    try:
        for _ in range(80):
            if call("GET", "/api/health", timeout=2)[0] == 200:
                break
            time.sleep(0.25)
        time.sleep(0.5)
        m = re.search(r"enter the code ([A-Z0-9]{5}-[A-Z0-9]{5})", open(logp).read())
        code = m.group(1) if m else ""

        section("a crowd right after the server starts")
        answers = []
        crowd = [threading.Thread(target=lambda: answers.append(http("GET", "/js/api.js", timeout=20)[0])) for _ in range(400)]
        started = time.time()
        [t.start() for t in crowd]
        [t.join() for t in crowd]
        check("400 first-time file requests at once are all answered", answers.count(200) == 400, (answers.count(200), round(time.time() - started, 1)))
        s, h, _, _ = http("GET", "/js/api.js")
        check("page files are sent with the right type", h.get("Content-Type") == "text/javascript; charset=utf-8", h.get("Content-Type"))

        section("no demo parts left")
        check("a new store is empty and asks to be set up", call("GET", "/api/store")[1] == {"setup_needed": True})
        check("a one-time setup code is shown in the server window", bool(code))
        for path in ["/api/demo-session?outlet=x", "/api/brands", "/api/info", "/demo.html", "/js/demo.js", "/js/hub.js"]:
            check("gone: %s" % path, call("GET", path)[0] == 404)
        check("gone: pretend-payment endpoint", call("POST", "/api/pay/test-complete", {"payment_ref": "x", "outcome": "success"})[0] == 404)
        check("online payment is off until a payment company is connected", call("POST", "/api/pay/start", {})[0] == 404 and call("POST", "/api/pay/webhook", {})[0] == 404)
        for slug, pin in [("cutting-chai", "2222"), ("cutting-chai-dadar", "1111")]:
            check("old sample PIN %s opens nothing" % pin, call("POST", "/api/login", {"scope": "admin", "slug": slug, "pin": pin})[0] == 401)

        section("first-time setup")
        good = {"code": code, "restaurant": "Cutting Chai Co.", "theme": "bombay", "outlet": "Malad", "city": "Mumbai", "tables": 12,
                "langs": ["en", "hi", "mr"], "owner_password": OWNER_PW, "staff_pin": STAFF_PIN, "starter_menu": True}
        check("wrong setup code refused", call("POST", "/api/setup", dict(good, code="AAAAA-AAAAA"))[0] == 401)
        for label, kw in [("short owner password", {"owner_password": "abc12"}), ("common owner password", {"owner_password": "password123"}),
                          ("4-digit PIN", {"staff_pin": "1111"}), ("repeated-digit PIN", {"staff_pin": "111111"}), ("counting PIN", {"staff_pin": "123456"}),
                          ("letters in PIN", {"staff_pin": "abcdef"}), ("zero tables", {"tables": 0}), ("unknown look", {"theme": "neon"}),
                          ("no restaurant name", {"restaurant": "  "})]:
            check("setup refuses: " + label, call("POST", "/api/setup", dict(good, **kw))[0] == 400)
        s, d = call("POST", "/api/setup", good)
        check("setup with the right code works", s == 201, d)
        brand, outlet = d.get("brand"), d.get("outlet")
        check("setup cannot be run twice (nobody can take the store over)", call("POST", "/api/setup", good)[0] == 409)

        section("sign-in")
        s, d = call("POST", "/api/login", {"scope": "admin", "slug": brand, "pin": OWNER_PW})
        owner, owner_key = d.get("token"), d.get("stream_key")
        check("owner signs in", s == 200 and owner)
        s, d = call("POST", "/api/login", {"scope": "kitchen", "slug": outlet, "pin": STAFF_PIN})
        staff, staff_key = d.get("token"), d.get("stream_key")
        check("staff signs in", s == 200 and staff)
        a = call("POST", "/api/login", {"scope": "admin", "slug": brand, "pin": "wrong-password-xx"})
        b = call("POST", "/api/login", {"scope": "admin", "slug": "no-such-store", "pin": "wrong-password-xx"})
        check("wrong password and unknown account give the same answer", a == b and a[0] == 401, (a, b))
        check("sign-in codes are not accepted in a web address", call("GET", "/api/admin/%s/overview?t=%s" % (brand, owner))[0] == 401)

        section("every staff and owner function needs the right sign-in")
        guarded_owner = [("GET", "/api/admin/%s/overview"), ("GET", "/api/admin/%s/menu?outlet=" + outlet), ("POST", "/api/admin/%s/items"),
                         ("PUT", "/api/admin/%s/items/1"), ("PUT", "/api/admin/%s/outlet-items?outlet=" + outlet), ("PUT", "/api/admin/%s/outlets/" + outlet),
                         ("POST", "/api/admin/%s/password"), ("POST", "/api/admin/%s/outlets/" + outlet + "/staff-pin"), ("GET", "/api/admin/%s/qr?outlet=" + outlet),
                         ("POST", "/api/admin/%s/outlets/" + outlet + "/new-qr"), ("GET", "/api/admin/%s/activity"), ("POST", "/api/admin/%s/backup"),
                         ("POST", "/api/admin/%s/backup/download"), ("POST", "/api/admin/%s/categories")]
        bad = []
        for method, tmpl in guarded_owner:
            path = tmpl % brand
            body = {} if method != "GET" else None
            for who, tok, want in [("nobody", None, 401), ("forged", "forged-token", 401), ("staff", staff, 403)]:
                got = call(method, path, body, tok)[0]
                if got != want:
                    bad.append((method, path, who, got))
        check("all %d owner functions refuse strangers, forged sign-ins and staff" % len(guarded_owner), not bad, bad)
        bad = []
        for method, path in [("GET", "/api/kitchen/%s/orders"), ("GET", "/api/kitchen/%s/printer"), ("PUT", "/api/kitchen/%s/settings"),
                             ("POST", "/api/kitchen/%s/orders/abc/status")]:
            for tok in (None, "forged"):
                got = call(method, path % outlet, {"auto_accept": True} if method != "GET" else None, tok)[0]
                if got != 401:
                    bad.append((path, tok, got))
        check("all kitchen functions refuse strangers", not bad, bad)

        section("table QR codes: only someone at the table can order")
        s, d = call("GET", "/api/admin/%s/qr?outlet=%s" % (brand, outlet), token=owner)
        links = {t["table"]: t["path"] for t in d.get("tables", [])}
        keys = {n: urllib.parse.parse_qs(urllib.parse.urlparse(p).query)["k"][0] for n, p in links.items()}
        check("owner gets one secret link per table", len(keys) == 12 and len(set(keys.values())) == 12)
        SEEN_KEYS.extend(keys.values())
        http("GET", links.get(1, "/"))
        menu = {i["slug"]: i for c in call("GET", "/api/menu/" + outlet)[1]["categories"] for i in c["items"]}
        food, tea = menu["vada-pav"]["id"], menu["cutting-chai"]["id"]

        def order(table=1, key="use", **kw):
            body = {"outlet": outlet, "table": table, "lines": [{"item_id": food, "qty": 1}]}
            if key == "use":
                body["key"] = keys.get(table if isinstance(table, int) else 1)
            elif key is not None:
                body["key"] = key
            body.update(kw)
            return call("POST", "/api/orders", body)
        check("no table code: refused", order(key=None)[0] == 403)
        check("made-up table code: refused", order(key="0" * 20)[0] == 403)
        check("table 1's code does not work for table 2", order(table=2, key=keys[1])[0] == 403)
        s, d = order(table=1)
        pid = d.get("public_id")
        check("the real QR code can order", s == 201 and pid, d)
        check("order ids are long and unguessable", pid and len(pid) >= 20)
        check("the page can tell if a scanned code is valid", call("GET", "/api/table/%s/1?k=%s" % (outlet, keys[1]))[1] == {"valid": True}
              and call("GET", "/api/table/%s/1?k=nope" % outlet)[1] == {"valid": False})

        section("order rules")
        for label, kw in [("table 0", dict(table=0)), ("table 99", dict(table=99)), ("table as text", dict(table="1; DROP TABLE orders")),
                          ("negative quantity", dict(lines=[{"item_id": food, "qty": -1}])), ("quantity 21", dict(lines=[{"item_id": food, "qty": 21}])),
                          ("half a dish", dict(lines=[{"item_id": food, "qty": 1.5}])), ("unknown dish", dict(lines=[{"item_id": 99999, "qty": 1}])),
                          ("same dish twice", dict(lines=[{"item_id": food, "qty": 1}] * 2)), ("empty order", dict(lines=[])),
                          ("name too long", dict(name="x" * 31)), ("endless number", dict(table=float("inf"))),
                          ("astronomical number", dict(lines=[{"item_id": 10 ** 40, "qty": 1}])), ("broken characters", dict(name="\ud800"))]:
            s = order(**kw)[0]
            check("refused: " + label, 400 <= s < 500, s)
        s, d = order(table=2, lines=[{"item_id": food, "qty": 2, "price": 0}], total=0)
        check("prices are set by the store, not by the phone", s == 201 and d["total"] == 2 * menu["vada-pav"]["price"], d)
        s, d = order(table=3, name="'; DROP TABLE orders;--")
        check("database attack text is stored as plain text", s == 201)
        s, d = order(table=4, name="<img src=x onerror=alert(1)>")
        check("script text is kept as data (screens never run it)", s == 201 and call("GET", "/api/orders/" + d["public_id"])[1]["name"].startswith("<img"))
        s, d = order(table=5, client_key="retry-1")
        s2, d2 = order(table=5, client_key="retry-1")
        check("a repeated tap does not create a second order", s2 == 200 and d2.get("public_id") == d.get("public_id"))
        flood = [order(table=6)[0] for _ in range(8)]
        check("one table cannot flood the kitchen", flood.count(201) == 4 and flood.count(429) == 4, flood)

        section("counter sales")
        take = {"outlet": outlet, "kind": "takeaway", "name": "Ravi", "lines": [{"item_id": food, "qty": 2}], "pay_method": "upi"}
        check("a phone cannot send unpaid takeaway", call("POST", "/api/orders", take)[0] == 402)
        check("a forged staff sign-in cannot either", call("POST", "/api/orders", take, "forged")[0] == 401)
        check("counter must record how it was paid", call("POST", "/api/orders", {k: v for k, v in take.items() if k != "pay_method"}, staff)[0] == 400)
        check("made-up payment type refused", call("POST", "/api/orders", dict(take, pay_method="iou"), staff)[0] == 400)
        s, cd = call("POST", "/api/orders", take, staff)
        check("signed-in counter can sell takeaway", s == 201, cd)
        s, d = call("POST", "/api/orders", {"outlet": outlet, "kind": "dine_in", "table": 7, "lines": [{"item_id": tea, "qty": 1}]}, staff)
        check("staff can enter a table order without a QR code", s == 201, d)

        section("kitchen and live screens")
        s, k = call("GET", "/api/kitchen/%s/orders" % outlet, token=staff)
        check("kitchen sees open orders and printer status", s == 200 and k["orders"] and "waiting" in k["printer"])
        st = lambda p, v: call("POST", "/api/kitchen/%s/orders/%s/status" % (outlet, p), {"status": v}, staff)[0]
        check("steps cannot be skipped", st(pid, "served") == 409)
        check("normal flow works", st(pid, "ready") == 200 and st(pid, "served") == 200)
        check("a finished order cannot be reopened", st(pid, "preparing") == 409)
        live, line = open_stream("/api/stream?outlet=%s&key=%s" % (outlet, staff_key))
        socks.append(live)
        check("kitchen live feed opens with its stream key", " 200 " in line, line)
        for label, q in [("no key", ""), ("forged key", "&key=forged"), ("the sign-in token instead of the key", "&key=" + staff), ("token the old way", "&t=" + staff)]:
            s2, line2 = open_stream("/api/stream?outlet=%s%s" % (outlet, q))
            s2.close()
            check("kitchen live feed refuses " + label, " 401 " in line2, line2)
        check("the stream key cannot be used as a sign-in", call("GET", "/api/kitchen/%s/orders" % outlet, token=staff_key)[0] == 401)
        s, d = order(table=8)
        got, _ = stream_reads(live, b"order_new", 5)
        check("a new order arrives on the kitchen screen", b"order_new" in got)
        s, extra = call("POST", "/api/login", {"scope": "kitchen", "slug": outlet, "pin": STAFF_PIN})
        feed2, _ = open_stream("/api/stream?outlet=%s&key=%s" % (outlet, extra["stream_key"]))
        socks.append(feed2)
        call("POST", "/api/logout", {}, extra["token"])
        check("signing out ends that sign-in", call("GET", "/api/kitchen/%s/orders" % outlet, token=extra["token"])[0] == 401)
        _, closed = stream_reads(feed2, None, 9)
        check("signing out also stops its live order feed", closed)
        s, board = call("GET", "/api/board/" + outlet)
        check("token board shows numbers only", s == 200 and board["orders"] and all(set(o) == {"token", "status"} for o in board["orders"]), board)

        live_feeds = [live]

        def restart():
            nonlocal srv
            srv.terminate()
            srv.wait(10)
            srv = subprocess.Popen([sys.executable, "-u", os.path.join(ROOT, "server.py"), "--port", str(PORT)], env=env, stdout=log, stderr=log)
            for _ in range(80):
                if call("GET", "/api/health", timeout=2)[0] == 200:
                    break
                time.sleep(0.25)
            a = call("POST", "/api/login", {"scope": "kitchen", "slug": outlet, "pin": STAFF_PIN})[1]
            b = call("POST", "/api/login", {"scope": "admin", "slug": brand, "pin": OWNER_PW})[1]
            feed, _ = open_stream("/api/stream?outlet=%s&key=%s" % (outlet, a.get("stream_key")))
            socks.append(feed)
            live_feeds[0], ctx["staff_key"] = feed, a.get("stream_key")
            return a.get("token"), b.get("token")

        ctx = {"outlet": outlet, "brand": brand, "owner": owner, "staff": staff, "tea": tea, "food": food, "sim": sim, "restart": restart}
        printing_tests(ctx)
        staff, owner, live = ctx["staff"], ctx["owner"], live_feeds[0]
        staff_key = ctx.get("staff_key", staff_key)
        ctx["food"] = food
        money_tests(ctx)

        section("owner: menu and settings")
        s, d = call("POST", "/api/admin/%s/categories" % brand, {"names": {"en": "Specials"}}, owner)
        check("owner adds a menu section", s == 201, d)
        special = d.get("slug")
        s, d = call("POST", "/api/admin/%s/items" % brand, {"category": special, "names": {"en": "Samosa"}, "price": 20}, owner)
        samosa = d.get("id")
        check("owner adds a dish", s == 201)
        call("PUT", "/api/admin/%s/items/%s" % (brand, samosa), {"price": 25}, owner)
        find = lambda: [i for c in call("GET", "/api/menu/" + outlet)[1]["categories"] for i in c["items"] if i["id"] == samosa]
        check("price change reaches the menu", find() and find()[0]["price"] == 25)
        call("PUT", "/api/admin/%s/items/%s" % (brand, samosa), {"archived": True}, owner)
        check("removed dish leaves the menu", not find())
        check("removed dish cannot be ordered", order(table=9, lines=[{"item_id": samosa, "qty": 1}])[0] == 400)
        page = lambda path: http("GET", path)[3].decode("utf-8", "replace")
        check("a restaurant with its own website gets it from its table QR", "/kit/guest.js" in page("/r/%s/1?k=x" % outlet))
        check("any other address gets the standard guest menu", "/js/customer.js" in page("/r/some-other-place/1"))
        check("the brand website files load", all(http("GET", f)[0] == 200 for f in ("/kit/guest.js", "/brands/cutting-chai-co/site.js", "/brands/cutting-chai-co/style.css")))
        check("a brand website cannot be used to read other files", call("GET", "/brands/../../server.py")[0] == 404 and call("GET", "/brands/cutting-chai-co/..%2f..%2f..%2fserver.py")[0] == 404)
        check("a real store is not marked as sample data", call("GET", "/api/store")[1].get("sample") is False)
        outlet_url = "/api/admin/%s/outlets/%s" % (brand, outlet)
        counter_sale = lambda: call("POST", "/api/orders", {"outlet": outlet, "kind": "takeaway", "name": "Asha", "pay_method": "cash", "lines": [{"item_id": food, "qty": 1}]}, staff)[0]
        check("owner can switch to dine-in only", call("PUT", outlet_url, {"takeaway": False}, owner)[0] == 200 and call("GET", "/api/outlet/" + outlet)[1]["outlet"]["takeaway"] is False)
        check("dine-in only refuses takeaway, even at the counter", counter_sale() == 409)
        s, d = order(table=2)
        check("table orders still work when dine-in only", s == 201, (s, d))
        check("a nonsense takeaway setting is refused", call("PUT", outlet_url, {"takeaway": "no"}, owner)[0] == 400)
        call("PUT", outlet_url, {"takeaway": True}, owner)
        check("takeaway can be switched back on", counter_sale() == 201)
        s, d = order(table=5, note="less spicy please")
        got = call("GET", "/api/orders/" + str(d.get("public_id")))[1]
        check("a special request is saved with the order", s == 201 and got.get("note") == "less spicy please", got)
        check("pausing orders blocks guests", call("PUT", "/api/admin/%s/outlets/%s" % (brand, outlet), {"accepting": False}, owner)[0] == 200 and order(table=10)[0] == 409)
        call("PUT", "/api/admin/%s/outlets/%s" % (brand, outlet), {"accepting": True}, owner)
        for gap in (5, 2, 0):
            check("print gap %s can be chosen" % gap, call("PUT", "/api/admin/%s/outlets/%s" % (brand, outlet), {"print_gap": gap}, owner)[0] == 200)

        section("privacy and what outsiders can see")
        public = json.dumps([call("GET", p)[1] for p in ["/api/store", "/api/outlet/" + outlet, "/api/menu/" + outlet, "/api/board/" + outlet, "/api/orders/" + cd["public_id"]]])
        check("public pages reveal no passwords, fingerprints, phones or kitchen settings",
              not re.search(r"pin_hash|600000\$|phone|print_gap|auto_accept|store_secret", public), re.findall(r"pin_hash|phone|print_gap|auto_accept|store_secret", public))
        check("sales numbers are not public", call("GET", "/api/admin/%s/overview" % brand)[0] == 401)
        for path in ["/server.py", "/security.py", "/db.py", "/data/store.db", "/../server.py", "/%2e%2e/server.py", "/css/../../db.py",
                     "/..%2f..%2fsecurity.py", "/%2e%2e%5cstore.py", "/loadtest/results/blackbox.server.log", "/.git/config", "/js/.hidden"]:
            s, _, _, payload = http("GET", path)
            check("file not served: " + path, s in (400, 404) and b"import " not in payload and b"SQLite" not in payload, s)

        section("browser protections")
        for label, path in [("a page", "/"), ("an order page", "/r/%s/1" % outlet), ("the data interface", "/api/store"), ("an error reply", "/nope")]:
            _, h, _, _ = http("GET", path)
            csp = h.get("Content-Security-Policy", "")
            check("security headers on " + label, "default-src 'self'" in csp and "frame-ancestors 'none'" in csp and h.get("X-Frame-Options") == "DENY"
                  and h.get("X-Content-Type-Options") == "nosniff" and h.get("Referrer-Policy") == "no-referrer", dict(h))
        _, h, _, _ = http("GET", "/")
        check("server software is not advertised", "Python" not in h.get("Server", ""), h.get("Server"))
        pages_ok = []
        for name in os.listdir(os.path.join(ROOT, "web")):
            if name.endswith(".html"):
                html = http("GET", "/" + name)[3].decode()
                if re.search(r"<script(?![^>]*\bsrc=)", html) or re.search(r"\son\w+\s*=", html):
                    pages_ok.append(name)
        check("no page contains inline script (so the script lock holds)", not pages_ok, pages_ok)

        section("broken and hostile requests")
        for label, size in [("negative size", "-1"), ("nonsense size", "abc"), ("huge size", "99999999999999999999")]:
            out, took = raw_exchange(("POST /api/orders HTTP/1.0\r\nContent-Length: %s\r\n\r\n{}" % size).encode())
            check("request with a %s is refused quickly" % label, out.startswith(b"HTTP/1.0 4") and took < 5, (out[:40], round(took, 1)))
        for label, raw, want in [("too large", b"x" * 70000, 413), ("not JSON", b"{oops", 400), ("a list", b"[1]", 400), ("deeply nested", b"[" * 30000 + b"]" * 30000, 400)]:
            s = call("POST", "/api/orders", raw=raw)[0]
            check("body that is %s is refused" % label, s == want, s)
        out, _ = raw_exchange(b"DELETE /api/orders/x HTTP/1.0\r\n\r\n")
        check("unsupported method gets a clean reply", out.startswith(b"HTTP/1.0 501"), out[:30])
        raw_exchange(b"\x00\xff garbage\r\n\r\n", timeout=4)
        check("binary garbage does not crash it", call("GET", "/api/health")[0] == 200)
        for p in ["/api/outlet/%27%20OR%201=1--", "/api/menu/x%27%3BDROP%20TABLE%20items%3B--", "/api/orders/%27%20OR%20%271%27=%271", "/api/board/%00"]:
            check("database attack in address finds nothing", call("GET", p)[0] in (400, 404), p)

        section("random junk sent to every function (fuzzing)")
        junk_values = [None, True, False, 0, -1, 1.5, 10 ** 30, float("inf"), "", "a" * 5000, "'; --", "<x>", [], [1, 2], {}, {"a": {"b": 1}}, [None], "\u0000", "../.."]
        fields = ["outlet", "table", "key", "lines", "kind", "name", "note", "prefs", "client_key", "pay_method", "status", "auto_accept", "scope", "slug", "pin",
                  "code", "restaurant", "theme", "tables", "langs", "current", "new", "password", "current_password", "mode", "width",
                  "method", "order", "unit", "action", "qty", "paid", "ingredient_id", "low_at", "per", "ingredients", "category", "names", "descs", "price",
                  "veg", "tag", "instant", "archived", "item_id", "available", "accepting", "kitchen_lang", "print_gap", "print_order", "payment_ref", "starter_menu"]
        targets = [("POST", "/api/orders", None), ("POST", "/api/orders", staff), ("POST", "/api/login", None), ("POST", "/api/setup", None),
                   ("PUT", "/api/kitchen/%s/settings" % outlet, staff), ("PUT", "/api/kitchen/%s/printer" % outlet, staff),
                   ("POST", "/api/kitchen/%s/printer/test" % outlet, staff), ("POST", "/api/kitchen/%s/slips/1/reprint" % outlet, staff),
                   ("POST", "/api/kitchen/%s/orders/%s/pay" % (outlet, pid), staff), ("POST", "/api/admin/%s/ingredients" % brand, owner),
                   ("PUT", "/api/admin/%s/ingredients/%s" % (brand, ctx["ingredient"]), owner), ("POST", "/api/admin/%s/stock?outlet=%s" % (brand, outlet), owner),
                   ("PUT", "/api/admin/%s/stock?outlet=%s" % (brand, outlet), owner), ("PUT", "/api/admin/%s/recipes/%s" % (brand, food), owner),
                   ("POST", "/api/admin/%s/payments/undo?outlet=%s" % (brand, outlet), owner),
                   ("POST", "/api/kitchen/%s/orders/%s/status" % (outlet, d.get("public_id", pid)), staff),
                   ("POST", "/api/admin/%s/items" % brand, owner), ("PUT", "/api/admin/%s/items/1" % brand, owner), ("PUT", "/api/admin/%s/items/999999999" % brand, owner),
                   ("PUT", "/api/admin/%s/outlet-items?outlet=%s" % (brand, outlet), owner), ("PUT", "/api/admin/%s/outlets/%s" % (brand, outlet), owner),
                   ("POST", "/api/admin/%s/categories" % brand, owner), ("POST", "/api/admin/%s/password" % brand, owner),
                   ("POST", "/api/admin/%s/outlets/%s/staff-pin" % (brand, outlet), owner), ("POST", "/api/admin/%s/backup/download" % brand, owner)]
        rng = random.Random(5)
        before_errors, sent = len(server_errors), 0
        for method, path, tok in targets:
            for _ in range(40):
                body = {f: rng.choice(junk_values) for f in rng.sample(fields, rng.randint(1, 8))}
                if "outlet" in body and rng.random() < 0.6:
                    body["outlet"] = outlet
                if "lines" in body and rng.random() < 0.5:
                    body["lines"] = [{"item_id": rng.choice(junk_values + [food]), "qty": rng.choice(junk_values + [1])}]
                http(method, path, body, tok)
                sent += 1
        check("%d junk requests caused no server errors" % sent, len(server_errors) == before_errors, server_errors[before_errors:][:3])
        check("the store still answers afterwards", call("GET", "/api/menu/" + outlet)[0] == 200)

        section("owner security tools")
        # a fresh sign-in, because the junk above used up this account's allowed wrong-password tries on purpose
        s, d = call("POST", "/api/login", {"scope": "admin", "slug": brand, "pin": OWNER_PW})
        locked_by_fuzz = s == 429
        if locked_by_fuzz:
            time.sleep(61)
            s, d = call("POST", "/api/login", {"scope": "admin", "slug": brand, "pin": OWNER_PW})
        owner = d.get("token", owner)
        change = "/api/admin/%s/password" % brand
        r = call("POST", change, {"current": "not-the-password", "new": NEW_OWNER_PW}, owner)[0]
        check("password change needs the current password", r in (403, 429), r)
        if r == 429:
            time.sleep(61)
        r = call("POST", change, {"current": OWNER_PW, "new": "password123"}, owner)[0]
        check("a weak new password is refused", r == 400, r)
        r = call("POST", change, {"current": OWNER_PW, "new": NEW_OWNER_PW}, owner)[0]
        check("owner changes the password", r == 200, r)
        check("every old owner sign-in is ended", call("GET", "/api/admin/%s/overview" % brand, token=owner)[0] == 401)
        check("the old password stops working", call("POST", "/api/login", {"scope": "admin", "slug": brand, "pin": OWNER_PW})[0] == 401)
        s, d = call("POST", "/api/login", {"scope": "admin", "slug": brand, "pin": NEW_OWNER_PW})
        owner = d.get("token")
        check("the new password works", s == 200)
        s = call("POST", "/api/admin/%s/outlets/%s/staff-pin" % (brand, outlet), {"current_password": NEW_OWNER_PW, "pin": NEW_STAFF_PIN}, owner)[0]
        check("owner changes the staff PIN", s == 200, s)
        check("old staff screens are signed out", call("GET", "/api/kitchen/%s/orders" % outlet, token=staff)[0] == 401)
        _, closed = stream_reads(live, None, 9)
        check("their live order feed stops too", closed)
        old_key = keys[11]
        call("POST", "/api/admin/%s/outlets/%s/new-qr" % (brand, outlet), {}, owner)
        check("after 'new QR codes' the old printed codes stop working", order(table=11, key=old_key)[0] == 403)
        s, d = call("GET", "/api/admin/%s/activity" % brand, token=owner)
        actions = {a["action"] for a in d.get("activity", [])}
        everything = json.dumps(d)
        for want in ["owner password changed", "staff PIN changed", "new table QR codes", "signed out"]:
            check("activity log records: " + want, want in actions, sorted(actions))
        check("the activity log never contains a password or PIN", not any(x in everything for x in (OWNER_PW, NEW_OWNER_PW, STAFF_PIN, NEW_STAFF_PIN)))
        s, d = call("POST", "/api/admin/%s/backup" % brand, {}, owner)
        check("owner can make a backup", s == 200 and d.get("name", "").endswith(".db"), d)
        check("downloading a backup asks for the password again", call("POST", "/api/admin/%s/backup/download" % brand, {"password": "nope-nope-nope"}, owner)[0] == 403)
        s, h, _, payload = http("POST", "/api/admin/%s/backup/download" % brand, {"password": NEW_OWNER_PW}, owner)
        check("the downloaded backup is a real database", s == 200 and payload.startswith(b"SQLite format 3"), s)
        check("passwords and PINs are not readable inside the backup", not any(x.encode() in payload for x in (OWNER_PW, NEW_OWNER_PW, STAFF_PIN, NEW_STAFF_PIN)))

        section("floods and stuck connections")
        opened, refused = [], 0
        for _ in range(70):
            sk, line = open_stream("/api/stream?board=" + outlet)
            socks.append(sk)
            if " 200 " in line:
                opened.append(sk)
            else:
                refused += 1
        check("one device cannot open unlimited live screens", len(opened) == 60 and refused == 10, (len(opened), refused))
        for sk in opened:
            sk.close()
        idle = []
        for _ in range(300):
            try:
                idle.append(socket.create_connection(("127.0.0.1", PORT), timeout=5))
            except OSError:
                break
        check("still answers with %d silent connections open" % len(idle), call("GET", "/api/health")[0] == 200)
        time.sleep(33)
        try:
            idle[0].settimeout(3)
            dropped = idle[0].recv(1) == b""
        except socket.timeout:
            dropped = False
        except OSError:
            dropped = True
        check("silent connections are dropped after about 30 s", dropped)
        for sk in idle:
            sk.close()
        codes = [order(table=12, key="bad")[0] for _ in range(170)]
        check("one network cannot send unlimited orders", 429 in codes, sorted(set(codes)))

        section("guessing the sign-in")
        s_codes = [call("POST", "/api/login", {"scope": "kitchen", "slug": outlet, "pin": "9%05d" % i})[0] for i in range(8)]
        check("PIN guessing is stopped after 5 tries", s_codes[:5] == [401] * 5 and set(s_codes[5:]) == {429}, s_codes)
        check("even the right PIN waits during the lockout", call("POST", "/api/login", {"scope": "kitchen", "slug": outlet, "pin": NEW_STAFF_PIN})[0] == 429)
    finally:
        for sk in socks:
            try:
                sk.close()
            except OSError:
                pass
        srv.terminate()
        try:
            srv.wait(10)
        except subprocess.TimeoutExpired:
            srv.kill()
        log.close()
    section("server log")
    text = open(logp, errors="replace").read()
    check("no crashes recorded", text.count("Traceback") == 0, "%d tracebacks" % text.count("Traceback"))
    check("passwords, PINs and table codes are not written to the log", not any(x in text for x in (OWNER_PW, NEW_OWNER_PW, STAFF_PIN, NEW_STAFF_PIN) + tuple(SEEN_KEYS)))
    fails = [r for r in results if not r[2]]
    summary = "%d checks, %d FAIL" % (len(results), len(fails))
    print("\n" + summary)
    with open(os.path.join(HERE, "results", "blackbox.txt"), "w", encoding="utf-8") as f:
        f.write(summary + "\n" + "".join("%s  [%s] %s\n" % ("PASS" if ok else "FAIL", sec, name) for sec, name, ok in results))
    sys.exit(1 if fails else 0)


if __name__ == "__main__":
    main()
