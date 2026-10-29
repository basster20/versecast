"""Cross-encoder reranking — the tie-breaker at the end of the ladder.

An embedding compares a sentence with a verse that was embedded separately, so
it can only ever be approximate. Measured on this machine, "the pastor said we
should put off the old man" put 1 Samuel 2:31 (0.501) ahead of Ephesians 4:22
(0.490) — close enough that no threshold can separate them. A cross-encoder
reads the pair *together* and scores it directly, which is what fixes exactly
that kind of near-miss.

It is deliberately the last and least trusted tier:

*Optional.* Pewbeam ships this as a resource pack and runs fail-open — if the
model is missing, candidates pass through unchanged and the app still works.
Same here. Nothing else depends on it.

*Bounded.* Only the top few candidates are scored, because the cost is one
forward pass per candidate rather than one for the whole Bible.

*Not a decision maker.* It reorders; it never introduces a verse the cheaper
tiers did not already find.
"""
from __future__ import annotations

import hashlib
import json
import os
import threading
import time
import urllib.request

PACK = "cross_encoder_miniLM"
HF_REPO = "Xenova/ms-marco-MiniLM-L-6-v2"
HF_BASE = f"https://huggingface.co/{HF_REPO}/resolve/main/"
PACK_FILES = (
    ("config.json", "config.json"),
    ("special_tokens_map.json", "special_tokens_map.json"),
    ("tokenizer_config.json", "tokenizer_config.json"),
    ("tokenizer.json", "tokenizer.json"),
    ("vocab.txt", "vocab.txt"),
    ("onnx/model_int8.onnx", "onnx/model_int8.onnx"),
)
MODEL_REL = "onnx/model_int8.onnx"
EXPECTED_MB = 23.0

# How many candidates a single query may send through the encoder. Enough to
# cover a genuine near-miss; small enough that a worst case stays under 100 ms.
MAX_PAIRS = 6
# Below this the pair is not a match at all, whatever the ordering says.
MIN_LOGIT = -2.0


def _app_dir() -> str:
    base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
    return os.path.join(base, "Verse")


def pack_dir() -> str:
    return os.path.join(_app_dir(), "models", PACK)


def _model_path() -> str:
    return os.path.join(pack_dir(), *MODEL_REL.split("/"))


def model_ready() -> bool:
    return os.path.isfile(_model_path()) and os.path.isfile(os.path.join(pack_dir(), "tokenizer.json"))


def _dir_mb(path: str) -> float:
    total = 0
    for root, _dirs, files in os.walk(path):
        for name in files:
            try:
                total += os.path.getsize(os.path.join(root, name))
            except OSError:
                pass
    return round(total / 1048576, 1)


class CrossEncoder:
    """MiniLM-L6 cross-encoder, int8, one forward pass per candidate."""

    def __init__(self, path: str | None = None):
        import onnxruntime as ort
        from tokenizers import Tokenizer

        root = path or pack_dir()
        options = ort.SessionOptions()
        options.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
        options.intra_op_num_threads = max(2, min(4, (os.cpu_count() or 4) - 2))
        self._session = ort.InferenceSession(
            os.path.join(root, *MODEL_REL.split("/")), options, providers=["CPUExecutionProvider"]
        )
        self._tokenizer = Tokenizer.from_file(os.path.join(root, "tokenizer.json"))
        self._inputs = {spec.name for spec in self._session.get_inputs()}
        self._lock = threading.Lock()

    def score(self, query: str, passages: list[str]) -> list[float]:
        import numpy as np

        pairs = [(query, p) for p in passages]
        batch = self._tokenizer.encode_batch(pairs, add_special_tokens=True)
        width = max(len(enc.ids) for enc in batch)
        feed = {}
        ids = np.zeros((len(batch), width), dtype=np.int64)
        mask = np.zeros((len(batch), width), dtype=np.int64)
        types = np.zeros((len(batch), width), dtype=np.int64)
        for row, enc in enumerate(batch):
            ids[row, : len(enc.ids)] = enc.ids
            mask[row, : len(enc.attention_mask)] = enc.attention_mask
            if enc.type_ids:
                types[row, : len(enc.type_ids)] = enc.type_ids
        feed["input_ids"] = ids
        if "attention_mask" in self._inputs:
            feed["attention_mask"] = mask
        if "token_type_ids" in self._inputs:
            feed["token_type_ids"] = types

        with self._lock:
            logits = np.asarray(self._session.run(None, feed)[0], dtype=np.float32)
        return [float(row[0]) for row in logits.reshape(len(batch), -1)]


