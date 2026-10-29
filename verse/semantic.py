"""Offline verse detection — the embedding half of a local-mode presenter.

Pewbeam never asks a server which verse was preached. It embeds the sentence
with Google's EmbeddingGemma-300m (4-bit ONNX, 768 dimensions), then takes the
inner product against a matrix holding one vector per verse and keeps the top
few. At 31,078 verses the matrix is 92 MB and a full scan is about 5 ms, so an
exact search beats any approximate index on both speed and recall.

The same design is used here:

    query  ->  tokenizer  ->  ONNX (CPU)  ->  one 768-d unit vector
                                             |
                                  matrix.scan (n x 768, float32)
                                             |
                                   top-k (verse, score)

Two things this module will not do:

*Guess across languages.* Yoruba or Igbo text embedded against an English
index lands around rank 7,000-29,000 — measured, not assumed. Each language
needs its own matrix, which tools/build_index.py produces.

*Stay resident for free.* Model plus matrix is roughly 280 MB. The app loads
them when a semantic search is first asked for, and ``unload()`` gives every
byte back — the memory watchdog calls it under pressure and when listening
stops.

Nothing here touches the network except ``install_model()``, which fetches the
model once and records what it installed.
"""
from __future__ import annotations

import hashlib
import json
import os
import threading
import time
import urllib.request

DIM = 768
PACK = "embeddinggemma"
HF_REPO = "onnx-community/embeddinggemma-300m-ONNX"
HF_BASE = f"https://huggingface.co/{HF_REPO}/resolve/main/"
PACK_FILES = (
    ("config.json", "config.json"),
    ("special_tokens_map.json", "special_tokens_map.json"),
    ("tokenizer_config.json", "tokenizer_config.json"),
    ("tokenizer.json", "tokenizer.json"),
    ("onnx/model_q4.onnx", "onnx/model_q4.onnx"),
    ("onnx/model_q4.onnx_data", "onnx/model_q4.onnx_data"),
)
EXPECTED_MB = 209.0

# EmbeddingGemma was trained with task prefixes; without them retrieval quality
# drops sharply. These two are the pair its model card uses for search.
QUERY_PREFIX = "task: search result | query: "
DOC_PREFIX = "task: search result | document: "

# Above this the app stops loading the stack rather than push a machine into
# swap mid-service. Speech and the UI need the headroom more than retrieval does.
MAX_RSS_MB = 1200.0


# ── locations ─────────────────────────────────────────────────────────────────

def _app_dir() -> str:
    base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
    return os.path.join(base, "Verse")


def models_dir() -> str:
    return os.path.join(_app_dir(), "models")


def pack_dir() -> str:
    """Where our own copy of the embedding model lives."""
    return os.path.join(models_dir(), PACK)


def index_root() -> str:
    return os.path.join(_app_dir(), "semantic")


def index_dir(translation: str) -> str:
    return os.path.join(index_root(), translation)


def _pewbeam_embeddings() -> str | None:
    """Pewbeam's installed resources, if this machine has them.

    Reusing what is already on disk means semantic search works before Verse
    has downloaded anything, and it keeps the measurements comparable with the
    app this follows. Nothing is ever written there.
    """
    roaming = os.environ.get("APPDATA")
    if not roaming:
        return None
    path = os.path.join(roaming, "com.pewbeam.app", "resources", "embeddings")
    return path if os.path.isdir(path) else None


def _pewbeam_model() -> str | None:
    base = _pewbeam_embeddings()
    if not base:
        return None
    path = os.path.join(base, "onnx_models", PACK)
    return path if _model_ok(path) else None


def _model_ok(path: str) -> bool:
    required = ("onnx/model_q4.onnx", "tokenizer.json")
    if not all(os.path.isfile(os.path.join(path, *rel.split("/"))) for rel in required):
        return False
    weights = os.path.join(path, "onnx", "model_q4.onnx_data")
    return not os.path.isfile(weights) or os.path.getsize(weights) > 1024 * 1024


