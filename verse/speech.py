"""Speech to text for Verse.

Three engines, chosen in Settings:

  local/whisper  Whisper base.en (CTranslate2), fully offline. ~141 MB on disk,
                 loaded only while listening. Much better than Vosk on
                 West-African and other accented English, and it follows a
                 Bible-book prompt, so it writes "Romans chapter 8 verse 28".
  local/vosk     Vosk small en-US, also offline and only 40 MB. Lower memory,
                 faster to load, but trained on read US speech: it misses most
                 references in accented preaching.
  browser        The Web Speech API inside the app window. No download, almost
                 no memory, but it needs internet during the service.

Only the local engines live here — the browser one is a few lines of JavaScript
in app.js. All three hand their text to the same detector, so a detected
reference behaves identically whichever one heard it.
"""
from __future__ import annotations

import json
import os
import queue
import shutil
import sys
import threading
import time
import urllib.request
import zipfile

MODEL_NAME = "vosk-model-small-en-us-0.15"
MODEL_URL = f"https://alphacephei.com/vosk/models/{MODEL_NAME}.zip"

WHISPER_NAME = "faster-whisper-base.en"
WHISPER_REPO = "Systran/faster-whisper-base.en"
WHISPER_FILES = (
    "config.json",
    "model.bin",
    "tokenizer.json",
    "vocabulary.txt",
)
# Only used to draw a progress bar before the server sends Content-Length.
WHISPER_EXPECTED_MB = 145.0

# The instant pipeline. Pewbeam runs two recognisers over the same audio — a
# short-window one that answers fast and a longer-window one that is accurate —
# and tunes them separately (STT_INSTANT_CHUNK_MS / STT_QUALITY_CHUNK_MS).
# tiny.en is the small end of that pair here: on this machine it transcribes a
# two-second window in about a fifth of the time base.en needs, which is enough
# to put a reference on screen while the sentence is still being spoken. The
# accurate pass then replaces it.
INSTANT_NAME = "faster-whisper-tiny.en"
INSTANT_REPO = "Systran/faster-whisper-tiny.en"
INSTANT_EXPECTED_MB = 78.0
# How often the fast pass runs while somebody is still speaking, and the
# shortest window worth transcribing. Below about a second the model sees too
# little to be useful and spends the time anyway.
INSTANT_EVERY_S = 1.1
INSTANT_MIN_S = 1.0

# Whisper reads this before every window. Listing the books (and the shape of a
# reference) is what stops "Deuteronomy" becoming "due to enemy" on a strong
# accent: the decoder is biased towards these spellings without being forced
# into a grammar.
WHISPER_PROMPT = (
    "Sermon Bible reading. Books of the Bible: Genesis, Exodus, Leviticus, Numbers, "
    "Deuteronomy, Joshua, Judges, Ruth, First Samuel, Second Samuel, First Kings, "
    "Second Kings, First Chronicles, Second Chronicles, Ezra, Nehemiah, Esther, Job, "
    "Psalm, Proverbs, Ecclesiastes, Song of Solomon, Isaiah, Jeremiah, Lamentations, "
    "Ezekiel, Daniel, Hosea, Joel, Amos, Obadiah, Jonah, Micah, Nahum, Habakkuk, "
    "Zephaniah, Haggai, Zechariah, Malachi, Matthew, Mark, Luke, John, Acts, Romans, "
    "First Corinthians, Second Corinthians, Galatians, Ephesians, Philippians, "
    "Colossians, First Thessalonians, Second Thessalonians, First Timothy, "
    "Second Timothy, Titus, Philemon, Hebrews, James, First Peter, Second Peter, "
    "First John, Second John, Third John, Jude, Revelation. "
    "References are said like Romans chapter 8 verse 28, Psalm 23 verse 1."
)