class Reranker:
    """Lazy wrapper: nothing loads until a query actually needs a tie broken."""

    def __init__(self):
        self._model: CrossEncoder | None = None
        self._lock = threading.Lock()
        self.disabled = False
        self.load_seconds = 0.0
        self.last_ms = 0.0
        self.pairs = 0
        self.error: str | None = None
        self.moved = 0  # how often reranking actually changed the top verse

    def available(self) -> bool:
        if self.disabled or not model_ready():
            return False
        try:
            self._engine()
            return True
        except Exception as exc:  # noqa: BLE001 - fail-open by design
            self.error = f"{exc.__class__.__name__}: {exc}"
            self.disabled = True
            return False

    def _engine(self) -> CrossEncoder:
        if self._model is not None:
            return self._model
        started = time.time()
        self._model = CrossEncoder()
        self.load_seconds = round(time.time() - started, 2)
        return self._model

    def rerank(self, query: str, candidates: list[dict], text_for=None) -> list[dict]:
        """Reorder candidates by reading each one against the query.

        ``text_for`` turns a candidate into the words to compare; without it the
        candidate's own ``evidence`` field is used, which is all Pewbeam's map
        carries. Any failure returns the input order untouched.
        """
        if not candidates:
            return candidates
        started = time.time()
        try:
            if not self.available():
                return candidates
            head = candidates[:MAX_PAIRS]
            passages = []
            for candidate in head:
                text = ""
                if text_for is not None:
                    text = text_for(candidate) or ""
                if not text:
                    text = candidate.get("evidence") or ""
                passages.append(text or candidate.get("id") or "")
            if not any(passages):
                return candidates

            logits = self._engine().score(query, passages)
            before = head[0].get("id")
            scored = []
            for candidate, logit in zip(head, logits):
                entry = dict(candidate)
                entry["cross_encoder_logit"] = round(logit, 3)
                # The blend keeps the retrieval order meaningful while letting a
                # confident pair win: retrieval scores are 0.3-0.7 here, so a
                # logit of +3 (a clear match) is decisive and -3 (clearly not)
                # sinks it.
                entry["rerank_score"] = round(float(candidate.get("score") or 0) + logit / 10.0, 4)
                scored.append(entry)
            scored.sort(key=lambda c: -c["rerank_score"])
            rest = [dict(c) for c in candidates[MAX_PAIRS:]]
            out = scored + rest
            out = [c for c in out if (c.get("cross_encoder_logit") is None or c["cross_encoder_logit"] >= MIN_LOGIT)] or out
            if out[0].get("id") != before:
                self.moved += 1
            self.pairs += len(head)
            self.last_ms = round((time.time() - started) * 1000, 1)
            return out
        except Exception as exc:  # noqa: BLE001 - a reranker must never break detection
            self.error = f"{exc.__class__.__name__}: {exc}"
            self.last_ms = round((time.time() - started) * 1000, 1)
            return candidates

    def unload(self) -> dict:
        with self._lock:
            had = self._model is not None
            self._model = None
            return {"ok": True, "freed": had}

    def report(self) -> dict:
        return {
            "ready": model_ready(),
            "available": False if self.disabled else model_ready(),
            "loaded": self._model is not None,
            "mb": _dir_mb(pack_dir()) if model_ready() else 0.0,
            "expected_mb": EXPECTED_MB,
            "load_seconds": self.load_seconds,
            "last_ms": self.last_ms,
            "pairs": self.pairs,
            "moved": self.moved,
            "disabled": self.disabled,
            "error": self.error,
        }


# ── installing the pack ─────────────────────────────────────────────────────

def install_model(progress=None, cancelled=None) -> str:
    """Fetch the int8 cross-encoder. 23 MB, once, and entirely optional."""
    if model_ready():
        return pack_dir()

    os.makedirs(os.path.join(pack_dir(), "onnx"), exist_ok=True)
    sizes = {local: _remote_size(HF_BASE + remote) for remote, local in PACK_FILES}
    total = sum(sizes.values()) or int(EXPECTED_MB * 1048576)
    done = 0
    last = 0.0

    for remote, local in PACK_FILES:
        target = os.path.join(pack_dir(), *local.split("/"))
        part = target + ".part"
        if sizes.get(local) and os.path.isfile(target) and os.path.getsize(target) == sizes[local]:
            done += sizes[local]
            continue
        req = urllib.request.Request(HF_BASE + remote, headers={"User-Agent": "Verse/1.0"})
        with urllib.request.urlopen(req, timeout=120) as response, open(part, "wb") as fh:
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
        manifest["files"][local] = {"bytes": os.path.getsize(path), "sha256": _sha256(path)}
    with open(os.path.join(pack_dir(), "manifest.json"), "w", encoding="utf-8") as fh:
        json.dump(manifest, fh, indent=1)

    if progress:
        progress(1.0, "ready")
    return pack_dir()


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


RERANKER = Reranker()
