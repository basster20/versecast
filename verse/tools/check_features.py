"""Drive the real window and check the live features.

Transcription, voice commands, the memory watch and NDI each need a live window
(and, for NDI, a live projection window), so this starts the app exactly as a
person would and asks the page what it sees.

    python tools/check_features.py

Prints PASS/FAIL per check and exits 0 only when everything passed. The
microphone is opened for about two seconds; nothing is recorded.
"""
import os
import sys
import threading
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import app as host  # noqa: E402

# The Bibles include Yorùbá and Igbo text; a cp1252 console would abort the
# whole check on the first print that mentions one.
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass


def main():
    host._ensure_stderr()

    if host.acquire_single_instance() is None:
        print("FAIL  another Verse window is open")
        return 1

    httpd, port = host.start_server(8778)
    base = f"http://127.0.0.1:{port}"

    import webview

    api = host.Api(base)
    # The same versioned URL the real window opens, so this check never tests a
    # page the profile happens to have cached from an older build.
    window = webview.create_window("Verse", f"{base}/{host.page_url('index.html')}", js_api=api,
                                   width=1200, height=800)
    # app.py does this in main(); without it every host-to-page push is dropped
    # and the transcription checks would only prove the Python side works.
    api._main = window
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

            # Every check below assumes the KJV, whatever the last session left
            # selected.
            window.evaluate_js("window.VerseApp.selectTranslation('kjv', {quiet:true})")
            time.sleep(1.2)
            check("starts on the King James",
                  window.evaluate_js("document.getElementById('translationSelect').value"),
                  "kjv")

            # ── transcription ──────────────────────────────────────────
            check("listen button is on the toolbar",
                  window.evaluate_js("!!document.getElementById('sttBtn')"))
            check("heard line exists",
                  window.evaluate_js("!!document.getElementById('heardLine')"))

            # A live partial is shown as it is spoken, but an unfinished
            # reference must not be staged: "verse twenty" is the first half of
            # "verse twenty eight", and "Romans 8" of "Romans 8:28".
            def shown_refs():
                return window.evaluate_js(
                    "Array.from(document.querySelectorAll("
                    "'#previewWrap .slide-ref, #displayBody .slide-ref'))"
                    ".map(e => e.textContent.trim())") or []

            api._heard("turn with me to romans chapter eight verse twenty", False)
            time.sleep(0.5)
            check("a half-spoken verse is not staged", "Romans 8:20" not in shown_refs(), True)
            check("a half-spoken chapter is not staged", "Romans 8" not in shown_refs(), True)

            # Feed a phrase the way the speech thread does (api._heard pushes
            # into window.verseHeard) — this is the path that silently broke
            # when a Python bool was interpolated into the JS expression.
            api._heard("romans chapter eight verse twenty eight", True)
            time.sleep(0.6)
            heard = window.evaluate_js("document.getElementById('heardText').textContent") or ""
            check("a heard phrase reaches the page", "romans" in heard.lower(), True)
            check("the heard reference is detected and staged",
                  "Romans 8:28" in (window.evaluate_js(
                      "document.querySelector('#previewWrap .slide-ref') ? "
                      "document.querySelector('#previewWrap .slide-ref').textContent : ''") or ""),
                  True)

            # Voice navigation works on the verse currently on screen, not the
            # one the app happened to open on.
            preview_ref = lambda: window.evaluate_js(
                "(document.querySelector('#previewWrap .slide-ref') || {}).textContent || ''"
            )
            # The book was said once; the follow-up only names chapter and verse.
            api._heard("now read verse twenty nine", True)
            time.sleep(0.5)
            check("a bare verse resolves against the last book",
                  "Romans 8:29" in preview_ref(), True)

            # Preaching that mentions "the next verse" must not move the screen.
            api._heard("let us go to the next verse", True)
            time.sleep(0.5)
            check("preaching about the next verse does not move it",
                  "Romans 8:29" in preview_ref(), True)

            api._heard("next verse", True)
            time.sleep(0.5)
            check("voice 'next verse' advances", "Romans 8:30" in preview_ref(), True)
            api._heard("previous verse", True)
            time.sleep(0.5)
            check("voice 'previous verse' goes back", "Romans 8:29" in preview_ref(), True)
            api._heard("next chapter", True)
            time.sleep(0.5)
            check("voice 'next chapter' advances", "Romans 9:1" in preview_ref(), True)

            api._heard("change the bible to Yoruba", True)
            time.sleep(3.0)
            check("voice command changes the Bible",
                  window.evaluate_js("VerseApp.state.settings.translation"), "yor")
            api._heard("switch to King James", True)
            time.sleep(2.5)
            check("voice command switches back",
                  window.evaluate_js("VerseApp.state.settings.translation"), "kjv")

            check("browser engine exists inside the app window",
                  window.evaluate_js(
                      "typeof (window.SpeechRecognition || window.webkitSpeechRecognition)"),
                  "function")

            # The Settings page is where the engine is switched; it must show
            # the installed model and flip between Local and Browser at once.
            window.evaluate_js("document.getElementById('settingsBtn').click()")
            time.sleep(0.4)
            window.evaluate_js(
                "[...document.querySelectorAll('.nav-item[data-sheet]')]"
                ".find(b => b.dataset.sheet === 'transcription').click()")
            time.sleep(1.6)
            sheet = window.evaluate_js("document.getElementById('sheetBody').innerText") or ""
            check("settings shows the model as installed", "installed" in sheet.lower(), True)
            check("settings names Whisper as the local model", "Whisper" in sheet, True)
            check("settings explains the voice commands", "Voice commands" in sheet, True)
            check("settings lists a microphone",
                  (window.evaluate_js(
                      "document.querySelectorAll('[data-setting=micDevice] option').length") or 0) >= 2,
                  True)

            def engine_now():
                return window.evaluate_js("VerseApp.state.settings.sttEngine")

            window.evaluate_js(
                "[...document.querySelectorAll('[data-seg=sttEngine] button')]"
                ".find(b => b.textContent === 'Browser').click()")
            time.sleep(0.5)
            check("engine switches to Browser", engine_now(), "browser")
            check("Browser is the active segment",
                  window.evaluate_js(
                      "[...document.querySelectorAll('[data-seg=sttEngine] button')]"
                      ".find(b => b.textContent === 'Browser').classList.contains('active')"),
                  True)

            window.evaluate_js(
                "[...document.querySelectorAll('[data-seg=sttEngine] button')]"
                ".find(b => b.textContent === 'Local').click()")
            time.sleep(0.5)
            check("engine switches back to Local", engine_now(), "local")

            local_now = lambda: window.evaluate_js("VerseApp.state.settings.localEngine")
            window.evaluate_js(
                "[...document.querySelectorAll('[data-seg=localEngine] button')]"
                ".find(b => b.textContent === 'Vosk').click()")
            time.sleep(0.6)
            check("local model switches to Vosk", local_now(), "vosk")
            window.evaluate_js(
                "[...document.querySelectorAll('[data-seg=localEngine] button')]"
                ".find(b => b.textContent === 'Whisper').click()")
            time.sleep(0.6)
            check("local model switches back to Whisper", local_now(), "whisper")
            window.evaluate_js("document.getElementById('sheetClose').click()")
            time.sleep(0.3)

            started = api.stt_start()
            # Whisper loads 141 MB before it opens the microphone; give it room.
            deadline = time.time() + 25
            while time.time() < deadline:
                if window.evaluate_js("VerseApp.state.stt.status") == "listening":
                    break
                time.sleep(0.3)
            status = api.stt_status()
            check("whisper model is downloaded", status.get("model"), True)
            check("whisper engine starts and listens",
                  window.evaluate_js("VerseApp.state.stt.status"), "listening")
            check("engine reports no error", status.get("error") in (None, ""), True)
            api.stt_stop()
            time.sleep(0.5)
            check("local engine stops", api.stt_status().get("running"), False)

            # ── manual browsing ────────────────────────────────────────
            window.evaluate_js("document.getElementById('bookBtn').click()")
            time.sleep(0.4)
            check("book menu lists every book",
                  window.evaluate_js("document.querySelectorAll('.bookmenu [data-book]').length"),
                  66)
            window.evaluate_js(
                "[...document.querySelectorAll('.bookmenu [data-book]')]"
                ".find(b => b.textContent === 'Psalms').click()"
            )
            time.sleep(0.5)
            check("choosing a book opens its first chapter",
                  window.evaluate_js("document.getElementById('chapterJump').textContent.trim()"),
                  "Psalms 1")
            check("the chapter lists verses",
                  (window.evaluate_js("document.querySelectorAll('#verseList .verse-row').length") or 0) > 0)

            window.evaluate_js("document.getElementById('chapterJump').click()")
            time.sleep(0.4)
            check("chapter picker offers every chapter",
                  window.evaluate_js("document.querySelectorAll('.chapmenu [data-chapter]').length"),
                  150)
            window.evaluate_js(
                "[...document.querySelectorAll('.chapmenu [data-chapter]')]"
                ".find(b => b.textContent === '23').click()"
            )
            time.sleep(0.5)
            check("choosing a chapter opens it",
                  window.evaluate_js("document.getElementById('chapterJump').textContent.trim()"),
                  "Psalms 23")
            check("the opened chapter shows its text",
                  "shepherd" in ((window.evaluate_js(
                      "document.querySelector('#verseList .verse-row .verse-text').textContent") or "").lower()))

            window.evaluate_js("document.querySelector('#verseList .verse-row').click()")
            time.sleep(0.4)
            check("a manually chosen verse reaches the preview",
                  window.evaluate_js("!!document.querySelector('#previewWrap .slide')"))

            # ── other translations ─────────────────────────────────────
            for tid, label, opening, short in (
                ("yor", "Yorùbá", "Ní ìbẹ̀rẹ̀", "YOR"),
                ("ibo", "Igbo", "Na mmalite", "IGB"),
                ("web", "World English Bible", "In the beginning", "WEB"),
            ):
                window.evaluate_js(f"window.VerseApp.selectTranslation('{tid}', {{quiet:true}})")
                time.sleep(3.0)
                # The list is showing whatever chapter was open; go to the first
                # verse so the wording is comparable across translations.
                window.evaluate_js(
                    "VerseApp.jumpTo(VerseApp.E.clamp(VerseApp.E.detect('Genesis 1:1')[0]))")
                time.sleep(0.6)
                text = window.evaluate_js(
                    "document.querySelector('#verseList .verse-row .verse-text').textContent") or ""
                check(f"{label} text loads and renders", text.startswith(opening))
                check(f"{label} is tagged on the output",
                      window.evaluate_js("document.getElementById('outputTranslation').textContent"),
                      short)

            window.evaluate_js("window.VerseApp.selectTranslation('kjv', {quiet:true})")
            time.sleep(2.5)
            window.evaluate_js(
                "VerseApp.jumpTo(VerseApp.E.clamp(VerseApp.E.detect('Genesis 1:1')[0]))")
            time.sleep(0.6)
            check("switching back restores the King James",
                  (window.evaluate_js(
                      "document.querySelector('#verseList .verse-row .verse-text').textContent") or "")
                  .startswith("In the beginning God created"))

            # ── memory ─────────────────────────────────────────────────
            report = api.memory_report()
            check("memory watch reports a figure", (report.get("total_mb") or 0) > 0, True)
            check("memory watch counts the webview processes",
                  (report.get("processes") or 0) > 1, True)
            # The page trims its own caches when the host says so: build the
            # keyword index, then check a trim really releases it.
            built = window.evaluate_js(
                "(function(){ Engine.search('love', 5); return Engine.indexBuilt(); })()"
            )
            check("keyword index builds", built, True)
            window.evaluate_js("window.verseTrim('manual')")
            time.sleep(0.3)
            check("trim releases the keyword index",
                  window.evaluate_js("Engine.indexBuilt()"), False)

            # Pressure path: lower the bar so the next sample crosses it.
            api._mem.soft_mb, api._mem.hard_mb = 1, 2
            time.sleep(3.5)
            check("pressure fires when memory crosses the limit",
                  api.memory_report().get("pressed"), "hard")
            api._mem.soft_mb, api._mem.hard_mb = 900, 1500

            # ── output ─────────────────────────────────────────────────
            api.open_output()
            api._output.events.loaded.wait(20)
            time.sleep(0.8)
            modes = [api.set_output_mode(m).get("mode") for m in ("window", "fullscreen", "ndi")]
            check("output mode switches", modes, ["window", "fullscreen", "ndi"])
            time.sleep(1.0)
            ndi = api.ndi_status()
            check("NDI source starts", ndi.get("running"), True)
            time.sleep(2.0)
            ndi = api.ndi_status()
            check("NDI sends frames", (ndi.get("frames") or 0) > 0, True)
            check("NDI source is discoverable by receivers",
                  api.ndi_visible(), True)
            if ndi.get("error"):
                print("      ndi note:", ndi["error"])
            api.ndi_stop()
            time.sleep(0.5)
            check("NDI source stops", api.ndi_status().get("running"), False)
        except Exception as exc:  # noqa: BLE001 - reported below
            results.append(("driver ran without exceptions", False, repr(exc)))
        finally:
            done.set()
            try:
                if api._output is not None:
                    api._output.destroy()
                    api._output = None
                time.sleep(0.4)
                window.destroy()
            except Exception:
                pass

    threading.Thread(target=drive, daemon=True).start()
    storage = os.path.join(os.environ.get("LOCALAPPDATA") or ROOT, "Verse", "WebView2")
    webview.start(storage_path=storage, private_mode=False)
    done.wait(5)

    for name, ok, value in results:
        print(("PASS  " if ok else "FAIL  ") + name + ("" if ok else f"   (got {value!r})"))
    passed = bool(results) and all(ok for _, ok, _ in results)
    print("FEATURES", "PASS" if passed else "FAIL")
    httpd.shutdown()
    httpd.server_close()
    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(main())
