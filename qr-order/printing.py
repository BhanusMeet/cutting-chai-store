"""Real slip printing: finding USB printers, laying out ESC/POS slips and sending them one at a time per store.

A slip is only marked 'printed' after Windows says the job was delivered. That is the strongest confirmation
Windows gives: many receipt printers do not report an empty paper roll, so staff can always reprint.

For tests there is a simulated printer: set QRO_PRINT_SIM to a folder. It reads <folder>/printers.json
([{"name", "port", "connected", "problem"}]) and <folder>/mode.txt (ok | unsure) and writes every slip to
<folder>/out/. It is never used unless that variable is set."""
import json
import os
import sys
import textwrap
import threading
import time
import traceback
from collections import deque

TIMEOUT = float(os.environ.get("QRO_PRINT_TIMEOUT", "20"))
RETRY_EVERY = 3.0       # how often a printer that is unplugged or out of paper is checked again
CACHE_SECONDS = 2.0
WIDTHS = {58: (32, 384), 80: (48, 576)}  # paper width in mm -> (characters per line, dots per line)


class NotSent(Exception):
    """Nothing reached the printer: it is safe to send again."""


class Unsure(Exception):
    """Paper may or may not have come out: a person has to look before it is sent again."""


# ------------------------------------------------------------ backends
class NoBackend:
    supported = False

    def detect(self):
        return {"printers": [], "without_driver": 0}

    def send(self, name, data):
        raise NotSent("printing works only when the store computer runs Windows")

    def raster(self, lines, width):
        return None


class WindowsBackend:
    supported = True

    def __init__(self):
        import winprint
        self.w = winprint

    def detect(self):
        """USB printers Windows has set up, and whether each is plugged in. Also counts plugged-in ones with no driver."""
        queues = [p for p in self.w.list_printers() if p["port"].upper().startswith("USB")]
        try:
            ports = self.w.usb_ports_present()
        except OSError:
            ports = None  # cannot tell what is plugged in: go by what Windows reports
        out = []
        for p in queues:
            if ports is None or (ports and all(x is None for x in ports)):
                connected = True
            else:
                connected = p["port"].upper() in [x for x in ports if x]
            out.append({"name": p["name"], "port": p["port"], "connected": connected, "problem": p["problem"]})
        known = {p["port"].upper() for p in queues}
        without = sum(1 for x in (ports or []) if x and x not in known)
        return {"printers": out, "without_driver": without}

    def send(self, name, data):
        try:
            self.w.send_raw(name, data, TIMEOUT)
        except self.w.NotSent as e:
            raise NotSent(str(e))
        except self.w.Unsure as e:
            raise Unsure(str(e))

    def raster(self, lines, width):
        return self.w.raster(lines, width)


class SimBackend:
    supported = True

    def __init__(self, folder):
        self.folder = folder
        os.makedirs(os.path.join(folder, "out"), exist_ok=True)
        self.count = len(os.listdir(os.path.join(folder, "out")))

    def _read(self, name, default):
        try:
            with open(os.path.join(self.folder, name), encoding="utf-8") as f:
                return f.read()
        except OSError:
            return default

    def detect(self):
        try:
            printers = json.loads(self._read("printers.json", "[]"))
        except ValueError:
            printers = []
        return {"printers": [{"name": p["name"], "port": p.get("port", "USB001"), "connected": p.get("connected", True),
                              "problem": p.get("problem", "")} for p in printers], "without_driver": 0}

    def send(self, name, data):
        if self._read("mode.txt", "ok").strip() == "unsure":
            time.sleep(0.2)
            raise Unsure("the printer did not finish in time")
        self.count += 1
        with open(os.path.join(self.folder, "out", "%04d.bin" % self.count), "wb") as f:
            f.write(data)

    def raster(self, lines, width):
        if sys.platform == "win32":
            import winprint
            return winprint.raster(lines, width)
        return None


def make_backend():
    if os.environ.get("QRO_PRINT_SIM"):
        return SimBackend(os.environ["QRO_PRINT_SIM"])
    if sys.platform == "win32":
        try:
            return WindowsBackend()
        except Exception:
            traceback.print_exc()
    return NoBackend()


