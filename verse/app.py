"""Verse — the desktop application.

Run this instead of a browser. It starts the loopback-only server the UI needs
and hosts it in one application window: its own taskbar entry, no tabs, no
address bar, no bookmarks, no extensions, no back button. Closing the window
closes the server.

    python app.py                 open the app
    python app.py --browser       serve and hand off to the system browser
    python app.py --selftest      automated check, exit code 0/1

The window is a WebView2 host: the Chromium engine built into Windows, the same
one Teams, Outlook and WhatsApp use. The rendering engine is Chromium; the
window is not a browser session you can navigate away from, and the page it
shows is fixed at start-up.

pywebview is required for the window (see requirements.txt). Speech, the memory
watch and NDI are optional: each is imported only when its feature is used, and
the UI says what is missing rather than failing. The server binds 127.0.0.1 and
serves nothing outside this folder.
"""
import argparse
import ctypes
import functools
import os
import sys
import threading
import time
import webbrowser

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)

import http.server  # noqa: E402
import socketserver  # noqa: E402

from serve import Handler, free_port  # noqa: E402  (one server implementation)

APP_NAME = "Verse"


# ── stderr ────────────────────────────────────────────────────────────────────
# Under pythonw.exe there is no console, so sys.stderr is None and anything that
# writes to it would raise. Send it to a log file instead: a silent crash is far
# worse than a stray file.

def _ensure_stderr():
    if sys.stderr is not None:
        return
    base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
    log_dir = os.path.join(base, APP_NAME)
    try:
        os.makedirs(log_dir, exist_ok=True)
        sys.stderr = open(os.path.join(log_dir, "verse.log"), "a", encoding="utf-8", buffering=1)
    except OSError:
        sys.stderr = open(os.devnull, "w", encoding="utf-8")


# ── server ────────────────────────────────────────────────────────────────────

def start_server(port):
    """Serve this folder on 127.0.0.1 in a daemon thread. Returns (httpd, port)."""
    port = free_port("127.0.0.1", port)
    handler = functools.partial(Handler, directory=ROOT)
    httpd = socketserver.ThreadingTCPServer(("127.0.0.1", port), handler)
    httpd.daemon_threads = True
    httpd.allow_reuse_address = True
    threading.Thread(target=httpd.serve_forever, name="verse-http", daemon=True).start()
    return httpd, port


# ── window bridge ─────────────────────────────────────────────────────────────