SAMPLE_RATE = 16000
# 100 ms at 16 kHz. Smaller blocks reach Vosk (and so the page) sooner; below
# this the per-call overhead cancels the gain. tools/bench_latency.py measures
# the difference: 250 ms blocks put a reference on screen ~240 ms later.
BLOCK = 1600


def _app_dir() -> str:
    base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
    return os.path.join(base, "Verse")


def models_dir() -> str:
    return os.path.join(_app_dir(), "models")


def model_path() -> str:
    return os.path.join(models_dir(), MODEL_NAME)


def whisper_path() -> str:
    return os.path.join(models_dir(), WHISPER_NAME)


def instant_path() -> str:
    return os.path.join(models_dir(), INSTANT_NAME)


def _dir_mb(path: str) -> float:
    total = 0
    for root, _dirs, files in os.walk(path):
        for name in files:
            try:
                total += os.path.getsize(os.path.join(root, name))
            except OSError:
                pass
    return round(total / 1048576, 1)


def model_ready(engine: str = "whisper") -> bool:
    if engine == "vosk":
        path = model_path()
        try:
            return os.path.isdir(path) and any(os.scandir(path))
        except OSError:
            return False
    path = instant_path() if engine == "instant" else whisper_path()
    return all(os.path.isfile(os.path.join(path, name)) for name in WHISPER_FILES)


def model_size_mb(engine: str = "whisper") -> float:
    if engine == "vosk":
        return _dir_mb(model_path())
    return _dir_mb(instant_path() if engine == "instant" else whisper_path())


MODEL_NAMES = {
    "vosk": "Vosk small en-US",
    "whisper": "Whisper base.en",
    "instant": "Whisper tiny.en",
}
EXPECTED_MB = {"vosk": 40, "whisper": WHISPER_EXPECTED_MB, "instant": INSTANT_EXPECTED_MB}


def model_info(engine: str = "whisper") -> dict:
    engine = engine if engine in MODEL_NAMES else "whisper"
    ready = model_ready(engine)
    return {
        "engine": engine,
        "ready": ready,
        "mb": model_size_mb(engine) if ready else 0,
        "name": MODEL_NAMES[engine],
        "expected_mb": EXPECTED_MB[engine],
    }


def _remote_size(url: str, timeout: int = 20) -> int:
    try:
        req = urllib.request.Request(url, method="HEAD", headers={"User-Agent": "Verse/1.0"})
        with urllib.request.urlopen(req, timeout=timeout) as response:
            return int(response.headers.get("Content-Length") or 0)
    except Exception:
        return 0


def download_whisper(progress=None, cancelled=None) -> str:
    """The accurate local model (Whisper base.en)."""
    return _download_ct2(whisper_path(), WHISPER_REPO, WHISPER_EXPECTED_MB, progress, cancelled)


def download_instant(progress=None, cancelled=None) -> str:
    """The fast local model (Whisper tiny.en) for the instant pipeline."""
    return _download_ct2(instant_path(), INSTANT_REPO, INSTANT_EXPECTED_MB, progress, cancelled)


