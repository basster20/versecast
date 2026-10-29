"""Measure detection latency and memory through the real window.

    python tools/bench_detect.py

Feeds a set of real utterances down the same path the microphone uses and
reports, per utterance: which tier answered, how long each stage took, and how
long passed between the transcript arriving and the verse being ready to show.
Also samples whole-app memory at each stage, because that is the number that
decides whether a 188 MB model can stay loaded during a service.

No microphone is opened and no audio is recorded.
"""
import os
import sys
import threading
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import app as host  # noqa: E402

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

UTTERANCES = [
    ("quoted verbatim", "for god so loved the world that he gave his only begotten son"),
    ("quoted verbatim", "the lord is my shepherd i shall not want"),
    ("quoted verbatim", "i can do all things through christ who strengthens me"),
    ("described, never named", "we are more than conquerors through him that loved us"),
    ("described, never named", "he said those who wait upon the lord shall renew their strength"),
    ("paraphrased", "the pastor said we should put off the old man and put on the new"),
    ("paraphrased", "nothing can separate us from the love of god"),
    ("not scripture", "the youth camp will hold its annual meeting on saturday morning"),
    ("not scripture", "please remember to turn off your phones before the service"),
]


def main():
    host._ensure_stderr()
    if host.acquire_single_instance() is None:
        print("FAIL  another Verse window is open")
        return 1

    httpd, port = host.start_server(8780)
    base = f"http://127.0.0.1:{port}"

    import webview

    api = host.Api(base)
    window = webview.create_window("Verse", f"{base}/{host.page_url('index.html')}", js_api=api,
                                   width=1200, height=800)
    api._main = window
    rows = []
    done = threading.Event()

    def drive():
        try:
            window.events.loaded.wait(30)
            time.sleep(1.5)
            window.evaluate_js("window.VerseApp.selectTranslation('kjv', {quiet:true})")
            time.sleep(1.0)

            memory = api.memory_report()
            print(f"idle                 {memory['total_mb']:>7} MB   {memory['processes']} processes")

            started = time.time()
            api.prewarm_detection()
            while api.detection_status()["prewarming"] and time.time() - started < 60:
                time.sleep(0.2)
            memory = api.memory_report()
            print(f"detection warm       {memory['total_mb']:>7} MB   "
                  f"(+{memory['total_mb'] - 0:>0.0f} MB, two pipelines {time.time() - started:.1f}s)")
            api.perf_clear()

            for label, text in UTTERANCES:
                # Wait for the ladder to answer rather than for a fixed time: a
                # slow query would otherwise be read as the previous utterance's
                # result, and the numbers would look better than they are.
                window.evaluate_js("VerseApp.state.detectLast = null")
                api._heard(text, True)
                deadline = time.time() + 12
                info = None
                while time.time() < deadline:
                    time.sleep(0.2)
                    last = window.evaluate_js("JSON.stringify(VerseApp.state.detectLast || null)")
                    import json

                    info = json.loads(last) if last else None
                    if info is not None and not window.evaluate_js("VerseApp.state.stt.asking || false"):
                        break
                ref = window.evaluate_js(
                    "(() => { const e = document.querySelector('#previewWrap .slide-ref'); "
                    "return e ? e.textContent.trim() : ''; })()") or "-"
                timings = (info or {}).get("timings") or {}
                rows.append({
                    "label": label,
                    "text": text,
                    "tier": (info or {}).get("tier") or (info or {}).get("reason") or "?",
                    "ref": ref,
                    "confidence": (info or {}).get("confidence"),
                    "shingle": timings.get("shingle_ms"),
                    "semantic": timings.get("semantic_ms"),
                    "rerank": timings.get("rerank_ms"),
                    "total": timings.get("total_ms"),
                    "e2e": (api.perf_report()["summary"]["latency_metrics"].get("e2e_ms") or {}).get("last"),
                })

            memory = api.memory_report()
            print(f"after the run        {memory['total_mb']:>7} MB   peak {memory['peak_mb']} MB")
            api.detection_unload()
            time.sleep(0.6)
            memory = api.memory_report()
            print(f"after release        {memory['total_mb']:>7} MB")
            report = api.perf_report()["summary"]
            latency = report["latency_metrics"]
            print(f"grade {report['performance_grade']}   events {report['total_events']}")
            for stage in sorted(latency):
                if stage.endswith("_ms") and latency[stage]["count"]:
                    s = latency[stage]
                    print(f"  {stage:<14} avg {s['avg']:>7} ms  p95 {s['p95']:>7}  max {s['max']:>8}  n={s['count']}")
        except Exception as exc:  # noqa: BLE001 - reported, not raised
            print(f"benchmark failed: {exc!r}")
        finally:
            done.set()

    threading.Thread(target=drive, daemon=True).start()

    def shutdown():
        done.wait(300)
        try:
            window.destroy()
        except Exception:
            pass

    threading.Thread(target=shutdown, daemon=True).start()
    webview.start()

    print()
    print(f"{'utterance':<48} {'tier':<16} {'verse':<16} {'conf':>5} {'total':>8}")
    for row in rows:
        print(f"{row['label'] + ': ' + row['text'][:32]:<48} "
              f"{str(row['tier'])[:15]:<16} {row['ref']:<16} "
              f"{(row['confidence'] if row['confidence'] is not None else 0):>5} "
              f"{(row['total'] if row['total'] is not None else 0):>7} ms")
        detail = " · ".join(
            f"{k} {v} ms" for k, v in (("shingle", row["shingle"]), ("semantic", row["semantic"]),
                                       ("rerank", row["rerank"])) if v
        )
        if detail:
            print(f"    {detail}")

    httpd.shutdown()
    httpd.server_close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