class Api:
    """Methods the page calls as window.pywebview.api.<name>().

    Because this is a native host rather than a browser, the projection window
    is a real application window owned by this process: no pop-up blocker can
    refuse it, and it survives the operator window losing focus.

    Window handles are stored on underscore-prefixed attributes on purpose:
    pywebview walks every *public* attribute of this object to build the JS
    bridge, and handing it a Window would send that walk through the entire
    WinForms object graph — thousands of attributes, sometimes a hang.
    """

    def __init__(self, base_url):
        self.base_url = base_url
        self._main = None
        self._output = None
        self._output_mode = "window"
        self._ndi_name = "Verse"
        self._stt = None
        self._stt_kind = None
        self._stt_device = None
        self._ndi = None
        self._stt_engine = "local"
        self._stt_local = "whisper"
        self._stt_instant = True
        self._downloading = False
        self._cancel_download = False

        # Offline detection (semantic + shingle + rerank). Nothing is loaded
        # until something asks for it: see the detect_* methods below.
        self._detect_installing = None
        self._detect_building = None
        self._cancel_build = False
        self._prewarming = False
        self._release_when_idle = True

        # Started here rather than in main() so every host of this bridge — the
        # app and the feature check — gets the same guard rails.
        self._mem = None
        try:
            import memory

            self._mem = memory.MemoryWatch()
            self._mem.on_pressure = self._pressure
            # The detection stack declares what it is holding, so the limits
            # rise while it is loaded instead of the watchdog releasing the
            # model the moment the app crosses its base limit.
            self._mem.reserve = self._detection_reserve
            self._mem.start()
        except Exception as exc:  # noqa: BLE001 - the app runs without it
            print(f"memory watchdog unavailable: {exc}", file=sys.stderr)

    # ── plumbing ───────────────────────────────────────────────────────────

    def _push(self, js: str) -> None:
        """Run JS in the main window from any thread. Never raises."""
        window = self._main
        if window is None:
            return
        try:
            window.evaluate_js(js)
        except Exception:
            pass

    def _projection_hwnd(self):
        hwnd = ctypes.windll.user32.FindWindowW(None, "Verse — Projection")
        return int(hwnd) if hwnd else None

    # ── projection window / output ─────────────────────────────────────────

    def open_output(self):
        import webview  # the host module is only importable in app mode

        if self._output is not None:
            try:
                self._output.show()
                self._output.restore()
                return True
            except Exception:
                self._output = None

        self._output = webview.create_window(
            "Verse — Projection",
            f"{self.base_url}/{page_url('output.html')}",
            width=1280,
            height=720,
            min_size=(480, 270),
            background_color="#000000",
        )
        time.sleep(0.4)
        if self._output_mode == "fullscreen":
            self.output_fullscreen()
        if self._output_mode == "ndi":
            self.ndi_start()
        return True

    def output_fullscreen(self, display=0):
        """Toggle the projection window between windowed and fullscreen."""
        if self._output is None:
            return False
        try:
            self._move_to_display(int(display or 0))
            self._output.toggle_fullscreen()
            return True
        except Exception:
            return False

    def _move_to_display(self, index: int):
        screens = list_displays()
        if not screens or self._output is None:
            return False
        index = max(0, min(index, len(screens) - 1))
        x, y, w, h = screens[index]
        try:
            self._output.move(x + 40, y + 40)
            self._output.resize(int(w * 0.8), int(h * 0.8))
            return True
        except Exception:
            return False

    def displays(self):
        return [{"index": i, "width": w, "height": h, "x": x, "y": y}
                for i, (x, y, w, h) in enumerate(list_displays())]

    def set_output_mode(self, mode="window", display=0):
        self._output_mode = mode if mode in ("window", "fullscreen", "ndi", "external") else "window"
        if self._output_mode != "ndi":
            self.ndi_stop()
        elif self._output is not None:
            self.ndi_start()
        if self._output_mode == "fullscreen" and self._output is not None:
            self.output_fullscreen(display)
        return {"mode": self._output_mode}

    def output_status(self):
        return {
            "mode": self._output_mode,
            "open": self._output is not None,
            "ndi": self._ndi.report() if self._ndi else None,
            "displays": self.displays(),
        }

    def ndi_start(self):
        if self._ndi is None:
            import ndi_out

            self._ndi = ndi_out.NdiOutput(on_state=self._ndi_state)
        if self._output is None:
            self.open_output()
            time.sleep(0.6)
        return self._ndi.start(self._projection_hwnd(), self._ndi_name)

    def ndi_stop(self):
        if self._ndi is None:
            return {"ok": True}
        return self._ndi.stop()

    def ndi_status(self):
        return self._ndi.report() if self._ndi else {"running": False, "frames": 0, "fps": 0}

    def ndi_visible(self):
        """True when a receiver's own discovery can see the source we are sending."""
        if self._ndi is None or not self._ndi.running():
            return False
        try:
            import NDIlib as ndi

            if not ndi.initialize():
                return False
            finder = ndi.find_create_v2()
            if finder is None:
                return False
            try:
                deadline = time.time() + 4.0
                while time.time() < deadline:
                    ndi.find_wait_for_sources(finder, 500)
                    names = [s.ndi_name for s in (ndi.find_get_current_sources(finder) or [])]
                    if any(self._ndi_name in n for n in names):
                        return True
                return False
            finally:
                ndi.find_destroy(finder)
        except Exception:
            return False

    def ndi_set_name(self, name="Verse"):
        self._ndi_name = (name or "Verse").strip()[:48] or "Verse"
        return {"name": self._ndi_name}

    def _ndi_state(self, state, note):
        self._push(f"window.verseNdiState && window.verseNdiState({state!r}, {note!r})")

    # ── speech ─────────────────────────────────────────────────────────────

    def stt_status(self):
        import speech

        running = bool(self._stt and self._stt.running())
        active = None
        if running:
            active = getattr(self._stt, "active_device", None)
        if active is None:
            active = self._stt_device
        if active is None:
            # "Automatic" means the same real microphone the engine would pick,
            # not the OS default, which is often a phone-as-webcam.
            active = speech.preferred_device()
        info = speech.model_info(self._stt_local)
        fast = speech.model_info("instant")
        return {
            "engine": self._stt_engine,
            "local_engine": self._stt_local,
            "running": running,
            "device": active,
            "device_name": speech.device_name(active),
            "model": info["ready"],
            "model_mb": info["mb"],
            "model_name": info["name"],
            "model_expected_mb": info["expected_mb"],
            "instant": self._stt_instant,
            "instant_ready": fast["ready"],
            "instant_mb": fast["mb"],
            "instant_name": fast["name"],
            "instant_expected_mb": fast["expected_mb"],
            "instant_active": bool(self._stt and getattr(self._stt, "instant_active", False)),
            "downloading": self._downloading,
            "error": (self._stt.error if self._stt else None),
        }

    def stt_set_instant(self, on=True):
        """Run the fast pipeline beside the accurate one.

        Both read the same microphone: tiny.en answers while the sentence is
        still being spoken, base.en replaces it with the accurate reading once
        the room goes quiet. Costs one extra model (75 MB) only while
        listening, and nothing at all if it is switched off.
        """
        self._stt_instant = bool(on)
        if self._stt is not None:
            if self._stt.running():
                self.stt_stop()
                if self._stt_instant:
                    self.stt_start()
            self._stt = None
            self._stt_kind = None
        return {"instant": self._stt_instant}

    def stt_set_engine(self, engine="local"):
        self._stt_engine = "browser" if engine == "browser" else "local"
        if self._stt and self._stt.running():
            self.stt_stop()
        return {"engine": self._stt_engine}

    def stt_set_local_engine(self, engine="whisper"):
        """Choose the offline recogniser: Whisper (accurate) or Vosk (small)."""
        self._stt_local = "vosk" if engine == "vosk" else "whisper"
        if self._stt is not None:
            if self._stt.running():
                self.stt_stop()
            self._stt = None
            self._stt_kind = None
        return {"local_engine": self._stt_local}

    def stt_devices(self):
        import speech

        return {"devices": speech.input_devices(), "selected": self._stt_device}

    def stt_set_device(self, index=-1):
        try:
            index = int(index)
        except (TypeError, ValueError):
            index = -1
        self._stt_device = None if index < 0 else index
        restarted = False
        if self._stt is not None and self._stt.running():
            self.stt_stop()
            self.stt_start()
            restarted = True
        return {"ok": True, "device": self._stt_device, "restarted": restarted}

    def stt_start(self):
        if self._stt_engine == "browser":
            return {"ok": True, "engine": "browser"}

        import speech

        listener = speech.WhisperListener if self._stt_local == "whisper" else speech.LocalListener
        if self._stt is None or self._stt_kind != self._stt_local:
            self._stt = listener(
                on_text=self._heard,
                on_state=self._stt_state,
                on_level=self._level,
                device=self._stt_device,
                instant=self._stt_instant if self._stt_local == "whisper" else False,
            )
            self._stt_kind = self._stt_local
        elif self._stt.device != self._stt_device:
            self._stt.device = self._stt_device
        # Load the detection stack now rather than in the middle of a reading.
        # Loading it costs about two seconds, and a service does not offer a
        # second chance at the first reference.
        self.prewarm_detection()
        result = self._stt.start()
        if not result.get("ok"):
            reason = result.get("error")
            text = "Download the speech model in Settings → Transcription." if reason == "model-missing" else str(reason)
            self._push(f"window.verseSttError && window.verseSttError({text!r})")
        return result

    def stt_stop(self):
        if self._stt is not None:
            self._stt.stop()
        # Same rule as the speech models: nothing stays resident while the room
        # is quiet. This is the single biggest memory release the app has.
        if self._release_when_idle:
            try:
                import detect

                detect.unload("idle")
            except Exception:
                pass
        return {"ok": True}

    def stt_download(self, engine=None):
        """Fetch a speech model. Defaults to the selected local engine; the page
        passes "instant" explicitly when the fast pipeline is switched on."""
        import speech

        engine = engine if engine in ("whisper", "vosk", "instant") else self._stt_local
        if self._downloading:
            return {"ok": False, "error": "already downloading"}
        if speech.model_ready(engine):
            return {"ok": True, "model": True}

        def progress(fraction, note):
            self._push(f"window.verseModelProgress && window.verseModelProgress({fraction:.3f}, {note!r})")

        def work():
            self._downloading = True
            try:
                speech.download_for(engine, progress=progress, cancelled=lambda: self._cancel_download)
                self._push("window.verseModelDone && window.verseModelDone(true)")
            except Exception as exc:  # noqa: BLE001
                self._push(f"window.verseModelDone && window.verseModelDone(false, {str(exc)!r})")
            finally:
                self._downloading = False

        threading.Thread(target=work, name="verse-model", daemon=True).start()
        return {"ok": True, "started": True}

    def _level(self, value):
        self._push(f"window.verseLevel && window.verseLevel({float(value):.3f})")

    def _heard(self, text, final):
        # "true"/"false" — Python's True/False are undefined identifiers in JS,
        # and a ReferenceError there silently swallowed every heard word.
        flag = "true" if final else "false"
        self._push(f"window.verseHeard && window.verseHeard({text!r}, {flag})")

    def _stt_state(self, state, note):
        self._push(f"window.verseSttState && window.verseSttState({state!r}, {note!r})")

    # ── memory ─────────────────────────────────────────────────────────────

    def memory_report(self):
        if self._mem is None:
            return {"available": False}
        return self._mem.report()

    def memory_trim(self):
        self._push("window.verseTrim && window.verseTrim('manual')")
        return {"ok": True}

    def _detection_reserve(self):
        try:
            import semantic

            return semantic.DETECT.footprint_mb()
        except Exception:
            return 0.0

    def _pressure(self, level):
        self._push(f"window.verseTrim && window.verseTrim({level!r})")
        self._push(f"window.versePressure && window.versePressure({level!r})")
        # The largest thing this process can hand back is not a cache, it is the
        # detection stack: 188 MB of model weights, a 91 MB vector matrix and
        # the reranker. Releasing it costs a two-second reload if it is needed
        # again; keeping it can cost the service, because Windows ends the
        # process that keeps growing.
        try:
            import detect

            freed = detect.unload(f"memory-{level}")
            if any(freed.get("freed", {}).values()):
                self._push(
                    f"window.verseNotice && window.verseNotice("
                    f"{('Memory ' + level + ' — released the detection model')!r})"
                )
        except Exception:
            pass

    # ── offline detection ──────────────────────────────────────────────────

    def prewarm_detection(self):
        """Load the detection stack in the background, before it is needed.

        Called when listening starts. Nothing here blocks the caller: the load
        is about two seconds of ONNX Runtime and the first utterance may arrive
        at any moment, so it happens beside the microphone rather than in front
        of it.
        """
        if self._prewarming:
            return {"ok": True, "note": "already warming"}

        def work():
            import detect, perf

            self._prewarming = True
            started = time.time()
            try:
                detect.semantic.DETECT._embedder_ready()
                result = detect.decide("for god so loved the world", "kjv", use_rerank=False)
                perf.METRICS.record("prewarm_ms", (time.time() - started) * 1000)
                perf.METRICS.count("prewarm")
                self._push(
                    f"window.verseWarm && window.verseWarm(true, "
                    f"{(time.time() - started):.2f}, {result.get('reason')!r})"
                )
            except Exception as exc:  # noqa: BLE001 - detection is optional
                perf.METRICS.count("prewarm.failed")
                self._push(f"window.verseWarm && window.verseWarm(false, 0, {str(exc)!r})")
            finally:
                self._prewarming = False

        threading.Thread(target=work, name="verse-warm", daemon=True).start()
        return {"ok": True, "started": True}

    def detection_status(self):
        import detect

        return {
            "stack": detect.status(),
            "memory": self.memory_report(),
            "installing": self._detect_installing,
            "building": self._detect_building,
            "release_when_idle": self._release_when_idle,
            "prewarming": self._prewarming,
        }

    def detect_text(self, text="", translation="kjv", use_rerank=True):
        """The detection ladder, for one utterance.

        The page calls this only when its own direct detector found nothing:
        an explicitly spoken reference is already handled there, instantly and
        without loading a model.
        """
        import detect, perf

        started = time.time()
        result = detect.decide(text, translation or "kjv", use_rerank=bool(use_rerank))
        perf.METRICS.timings(result.get("timings") or {})
        perf.METRICS.record("detect_ms", (time.time() - started) * 1000)
        if result.get("ok"):
            perf.METRICS.count("detections")
            perf.METRICS.count(f"detections.{result.get('tier') or 'unknown'}")
        else:
            perf.METRICS.count(f"no_match.{result.get('reason') or 'unknown'}")
        return result

    def detection_install(self, kind="semantic"):
        """Download one detection model. Runs beside the UI, never in it."""
        import perf

        kind = "rerank" if kind == "rerank" else "semantic"
        if self._detect_installing:
            return {"ok": False, "error": "already installing", "kind": self._detect_installing}
        if self._downloading:
            return {"ok": False, "error": "a speech model is downloading"}

        def progress(fraction, note):
            self._push(
                f"window.verseDetectProgress && window.verseDetectProgress("
                f"{kind!r}, {fraction:.3f}, {note!r})"
            )

        def work():
            self._detect_installing = kind
            try:
                if kind == "rerank":
                    import rerank

                    rerank.install_model(progress=progress)
                else:
                    import semantic

                    semantic.install_model(progress=progress)
                perf.METRICS.count(f"install.{kind}")
                self._push(
                    f"window.verseDetectDone && window.verseDetectDone({kind!r}, true, '')"
                )
            except Exception as exc:  # noqa: BLE001 - reported to the page
                self._push(
                    f"window.verseDetectDone && window.verseDetectDone({kind!r}, false, {str(exc)!r})"
                )
            finally:
                self._detect_installing = None

        threading.Thread(target=work, name=f"verse-install-{kind}", daemon=True).start()
        return {"ok": True, "started": True, "kind": kind}

    def index_build(self, translation="yor"):
        """Build this translation's own verse vectors, in the background.

        An hour of CPU per Bible on an eight-core machine, resumable, and the
        only way Yoruba or Igbo text can be found semantically at all.
        """
        import semantic

        translation = (translation or "yor").strip()
        if self._detect_building:
            return {"ok": False, "error": "already building", "translation": self._detect_building}

        def progress(fraction, note, extra=None):
            extra = extra or {}
            self._push(
                f"window.verseIndexProgress && window.verseIndexProgress("
                f"{translation!r}, {fraction:.4f}, {note!r}, {int(extra.get('done') or 0)}, "
                f"{int(extra.get('total') or 0)}, {float(extra.get('per_second') or 0)}, "
                f"{float(extra.get('eta_seconds') or -1)})"
            )

        def work():
            self._detect_building = translation
            self._cancel_build = False
            try:
                result = semantic.build_index(
                    translation, progress=progress, cancelled=lambda: self._cancel_build
                )
                self._push(
                    "window.verseIndexDone && window.verseIndexDone("
                    f"{translation!r}, {bool(result.get('ok'))}, {str(result.get('error') or '')!r})"
                )
            except Exception as exc:  # noqa: BLE001 - reported to the page
                self._push(
                    f"window.verseIndexDone && window.verseIndexDone({translation!r}, false, {str(exc)!r})"
                )
            finally:
                self._detect_building = None

        threading.Thread(target=work, name="verse-index", daemon=True).start()
        return {"ok": True, "started": True, "translation": translation}

    def index_cancel(self):
        self._cancel_build = True
        return {"ok": True, "building": self._detect_building}

    def detection_unload(self):
        import detect

        return detect.unload("manual")

    def detection_set_idle_release(self, on=True):
        self._release_when_idle = bool(on)
        return {"release_when_idle": self._release_when_idle}

    # ── performance ────────────────────────────────────────────────────────

    def perf_report(self):
        import detect, perf

        memory = self.memory_report()
        return {
            "summary": perf.METRICS.summary(memory),
            "recommendations": perf.METRICS.recommendations(memory, detect.status()),
            "detection": detect.status(),
            "memory": memory,
        }

    def perf_clear(self):
        import perf

        perf.METRICS.reset()
        return {"ok": True}

    def perf_note(self, stage="e2e_ms", ms=0.0):
        """Timing measured in the page, where the screen is.

        The one figure this side cannot take itself: how long passed between
        the last word being heard and the verse being ready to display.
        """
        import perf

        try:
            perf.METRICS.record(str(stage), float(ms))
        except (TypeError, ValueError):
            pass
        return {"ok": True}

    def close_output(self):
        if self._output is not None:
            try:
                self._output.destroy()
            finally:
                self._output = None
        return True