BACKEND = make_backend()
_cache = {"at": 0.0, "value": None}
_cache_lock = threading.Lock()


def detect(fresh=False):
    """What is plugged in. Cached briefly, because every kitchen screen asks every few seconds."""
    with _cache_lock:
        if fresh or _cache["value"] is None or time.time() - _cache["at"] > CACHE_SECONDS:
            try:
                value = BACKEND.detect()
            except Exception:
                traceback.print_exc()
                value = {"printers": [], "without_driver": 0}
            _cache.update(at=time.time(), value=value)
        return _cache["value"]


def readiness(name):
    """'' if the printer can be sent to now, otherwise why not."""
    p = next((p for p in detect()["printers"] if p["name"] == name), None)
    if p is None:
        return "the printer is no longer set up on the store computer"
    if not p["connected"]:
        return "the printer is unplugged or switched off"
    return p["problem"]


# ------------------------------------------------------------ slip layout
def clean(s):
    """Text from guests must never carry printer commands: every control character is removed."""
    return "".join(ch for ch in str(s) if ch >= " " and not "\x7f" <= ch <= "\x9f")


def slip_lines(slip):
    lines = []
    if slip.get("reprint"):
        lines.append(("*** REPRINT ***", "bold"))
    lines.append(("COUNTER" if slip["station"] == "counter" else "KITCHEN", "bold"))
    lines.append(("#%03d" % slip["token"], "big"))
    lines.append((("TAKEAWAY - %s" % slip["name"]) if slip["kind"] == "takeaway" else "TABLE %d" % slip["table"], "bold"))
    if slip["kind"] != "takeaway" and slip["name"]:
        lines.append((slip["name"], "normal"))
    lines.append((time.strftime("%d-%m-%Y %H:%M", time.localtime(slip["queued_at"])), "normal"))
    lines.append(("-" * 24, "normal"))
    for item in slip["items"]:
        lines.append(("%d x %s" % (item["qty"], item["name"]), "bold"))
    if slip.get("prefs"):
        lines.append(("Chai: %s, sugar %s" % (slip["prefs"]["strength"], slip["prefs"]["sugar"]), "normal"))
    if slip.get("note"):
        lines.append(("Note: %s" % slip["note"], "normal"))
    return [(clean(text), style) for text, style in lines]


def escpos(lines, paper):
    """ESC/POS bytes for a receipt printer. English prints as text; anything else prints as an image."""
    cols, dots = WIDTHS[paper]
    out = bytearray(b"\x1b@")  # reset
    image = None
    if not all(text.isascii() for text, _ in lines):
        image = BACKEND.raster(lines, dots)
    if image:
        stride, rows, data = image
        for top in range(0, rows, 128):  # in bands: small printers have small memories
            band = min(128, rows - top)
            out += b"\x1dv0\x00" + bytes((stride & 255, stride >> 8, band & 255, band >> 8))
            out += data[top * stride:(top + band) * stride]
    else:
        for text, style in lines:
            if set(text) == {"-"}:
                text = "-" * cols
            width = cols // 2 if style == "big" else cols
            out += b"\x1bE" + (b"\x01" if style != "normal" else b"\x00")
            out += b"\x1d!" + (b"\x11" if style == "big" else b"\x00")
            for part in textwrap.wrap(text, width) or [""]:
                out += part.encode("ascii", "replace") + b"\n"
        out += b"\x1bE\x00\x1d!\x00"
    out += b"\n\n\n\x1dV\x42\x00"  # feed and cut (printers without a cutter ignore it)
    return bytes(out)


def test_slip(paper):
    return escpos([("PRINTER TEST", "bold"), ("#000", "big"), ("-" * 24, "normal"),
                   ("English: 2 x Cutting Chai", "normal"), ("हिन्दी: कटिंग चाय", "normal"),
                   ("मराठी: कटिंग चहा", "normal"), (time.strftime("%d-%m-%Y %H:%M"), "normal")], paper)


