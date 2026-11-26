"""Printer functions for the kitchen screen and the owner panel: choose a USB printer or 'No print',
print a test slip, retry or reprint. All of them need a staff (or owner) sign-in for that store."""
import time

import db
import printing
import security
from core import ApiError, as_int, get_outlet, writer

MODES = ("ask", "none", "usb")


def info(c, o, pacer, dispatch):
    mode = o["print_mode"]
    stats = pacer.stats(o["id"])
    waiting, oldest = c.execute("SELECT COUNT(*), MIN(queued_at) FROM slips WHERE outlet_id=? AND status IN ('queued','sending')", (o["id"],)).fetchone()
    stats.update(waiting=waiting, oldest_wait=round(time.time() - oldest) if oldest else 0)
    found = printing.detect() if mode != "none" else {"printers": [], "without_driver": 0}  # 'No print' never looks or asks
    stats.update(mode=mode, name=o["printer_name"] or "", width=o["paper_width"], supported=printing.BACKEND.supported,
                 detected=found["printers"], without_driver=found["without_driver"], problem="", stopped=False, failed=0)
    if mode == "usb":
        state = dispatch.status(o["id"])
        stats.update(problem=state["problem"] or printing.readiness(o["printer_name"]), stopped=state["stopped"],
                     failed=c.execute("SELECT COUNT(*) FROM slips WHERE outlet_id=? AND status='failed'", (o["id"],)).fetchone()[0])
    return stats


class PrintRoutes:
    pacer = None
    dispatch = None

    def printer_outlet(self, c, slug):
        o = get_outlet(c, slug)
        self.need_kitchen(c, o)
        return o

    def staff_log(self, c, slug, action, detail=""):
        security.log_activity(c, "staff:" + slug, self.ip(), action, detail)

    def r_kitchen_printer(self, slug):
        with db.connect() as c:
            o = self.printer_outlet(c, slug)
            self.send_json(info(c, o, self.pacer, self.dispatch))

    def r_printer_choose(self, slug):
        """{mode: 'usb', name, width} | {mode: 'none'} | {mode: 'ask'}"""
        d = self.body()
        mode = d.get("mode")
        if mode not in MODES:
            raise ApiError(400, "mode must be usb, none or ask")
        with db.connect() as c:
            self.printer_outlet(c, slug)
        name, width = None, None
        if mode == "usb":
            name = d.get("name")
            width = as_int(d.get("width"), 58, 80, "width")
            if width not in printing.WIDTHS:
                raise ApiError(400, "width must be 58 or 80")
            if not any(p["name"] == name for p in printing.detect(fresh=True)["printers"]):
                raise ApiError(409, "That USB printer is not set up on the store computer")
        with writer() as c:
            o = self.printer_outlet(c, slug)
            c.execute("UPDATE outlets SET print_mode=?, printer_name=COALESCE(?, printer_name), paper_width=COALESCE(?, paper_width) WHERE id=?",
                      (mode, name, width, o["id"]))
            if mode != "usb":  # nothing that was waiting for a printer may come out later by surprise
                c.execute("UPDATE slips SET status='skipped' WHERE outlet_id=? AND status IN ('queued','sending','failed')", (o["id"],))
            self.staff_log(c, slug, "printer setting", {"usb": "print on %s, %s mm" % (name, width), "none": "no print", "ask": "no printer chosen"}[mode])
        if mode == "usb":
            self.dispatch.resume(o["id"])
        else:
            self.pacer.drop_all(o["id"])
            self.dispatch.clear(o["id"])
        self.r_kitchen_printer(slug)

    def usb_only(self, o):
        if o["print_mode"] != "usb":
            raise ApiError(409, "No printer is chosen for this store")

    def r_printer_test(self, slug):
        self.body()
        with db.connect() as c:
            o = self.printer_outlet(c, slug)
        self.usb_only(o)
        station = self.dispatch.station(o["id"])
        why = printing.readiness(o["printer_name"])
        if not why:
            if not station.send_lock.acquire(timeout=printing.TIMEOUT + 5):
                raise ApiError(409, "The printer is busy. Try again in a moment.")
            try:
                printing.BACKEND.send(o["printer_name"], printing.test_slip(o["paper_width"]))
            except (printing.NotSent, printing.Unsure) as e:
                why = str(e)
            finally:
                station.send_lock.release()
        self.send_json({"ok": not why, "error": why})

    def send_again(self, c, slip_id):
        c.execute("UPDATE slips SET status='queued', reprint=1, error='' WHERE id=?", (slip_id,))

    def r_printer_retry(self, slug):
        """'Try again': every failed slip goes first, marked REPRINT because paper may already have come out."""
        self.body()
        with writer() as c:
            o = self.printer_outlet(c, slug)
            self.usb_only(o)
            failed = c.execute("SELECT id, station FROM slips WHERE outlet_id=? AND status='failed' ORDER BY id DESC LIMIT 50", (o["id"],)).fetchall()
            for r in failed:
                self.send_again(c, r["id"])
            self.staff_log(c, slug, "printer retry", "%d slips" % len(failed))
        for r in failed:  # newest added first to the front, so the oldest ends up first
            self.dispatch.add(o["id"], r["id"], r["station"], front=True)
        self.dispatch.resume(o["id"])
        self.send_json({"retrying": len(failed)})

    def r_printer_clear(self, slug):
        """Give up on failed slips (staff wrote them by hand, or the food is gone) and carry on."""
        self.body()
        with writer() as c:
            o = self.printer_outlet(c, slug)
            self.usb_only(o)
            n = c.execute("UPDATE slips SET status='skipped' WHERE outlet_id=? AND status='failed'", (o["id"],)).rowcount
            self.staff_log(c, slug, "failed slips cleared", "%d slips" % n)
        self.dispatch.resume(o["id"])
        self.send_json({"cleared": n})

    def r_slip_reprint(self, slug, slip_id):
        self.body()
        with writer() as c:
            o = self.printer_outlet(c, slug)
            self.usb_only(o)
            r = c.execute("""SELECT s.id, s.station, s.status, o.token FROM slips s JOIN orders o ON o.id=s.order_id
                             WHERE s.id=? AND s.outlet_id=?""", (int(slip_id), o["id"])).fetchone()
            if not r:
                raise ApiError(404, "Slip not found")
            if r["status"] in ("queued", "sending"):
                raise ApiError(409, "That slip is already waiting to print")
            self.send_again(c, r["id"])
            self.staff_log(c, slug, "slip reprinted", "token %d, %s" % (r["token"], r["station"]))
        self.dispatch.add(o["id"], r["id"], r["station"], front=True)
        self.dispatch.resume(o["id"])
        self.send_json({"ok": True})


S = r"([a-z0-9-]+)"
PRINT_ROUTES = [
    ("GET", r"^/api/kitchen/" + S + "/printer$", "r_kitchen_printer"),
    ("PUT", r"^/api/kitchen/" + S + "/printer$", "r_printer_choose"),
    ("POST", r"^/api/kitchen/" + S + "/printer/test$", "r_printer_test"),
    ("POST", r"^/api/kitchen/" + S + "/printer/retry$", "r_printer_retry"),
    ("POST", r"^/api/kitchen/" + S + "/printer/clear$", "r_printer_clear"),
    ("POST", r"^/api/kitchen/" + S + r"/slips/(\d{1,12})/reprint$", "r_slip_reprint"),
]