# ── single instance ───────────────────────────────────────────────────────────
# WebView2 gives one profile folder to one process. A second copy would fail
# with "the requested resource is in use", so a second launch restores the
# window that already exists instead of starting a broken one.

MUTEX_NAME = "Local\\VerseDesktopApp"


def acquire_single_instance():
    """Return a held mutex handle, or None when another copy is running."""
    kernel32 = ctypes.windll.kernel32
    kernel32.CreateMutexW.restype = ctypes.c_void_p
    handle = kernel32.CreateMutexW(None, False, MUTEX_NAME)
    if kernel32.GetLastError() == 183:  # ERROR_ALREADY_EXISTS
        if handle:
            kernel32.CloseHandle(ctypes.c_void_p(handle))
        return None
    return handle


def focus_existing_window(window_title):
    """Bring a running window forward (ShowWindow + SetForegroundWindow)."""
    user32 = ctypes.windll.user32
    hwnd = user32.FindWindowW(None, window_title)
    if hwnd:
        user32.ShowWindow(hwnd, 9)  # SW_RESTORE
        user32.SetForegroundWindow(hwnd)
        return True
    return False


class _RECT(ctypes.Structure):
    _fields_ = [
        ("left", ctypes.c_long),
        ("top", ctypes.c_long),
        ("right", ctypes.c_long),
        ("bottom", ctypes.c_long),
    ]