# ------------------------------------------------------------ one sender per store
class Station:
    def __init__(self):
        self.counter, self.kitchen = deque(), deque()
        self.wake = threading.Condition()
        self.send_lock = threading.Lock()  # a test slip and an order slip never mix
        self.kitchen_next = 0.0
        self.retry_at = 0.0
        self.problem = ""       # why printing is stopped or waiting
        self.stopped = False    # True: a person has to press Try again


class Dispatcher:
    """store(outlet_id) -> {printer_name, paper_width, print_gap, print_mode}
    load(slip_id) -> slip dict, or None if it should no longer print
    mark(slip_id, status, error, at) saves the result and tells the kitchen screen."""

    def __init__(self, store, load, mark):
        self.store, self.load, self.mark = store, load, mark
        self.stations, self.lock = {}, threading.Lock()

    def station(self, outlet_id):
        with self.lock:
            st = self.stations.get(outlet_id)
            if st is None:
                st = self.stations[outlet_id] = Station()
                threading.Thread(target=self._run, args=(outlet_id, st), daemon=True).start()
            return st

    def add(self, outlet_id, slip_id, kind, front=False):
        st = self.station(outlet_id)
        with st.wake:
            q = st.counter if kind == "counter" else st.kitchen
            if slip_id not in q:
                q.appendleft(slip_id) if front else q.append(slip_id)
            st.wake.notify()

    def status(self, outlet_id):
        st = self.station(outlet_id)
        with st.wake:
            return {"holding": len(st.counter) + len(st.kitchen), "problem": st.problem, "stopped": st.stopped}

    def resume(self, outlet_id):
        st = self.station(outlet_id)
        with st.wake:
            st.stopped, st.problem, st.retry_at, st.kitchen_next = False, "", 0.0, 0.0
            st.wake.notify()

    def clear(self, outlet_id):
        st = self.station(outlet_id)
        with st.wake:
            st.counter.clear()
            st.kitchen.clear()
        self.resume(outlet_id)

    def _next(self, st):
        """Waits until a slip may be sent. Counter slips (tea and other ready items) go first and are never paced."""
        with st.wake:
            while True:
                now = time.time()
                if not st.stopped and now >= st.retry_at:
                    if st.counter:
                        return st.counter.popleft(), "counter"
                    if st.kitchen and now >= st.kitchen_next:
                        return st.kitchen.popleft(), "kitchen"
                st.wake.wait(0.2)

    def _run(self, outlet_id, st):
        while True:
            try:
                slip_id, kind = self._next(st)
                self._one(outlet_id, st, slip_id, kind)
            except Exception:
                traceback.print_exc()
                time.sleep(1)

    def _one(self, outlet_id, st, slip_id, kind):
        cfg = self.store(outlet_id)
        slip = self.load(slip_id)
        if not slip or not cfg or cfg["print_mode"] != "usb":
            return
        marked = False
        try:
            why = readiness(cfg["printer_name"])
            if why:
                raise NotSent(why)
            data = escpos(slip_lines(slip), cfg["paper_width"])
            self.mark(slip_id, "sending", "")
            marked = True
            with st.send_lock:
                BACKEND.send(cfg["printer_name"], data)
        except NotSent as e:  # safe to try again by itself: put it back at the front and look again shortly
            with st.wake:
                changed, st.problem, st.retry_at = st.problem != str(e), str(e), time.time() + RETRY_EVERY
                (st.counter if kind == "counter" else st.kitchen).appendleft(slip_id)
            if changed or marked:  # a slip left as 'sending' would never be picked up again
                self.mark(slip_id, "queued", str(e))
        except Exception as e:  # unsure what came out: stop, and let a person decide
            if not isinstance(e, Unsure):
                traceback.print_exc()
            with st.wake:
                st.stopped, st.problem = True, str(e) or "printing failed"
            self.mark(slip_id, "failed", str(e) or "printing failed")
        else:
            sent_at = time.time()  # when the printer took it, not when the database got round to saving that
            with st.wake:
                st.problem = ""
                if kind == "kitchen":
                    st.kitchen_next = sent_at + max(cfg["print_gap"], 0)
            self.mark(slip_id, "printed", "", sent_at)