def _download_ct2(target_path: str, repo: str, expected_mb: float, progress=None, cancelled=None) -> str:
    """Fetch the CTranslate2 Whisper model files straight from Hugging Face.

    The four small files are what `faster_whisper.WhisperModel` needs; downloading
    them ourselves (rather than letting the library do it) gives the page a real
    percentage and keeps the model out of the shared Hugging Face cache.
    """
    if all(os.path.isfile(os.path.join(target_path, name)) for name in WHISPER_FILES):
        return target_path

    os.makedirs(target_path, exist_ok=True)
    base = f"https://huggingface.co/{repo}/resolve/main/"
    urls = {name: base + name for name in WHISPER_FILES}
    sizes = {name: _remote_size(url) for name, url in urls.items()}
    total = sum(sizes.values()) or int(expected_mb * 1048576)
    done = 0
    last_report = 0.0

    for name, url in urls.items():
        target = os.path.join(target_path, name)
        part = target + ".part"
        # A retry should not re-fetch the 74 MB model because a later small
        # file failed.
        if sizes.get(name) and os.path.isfile(target) and os.path.getsize(target) == sizes[name]:
            done += sizes[name]
            if progress:
                progress(min(0.99, done / max(total, 1)), "download")
            continue
        req = urllib.request.Request(url, headers={"User-Agent": "Verse/1.0"})
        with urllib.request.urlopen(req, timeout=60) as response, open(part, "wb") as fh:
            while True:
                if cancelled and cancelled():
                    raise RuntimeError("cancelled")
                chunk = response.read(256 * 1024)
                if not chunk:
                    break
                fh.write(chunk)
                done += len(chunk)
                if progress:
                    now = time.time()
                    if now - last_report > 0.3:
                        last_report = now
                        progress(min(0.99, done / max(total, 1)), "download")
        os.replace(part, target)

    # Remove a half-finished attempt from an earlier run.
    for entry in os.listdir(target_path):
        if entry.endswith(".part"):
            try:
                os.remove(os.path.join(target_path, entry))
            except OSError:
                pass

    if progress:
        progress(1.0, "ready")
    return target_path


def download_for(engine: str, progress=None, cancelled=None) -> str:
    """Download the model for the chosen local engine."""
    if engine == "vosk":
        return download_model(progress=progress, cancelled=cancelled)
    if engine == "instant":
        return download_instant(progress=progress, cancelled=cancelled)
    return download_whisper(progress=progress, cancelled=cancelled)


def download_model(progress=None, cancelled=None) -> str:
    """Fetch and unpack the Vosk model. Safe to call twice.

    progress: callable(fraction: float, note: str) — called sparingly.
    cancelled: callable() -> bool — abort between chunks.
    """
    if model_ready("vosk"):
        return model_path()

    os.makedirs(models_dir(), exist_ok=True)
    archive = os.path.join(models_dir(), MODEL_NAME + ".zip.part")
    target = os.path.join(models_dir(), MODEL_NAME + ".zip")

    req = urllib.request.Request(MODEL_URL, headers={"User-Agent": "Verse/1.0"})
    with urllib.request.urlopen(req, timeout=30) as response, open(archive, "wb") as fh:
        length = int(response.headers.get("Content-Length") or 0)
        done = 0
        last_report = 0.0
        while True:
            if cancelled and cancelled():
                raise RuntimeError("cancelled")
            chunk = response.read(256 * 1024)
            if not chunk:
                break
            fh.write(chunk)
            done += len(chunk)
            if progress and length:
                now = time.time()
                if now - last_report > 0.4:
                    last_report = now
                    progress(min(0.95, done / length), "download")

    os.replace(archive, target)

    if progress:
        progress(0.96, "unpack")
    staging = os.path.join(models_dir(), MODEL_NAME + ".staging")
    if os.path.isdir(staging):
        shutil.rmtree(staging, ignore_errors=True)
    with zipfile.ZipFile(target) as zf:
        zf.extractall(staging)

    unpacked = os.path.join(staging, MODEL_NAME)
    source = unpacked if os.path.isdir(unpacked) else staging
    if os.path.isdir(model_path()):
        shutil.rmtree(model_path(), ignore_errors=True)
    os.replace(source, model_path())
    shutil.rmtree(staging, ignore_errors=True)
    try:
        os.remove(target)
    except OSError:
        pass

    if progress:
        progress(1.0, "ready")
    return model_path()


# Names that mean "not the room microphone": virtual cameras, streaming
# cables and the Windows alias that just forwards to the default.
VIRTUAL_HINTS = (
    "iriiun", "webcam", "obs", "virtual", "vb-audio", "cable",
    "voicemeeter", "ndi", "midi", "sound mapper",
)


def device_name(index=None) -> str:
    try:
        import sounddevice as sd

        if index is None:
            return sd.query_devices(kind="input")["name"]
        return sd.query_devices()[index]["name"]
    except Exception:
        return ""


