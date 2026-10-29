"""NDI output.

Captures the projection window and publishes it as an NDI source, so vMix, OBS,
Studio Monitor, a hardware encoder or another machine on the network can pick
"Verse" up directly — no HDMI splitter and no full-screen capture card.

Why capture the window instead of re-rendering the slide here: the projection
window is the single source of truth. Whatever the operator sees on the wall is
exactly what leaves on the wire, including blackouts and live theme changes.

The capture path is Windows Graphics Capture (the same API OBS uses for window
capture), and frames are pushed synchronously so a slow receiver can never make
this process accumulate a backlog of images.
"""
from __future__ import annotations

import threading
import time


class NdiOutput:
    def __init__(self, on_state=None):
        self._on_state = on_state or (lambda *_: None)
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self.error: str | None = None
        self.source_name = ""
        self.frames = 0
        self.fps = 0.0
        self.width = 0
        self.height = 0
        self._capture = None

    # ── lifecycle ──────────────────────────────────────────────────────────

    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def start(self, hwnd: int | None, source_name: str = "Verse") -> dict:
        if self.running():
            return {"ok": True, "note": "already sending"}
        if hwnd is None:
            return {"ok": False, "error": "projection-window-missing"}

        try:
            import NDIlib  # noqa: F401
            from windows_capture import WindowsCapture  # noqa: F401
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "error": f"ndi-unavailable: {exc}"}

        self._stop.clear()
        self.error = None
        self.frames = 0
        self.source_name = source_name or "Verse"
        self._thread = threading.Thread(
            target=self._run, args=(hwnd, self.source_name), name="verse-ndi", daemon=True
        )
        self._thread.start()
        return {"ok": True, "source": self.source_name}

    def stop(self) -> dict:
        self._stop.set()
        capture = self._capture
        self._capture = None
        if capture is not None:
            try:
                capture.stop()
            except Exception:
                pass
        thread = self._thread
        self._thread = None
        if thread is not None:
            thread.join(timeout=3)
        self.fps = 0.0
        return {"ok": True}

    def report(self) -> dict:
        return {
            "running": self.running(),
            "source": self.source_name,
            "frames": self.frames,
            "fps": round(self.fps, 1),
            "width": self.width,
            "height": self.height,
            "error": self.error,
        }

    # ── worker ─────────────────────────────────────────────────────────────

    def _run(self, hwnd: int, source_name: str):
        import NDIlib as ndi
        from windows_capture import WindowsCapture

        ndi.initialize()
        settings = ndi.SendCreate()
        settings.ndi_name = source_name
        settings.groups = ""
        settings.clock_video = True
        settings.clock_audio = False

        sender = ndi.send_create(settings)
        if sender is None:
            self.error = "The NDI runtime refused to create a sender."
            self._on_state("error", self.error)
            return

        frame_out = ndi.VideoFrameV2()
        frame_out.FourCC = ndi.FOURCC_VIDEO_TYPE_BGRA
        frame_out.frame_format_type = ndi.FRAME_FORMAT_TYPE_PROGRESSIVE
        frame_out.frame_rate_N = 30000
        frame_out.frame_rate_D = 1001
        frame_out.timecode = ndi.SEND_TIMECODE_SYNTHESIZE

        capture = WindowsCapture(
            cursor_capture=False,
            draw_border=False,
            window_hwnd=int(hwnd),
            minimum_update_interval=33,  # ~30 fps ceiling
        )
        self._capture = capture

        @capture.event
        def on_frame_arrived(frame, capture_control):  # noqa: N802 - library API
            if self._stop.is_set():
                capture_control.stop()
                return
            try:
                buffer = frame.frame_buffer
                height, width = buffer.shape[0], buffer.shape[1]
                if not buffer.flags["C_CONTIGUOUS"]:
                    buffer = buffer.copy()

                self.width, self.height = width, height
                frame_out.data = buffer
                frame_out.xres = width
                frame_out.yres = height
                frame_out.line_stride_in_bytes = width * 4
                frame_out.picture_aspect_ratio = width / height if height else 16 / 9
                ndi.send_send_video_v2(sender, frame_out)
                self.frames += 1
            except Exception as exc:  # noqa: BLE001 - keep sending the next frame
                self.error = str(exc)

        @capture.event
        def on_closed():  # noqa: N802 - library API
            self._stop.set()

        self._on_state("sending", source_name)
        try:
            control = capture.start_free_threaded()
            started = time.time()
            last_count = 0
            while not self._stop.is_set():
                time.sleep(1.0)
                elapsed = time.time() - started
                if elapsed > 0:
                    self.fps = (self.frames - last_count) / 1.0
                    last_count = self.frames
            try:
                control.stop()
            except Exception:
                pass
        except Exception as exc:  # noqa: BLE001 - surfaced to the UI
            self.error = f"Window capture failed: {exc}"
        finally:
            self.fps = 0.0
            try:
                ndi.send_destroy(sender)
            except Exception:
                pass
            self._on_state("stopped", "")
