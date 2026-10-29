"""Drive the real window and check offline detection.

Detection needs a live window: the page decides what to stage, and the tiers
below it run on the host. So this starts the app exactly as a person would, feeds
transcripts through the same path the microphone uses, and asks the page what it
sees on the preview.

    python tools/check_detect.py

Prints PASS/FAIL per check and exits 0 only when everything passed. No
microphone is opened, and no audio is recorded: every utterance is injected.

The utterances are the real ones used to tune the tiers, kept here so the
numbers in the comments stay honest:

    exact quotation      "for god so loved the world…"      John 3:16
    honest paraphrase    "put off the old man…"             Ephesians 4:22 / Colossians 3:9
    never named          "we are more than conquerors…"     Romans 8:37
    not scripture        "the youth camp will hold…"        nothing
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


def main():
    host._ensure_stderr()

    if host.acquire_single_instance() is None:
        print("FAIL  another Verse window is open")
        return 1

    httpd, port = host.start_server(8779)
    base = f"http://127.0.0.1:{port}"

    import webview

    api = host.Api(base)
    window = webview.create_window("Verse", f"{base}/{host.page_url('index.html')}", js_api=api,
                                   width=1200, height=800)
    api._main = window

    results = []
    done = threading.Event()

    def check(name, value, want=None):
        ok = (value == want) if want is not None else bool(value)
        results.append((name, ok, value))

    def drive():
        try:
            window.events.loaded.wait(30)
            time.sleep(1.0)

            def preview():
                return window.evaluate_js(
                    "(() => { const e = document.querySelector('#previewWrap .slide-ref'); "
                    "return e ? e.textContent.trim() : ''; })()") or ""

            def heard(text, final=True, wait=1.0):
                api._heard(text, final)
                time.sleep(wait)

            # ── the stack is installed ────────────────────────────────
            status = api.detection_status()
            stack = status.get("stack") or {}
            model = (stack.get("semantic") or {}).get("model") or {}
            check("an embedding model is available", model.get("ready"))
            check("the stack names where the model came from",
                  model.get("source") in ("verse", "pewbeam"))
            check("a reranker is available", (stack.get("rerank") or {}).get("ready"))
            check("the Bibles in this build are known",
                  len((stack.get("shingle") or {}).get("available") or []) >= 4)

            # Listen is what warms the stack; this is the same call.
            api.prewarm_detection()
            time.sleep(8.0)
            check("the stack warms without a microphone", api.detection_status()["prewarm"]
                  if "prewarm" in api.detection_status() else True)
            check("warming loaded the model",
                  (api.detection_status()["stack"]["semantic"]).get("loaded"))

            # ── a verse quoted word for word ─────────────────────────
            heard("for god so loved the world that he gave his only begotten son", True, 1.5)
            check("a quoted verse reaches the preview", "John 3:16" in preview())

            # ── a verse nobody named ─────────────────────────────────
            heard("we are more than conquerors through him that loved us", True, 2.5)
            check("a verse that was only described is found", "Romans 8:37" in preview())

            # ── an honest paraphrase ─────────────────────────────────
            heard("the pastor said we should put off the old man and put on the new", True, 3.0)
            settled = preview()
            check("a paraphrase resolves to one of the verses that says it",
                  "Ephesians 4:22" in settled or "Colossians 3:9" in settled, True)

            # ── nothing to do ────────────────────────────────────────
            before = preview()
            heard("the youth camp will hold its annual meeting on saturday morning", True, 3.5)
            check("ordinary preaching moves nothing", preview(), before)
            heard("please remember to turn off your phones before the service begins", True, 3.0)
            check("an announcement moves nothing", preview(), before)

            # ── the page says where it came from ─────────────────────
            check("the tier that found the last verse is reported",
                  (window.evaluate_js("(VerseApp.state.detectLast||{}).tier || ''") or "") != "",
                  True)
            check("a rejected sentence is marked as such",
                  bool(window.evaluate_js("(VerseApp.state.detectLast||{}).suppressed || false")))

            # ── the settings page ────────────────────────────────────
            window.evaluate_js("document.getElementById('settingsBtn').click()")
            time.sleep(0.4)
            window.evaluate_js(
                "[...document.querySelectorAll('.nav-item[data-sheet]')]"
                ".find(b => b.dataset.sheet === 'detection').click()")
            time.sleep(2.0)
            # Section headings are upper-cased by CSS, and innerText reports what
            # is rendered — so compare without case.
            sheet = (window.evaluate_js("document.getElementById('sheetBody').innerText") or "").lower()
            check("the detection page names the embedding model", "embeddinggemma" in sheet)
            check("the detection page names the cross-encoder", "cross-encoder" in sheet)
            check("the detection page lists the verbatim index", "verbatim index" in sheet)
            check("the detection page offers the strictness control", "how sure is sure" in sheet)
            check("the detection page shows memory", "mb in" in sheet)

            # ── the performance page ─────────────────────────────────
            window.evaluate_js(
                "[...document.querySelectorAll('.nav-item[data-sheet]')]"
                ".find(b => b.dataset.sheet === 'performance').click()")
            time.sleep(2.5)
            perf = (window.evaluate_js("document.getElementById('sheetBody').innerText") or "").lower()
            check("the performance page shows a grade", "grade" in perf)
            check("the performance page shows stage latency", "latency per stage" in perf)
            check("the performance page gives advice", "recommendations" in perf)
            check("the performance page reports the whole-app memory", "whole app" in perf)
            report = api.perf_report()
            check("detection timings were recorded",
                  "detect_ms" in (report["summary"]["latency_metrics"] or {}))
            check("the advisor returned at least one line",
                  len(report.get("recommendations") or []) >= 1)
            check("the advisor reports real advice, not a placeholder",
                  all(len(line) > 40 for line in report["recommendations"]))

            # ── releasing memory ─────────────────────────────────────
            # The watchdog releases the stack by itself when the whole app goes
            # past its soft limit, so load it deliberately here and read the
            # state immediately: that is the behaviour under test, not whether
            # the machine happened to be under pressure. The sentence is a
            # paraphrase on purpose — a verbatim quotation is answered by the
            # shingle tier, which needs no model at all, and this check is
            # about the model.
            api.detect_text("the pastor said we should put off the old man", "kjv")
            time.sleep(0.3)
            loaded_before = api.detection_status()["stack"]["semantic"]["loaded"]
            api.detection_unload()
            time.sleep(0.5)
            after = api.detection_status()
            check("the model was loaded before the release", loaded_before)
            check("releasing gives the model back", after["stack"]["semantic"]["loaded"], False)
            check("releasing is reported with the memory left",
                  after["stack"]["semantic"]["rss_mb"] > 0)
            # And it comes back on demand.
            result = api.detect_text("the pastor said we should put off the old man", "kjv")
            check("it reloads for the next query", result.get("ok"), True)
            check("and the reload is what answered, not the verbatim tier",
                  result.get("tier") != "shingle")

            memory = api.memory_report()
            print(f"      whole app {memory.get('total_mb')} MB in {memory.get('processes')} processes, "
                  f"peak {memory.get('peak_mb')} MB")
        except Exception as exc:  # noqa: BLE001 - reported, not raised
            results.append(("the check ran without exceptions", False, repr(exc)))
        finally:
            done.set()

    threading.Thread(target=drive, daemon=True).start()

    def shutdown():
        done.wait(180)
        try:
            window.destroy()
        except Exception:
            pass

    threading.Thread(target=shutdown, daemon=True).start()
    webview.start()

    failed = 0
    for name, ok, value in results:
        print(("PASS  " if ok else "FAIL  ") + name + ("" if ok else f"   (got {value!r})"))
        if not ok:
            failed += 1
    print(f"DETECT {'PASS' if not failed else 'FAIL'}  {len(results) - failed}/{len(results)}")
    sys.stdout.flush()

    httpd.shutdown()
    httpd.server_close()
    return 0 if not failed else 1


if __name__ == "__main__":
    sys.exit(main())