def preferred_device():
    """The input to use when nobody has chosen one.

    Windows happily makes a phone-as-webcam the default recording device, and
    then the local engine hears silence — so skip the obvious virtual ones and
    take the first real microphone. None means "whatever the OS picked".
    """
    for dev in input_devices():
        name = dev["name"].lower()
        if not any(hint in name for hint in VIRTUAL_HINTS):
            return dev["index"]
    return None


def input_devices() -> list[dict]:
    """Every device that can record, with the system default marked.

    A laptop often has several — the built-in array, a headset, and whatever
    virtual cable a streaming tool installed — so the operator needs to see and
    choose rather than trust the default.
    """
    try:
        import sounddevice as sd

        devices = sd.query_devices()
        default_in = sd.default.device[0]
    except Exception:
        return []

    out = []
    for index, dev in enumerate(devices):
        if dev.get("max_input_channels", 0) < 1:
            continue
        out.append({
            "index": index,
            "name": dev.get("name", f"Input {index}"),
            "default": index == default_in,
            "channels": dev.get("max_input_channels", 1),
        })
    return out


class LocalListener:
    """Streams the microphone through Vosk on a background thread.

    The model is loaded on start and dropped on stop: it is by far the largest
    allocation in the app and there is no reason to keep it resident while the
    pastor is not speaking.
    """

    def __init__(self, on_text, on_state=None, on_level=None, device=None):
        self._on_text = on_text
        self._on_state = on_state or (lambda *_: None)
        self._on_level = on_level or (lambda *_: None)
        self.device = device
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self.error: str | None = None
        self.engine_mb = 0.0
        self.active_device = device

    # ── lifecycle ──────────────────────────────────────────────────────────

    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def start(self) -> dict:
        if self.running():
            return {"ok": True, "note": "already listening"}
        if not model_ready("vosk"):
            return {"ok": False, "error": "model-missing"}

        self._stop.clear()
        self.error = None
        self._thread = threading.Thread(target=self._run, name="verse-stt", daemon=True)
        self._thread.start()
        return {"ok": True}

    def stop(self) -> dict:
        self._stop.set()
        thread = self._thread
        self._thread = None
        if thread is not None:
            thread.join(timeout=4)
        self.engine_mb = 0.0
        return {"ok": True}

    # ── worker ─────────────────────────────────────────────────────────────

    def _run(self):
        try:
            import sounddevice as sd
            import vosk

            vosk.SetLogLevel(-1)
            self._on_state("loading", "Loading speech model…")
            model = vosk.Model(model_path())
            recognizer = vosk.KaldiRecognizer(model, SAMPLE_RATE)
            recognizer.SetWords(False)
            self.engine_mb = round(_rss_mb(), 1)

            self.active_device = self.device
            if self.active_device is None:
                self.active_device = preferred_device()
            self._on_state("listening", "Listening")
            with sd.RawInputStream(
                samplerate=SAMPLE_RATE,
                blocksize=BLOCK,
                dtype="int16",
                channels=1,
                device=self.active_device,
            ) as stream:
                blocks = 0
                while not self._stop.is_set():
                    data, overflowed = stream.read(BLOCK)
                    if overflowed:
                        continue
                    pcm = bytes(data)
                    # A meter is the quickest way to tell "the model hears
                    # nothing" apart from "the microphone is silent".
                    blocks += 1
                    if blocks % 2 == 0:
                        self._on_level(_level(pcm))
                    if recognizer.AcceptWaveform(pcm):
                        text = (json.loads(recognizer.Result()).get("text") or "").strip()
                        if text:
                            self._on_text(text, True)
                    else:
                        partial = (json.loads(recognizer.PartialResult()).get("partial") or "").strip()
                        if partial:
                            self._on_text(partial, False)

            del recognizer
            del model
        except Exception as exc:  # noqa: BLE001 - surfaced to the UI
            self.error = _friendly_error(exc)
            self._on_state("error", self.error)
        finally:
            self._on_state("stopped", "")
            self.engine_mb = 0.0