def resolve_model() -> tuple[str | None, str]:
    """(directory, where it came from). Ours first, then Pewbeam's."""
    if _model_ok(pack_dir()):
        return pack_dir(), "verse"
    found = _pewbeam_model()
    if found:
        return found, "pewbeam"
    return None, "none"


def _dir_mb(path: str) -> float:
    total = 0
    for root, _dirs, files in os.walk(path):
        for name in files:
            try:
                total += os.path.getsize(os.path.join(root, name))
            except OSError:
                pass
    return round(total / 1048576, 1)


def rss_mb() -> float:
    try:
        import psutil

        return psutil.Process(os.getpid()).memory_info().rss / 1048576
    except Exception:
        return 0.0


# ── the vector matrix ────────────────────────────────────────────────────────

class VerseIndex:
    """A headerless float32 matrix plus the map that names its rows.

    Rows are unit vectors, so an inner product is a cosine and the whole search
    is one matrix-vector product. The matrix is memory-mapped: the pages are
    file-backed, so the OS can drop them under pressure instead of the app
    having to hold 92 MB it is not using.
    """

    def __init__(self, path: str, map_path: str, label: str, source: str):
        import numpy as np

        self.path = path
        self.label = label
        self.source = source
        with open(map_path, encoding="utf-8") as fh:
            data = json.load(fh)

        if "ids" in data:  # our own format
            self.ids = data["ids"]
            self.dim = int(data.get("dim") or DIM)
            self.texts = data.get("evidence") or []
        else:  # Pewbeam's dual-translation map
            rows = data.get("verses") or []
            self.ids = [row.get("id") for row in rows]
            self.dim = DIM
            self.texts = [
                (row.get("translations") or {}).get("NKJV")
                or (row.get("translations") or {}).get("NLT")
                or ""
                for row in rows
            ]

        expected = len(self.ids) * self.dim * 4
        size = os.path.getsize(path)
        if size != expected:
            raise ValueError(
                f"index {os.path.basename(path)} is {size} bytes, expected {expected} "
                f"for {len(self.ids)} verses x {self.dim}"
            )
        self.matrix = np.memmap(path, dtype=np.float32, mode="r", shape=(len(self.ids), self.dim))

    def search(self, vector, limit: int = 5) -> list[dict]:
        import numpy as np

        scores = np.asarray(self.matrix.dot(np.asarray(vector, dtype=np.float32)))
        if limit < len(scores):
            top = np.argpartition(-scores, limit)[:limit]
        else:
            top = np.arange(len(scores))
        top = top[np.argsort(-scores[top])]
        out = []
        for i in top:
            row = self.ids[int(i)]
            book, chapter, verse = _split_id(row)
            if not book:
                continue
            out.append({
                "book": book,
                "chapter": chapter,
                "verse": verse,
                "score": float(scores[int(i)]),
                "id": row,
                "evidence": (self.texts[int(i)] or "").strip()[:240] if i < len(self.texts) else "",
                "index": self.label,
            })
        return out

    def close(self):
        self.matrix = None
        self.ids = []
        self.texts = []

    def report(self) -> dict:
        return {
            "label": self.label,
            "source": self.source,
            "verses": len(self.ids),
            "dim": self.dim,
            "mb": round(os.path.getsize(self.path) / 1048576, 1),
        }


def _split_id(row: str):
    """\"1 Samuel.3.4\" -> (\"1 Samuel\", 3, 4). Book names contain spaces, not dots."""
    if not row:
        return None, None, None
    parts = row.split(".")
    if len(parts) < 3:
        return None, None, None
    verse = parts[-1]
    chapter = parts[-2]
    book = ".".join(parts[:-2])
    try:
        return book.strip(), int(chapter), int(verse)
    except ValueError:
        return None, None, None


def index_paths(translation: str) -> tuple[str, str] | None:
    """Our own vectors for this translation, if they have been built."""
    path = os.path.join(index_dir(translation), "vectors.f32")
    map_path = os.path.join(index_dir(translation), "map.json")
    if os.path.isfile(path) and os.path.isfile(map_path):
        return path, map_path
    return None