def list_displays():
    """Every monitor as (x, y, width, height) in virtual-screen coordinates."""
    monitors = []
    proto = ctypes.WINFUNCTYPE(
        ctypes.c_int, ctypes.c_void_p, ctypes.c_void_p, ctypes.POINTER(_RECT), ctypes.c_double
    )

    def collect(hmonitor, hdc, rect, data):
        r = rect.contents
        monitors.append((r.left, r.top, r.right - r.left, r.bottom - r.top))
        return 1

    try:
        ctypes.windll.user32.EnumDisplayMonitors(None, None, proto(collect), 0)
    except Exception:
        pass
    if not monitors:
        w, h = work_area()
        monitors.append((0, 0, w, h))
    return monitors


def work_area():
    """Usable screen size, excluding the taskbar. Falls back to 1500x950."""
    try:
        rect = (ctypes.c_long * 4)()
        if ctypes.windll.user32.SystemParametersInfoW(0x0030, 0, rect, 0):  # SPI_GETWORKAREA
            return rect[2] - rect[0], rect[3] - rect[1]
    except Exception:
        pass
    return 1500, 950


def page_url(name: str) -> str:
    """A URL that changes whenever the shell does.

    WebView2 keeps its own disk cache per profile. Stamping the document with a
    modification time means a launch after an update always loads the new shell
    instead of whatever it had cached.
    """
    rels = [name, "assets/css/app.css", "assets/js/app.js", "assets/js/engine.js",
            "assets/js/translations.js"]
    js_dir = os.path.join(ROOT, "assets", "js")
    try:
        # A regenerated translation must change the stamp too, or the window
        # would keep the copy it cached.
        rels += [os.path.join("assets", "js", entry) for entry in os.listdir(js_dir)
                 if entry.startswith("data") and entry.endswith(".js")]
    except OSError:
        pass

    newest = 0.0
    for rel in rels:
        try:
            newest = max(newest, os.path.getmtime(os.path.join(ROOT, rel)))
        except OSError:
            continue
    return f"{name}?v={int(newest)}"