class WhisperListener:
    """Microphone -> endpointed utterances -> Whisper.

    Whisper is not a streaming recogniser: it reads a completed window. The
    listener therefore watches the input level, keeps a short pre-roll, and
    transcribes as soon as the room has been quiet for half a second. That is
    where the accuracy comes from — it sees the whole reference, not a fragment
    — and on an eight-core machine the wait after the last word is about a
    second. Audio keeps flowing while the previous window is being transcribed,
    so nothing is dropped mid-sentence.

    With ``instant`` on, a second and much smaller model reads the same audio a
    second in, while the sentence is still being spoken. Its text is pushed to
    the page as an interim transcript, so a reference can appear on screen
    before the speaker draws breath, and the accurate pass replaces it a moment
    later. The fast pass stands down whenever the accurate one is busy, or the
    two would compete for the same cores and both would be late.
    """

    ENDPOINT_S = 0.5
    MAX_SEGMENT_S = 14.0
    MIN_SEGMENT_S = 0.5
    PRE_ROLL_BLOCKS = 3  # 300 ms at 100 ms per block

    def __init__(self, on_text, on_state=None, on_level=None, device=None, instant=False):
        self._on_text = on_text
        self._on_state = on_state or (lambda *_: None)
        self._on_level = on_level or (lambda *_: None)
        self.device = device
        # Only meaningful if its model is present; start() decides that, so a
        # machine that never downloaded tiny.en simply runs one pipeline.
        self.instant = bool(instant)
        self.instant_active = False
        self._instant_thread: threading.Thread | None = None
        self._instant_busy = threading.Event()
        self._live_parts: list = []
        self._live_lock = threading.Lock()
        self._live_at = 0.0
        self._thread: threading.Thread | None = None
        self._worker: threading.Thread | None = None
        self._stop = threading.Event()
        self._jobs: queue.Queue = queue.Queue()
        self.error: str | None = None
        self.engine_mb = 0.0
        self.active_device = device

    # ── lifecycle ──────────────────────────────────────────────────────────

    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def start(self) -> dict:
        if self.running():
            return {"ok": True, "note": "already listening"}
        if not model_ready("whisper"):
            return {"ok": False, "error": "model-missing"}

        self._stop.clear()
        self.error = None
        self._thread = threading.Thread(target=self._run, name="verse-whisper", daemon=True)
        self._thread.start()
        return {"ok": True}

    def stop(self) -> dict:
        self._stop.set()
        self._jobs.put(None)
        for thread, timeout in ((self._thread, 4), (self._worker, 10), (self._instant_thread, 8)):
            if thread is not None:
                thread.join(timeout=timeout)
        self._thread = None
        self._worker = None
        self._instant_thread = None
        self.instant_active = False
        with self._live_lock:
            self._live_parts = []
        self.engine_mb = 0.0
        return {"ok": True}

    # ── worker ─────────────────────────────────────────────────────────────

    def _run(self):
        model = None
        try:
            import numpy as np
            import sounddevice as sd
            from faster_whisper import WhisperModel

            from collections import deque

            self._on_state("loading", "Loading Whisper…")
            threads = max(2, min(6, (os.cpu_count() or 4) - 2))
            model = WhisperModel(
                whisper_path(),
                device="cpu",
                compute_type="int8",
                cpu_threads=threads,
                local_files_only=True,
            )
            self.engine_mb = round(_rss_mb(), 1)

            self._worker = threading.Thread(
                target=self._transcribe_loop, args=(model,), name="verse-whisper-work", daemon=True
            )
            self._worker.start()
            self._start_instant_pipeline()

            self.active_device = self.device
            if self.active_device is None:
                self.active_device = preferred_device()
            self._on_state("listening", "Listening")
            with sd.RawInputStream(
                samplerate=SAMPLE_RATE,
                blocksize=BLOCK,
                dtype="int16",
                channels=1,
                device=self.active_device,
            ) as stream:
                buffer = []
                pre = deque(maxlen=self.PRE_ROLL_BLOCKS)
                # Start low, not at the first block: if the pastor is already
                # speaking when Listen is pressed, that block is speech, and
                # using it as the noise floor would make the engine deaf for the
                # rest of the sentence.
                noise = 80.0
                spoke = False
                last_voice = 0.0
                blocks = 0

                while not self._stop.is_set():
                    data, overflowed = stream.read(BLOCK)
                    if overflowed:
                        continue
                    pcm = np.frombuffer(bytes(data), dtype=np.int16)
                    if pcm.size == 0:
                        continue

                    blocks += 1
                    if blocks % 2 == 0:
                        self._on_level(_level(bytes(data)))

                    rms = float(np.sqrt(np.mean(np.square(pcm.astype(np.float32)))))
                    if not spoke:
                        # Follow the room, not the sermon: updating while the
                        # pastor speaks would slowly deafen the detector.
                        noise = 0.95 * noise + 0.05 * min(rms, noise * 4.0)
                    voiced = rms > max(noise * 3.0, 170)
                    now = time.monotonic()

                    if voiced:
                        if not spoke:
                            buffer = list(pre)
                            pre.clear()
                            with self._live_lock:
                                self._live_parts = []
                        buffer.append(pcm)
                        spoke = True
                        last_voice = now
                    elif spoke:
                        buffer.append(pcm)
                    else:
                        pre.append(pcm)

                    # What the fast pass reads: the utterance as it grows. A
                    # copy of the block list costs nothing; concatenating it is
                    # the other thread's job, only when it needs to.
                    if spoke:
                        with self._live_lock:
                            self._live_parts.append(pcm)
                            self._live_at = now

                    if not spoke:
                        continue
                    length = sum(len(b) for b in buffer) / SAMPLE_RATE
                    if (now - last_voice < self.ENDPOINT_S) and length < self.MAX_SEGMENT_S:
                        continue

                    audio = np.concatenate(buffer).astype(np.float32) / 32768.0
                    buffer = []
                    spoke = False
                    with self._live_lock:
                        self._live_parts = []
                        self._live_at = 0.0
                    if len(audio) / SAMPLE_RATE >= self.MIN_SEGMENT_S:
                        self._jobs.put(audio)

        except Exception as exc:  # noqa: BLE001 - surfaced to the UI
            self.error = _friendly_error(exc)
            self._on_state("error", self.error)
        finally:
            self._jobs.put(None)
            for worker, timeout in ((self._worker, 12), (self._instant_thread, 10)):
                if worker is not None and worker is not threading.current_thread():
                    worker.join(timeout=timeout)
            self.instant_active = False
            del model
            self._on_state("stopped", "")
            self.engine_mb = 0.0

    # ── instant pipeline ───────────────────────────────────────────────────

    def _start_instant_pipeline(self):
        if not self.instant:
            return
        if not model_ready("instant"):
            # Not an error: the accurate pass alone is exactly what this app did
            # before, and the page says the fast model is not installed.
            print("instant pipeline off: Whisper tiny.en is not installed", file=sys.stderr)
            return
        try:
            from faster_whisper import WhisperModel

            instant = WhisperModel(
                instant_path(),
                device="cpu",
                compute_type="int8",
                cpu_threads=2,
                local_files_only=True,
            )
        except Exception as exc:  # noqa: BLE001 - the accurate pass still works
            print(f"instant pipeline unavailable: {exc}", file=sys.stderr)
            return
        self._instant_thread = threading.Thread(
            target=self._instant_loop, args=(instant,), name="verse-whisper-fast", daemon=True
        )
        self._instant_thread.start()
        self.instant_active = True
        self.engine_mb = round(_rss_mb(), 1)

    def _instant_loop(self, model):
        last = 0.0
        failures = 0
        while not self._stop.is_set():
            self._stop.wait(0.15)
            if self._stop.is_set():
                break
            if self._instant_busy.is_set():
                # The accurate pass has the cores; do not take them from it.
                continue
            now = time.monotonic()
            with self._live_lock:
                fresh = now - self._live_at < 0.8
                parts = list(self._live_parts) if fresh else []
            if not parts or now - last < INSTANT_EVERY_S:
                continue
            try:
                import numpy as np

                audio = np.concatenate(parts).astype(np.float32) / 32768.0
            except Exception:  # noqa: BLE001
                continue
            if len(audio) / SAMPLE_RATE < INSTANT_MIN_S:
                continue
            last = now
            try:
                segments, _info = model.transcribe(
                    audio,
                    language="en",
                    beam_size=1,
                    condition_on_previous_text=False,
                    initial_prompt=WHISPER_PROMPT,
                    vad_filter=False,
                    without_timestamps=True,
                )
                text = " ".join(segment.text.strip() for segment in segments).strip()
                # Interim, never final: the page treats it as a snapshot that a
                # later pass may extend or correct.
                if text and not self._stop.is_set():
                    self._on_text(text, False)
                failures = 0
            except Exception as exc:  # noqa: BLE001 - the fast pass is expendable
                # One bad window is not a reason to stop answering quickly; a
                # model that fails three times in a row is.
                failures += 1
                self.error = _friendly_error(exc)
                if failures >= 3:
                    self.instant_active = False
                    print(f"instant pipeline stopped after {failures} failures: {exc}", file=sys.stderr)
                    return

    def _transcribe_loop(self, model):
        while not self._stop.is_set():
            audio = self._jobs.get()
            if audio is None:
                break
            self._on_state("working", "Transcribing…")
            self._instant_busy.set()
            try:
                segments, _info = model.transcribe(
                    audio,
                    language="en",
                    beam_size=1,
                    condition_on_previous_text=False,
                    initial_prompt=WHISPER_PROMPT,
                    vad_filter=False,
                    without_timestamps=True,
                )
                text = " ".join(segment.text.strip() for segment in segments).strip()
                # A stop can land while the last window is still being decoded;
                # do not put a verse on screen after the operator stopped.
                if text and not self._stop.is_set():
                    self._on_text(text, True)
            except Exception as exc:  # noqa: BLE001
                self.error = _friendly_error(exc)
                self._on_state("error", self.error)
                break
            finally:
                self._instant_busy.clear()
                if not self._stop.is_set():
                    self._on_state("listening", "Listening")


def _level(pcm: bytes) -> float:
    """0..1 loudness of one block, shaped so speech is visible on a bar."""
    try:
        import numpy as np

        samples = np.frombuffer(pcm, dtype=np.int16).astype(np.float32)
        if samples.size == 0:
            return 0.0
        rms = float(np.sqrt(np.mean(np.square(samples))))
    except Exception:
        return 0.0
    return max(0.0, min(1.0, (rms / 6000.0) ** 0.6))


def _rss_mb() -> float:
    try:
        import psutil

        return psutil.Process(os.getpid()).memory_info().rss / 1048576
    except Exception:
        return 0.0


def _friendly_error(exc: Exception) -> str:
    text = str(exc) or exc.__class__.__name__
    lowered = text.lower()
    if "portaudio" in lowered or "no default" in lowered or "device" in lowered and "found" in lowered:
        return "No microphone found. Plug one in, or pick another engine in Settings → Transcription."
    if "model" in lowered:
        return "The speech model is missing or damaged. Download it again in Settings → Transcription."
    if "ctranslate2" in lowered or "whisper" in lowered or "onnxruntime" in lowered:
        return (
            "The Whisper engine could not start. Download its model again in "
            "Settings → Transcription, or switch Local model to Vosk."
        )
    return text