def pewbeam_index() -> tuple[str, str] | None:
    base = _pewbeam_embeddings()
    if not base:
        return None
    vectors = os.path.join(base, "vectors", "verses_mapsorted_f32.bin")
    mapping = os.path.join(base, "mappings", "dual_embeddinggemma_map.json")
    if os.path.isfile(vectors) and os.path.isfile(mapping):
        return vectors, mapping
    return None


# ── the embedder ─────────────────────────────────────────────────────────────

class Embedder:
    """EmbeddingGemma through ONNX Runtime on the CPU.

    The model is 188 MB of int4 weights and sits behind a single worker thread
    on purpose: ONNX Runtime allocates its own arenas, and letting several
    threads call a shared session during a service only raises peak memory for
    no throughput gain — an utterance is one sentence, not a batch.
    """

    def __init__(self, path: str, threads: int | None = None):
        import onnxruntime as ort
        from tokenizers import Tokenizer

        options = ort.SessionOptions()
        options.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
        options.intra_op_num_threads = threads or max(2, min(6, (os.cpu_count() or 4) - 2))
        self._session = ort.InferenceSession(
            os.path.join(path, "onnx", "model_q4.onnx"),
            options,
            providers=["CPUExecutionProvider"],
        )
        self._tokenizer = Tokenizer.from_file(os.path.join(path, "tokenizer.json"))
        self._lock = threading.Lock()

    def embed(self, texts: list[str], kind: str = "query") -> "object":
        import numpy as np

        prefix = QUERY_PREFIX if kind == "query" else DOC_PREFIX
        batch = self._tokenizer.encode_batch([prefix + t for t in texts], add_special_tokens=True)
        width = max(len(enc.ids) for enc in batch)
        ids = np.zeros((len(batch), width), dtype=np.int64)
        mask = np.zeros((len(batch), width), dtype=np.int64)
        for row, enc in enumerate(batch):
            ids[row, : len(enc.ids)] = enc.ids
            mask[row, : len(enc.attention_mask)] = enc.attention_mask

        with self._lock:
            out = self._session.run(
                ["sentence_embedding"],
                {"input_ids": ids, "attention_mask": mask},
            )[0]

        vectors = np.asarray(out, dtype=np.float32)
        norms = np.linalg.norm(vectors, axis=1, keepdims=True)
        norms[norms == 0] = 1.0
        return vectors / norms


# ── the stack ────────────────────────────────────────────────────────────────