def message_box(text, title=APP_NAME):
    # MB_ICONERROR | MB_SETFOREGROUND
    ctypes.windll.user32.MessageBoxW(None, text, title, 0x10 | 0x10000)


def watch_load(window, state, timeout=25):
    """Record whether the main window ever finished loading."""
    try:
        window.events.loaded.wait(timeout)
        state["loaded"] = True
    except Exception as exc:  # noqa: BLE001 - reported, not raised
        state["error"] = exc


# ── self-test ─────────────────────────────────────────────────────────────────

def run_selftest(window, api, result):
    """Drive the real window and assert what a person would see."""
    report = []

    def check(name, value, want=None):
        ok = (value == want) if want is not None else bool(value)
        report.append((name, ok, value))
        return ok

    try:
        window.events.loaded.wait(30)
        check("window loads the app", window.evaluate_js("document.readyState"), "complete")
        check(
            "scripture panel renders verses",
            (window.evaluate_js("document.querySelectorAll('#verseList .verse-row').length") or 0) > 0,
        )
        check("no browser chrome surface (fixed URL)", window.evaluate_js("location.pathname"), "/index.html")
        check(
            "native bridge is exposed",
            window.evaluate_js("typeof window.pywebview.api.open_output"),
            "function",
        )
        check("projection window opens", api.open_output())

        api._output.events.loaded.wait(20)
        check(
            "projection window renders",
            api._output.evaluate_js("!!document.getElementById('root')"),
        )

        window.evaluate_js("document.querySelector('#verseList .verse-row').click()")
        window.evaluate_js("document.dispatchEvent(new KeyboardEvent('keydown',{key:'Enter'}))")
        time.sleep(1.2)
        text = api._output.evaluate_js("document.getElementById('root').innerText.slice(0,60)") or ""
        check("verse reaches the projection window", text.strip() and "No signal" not in text)
    except Exception as exc:  # noqa: BLE001 - a failure here must be reported, not raised
        report.append(("selftest ran without exceptions", False, repr(exc)))

    for name, ok, value in report:
        print(("PASS  " if ok else "FAIL  ") + name + ("" if ok else f"   (got {value!r})"))
    passed = all(ok for _, ok, _ in report)
    print("SELFTEST", "PASS" if passed else "FAIL")
    sys.stdout.flush()
    result["code"] = 0 if passed else 1

    # Close down in order and let the event loop end by itself. Killing the
    # process here would leave WebView2 holding the profile folder, and the
    # next launch would fail with "the requested resource is in use".
    try:
        if api._output is not None:
            api._output.destroy()
            api._output = None
            time.sleep(0.5)
        window.destroy()
    except Exception:
        pass


