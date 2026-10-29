"""Memory watch.

A WebView2 app is several processes at once: the Python host, the browser
process, its GPU and renderer children. Watching any one of them is useless, so
this samples the whole tree, keeps the peak, and calls back when the total
crosses a threshold — the UI then drops what it can live without (the keyword
search index, old queue entries, decoded images) instead of growing until
Windows kills it.

Numbers are working set (RSS), which is what Task Manager shows.
"""
from __future__ import annotations

import os
import threading
import time

SOFT_MB = 900      # trim caches, release what is droppable
HARD_MB = 1500     # trim hard, and say so in the UI
SAMPLE_S = 3.0


class MemoryWatch:
    def __init__(self, soften_mb: int = SOFT_MB, harden_mb: int = HARD_MB, interval: float = SAMPLE_S):
        self.soft_mb = soften_mb
        self.hard_mb = harden_mb
        self.interval = interval
        self.peak_mb = 0.0
        self.current_mb = 0.0
        self.pressed = "none"
        self.on_pressure = None       # callable(level: "soft"|"hard")
        # A feature can declare memory it legitimately needs while it is in use,
        # and the limits move up by that much. Without this the detection stack
        # would be released by the very watchdog meant to protect the app: the
        # page and the 188 MB model together sit near 900 MB, so the model would
        # be dropped mid-service and the next query would pay two seconds to
        # reload it. callable() -> MB, or None.
        self.reserve = None
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._proc = None
        self._last_trim = 0.0

        try:
            import psutil

            self._psutil = psutil
            self._proc = psutil.Process(os.getpid())
        except Exception:
            self._psutil = None

    # ── sampling ───────────────────────────────────────────────────────────

    def sample(self) -> float:
        if self._proc is None:
            return self.current_mb
        total = 0
        try:
            processes = [self._proc, *self._proc.children(recursive=True)]
        except Exception:
            processes = [self._proc]
        for proc in processes:
            try:
                total += proc.memory_info().rss
            except Exception:
                continue
        self.current_mb = round(total / 1048576, 1)
        self.peak_mb = max(self.peak_mb, self.current_mb)
        return self.current_mb

    def report(self) -> dict:
        total = self.sample()
        own = 0.0
        children = 0
        try:
            processes = [self._proc, *self._proc.children(recursive=True)] if self._proc else []
        except Exception:
            processes = [self._proc] if self._proc else []
        for index, proc in enumerate(processes):
            try:
                mb = proc.memory_info().rss / 1048576
            except Exception:
                continue
            if index == 0:
                own = mb
            children += 1
        children = max(0, children - 1)
        soft, hard = self.limits()
        return {
            "total_mb": total,
            "peak_mb": round(self.peak_mb, 1),
            "processes": children + 1,
            "reserved_mb": round(self.reserved_mb(), 1),
            # The two halves matter separately: the host holds the speech and
            # detection models, WebView2 holds the page. "Which one grew" is
            # the first question when the total looks wrong.
            "own_mb": round(own, 1),
            "children_mb": round(max(0.0, total - own), 1),
            "soft_mb": soft,
            "hard_mb": hard,
            "pressed": self.pressed,
            "available": self._psutil is not None,
        }

    # ── watchdog ───────────────────────────────────────────────────────────

    def start(self):
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, name="verse-memory", daemon=True)
        self._thread.start()

    def stop(self):
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=2)
        self._thread = None

    def _loop(self):
        while not self._stop.is_set():
            mb = self.sample()
            soft, hard = self.limits()
            level = "none"
            if mb >= hard:
                level = "hard"
            elif mb >= soft:
                level = "soft"

            if level != "none" and self.on_pressure:
                now = time.time()
                # Never hammer the UI: once a minute is plenty for a leak that
                # took minutes to build up.
                if level == "hard" or now - self._last_trim > 60:
                    self._last_trim = now
                    self.pressed = level
                    try:
                        self.on_pressure(level)
                    except Exception:
                        pass
            if level == "none":
                self.pressed = "none"

            self._stop.wait(self.interval)

    def reserved_mb(self) -> float:
        """Memory that features in use have declared, in MB."""
        if not self.reserve:
            return 0.0
        try:
            return max(0.0, float(self.reserve() or 0.0))
        except Exception:
            return 0.0

    def limits(self) -> tuple[float, float]:
        reserve = self.reserved_mb()
        return self.soft_mb + reserve, self.hard_mb + reserve
