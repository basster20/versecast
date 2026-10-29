"""Build Verse's own verse vectors, one Bible at a time.

    python tools/build_index.py --status
    python tools/build_index.py --translation yor
    python tools/build_index.py --all

Why build at all, when the app can borrow an existing English index? Two
reasons, both measured:

*Yoruba and Igbo cannot be borrowed.* EmbeddingGemma does not place Yoruba or
Igbo text near its English meaning (a Yoruba psalm lands at rank 7,298 against
an English index). A language needs vectors built from that language's own
words, so these are the translations worth building first.

*A borrowed index carries borrowed words.* Pewbeam's matrix was made from NKJV
and NLT, which are licensed; this build's are made from the public-domain and
CC BY-SA texts the app is allowed to ship.

Expect roughly an hour per English Bible and 75 minutes per Yoruba/Igbo one on
an eight-core CPU. The run is resumable: stop it whenever and start it again.
"""
import argparse
import json
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

import semantic  # noqa: E402


def human(seconds):
    if not seconds:
        return "?"
    seconds = int(seconds)
    if seconds < 90:
        return f"{seconds}s"
    return f"{seconds // 60}m{seconds % 60:02d}s"


def show_status():
    import canon

    print(f"model     : {semantic.resolve_model()[0] or 'not installed'}")
    print(f"vectors   : {semantic.index_root()}")
    available = sorted(canon.data_files())
    print(f"bibles    : {', '.join(available)}")
    for entry in sorted(os.listdir(semantic.index_root())) if os.path.isdir(semantic.index_root()) else []:
        progress = semantic.read_progress(entry)
        built = semantic.index_paths(entry)
        if built:
            print(f"  {entry:<5} built   {semantic._count_rows(built[0]):>6} verses")
        elif progress:
            done = progress.get("done") or 0
            total = progress.get("total") or 1
            print(f"  {entry:<5} partial {done:>6}/{total} ({done * 100 // max(total, 1)}%) — rerun to continue")
    if semantic.pewbeam_index():
        print("borrowed  : an English index is available from Pewbeam's install")


def main():
    ap = argparse.ArgumentParser(description="Build verse embeddings for offline detection")
    ap.add_argument("--translation", "-t", help="translation id, e.g. yor")
    ap.add_argument("--all", action="store_true", help="every Bible this build ships")
    ap.add_argument("--order", default="yor,ibo,kjv,web",
                    help="build order for --all (new capability first, then licence-clean)")
    ap.add_argument("--batch", type=int, default=semantic.BUILD_BATCH)
    ap.add_argument("--threads", type=int, default=semantic.BUILD_THREADS)
    ap.add_argument("--status", action="store_true", help="what is built, what is not")
    args = ap.parse_args()

    if args.status or (not args.translation and not args.all):
        show_status()
        return 0

    import canon

    if not semantic.model_ready():
        print("The embedding model is not installed. Run the app: Settings → Detection → Install.")
        return 2

    wanted = []
    if args.all:
        available = set(canon.data_files())
        wanted = [t for t in args.order.split(",") if t in available]
        wanted += sorted(available - set(wanted))
    else:
        wanted = [args.translation]

    for translation in wanted:
        if semantic.index_paths(translation):
            print(f"{translation}: already built, skipping")
            continue
        rows = len(semantic.canon_rows(translation))
        if not rows:
            print(f"{translation}: no verses found")
            continue
        print(f"{translation}: {rows} verses, ~{human(rows * 0.104)} at 4 threads", flush=True)
        last = [0.0]

        def report(fraction, note, extra=None):
            now = time.time()
            if note != "ready" and now - last[0] < 2.0:
                return
            last[0] = now
            extra = extra or {}
            eta = human(extra.get("eta_seconds"))
            print(f"  {fraction * 100:5.1f}%  {extra.get('done', '')}/{extra.get('total', rows)}"
                  f"  {extra.get('per_second', 0)}/s  eta {eta}", flush=True)

        result = semantic.build_index(translation, batch=args.batch, threads=args.threads, progress=report)
        print(json.dumps(result), flush=True)

    return 0


if __name__ == "__main__":
    sys.exit(main())