# ── entry point ───────────────────────────────────────────────────────────────

def main():
    _ensure_stderr()

    mutex = acquire_single_instance()
    if mutex is None:
        print("Verse is already running in another window.")
        focus_existing_window(APP_NAME)
        return 0

    ap = argparse.ArgumentParser(description="Verse — scripture presenter")
    ap.add_argument("--port", type=int, default=8777)
    ap.add_argument("--browser", action="store_true", help="open in the system browser instead")
    ap.add_argument("--selftest", action="store_true", help="verify the window and exit")
    args = ap.parse_args()

    httpd, port = start_server(args.port)
    base = f"http://127.0.0.1:{port}"

    try:
        if args.browser:
            url = f"{base}/index.html"
            print(f"Verse at {url}\nCtrl+C to stop.")
            threading.Timer(0.8, lambda: webbrowser.open(url)).start()
            try:
                threading.Event().wait()
            except KeyboardInterrupt:
                pass
            return 0

        global webview
        try:
            import webview  # imported late so --browser works without it
        except ImportError:
            print(
                "pywebview is not installed for this Python.\n"
                "  python -m pip install -r requirements.txt\n"
                "or run: python app.py --browser",
                file=sys.stderr,
            )
            return 2

        # Fit the screen: a fixed 1500x950 opens partly off-screen on a laptop.
        # On a small display the four panels want every pixel, so fill the work
        # area; on a large one, a centred 1500x950 window is easier to work in.
        avail_w, avail_h = work_area()
        small = avail_w < 1600 or avail_h < 900
        width = min(1500, max(1024, avail_w - 60))
        height = min(950, max(680, avail_h - 60))

        api = Api(base)

        window = webview.create_window(
            APP_NAME,
            f"{base}/{page_url('index.html')}",
            width=width,
            height=height,
            maximized=small,
            min_size=(1024, 600),
            background_color="#0c0b0b",
            js_api=api,
        )
        api._main = window

        result = {"code": None, "loaded": False, "error": None}
        threading.Thread(target=watch_load, args=(window, result), daemon=True).start()
        if args.selftest:
            threading.Thread(target=run_selftest, args=(window, api, result), daemon=True).start()

        # A fixed profile folder keeps theme and preferences between launches;
        # private_mode would wipe them on exit.
        storage = os.path.join(os.environ.get("LOCALAPPDATA") or ROOT, APP_NAME, "WebView2")
        webview.start(storage_path=storage, private_mode=False)

        if args.selftest and result["code"] is not None:
            return result["code"]
        if api._mem is not None:
            api._mem.stop()

        if not result["loaded"]:
            print(f"Window did not load: {result['error']!r}", file=sys.stderr)
            message_box(
                "Verse could not open its window.\n\n"
                "Another copy may still be shutting down, or the browser profile "
                "is locked. Close any other Verse windows, wait a moment, and "
                "start again.",
            )
            return 3
        return 0
    finally:
        httpd.shutdown()
        httpd.server_close()


if __name__ == "__main__":
    sys.exit(main())
