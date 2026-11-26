"""Slip pacing queue. Every store has its OWN queue and its own pace: "one slip every N seconds" in
Malad has no effect on any other store.

The queue lives on the server and is also saved in the database (table `slips`), so refreshing a kitchen tablet
or restarting the server does not lose slips. This file only decides WHEN each slip is released; the server then
sends it to the store's printer (printing.py) or just shows it on screen.

Order of printing:
  fifo        first in, first out
  small_first the order with the fewest items goes first, but nothing waits longer than MAX_HOLD seconds
"""
import threading
import time
import traceback

MAX_HOLD = 120  # small_first: an order older than this is printed next, so big orders are never starved
TICK = 0.05


class PrintQueue:
    def __init__(self, on_printed):
        self.on_printed = on_printed  # callback(list_of_slips): save as printed and tell the kitchen
        self.lock = threading.Lock()
        self.queues = {}    # outlet_id -> [slip dict, ...] in arrival order
        self.settings = {}  # outlet_id -> (gap_seconds, order_mode)
        self.next_at = {}   # outlet_id -> earliest time this store may print again
        self._started = False

    def configure(self, outlet_id, gap, mode):
        with self.lock:
            old = self.settings.get(outlet_id)
            self.settings[outlet_id] = (float(gap), mode)
            if old and float(gap) < old[0]:  # a faster setting takes effect at once
                self.next_at[outlet_id] = min(self.next_at.get(outlet_id, 0), time.time() + float(gap))

    def add(self, outlet_id, slip):
        """slip needs: id, queued_at, size (number of pieces on it), order_id."""
        with self.lock:
            self.queues.setdefault(outlet_id, []).append(slip)

    def drop_order(self, outlet_id, order_id):
        with self.lock:
            q = self.queues.get(outlet_id)
            if q:
                self.queues[outlet_id] = [s for s in q if s["order_id"] != order_id]

    def drop_all(self, outlet_id):
        with self.lock:
            self.queues.pop(outlet_id, None)

    def stats(self, outlet_id):
        with self.lock:
            q = self.queues.get(outlet_id, [])
            gap, mode = self.settings.get(outlet_id, (0.0, "fifo"))
            return {"waiting": len(q), "oldest_wait": round(time.time() - min(s["queued_at"] for s in q)) if q else 0,
                    "gap": gap, "order": mode}

    def ahead(self, outlet_id):
        with self.lock:
            return len(self.queues.get(outlet_id, []))

    def _due(self, now):
        out = []
        with self.lock:
            for oid, q in self.queues.items():
                gap, mode = self.settings.get(oid, (0.0, "fifo"))
                if not q:
                    continue
                if gap <= 0:  # no pacing: everything prints straight away
                    out.extend(q)
                    q.clear()
                    continue
                at = self.next_at.get(oid, 0)
                if now < at:
                    continue
                pick = 0
                if mode == "small_first" and now - q[0]["queued_at"] < MAX_HOLD:
                    pick = min(range(len(q)), key=lambda i: (q[i]["size"], q[i]["queued_at"]))
                slip = q.pop(pick)
                slip["printed_at"] = now
                out.append(slip)
                # Always a full gap after the slip that really printed. (Timing it from the planned slot let two
                # slips come out almost together when one arrived late in a slot; the load test caught that.)
                self.next_at[oid] = now + gap
        return out

    def _run(self):
        while True:
            try:
                due = self._due(time.time())
                if due:
                    self.on_printed(due)
            except Exception:
                traceback.print_exc()
            time.sleep(TICK)

    def start(self):
        if not self._started:
            self._started = True
            threading.Thread(target=self._run, daemon=True).start()
