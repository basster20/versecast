"""Prove the local engines hear a spoken reference, without a microphone.

Windows' own speech synthesiser writes a sentence to a WAV file, and the real
listener is pointed at that file. Everything else is the shipping path: model
load, endpointing, callbacks the host pushes into the page, and the detector
that turns "romans chapter eight verse twenty eight" into Romans 8:28.

    python tools/check_speech.py                 # both local engines
    python tools/check_speech.py --engine whisper

The replay is paced at speaking speed because the Whisper listener endpoints on
real time; an un-paced burst would look like one long sentence with no pause.
Needs the chosen model (Settings -> Transcription -> Download) and the
PowerShell that ships with Windows. Exits 0 only when every requested engine
resolved the reference.
"""
import argparse
import json
import os
import subprocess
import sys
import tempfile
import threading
import time
import wave

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import numpy as np  # noqa: E402

import speech  # noqa: E402

SENTENCE = "Turn with me to Romans chapter eight verse twenty eight."
RATE = 16000
TRAILING_S = 1.0


def synthesise(path: str) -> bool:
    script = (
        "Add-Type -AssemblyName System.Speech\n"
        "$s = New-Object System.Speech.Synthesis.SpeechSynthesizer\n"
        f'$s.SetOutputToWaveFile("{path}")\n'
        "$s.Rate = -1\n"
        f'$s.Speak("{SENTENCE}")\n'
        "$s.Dispose()\n"
    )
    with tempfile.NamedTemporaryFile("w", suffix=".ps1", delete=False) as fh:
        fh.write(script)
        script_path = fh.name
    try:
        subprocess.run(
            ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", script_path],
            check=True, capture_output=True,
        )
    except Exception as exc:  # noqa: BLE001 - reported by the caller
        print("could not synthesise speech:", exc)
        return False
    finally:
        try:
            os.remove(script_path)
        except OSError:
            pass
    return os.path.exists(path)


def load_pcm(path: str) -> bytes:
    with wave.open(path) as w:
        rate = w.getframerate()
        pcm = np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16)
    if rate != RATE:
        n = int(len(pcm) * RATE / rate)
        pcm = np.interp(np.linspace(0, len(pcm) - 1, n), np.arange(len(pcm)), pcm).astype(np.int16)
    return pcm.tobytes()


class ReplayStream:
    """Stands in for sounddevice.RawInputStream and plays a byte string.

    Real time, not as fast as possible: the Whisper engine decides where a
    sentence ends by listening for half a second of quiet, so a burst would
    never look like a finished utterance.
    """

    def __init__(self, pcm: bytes, block: int, **_kwargs):
        self._pcm = pcm + b"\x00" * (int(RATE * TRAILING_S) * 2)
        self._pos = 0
        self._start = time.monotonic()

    def __enter__(self):
        return self

    def __exit__(self, *_exc):
        return False

    def read(self, frames):
        target = self._start + (self._pos + frames * 2) / (RATE * 2)
        delay = target - time.monotonic()
        if delay > 0:
            time.sleep(delay)
        chunk = self._pcm[self._pos:self._pos + frames * 2]
        self._pos += len(chunk)
        if len(chunk) < frames * 2:
            # Silence pads the tail so a recogniser flushes its last words.
            chunk = chunk + b"\x00" * (frames * 2 - len(chunk))
        return chunk, False


def detected(text: str) -> str:
    with open(os.path.join(ROOT, "assets", "js", "engine.js"), encoding="utf-8") as fh:
        assert fh  # the detector is shared with the page; run it under node
    result = subprocess.run(
        ["node", "-e",
         "const E=require('./assets/js/engine.js');"
         f"const hits=E.detect({json.dumps(text)});"
         "console.log(hits.map(h=>h.reference).join(','))"],
        cwd=ROOT, capture_output=True, text=True,
    )
    return (result.stdout or "").strip()


