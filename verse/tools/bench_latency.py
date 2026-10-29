"""Measure how long the local engine takes from sound to a detected reference.

The microphone is replaced by a paced replay of a synthesised sentence, so the
clock behaves like a live service: a block is only handed to the recogniser when
that much real audio would have been captured. Every callback is timestamped, so
the report separates the two delays that make up the felt lag:

  speech -> partial   how soon the words appear (the recogniser's speed)
  speech -> final     how long Vosk waits for silence before committing

    python tools/bench_latency.py

The detector is timed separately, because a regex that costs 1 ms cannot be the
reason a slide appears late.
"""
import argparse
import json
import os
import subprocess
import sys
import tempfile
import threading
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import numpy as np  # noqa: E402

import speech  # noqa: E402
from check_speech import RATE, SENTENCE, load_pcm, synthesise  # noqa: E402

REFERENCE = "romans chapter eight verse twenty eight"
TRAILING_S = 1.0


class PacedStream:
    """A microphone that plays a recording at exactly the speed it was spoken."""

    def __init__(self, pcm: bytes, block: int, **_kwargs):
        self._pcm = pcm + b"\x00" * (int(RATE * TRAILING_S) * 2)
        self._block = block
        self._pos = 0
        self.started = time.monotonic()
        self.delivered = 0  # seconds of audio handed over so far

    def __enter__(self):
        return self

    def __exit__(self, *_exc):
        return False

    def read(self, frames):
        # Wait until this block would have finished arriving.
        target = self.started + (self._pos + frames * 2) / (RATE * 2)
        delay = target - time.monotonic()
        if delay > 0:
            time.sleep(delay)
        chunk = self._pcm[self._pos:self._pos + frames * 2]
        self._pos += len(chunk)
        self.delivered = self._pos / (RATE * 2)
        if len(chunk) < frames * 2:
            chunk = chunk + b"\x00" * (frames * 2 - len(chunk))
        return chunk, False


def detect_many(texts):
    """Run the shipping detector over several strings in one node process."""
    script = (
        "const E=require('./assets/js/engine.js');"
        "const ts=JSON.parse(process.argv[1]);"
        "console.log(JSON.stringify(ts.map(t=>E.detect(t,{partial:true}))));"
    )
    result = subprocess.run(
        ["node", "-e", script, json.dumps(texts)], cwd=ROOT, capture_output=True, text=True
    )
    if result.returncode != 0:
        return [[] for _ in texts]
    try:
        return json.loads(result.stdout)
    except Exception:
        return [[] for _ in texts]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--block", type=int, default=speech.BLOCK,
                    help="frames per read (default: the shipping value)")
    ap.add_argument("--engine", choices=("whisper", "vosk"), default="whisper",
                    help="local recogniser to measure")
    args = ap.parse_args()
    speech.BLOCK = args.block

    if not speech.model_ready(args.engine):
        print(f"FAIL  {args.engine} model missing — download it in Settings → Transcription")
        return 1

    wav = os.path.join(tempfile.gettempdir(), "verse-bench.wav")
    if not synthesise(wav):
        print("FAIL  could not synthesise the test sentence")
        return 1

    pcm = load_pcm(wav)
    speech_s = len(pcm) / (RATE * 2)

    events = []
    lock = threading.Lock()
    started = {}
    stream_ref = {"s": None}
    listening_at = {"t": None}

    def on_text(text, final):
        with lock:
            events.append((time.monotonic(), bool(final), text))

    def on_state(state, _note):
        if state == "listening":
            listening_at["t"] = time.monotonic()

    import sounddevice as sd

    original = sd.RawInputStream

    def factory(**kw):
        stream = PacedStream(pcm, kw.get("blocksize", args.block))
        stream_ref["s"] = stream
        return stream

    sd.RawInputStream = factory
    try:
        cls = speech.WhisperListener if args.engine == "whisper" else speech.LocalListener
        listener = cls(on_text=on_text, on_state=on_state)
        t0 = time.monotonic()
        listener.start()
        deadline = time.time() + 30
        while time.time() < deadline:
            with lock:
                if any(final for _, final, _ in events):
                    break
            time.sleep(0.05)
        listener.stop()
    finally:
        sd.RawInputStream = original
        try:
            os.remove(wav)
        except OSError:
            pass

    stream = stream_ref["s"]
    if stream is None or not events:
        print("FAIL  nothing was heard")
        return 1

    load_s = (listening_at["t"] or t0) - t0
    speech_end = stream.started + speech_s
    with lock:
        first_partial = next(
            (t for t, final, text in events if not final and REFERENCE in text.lower()), None
        )
        first_any_partial = next((t for t, final, _ in events if not final), None)
        final_at = next((t for t, final, text in events if final and "romans" in text.lower()), None)
        heard = " ".join(text for _, final, text in events if final)

    print(f"engine            {args.engine}")
    print(f"block             {args.block} frames ({args.block / RATE * 1000:.0f} ms)")
    print(f"sentence          {SENTENCE}")
    print(f"audio             {speech_s:.2f}s + {TRAILING_S:.1f}s trailing silence")
    print(f"model load        {load_s * 1000:.0f} ms")
    if first_any_partial:
        print(f"first partial     {first_any_partial - stream.started:+.2f}s (from speech start)")
    if first_partial:
        print(f"full ref partial  {first_partial - speech_end:+.2f}s relative to last word")
    if final_at:
        print(f"final result      {final_at - speech_end:+.2f}s relative to last word")
    if first_partial and final_at:
        print(f"partial advantage {(final_at - first_partial) * 1000:.0f} ms earlier")
    print(f"heard             {heard or '(nothing)'}")

    # What the page would act on: a partial whose reference is complete. This is
    # the number that matters, because an unfinished "verse twenty" is held back
    # until the next block can tell whether it is 20 or 28.
    partial_texts = [text for _, final, text in events if not final]
    hit_list = detect_many(partial_texts)
    hits_for = dict(zip(partial_texts, hit_list))

    with lock:
        usable = [
            t for t, final, text in events
            if not final and any(
                not h.get("open") and h.get("verseStart") is not None
                for h in hits_for.get(text, [])
            )
        ]
        timeline = [(t, text) for t, final, text in events if not final]

    if usable:
        print(f"usable partial    {usable[0] - speech_end:+.2f}s relative to last word")
        if final_at:
            print(f"acted-on gain     {(final_at - usable[0]) * 1000:.0f} ms earlier than the final")

    print("partial timeline:")
    last = None
    for t, text in timeline:
        if text == last:
            continue
        last = text
        marks = ", ".join(
            ("*" if h.get("open") else "") + h["reference"]
            for h in hits_for.get(text, [])
        )
        print(f"  {t - stream.started:5.2f}s  {text[:64]:<64} {marks}")

    sampled = subprocess.run(
        ["node", "-e",
         "const E=require('./assets/js/engine.js');"
         "const t=process.hrtime.bigint();"
         "for(let i=0;i<1000;i++)E.detect(" + json.dumps(heard or SENTENCE) + ");"
         "const ms=Number(process.hrtime.bigint()-t)/1e6/1000;"
         "console.log(ms.toFixed(3))"],
        cwd=ROOT, capture_output=True, text=True,
    )
    if sampled.returncode == 0:
        print(f"detector          {sampled.stdout.strip()} ms per sentence")

    ok = bool(final_at) and "romans" in heard.lower()
    print("BENCH", "PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