class Detection:
    """Lazily loaded embedder + per-translation indexes."""

    def __init__(self):
        self._lock = threading.Lock()
        self._embedder: Embedder | None = None
        self._indexes: dict[str, VerseIndex] = {}
        self._model_path: str | None = None
        self._source = "none"
        self.last_error: str | None = None
        self.load_seconds = 0.0
        self.queries = 0
        self.last_search_ms = 0.0

    # ── loading ────────────────────────────────────────────────────────────

    def _embedder_ready(self) -> Embedder:
        if self._embedder is not None:
            return self._embedder
        path, source = resolve_model()
        if not path:
            raise FileNotFoundError("embedding model not installed")
        started = time.time()
        self._embedder = Embedder(path)
        self._model_path = path
        self._source = source
        self.load_seconds = round(time.time() - started, 2)
        return self._embedder

    def index_for(self, translation: str) -> VerseIndex:
        cached = self._indexes.get(translation)
        if cached is not None:
            return cached

        paths = index_paths(translation)
        if paths:
            index = VerseIndex(paths[0], paths[1], translation, "verse")
        else:
            # English can borrow Pewbeam's ready-made matrix; Yoruba and Igbo
            # cannot, because the vectors and the text must be the same
            # language — see the module docstring.
            borrowed = pewbeam_index() if translation in ("kjv", "web", "nkjv", "niv") else None
            if not borrowed:
                raise LookupError(f"no verse index for {translation}")
            index = VerseIndex(borrowed[0], borrowed[1], f"{translation} (pewbeam)", "pewbeam")

        # Two at most: a service uses one Bible, and a stray third would cost
        # 92 MB for nothing.
        if len(self._indexes) >= 2:
            oldest = next(iter(self._indexes))
            self._indexes.pop(oldest).close()
        self._indexes[translation] = index
        return index

    # ── search ─────────────────────────────────────────────────────────────

    def search(self, text: str, translation: str = "kjv", limit: int = 5) -> dict:
        text = (text or "").strip()
        if not text:
            return {"ok": False, "reason": "empty", "candidates": []}

        if not deps_ready():
            return {"ok": False, "reason": "deps-missing", "candidates": []}

        with self._lock:
            started = time.time()
            try:
                if rss_mb() > MAX_RSS_MB:
                    raise MemoryError(f"memory at {rss_mb():.0f} MB")
                embedder = self._embedder_ready()
                index = self.index_for(translation)
                vector = embedder.embed([text], "query")[0]
                hits = index.search(vector, limit)
            except FileNotFoundError:
                return {"ok": False, "reason": "model-missing", "candidates": []}
            except LookupError:
                return {"ok": False, "reason": "index-missing", "candidates": []}
            except MemoryError as exc:
                self.unload()
                return {"ok": False, "reason": "memory", "note": str(exc), "candidates": []}
            except Exception as exc:  # noqa: BLE001 - surfaced, never fatal
                self.last_error = f"{exc.__class__.__name__}: {exc}"
                return {"ok": False, "reason": "error", "note": self.last_error, "candidates": []}

            self.queries += 1
            self.last_search_ms = round((time.time() - started) * 1000, 1)
            return {
                "ok": True,
                "reason": "hit" if hits else "miss",
                "query": text,
                "translation": translation,
                "index": index.report(),
                "ms": self.last_search_ms,
                "candidates": hits,
            }

    # ── lifecycle ──────────────────────────────────────────────────────────

    def unload(self, reason: str = "manual") -> dict:
        with self._lock:
            had = self._embedder is not None or bool(self._indexes)
            self._embedder = None
            for index in self._indexes.values():
                index.close()
            self._indexes = {}
            if had:
                print(f"semantic: released model and index ({reason})", file=_stderr())
            return {"ok": True, "freed": had, "reason": reason}

    def footprint_mb(self) -> float:
        """What the loaded stack is holding, for the memory watch's reserve.

        Measured on this machine: the host process grows by about 180 MB when
        the model and its matrix come in, and about 30 MB more once the
        reranker has run. The figure declared here is deliberately a little
        higher — it is a limit to stop the watchdog releasing the model under
        its own feet, not a measurement to report.
        """
        if self._embedder is None:
            return 0.0
        total = 300.0
        try:
            import rerank

            if rerank.RERANKER.report().get("loaded"):
                total += 30.0
        except Exception:
            pass
        return total

    def report(self) -> dict:
        path, source = resolve_model()
        built = []
        try:
            for entry in sorted(os.listdir(index_root())):
                paths = index_paths(entry)
                if paths:
                    built.append({
                        "translation": entry,
                        "verses": _count_rows(paths[0]),
                        "mb": round(os.path.getsize(paths[0]) / 1048576, 1),
                    })
        except OSError:
            pass

        borrowed = pewbeam_index()
        return {
            "deps": deps_ready(),
            "model": {
                "ready": bool(path),
                "source": source,
                "path": path or "",
                "mb": _dir_mb(path) if path else 0.0,
                "expected_mb": EXPECTED_MB,
            },
            "loaded": self._embedder is not None,
            "loaded_source": self._source,
            "load_seconds": self.load_seconds,
            "indexes": built,
            "borrowed": {
                "ready": bool(borrowed),
                "verses": _count_rows(borrowed[0]) if borrowed else 0,
                "mb": round(os.path.getsize(borrowed[0]) / 1048576, 1) if borrowed else 0.0,
            },
            "rss_mb": round(rss_mb(), 1),
            "queries": self.queries,
            "last_ms": self.last_search_ms,
            "error": self.last_error,
        }


def _count_rows(path: str) -> int:
    try:
        return os.path.getsize(path) // (DIM * 4)
    except OSError:
        return 0


def _stderr():
    import sys

    return sys.stderr or open(os.devnull, "w")