def run(listener_cls, label: str, pcm: bytes, expect: str) -> bool:
    if not speech.model_ready("vosk" if label == "vosk" else "whisper"):
        print(f"FAIL  {label} model missing — download it in Settings -> Transcription")
        return False

    finals = []
    partials = []
    errors = []
    lock = threading.Lock()

    def on_text(text, final):
        with lock:
            (finals if final else partials).append(text)

    def on_state(state, note):
        if state == "error":
            with lock:
                errors.append(note or "error")

    import sounddevice as sd

    original = sd.RawInputStream
    sd.RawInputStream = lambda **kw: ReplayStream(pcm, kw.get("blocksize", speech.BLOCK))
    try:
        listener = listener_cls(on_text=on_text, on_state=on_state)
        started = listener.start()
        if not started.get("ok"):
            print(f"FAIL  {label} engine did not start:", started)
            return False
        deadline = time.time() + 30
        while time.time() < deadline and not finals:
            time.sleep(0.2)
        listener.stop()
    finally:
        sd.RawInputStream = original

    with lock:
        heard = " ".join(finals).strip()
        unseen = " / ".join(p for p in partials[-3:] if p)
        problem = errors[-1] if errors else ""
    print(f"[{label}] heard:", heard or "(nothing)")
    if unseen and not heard:
        print(f"[{label}] partials:", unseen)
    if problem:
        print(f"[{label}] error:", problem)

    refs = detected(heard)
    print(f"[{label}] detected:", refs or "(none)")
    return expect in refs


def run_instant(pcm: bytes, expect: str) -> bool:
    """The two-pipeline path: the fast model answers while the sentence is spoken.

    tiny.en reads the same audio about a second in and pushes an interim
    transcript; base.en then replaces it at the pause. What is asserted here is
    that both actually ran, and that the accurate pass still resolved the
    reference — a fast pass that replaced the good answer with a worse one would
    be a regression, not a speed-up.
    """
    if not speech.model_ready("instant"):
        print("SKIP  Whisper tiny.en is not installed — the instant pipeline is off")
        return True

    interims: list = []
    finals: list = []
    errors: list = []
    lock = threading.Lock()

    def on_text(text, final):
        with lock:
            (finals if final else interims).append(text)

    def on_state(state, note):
        if state == "error":
            with lock:
                errors.append(note or "error")

    import sounddevice as sd

    original = sd.RawInputStream
    sd.RawInputStream = lambda **kw: ReplayStream(pcm, kw.get("blocksize", speech.BLOCK))
    listener = None
    try:
        listener = speech.WhisperListener(on_text=on_text, on_state=on_state, instant=True)
        started = listener.start()
        if not started.get("ok"):
            print("FAIL  the instant run did not start:", started)
            return False
        deadline = time.time() + 30
        while time.time() < deadline and not finals:
            time.sleep(0.2)
        active = bool(listener.instant_active)
        listener.stop()
    finally:
        sd.RawInputStream = original

    with lock:
        heard = " ".join(finals).strip()
        early = [text for text in interims if text.strip()]
        problem = errors[-1] if errors else ""

    refs = detected(heard)
    print("[instant] fast pass active:", active)
    print("[instant] interim transcripts:", len(early), "|", (early[0][:60] if early else "(none)"))
    print("[instant] accurate pass heard:", heard or "(nothing)")
    print("[instant] detected:", refs or "(none)")
    if problem:
        print("[instant] error:", problem)

    ok = True
    if not active:
        print("FAIL  the fast pass never started")
        ok = False
    if not early:
        print("FAIL  the fast pass produced no interim transcript")
        ok = False
    if expect not in refs:
        print("FAIL  the accurate pass did not resolve the reference")
        ok = False
    return ok


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--engine", choices=("whisper", "vosk", "both"), default="both")
    ap.add_argument("--wav", help="test this recording instead of synthesising one")
    ap.add_argument("--expect", default="Romans 8:28", help="reference the recording says")
    args = ap.parse_args()

    wav = os.path.join(tempfile.gettempdir(), "verse-check-speech.wav")
    synthesised = not args.wav
    if args.wav:
        wav = args.wav
        if not os.path.isfile(wav):
            print("FAIL  no such file:", wav)
            return 1
    elif not synthesise(wav):
        print("FAIL  could not synthesise the test sentence")
        return 1
    pcm = load_pcm(wav)
    try:
        results = {}
        if args.engine in ("whisper", "both"):
            results["whisper"] = run(speech.WhisperListener, "whisper", pcm, args.expect)
            results["instant"] = run_instant(pcm, args.expect)
        if args.engine in ("vosk", "both"):
            results["vosk"] = run(speech.LocalListener, "vosk", pcm, args.expect)
    finally:
        if synthesised:
            try:
                os.remove(wav)
            except OSError:
                pass

    passed = bool(results) and all(results.values())
    print("SPEECH", "PASS" if passed else "FAIL", results)
    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(main())
