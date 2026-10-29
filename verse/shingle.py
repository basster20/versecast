"""Verbatim phrase index — the cheap tier of the detection ladder.

Most references a preacher reads aloud arrive one of two ways: the reference is
spoken ("turn to Romans chapter eight"), or the verse itself is quoted word for
word ("the Lord is my shepherd, I shall not want"). The first is handled by the
direct detector in engine.js. This module handles the second, and it does so
with an exact match: five consecutive words, hashed, looked up.

That tier matters because it is *precise* where embeddings are fuzzy. A
semantic search over 31,078 verses will happily return Ephesians 4:22 for "put
off the old man" and 1 Samuel 2:31 alongside it; an exact five-word match has no
such ambiguity, costs microseconds instead of 30 ms, and needs no model loaded.

Design, and why:

*Five-word shingles.* Shorter than five and common phrases vote for hundreds of
verses; longer and a single misheard word breaks the match. Five is the point
where a match is almost always a real quotation.

*Hashed, not stored.* Only the 64-bit hash and the row it came from are kept —
about 12 MB for a whole Bible, against hundreds of MB for a Python dictionary
of strings. Counts are recovered by sorting, searching and bincounting, so a
query touches numpy instead of the interpreter.

*Cached beside the app.* Building takes a couple of seconds; the result is kept
in %LOCALAPPDATA%\\Verse\\semantic\\shingle and rebuilt only when the Bible file
itself changes.
"""
from __future__ import annotations

import json
import os
import re
import threading
import time

import canon as _canon

NGRAM = 5
# FNV-1a's 64-bit prime. Any odd constant works; this one is a known-good mixer
# for the shift-free multiply-and-add scheme below.
PRIME = 1099511628211
MIN_MATCHES = 3
MIN_COVERAGE = 0.30

TOKEN_RE = re.compile(r"[^\W_]+(?:['\u2019][^\W_]+)*", re.UNICODE)


# ── canons ───────────────────────────────────────────────────────────────────
# The Bibles themselves are read through canon.py, so this tier and the
# reranker agree on the exact words a verse contains.

translations = _canon.data_files
load_canon = _canon.load
_canon_path = _canon.path_for


# ── index ────────────────────────────────────────────────────────────────────

def _cache_dir() -> str:
    base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
    return os.path.join(base, "Verse", "semantic", "shingle")


class ShingleIndex:
    """Hashed five-word shingles for one Bible, held as sorted numpy arrays."""

    def __init__(self, translation: str, canon: dict, vectors: dict):
        import numpy as np

        self.translation = translation
        self.verses: list[tuple[str, int, int]] = []
        self.word_count = None
        words: list[list[int]] = []
        ids: dict[str, int] = {}

        for book in canon.get("books") or []:
            chapters = (canon.get("canon") or {}).get(book) or {}
            for chapter, verses in chapters.items():
                for verse, text in verses.items():
                    tokens = [t.lower() for t in TOKEN_RE.findall(text or "")]
                    if len(tokens) < NGRAM:
                        continue
                    row = len(self.verses)
                    self.verses.append((book, int(chapter), int(verse)))
                    encoded = []
                    for token in tokens:
                        value = ids.get(token)
                        if value is None:
                            value = len(ids) + 1
                            ids[token] = value
                        encoded.append(value)
                    words.append(encoded)

        hashes = []
        owners = []
        for row, encoded in enumerate(words):
            array = np.asarray(encoded, dtype=np.uint64)
            # Rolling hash of every 5-word window, computed in numpy: the
            # interpreter never sees an individual shingle.
            acc = np.zeros(len(array) - NGRAM + 1, dtype=np.uint64)
            for offset in range(NGRAM):
                acc = acc * np.uint64(PRIME) + array[offset : offset + acc.size]
            hashes.append(acc)
            owners.append(np.full(acc.size, row, dtype=np.int32))

        self.hashes = np.concatenate(hashes) if hashes else np.zeros(0, dtype=np.uint64)
        self.owners = np.concatenate(owners) if owners else np.zeros(0, dtype=np.int32)
        order = np.argsort(self.hashes, kind="stable")
        self.hashes = self.hashes[order]
        self.owners = self.owners[order]
        self.vectors = vectors
        # A query is hashed with the same vocabulary, so the words themselves
        # have to survive the trip to disk: without them a cached index would
        # hash every token to the same value and never match anything.
        self.ids = ids
        self.vocab = [""] * len(ids)
        for word, value in ids.items():
            self.vocab[value - 1] = word

    # ── search ─────────────────────────────────────────────────────────────

    def shingles(self, text: str):
        """Hashes for every 5-word window of an utterance."""
        import numpy as np

        tokens = [t.lower() for t in TOKEN_RE.findall(text or "")]
        if len(tokens) < NGRAM:
            return np.zeros(0, dtype=np.uint64)
        # Unknown words still need a value: they can never match a verse, and
        # keeping them in the stream preserves the window positions either way.
        encoded = np.asarray([self.ids.get(t, 0) for t in tokens], dtype=np.uint64)
        acc = np.zeros(len(encoded) - NGRAM + 1, dtype=np.uint64)
        for offset in range(NGRAM):
            acc = acc * np.uint64(PRIME) + encoded[offset : offset + acc.size]
        return acc

    def search(self, text: str, limit: int = 5) -> list[dict]:
        import numpy as np

        query = self.shingles(text)
        if query.size == 0:
            return []
        unique = np.unique(query)

        # Every (shingle, verse) pair the query touches: one searchsorted per
        # side of the range, then a bincount to tally votes per verse.
        left = np.searchsorted(self.hashes, unique, side="left")
        right = np.searchsorted(self.hashes, unique, side="right")
        spans = right - left
        keep = spans > 0
        if not keep.any():
            return []
        left, spans = left[keep], spans[keep]
        total = int(spans.sum())
        offsets = np.repeat(left, spans)
        owners = self.owners[offsets]

        matches = np.bincount(owners, minlength=len(self.verses))
        best = np.nonzero(matches)[0]
        if best.size == 0:
            return []

        query_windows = int(unique.size)
        rows = []
        for row in best:
            matched = int(matches[row])
            if matched < MIN_MATCHES:
                continue
            # Coverage against the utterance: enough of what was said must be
            # in this verse. A long verse that matches three shingles of forty
            # is a coincidence; a short one matching three of three is a quote.
            coverage = matched / max(1, query_windows)
            rows.append({
                "book": self.verses[row][0],
                "chapter": self.verses[row][1],
                "verse": self.verses[row][2],
                "id": "%s.%d.%d" % self.verses[row],
                "score": round(coverage, 4),
                "matched": matched,
                "coverage": round(coverage, 4),
                "index": f"{self.translation} (shingle)",
            })

        rows = [r for r in rows if r["coverage"] >= MIN_COVERAGE] or rows
        rows.sort(key=lambda r: (-r["matched"], -r["coverage"]))
        return rows[:limit]

    def save(self, path: str, stamp: dict):
        import numpy as np

        os.makedirs(os.path.dirname(path), exist_ok=True)
        np.savez_compressed(
            path,
            hashes=self.hashes,
            owners=self.owners,
            vocab=np.asarray(self.vocab),
            verses=np.asarray([f"{b}.{c}.{v}" for b, c, v in self.verses]),
            stamp=np.asarray([json.dumps(stamp)]),
        )

    @classmethod
    def load(cls, path: str, translation: str):
        import numpy as np

        with np.load(path, allow_pickle=False) as data:
            self = cls.__new__(cls)
            self.translation = translation
            self.hashes = data["hashes"]
            self.owners = data["owners"]
            vocab = [str(w) for w in data["vocab"]]
            rows = [str(v) for v in data["verses"]]
            parsed = []
            for row in rows:
                book, chapter, verse = row.rsplit(".", 2)
                parsed.append((book, int(chapter), int(verse)))
            self.verses = parsed
            self.vectors = {"rows": len(parsed), "shingles": int(self.hashes.size)}
            self.ids = {word: index + 1 for index, word in enumerate(vocab)}
            self.vocab = vocab
            return self

    def report(self) -> dict:
        return {
            "translation": self.translation,
            "verses": len(self.verses),
            "shingles": int(self.hashes.size),
            "mb": round((self.hashes.nbytes + self.owners.nbytes) / 1048576, 1),
        }