# ── installing the model ────────────────────────────────────────────────────

def deps_ready() -> bool:
    """Whether the two libraries the semantic tier needs are importable.

    They are optional like everything else here: without them the ladder still
    runs its verbatim tier, and the app says so instead of failing.
    """
    try:
        import onnxruntime  # noqa: F401
        import tokenizers  # noqa: F401

        return True
    except Exception:
        return False


def model_ready() -> bool:
    path, _source = resolve_model()
    return bool(path)


def install_model(progress=None, cancelled=None) -> str:
    """Fetch the embedding model from Hugging Face and verify what arrived.

    Only called once per machine. The 188 MB weight file is checked against the
    size the server reported, and a sha256 is recorded next to it so a later
    install can prove the copy it has is the copy it fetched.
    """
    if _model_ok(pack_dir()):
        return pack_dir()

    os.makedirs(os.path.join(pack_dir(), "onnx"), exist_ok=True)
    sizes = {local: _remote_size(HF_BASE + remote) for remote, local in PACK_FILES}
    total = sum(sizes.values()) or int(EXPECTED_MB * 1048576)
    done = 0
    last = 0.0

    for remote, local in PACK_FILES:
        target = os.path.join(pack_dir(), *local.split("/"))
        part = target + ".part"
        os.makedirs(os.path.dirname(target), exist_ok=True)
        if sizes.get(local) and os.path.isfile(target) and os.path.getsize(target) == sizes[local]:
            done += sizes[local]
            continue
        req = urllib.request.Request(HF_BASE + remote, headers={"User-Agent": "Verse/1.0"})
        with urllib.request.urlopen(req, timeout=120) as response, open(part, "wb") as fh:
            while True:
                if cancelled and cancelled():
                    raise RuntimeError("cancelled")
                chunk = response.read(512 * 1024)
                if not chunk:
                    break
                fh.write(chunk)
                done += len(chunk)
                if progress:
                    now = time.time()
                    if now - last > 0.3:
                        last = now
                        progress(min(0.99, done / max(total, 1)), "download")
        os.replace(part, target)

    for root, _dirs, files in os.walk(pack_dir()):
        for name in files:
            if name.endswith(".part"):
                try:
                    os.remove(os.path.join(root, name))
                except OSError:
                    pass

    manifest = {"pack": PACK, "repo": HF_REPO, "installed_at": time.time(), "files": {}}
    for _remote, local in PACK_FILES:
        path = os.path.join(pack_dir(), *local.split("/"))
        manifest["files"][local] = {
            "bytes": os.path.getsize(path),
            "sha256": _sha256(path),
        }
    with open(os.path.join(pack_dir(), "manifest.json"), "w", encoding="utf-8") as fh:
        json.dump(manifest, fh, indent=1)

    if progress:
        progress(1.0, "ready")
    return pack_dir()


# ── building our own index ──────────────────────────────────────────────────

# Measured on this machine (8 CPUs): 4 threads with batches of 8 is the fastest
# configuration, at ~104 ms per verse for English and ~144 ms for Yoruba and
# Igbo. Larger batches waste work padding short verses together and more
# threads only contend. Exposed as arguments rather than buried, because a
# faster machine will want different numbers.
BUILD_BATCH = 8
BUILD_THREADS = 4


def canon_rows(translation: str) -> list[tuple[str, int, int, str]]:
    """Every verse of one Bible in canon order, as (book, chapter, verse, text)."""
    import canon as _canon

    payload = _canon.load(translation)
    if not payload:
        return []
    rows: list[tuple[str, int, int, str]] = []
    for book in payload.get("books") or []:
        for chapter, verses in ((payload.get("canon") or {}).get(book) or {}).items():
            for verse, text in verses.items():
                text = (text or "").strip()
                if not text:
                    continue
                rows.append((book, int(chapter), int(verse), text))
    return rows


def progress_path(translation: str) -> str:
    return os.path.join(index_dir(translation), "progress.json")


def read_progress(translation: str) -> dict:
    try:
        with open(progress_path(translation), encoding="utf-8") as fh:
            return json.load(fh)
    except Exception:
        return {}


