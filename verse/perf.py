"""Performance metrics and advice — the app measuring itself.

Pewbeam exposes get_performance_metrics, get_optimization_recommendations and
clear_performance_metrics, and its advisor prints concrete tuning advice rather
than a chart. The point of that is real-time behaviour: a presenter has one
chance at a service, and "the verse appears about a second after he pauses" is
only knowable by measuring the stages as they run.

What is measured here:

    stt_ms        microphone stops -> transcript in hand
    shingle_ms    exact-match tier
    semantic_ms   embedding tier (including the one-off model load)
    rerank_ms     cross-encoder tier
    detect_ms     the whole detection for one utterance
    e2e_ms        last word spoken -> verse ready to display

Latency keeps the last 200 samples per stage, so average and p95 describe the
current service rather than the whole session. Advice is generated from those
numbers and from what is installed, and every recommendation names a setting
that exists.
"""
from __future__ import annotations

import os
import threading
import time
from collections import deque

WINDOW = 200
# Where real-time stops being real-time. A reference that appears later than
# this reads as lag to the person speaking.
E2E_GOOD_MS = 900
E2E_POOR_MS = 2500


def _percentile(values: list[float], fraction: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, int(round(fraction * (len(ordered) - 1)))))
    return ordered[index]


class Metrics:
    def __init__(self):
        self.started_at = time.time()
        self._lock = threading.Lock()
        self._latency: dict[str, deque] = {}
        self._counters: dict[str, int] = {}

    # ── recording ──────────────────────────────────────────────────────────

    def record(self, stage: str, ms: float) -> None:
        if ms is None or ms < 0:
            return
        with self._lock:
            series = self._latency.get(stage)
            if series is None:
                series = self._latency[stage] = deque(maxlen=WINDOW)
            series.append(round(float(ms), 2))

    def timings(self, values: dict[str, float]) -> None:
        for stage, value in (values or {}).items():
            self.record(stage, value)

    def count(self, name: str, amount: int = 1) -> None:
        with self._lock:
            self._counters[name] = self._counters.get(name, 0) + amount

    def reset(self) -> None:
        with self._lock:
            self._latency.clear()
            self._counters.clear()
            self.started_at = time.time()

    # ── reporting ──────────────────────────────────────────────────────────

    def latency(self, stage: str) -> dict:
        with self._lock:
            values = list(self._latency.get(stage) or [])
        if not values:
            return {"count": 0, "avg": 0.0, "p95": 0.0, "max": 0.0, "last": 0.0}
        return {
            "count": len(values),
            "avg": round(sum(values) / len(values), 1),
            "p95": round(_percentile(values, 0.95), 1),
            "max": round(max(values), 1),
            "last": round(values[-1], 1),
        }

    def counters(self) -> dict:
        with self._lock:
            return dict(self._counters)

    def summary(self, memory: dict | None = None, system: dict | None = None) -> dict:
        stages = {stage: self.latency(stage) for stage in sorted(self._latency)}
        total = sum(self.counters().values()) + sum(s["count"] for s in stages.values())
        return {
            "uptime_seconds": round(time.time() - self.started_at, 1),
            "total_events": total,
            "latency_metrics": stages,
            "counters": self.counters(),
            "system_metrics": system or system_metrics(memory),
            "performance_grade": self.grade(memory),
        }

    def grade(self, memory: dict | None = None) -> str:
        """One letter for the whole pipeline, floored by the worst stage.

        Deliberately blunt: the person reading it wants to know whether the
        screen will keep up, not to study a table.
        """
        e2e = self.latency("e2e_ms")
        stt = self.latency("stt_ms")
        memory_mb = (memory or {}).get("total_mb") or 0.0
        if not e2e["count"] and not stt["count"]:
            return "—"
        slow = max(e2e["avg"], stt["avg"])
        if memory_mb >= 1500 or slow > E2E_POOR_MS:
            return "D"
        if memory_mb >= 1200 or slow > 1600:
            return "C"
        if memory_mb >= 900 or slow > E2E_GOOD_MS:
            return "B"
        return "A"

    def recommendations(self, memory: dict | None = None, detection: dict | None = None) -> list[str]:
        """Concrete, actionable advice drawn from the numbers just measured."""
        out: list[str] = []
        counters = self.counters()
        e2e = self.latency("e2e_ms")
        stt = self.latency("stt_ms")
        semantic = self.latency("semantic_ms")
        detect = self.latency("detect_ms")
        memory_mb = (memory or {}).get("total_mb") or 0.0
        detection = detection or {}
        semantic_report = detection.get("semantic") or {}
        rerank_report = detection.get("rerank") or {}
        shingle_report = detection.get("shingle") or {}

        if e2e["count"] and e2e["avg"] > E2E_GOOD_MS:
            out.append(
                f"A verse reaches the screen {e2e['avg']:.0f} ms after the last word "
                f"(p95 {e2e['p95']:.0f} ms). Most of that is speech recognition: switch the "
                "instant pipeline on, or drop the local model to Whisper tiny."
            )
        if stt["count"] and stt["avg"] > 1500:
            out.append(
                f"Speech recognition averages {stt['avg']:.0f} ms per utterance. Whisper base.en "
                "reads a whole sentence; if this is still too slow, the instant pipeline answers "
                "from a smaller model first and lets this one refine it."
            )
        if semantic["count"] and semantic["avg"] > 250:
            out.append(
                f"Semantic search averages {semantic['avg']:.0f} ms. The model loads once "
                f"({semantic_report.get('load_seconds', 0)} s here) — after that a query is about "
                "35 ms, so a figure this high usually means memory pressure is unloading it."
            )
        if detect["count"] and detect["p95"] > 700:
            out.append(
                f"Detection p95 is {detect['p95']:.0f} ms. If an exact quotation is being spoken, "
                "the shingle tier should be answering in under a millisecond — check that the "
                "Bible in use has an index built."
            )
        if memory_mb >= 900:
            out.append(
                f"Memory is {memory_mb:.0f} MB. Release the embedding model when listening stops "
                "(Settings → Detection → Release model when idle): it is 290 MB of the total."
            )
        if memory_mb >= 1500:
            out.append(
                "Memory is close to what WebView2 and a 188 MB model can share. Close the browser "
                "speech engine, or run Local only."
            )
        if not (semantic_report.get("model") or {}).get("ready"):
            out.append(
                "The embedding model is not installed, so a verse that is never named out loud "
                "cannot be found. Install it in Settings → Detection (209 MB, once)."
            )
        if not rerank_report.get("ready"):
            out.append(
                "The cross-encoder is not installed (23 MB). Without it, near-miss verses — "
                "1 Samuel 2:31 against Ephesians 4:22, for instance — cannot be told apart."
            )
        if not shingle_report.get("cached"):
            out.append(
                "No verbatim index is built yet. It takes about a second and 6 MB, and it is what "
                "makes a quoted verse instant and certain."
            )
        counted = counters.get("detections", 0)
        utterances = counters.get("utterances", 0)
        if utterances >= 20 and counted == 0:
            out.append(
                f"{utterances} utterances have been heard and none produced a verse. If references "
                "are being spoken, lower the Detection strictness in Settings → Detection."
            )
        if not out:
            out.append("Nothing to tune: every stage is inside its budget for real-time use.")
        return out


def system_metrics(memory: dict | None = None) -> dict:
    cpu = 0.0
    try:
        import psutil

        cpu = psutil.cpu_percent(interval=None)
    except Exception:
        pass
    memory = memory or {}
    total_mb = memory.get("total_mb") or 0.0
    return {
        "cpu_usage": round(cpu, 1),
        "memory_usage_mb": total_mb,
        "memory_peak_mb": memory.get("peak_mb") or total_mb,
        "processes": memory.get("processes") or 1,
        "available_mb": round(_available_mb(), 0),
    }


def _available_mb() -> float:
    try:
        import psutil

        return psutil.virtual_memory().available / 1048576
    except Exception:
        return 0.0


METRICS = Metrics()