# ── the stack ────────────────────────────────────────────────────────────────

class Shingles:
    """Lazily built, cached per translation."""

    def __init__(self):
        self._lock = threading.Lock()
        self._index: ShingleIndex | None = None
        self._translation: str | None = None
        self.build_seconds = 0.0
        self.queries = 0
        self.last_ms = 0.0

    def _cache_path(self, translation: str) -> str:
        return os.path.join(_cache_dir(), f"{translation}.npz")

    def _stamp(self, translation: str) -> dict:
        path = _canon_path(translation)
        try:
            info = os.stat(path)
            return {"file": os.path.basename(path), "size": info.st_size, "mtime": int(info.st_mtime),
                    "ngram": NGRAM}
        except OSError:
            return {}

    def index_for(self, translation: str) -> ShingleIndex:
        if self._index is not None and self._translation == translation:
            return self._index

        cache = self._cache_path(translation)
        stamp = self._stamp(translation)
        if os.path.isfile(cache):
            try:
                import numpy as np

                with np.load(cache, allow_pickle=False) as data:
                    cached = json.loads(str(data["stamp"][0]))
                if cached == stamp:
                    self._index = ShingleIndex.load(cache, translation)
                    self._translation = translation
                    return self._index
            except Exception:  # noqa: BLE001 - a bad cache must never stop the app
                pass

        canon = load_canon(translation)
        if not canon:
            raise LookupError(f"no canon for {translation}")
        started = time.time()
        index = ShingleIndex(translation, canon, stamp)
        self.build_seconds = round(time.time() - started, 2)
        self._index = index
        self._translation = translation
        try:
            index.save(cache, stamp)
        except OSError:
            pass
        return index

    def search(self, text: str, translation: str = "kjv", limit: int = 5) -> dict:
        with self._lock:
            started = time.time()
            try:
                index = self.index_for(translation)
                hits = index.search(text, limit)
            except LookupError as exc:
                return {"ok": False, "reason": str(exc), "candidates": []}
            except Exception as exc:  # noqa: BLE001 - reported, never fatal
                return {"ok": False, "reason": f"{exc.__class__.__name__}: {exc}", "candidates": []}
            self.queries += 1
            self.last_ms = round((time.time() - started) * 1000, 2)
            return {
                "ok": True,
                "reason": "hit" if hits else "miss",
                "index": index.report(),
                "ms": self.last_ms,
                "candidates": hits,
            }

    def unload(self) -> dict:
        with self._lock:
            had = self._index is not None
            self._index = None
            self._translation = None
            return {"ok": True, "freed": had}

    def report(self) -> dict:
        available = sorted(translations())
        cached = []
        try:
            for name in sorted(os.listdir(_cache_dir())):
                if name.endswith(".npz"):
                    path = os.path.join(_cache_dir(), name)
                    cached.append({
                        "translation": name[:-4],
                        "mb": round(os.path.getsize(path) / 1048576, 1),
                    })
        except OSError:
            pass
        return {
            "loaded": self._translation,
            "available": available,
            "cached": cached,
            "build_seconds": self.build_seconds,
            "queries": self.queries,
            "last_ms": self.last_ms,
        }


SHINGLES = Shingles()