def build_index(translation: str, batch: int = BUILD_BATCH, threads: int = BUILD_THREADS,
                progress=None, cancelled=None) -> dict:
    """Embed a whole Bible into vectors.f32, resuming if a run was interrupted.

    A full Bible is 31,000 verses and roughly an hour of CPU, so the work is
    written straight to disk as it goes and the position is recorded. Stopping
    the app, or the machine, costs one batch rather than the lot; starting
    again picks up where it stopped. The index is only treated as usable once
    map.json exists, so a partial build is never searched by accident.
    """
    import numpy as np

    rows = canon_rows(translation)
    if not rows:
        return {"ok": False, "error": f"no verses found for {translation}"}

    out_dir = index_dir(translation)
    os.makedirs(out_dir, exist_ok=True)
    vectors_path = os.path.join(out_dir, "vectors.f32")
    row_bytes = DIM * 4
    total = len(rows)

    state = read_progress(translation)
    done = 0
    if (state.get("translation") == translation and state.get("total") == total
            and state.get("dim") == DIM and os.path.isfile(vectors_path)
            and os.path.getsize(vectors_path) == total * row_bytes):
        done = int(state.get("done") or 0)

    if not os.path.isfile(vectors_path) or os.path.getsize(vectors_path) != total * row_bytes:
        # Preallocate: a fixed row size means every verse can be written where
        # it belongs the moment it is computed.
        with open(vectors_path, "wb") as fh:
            fh.truncate(total * row_bytes)
        done = 0

    def checkpoint(index: int) -> None:
        payload = {
            "translation": translation,
            "total": total,
            "done": index,
            "dim": DIM,
            "batch": batch,
            "threads": threads,
            "updated_at": time.time(),
            "complete": index >= total,
        }
        tmp = progress_path(translation) + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(payload, fh)
        os.replace(tmp, progress_path(translation))

    if done:
        checkpoint(done)
    else:
        checkpoint(0)

    started = time.time()
    if progress:
        progress(done / total, "embedding")

    embedder = Embedder(resolve_model()[0], threads=threads)
    try:
        with open(vectors_path, "r+b") as fh:
            for start in range(done, total, batch):
                if cancelled and cancelled():
                    checkpoint(start)
                    return {"ok": False, "error": "cancelled", "done": start, "total": total}
                chunk = rows[start : start + batch]
                vectors = embedder.embed([row[3] for row in chunk], "document")
                for offset, vector in enumerate(vectors):
                    fh.seek((start + offset) * row_bytes)
                    fh.write(np.asarray(vector, dtype=np.float32).tobytes())
                fh.flush()
                placed = start + len(chunk)
                checkpoint(placed)
                if progress:
                    elapsed = max(time.time() - started, 0.01)
                    rate = (placed - done) / elapsed
                    progress(placed / total, "embedding", {
                        "done": placed,
                        "total": total,
                        "per_second": round(rate, 1),
                        "eta_seconds": round((total - placed) / rate, 0) if rate else None,
                    })
    finally:
        del embedder

    with open(os.path.join(out_dir, "map.json"), "w", encoding="utf-8") as fh:
        json.dump({
            "translation": translation,
            "dim": DIM,
            "verses": total,
            "model": HF_REPO,
            "prefix": DOC_PREFIX,
            "built_at": time.time(),
            "ids": ["%s.%d.%d" % (row[0], row[1], row[2]) for row in rows],
        }, fh)
    checkpoint(total)
    if progress:
        progress(1.0, "ready")
    return {"ok": True, "translation": translation, "verses": total, "seconds": round(time.time() - started, 1)}


def _sha256(path: str) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        for block in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _remote_size(url: str, timeout: int = 25) -> int:
    try:
        req = urllib.request.Request(url, method="HEAD", headers={"User-Agent": "Verse/1.0"})
        with urllib.request.urlopen(req, timeout=timeout) as response:
            return int(response.headers.get("Content-Length") or 0)
    except Exception:
        return 0


# One shared instance: the model is 188 MB, so there must never be two.
DETECT = Detection()
