"""The detection ladder — cheapest tier first, stop as soon as one is sure.

Pewbeam's search_dispatch exposes four tiers (direct, shingle, semantic,
verbatim) and short-circuits them: a cheap answer is emitted, and a better one
only replaces it if the expensive tiers actually find something stronger.

    direct      "turn to Romans chapter eight verse twenty eight"
                -> engine.js, in the page, free and instant
    shingle     "the Lord is my shepherd, I shall not want"
                -> exact five-word match, ~0.2 ms, precise
    semantic    "the pastor put off the old man and put on the new"
                -> embeddings, ~35 ms, finds what was never quoted word for word
    rerank      a cross-encoder reads the shortlist against the sentence to
                break near-misses (optional; fail-open)

This module owns everything below "direct": the page calls the direct detector
first because it already has the words in hand, and only asks this side when
that finds nothing.

Measured on this machine, one utterance costs: shingle 0.2 ms, semantic 35 ms
(model load 2.4 s, once), rerank 40 ms for six pairs. A confident shingle hit
returns without loading a model at all, which is why the order matters.
"""
from __future__ import annotations

import time

import canon
import rerank
import semantic
import shingle

# Retrieval scores differ by language. EmbeddingGemma separates English verses
# well (mean off-diagonal cosine 0.44, correct hits 0.50-0.71). Yoruba and Igbo
# sit closer together (0.57 off-diagonal), so the same threshold that is
# cautious in English would accept noise in them.
MIN_SCORE = {"default": 0.42, "yor": 0.62, "ibo": 0.62}
# A five-word quotation that covers this much of the utterance needs no model.
SHINGLE_CERTAIN = 0.55
# Exact five-word runs a shingle candidate must have before it outweighs the
# reranker: matching that much text word for word is not a coincidence.
SHINGLE_TRUSTED = 4
# Below this a candidate is reported but flagged as a guess.
WEAK = 0.38

# The cross-encoder is trained on English question/answer pairs, so its logit
# is a decision only for the English Bibles. Reordering Yoruba with it would be
# worse than not running it at all, so for those translations it is skipped.
ENGLISH = {"kjv", "web", "nkjv", "niv", "esv", "nasb", "nlt", "amp", "msg"}
# A logit above this means the pair was read together and judged a match. On
# this machine real quotations score 7-9, honest paraphrases 1-3, and sentences
# that merely share vocabulary 0.0 and below — so the line is drawn at 0.6.
RERANK_MIN = 0.6
# Retrieval floor when the reranker is not installed at all.
NO_RERANK_FLOOR = 0.55


def _min_score(translation: str) -> float:
    return MIN_SCORE.get(translation, MIN_SCORE["default"])


def _confidence(score: float, margin: float, tier: str) -> float:
    """Turn a retrieval score into the 0-1 the UI shows.

    Calibrated against the measurements above rather than invented: 0.42 is the
    point below which English candidates stop being right, 0.75 is a near-exact
    quotation. The margin nudges, it does not decide — parallel passages are
    genuinely close, and punishing that would hide correct answers.
    """
    del tier  # the tier is reported beside the confidence, not folded into it
    base = (score - 0.30) / 0.45
    base = max(0.0, min(1.0, base))
    return round(max(0.0, min(1.0, base + min(0.12, margin * 1.5))), 3)


def _logit_confidence(logit: float) -> float:
    """Cross-encoder logit -> the same 0-1 scale, from the same measurements.

    A -10 (clearly unrelated) must read as low, a +9 (a repeated quotation) as
    high, and the 0.6 acceptance line as a little under half — visible, but
    asking to be confirmed by eye before it goes live.
    """
    return round(max(0.0, min(0.99, 0.35 + logit * 0.075)), 3)


def _merge(*groups: list[dict]) -> list[dict]:
    """Union by verse, keeping the best score seen for each."""
    best: dict[str, dict] = {}
    for group in groups:
        for candidate in group or []:
            key = candidate.get("id") or f"{candidate.get('book')}.{candidate.get('chapter')}.{candidate.get('verse')}"
            current = best.get(key)
            if current is None or (candidate.get("score") or 0) > (current.get("score") or 0):
                merged = dict(candidate)
                # Remember that more than one tier found it: agreement between
                # an exact quote and the embeddings is the strongest signal
                # available here.
                merged["tiers"] = sorted(set((current or {}).get("tiers", [])) | {candidate.get("index") or "?"})
                best[key] = merged
            else:
                current["tiers"] = sorted(set(current.get("tiers", [])) | {candidate.get("index") or "?"})
    return sorted(best.values(), key=lambda c: -(c.get("score") or 0))


def decide(text: str, translation: str = "kjv", limit: int = 5, use_rerank: bool = True) -> dict:
    """Pick the verse an utterance is about, or say confidently that there is none.

    Always returns a dict. Failure is a normal outcome — most sentences in a
    sermon are not scripture — and the caller distinguishes "nothing found"
    from "the stack is not installed" by ``reason``.
    """
    text = (text or "").strip()
    if len(text.split()) < 4:
        return {"ok": False, "reason": "too-short", "candidates": [], "timings": {}}

    started = time.time()
    timings: dict[str, float] = {}

    mark = time.time()
    exact = shingle.SHINGLES.search(text, translation, limit)
    timings["shingle_ms"] = round((time.time() - mark) * 1000, 2)

    exact_candidates = exact.get("candidates") or []
    if exact.get("ok") and exact_candidates:
        top = exact_candidates[0]
        if (top.get("coverage") or 0) >= SHINGLE_CERTAIN and (top.get("matched") or 0) >= 4:
            timings["total_ms"] = round((time.time() - started) * 1000, 2)
            return {
                "ok": True,
                "reason": "hit",
                "tier": "shingle",
                "query": text,
                "translation": translation,
                "confidence": _confidence(top["score"], 0.3, "shingle"),
                "decision": _decision(top),
                "candidates": exact_candidates,
                "timings": timings,
            }

    mark = time.time()
    deep = semantic.DETECT.search(text, translation, limit + 2)
    timings["semantic_ms"] = round((time.time() - mark) * 1000, 2)

    # Without an index the embeddings cannot help, and the caller should be told
    # which piece is missing rather than just "nothing found": one needs an
    # install, the other needs an hour of building.
    if not exact_candidates and deep.get("reason") in ("model-missing", "index-missing"):
        timings["total_ms"] = round((time.time() - started) * 1000, 2)
        return {
            "ok": False,
            "reason": deep["reason"],
            "translation": translation,
            "candidates": [],
            "timings": timings,
        }

    merged = _merge(deep.get("candidates") or [], exact_candidates)

    mark = time.time()
    if merged and use_rerank and translation in ENGLISH:
        merged = rerank.RERANKER.rerank(text, merged, text_for=lambda c: _passage(c, translation))
    timings["rerank_ms"] = round((time.time() - mark) * 1000, 1)

    if not merged:
        timings["total_ms"] = round((time.time() - started) * 1000, 2)
        return {
            "ok": False,
            "reason": deep.get("reason") or "no-candidate",
            "query": text,
            "translation": translation,
            "candidates": [],
            "timings": timings,
        }

    top = merged[0]
    second = merged[1] if len(merged) > 1 else None
    retrieval = float(top.get("score") or 0)
    margin = retrieval - float((second or {}).get("score") or 0)
    logit = top.get("cross_encoder_logit")
    tier = "shingle+semantic" if len(top.get("tiers") or []) > 1 else (
        "shingle" if (top.get("index") or "").endswith("(shingle)") else "semantic"
    )

    # Three ways to be sure, strongest first. Matching this many five-word runs
    # word for word is not a coincidence, in any language.
    if (top.get("matched") or 0) >= SHINGLE_TRUSTED:
        accepted = True
        confidence = max(0.8, _confidence(retrieval, margin, "shingle"))
        gate, threshold = retrieval, None
    elif logit is not None:
        accepted = float(logit) >= RERANK_MIN
        confidence = _logit_confidence(float(logit))
        gate, threshold = float(logit), RERANK_MIN
    else:
        # No reranker, so nothing read the pair together and the embedding score
        # is all there is. English sentences that merely share vocabulary land
        # at 0.49-0.51 here — above the normal floor — so without the reranker
        # the floor has to carry the precision on its own.
        threshold = _min_score(translation)
        if translation in ENGLISH and not rerank.RERANKER.available():
            threshold = max(threshold, NO_RERANK_FLOOR)
        accepted = retrieval >= threshold
        confidence = _confidence(retrieval, margin, tier)
        gate = retrieval

    timings["total_ms"] = round((time.time() - started) * 1000, 2)
    result = {
        "ok": bool(accepted),
        "reason": "hit" if accepted else "below-threshold",
        "tier": tier,
        "query": text,
        "translation": translation,
        "confidence": confidence,
        "weak": confidence < WEAK,
        "gate": round(gate, 4),
        "threshold": threshold,
        "retrieval": round(retrieval, 4),
        "candidates": merged[:limit],
        "timings": timings,
    }
    if accepted:
        result["decision"] = _decision(top)
    return result


def _decision(candidate: dict) -> dict | None:
    book = candidate.get("book")
    if not book:
        return None
    return {
        "book": book,
        "chapter": int(candidate.get("chapter") or 1),
        "verseStart": int(candidate.get("verse") or 1),
        "verseEnd": None,
        "reference": "%s %s:%s" % (book, candidate.get("chapter"), candidate.get("verse")),
    }


def _passage(candidate: dict, translation: str) -> str:
    text = canon.passage_text(
        translation,
        candidate.get("book") or "",
        int(candidate.get("chapter") or 0),
        int(candidate.get("verse") or 0),
    )
    return text or (candidate.get("evidence") or "")


def status() -> dict:
    return {
        "shingle": shingle.SHINGLES.report(),
        "semantic": semantic.DETECT.report(),
        "rerank": rerank.RERANKER.report(),
        "thresholds": {
            "min_score": MIN_SCORE,
            "shingle_certain": SHINGLE_CERTAIN,
            "weak": WEAK,
        },
    }


def unload(reason: str = "manual") -> dict:
    """Give back every byte the detection stack holds."""
    freed = {
        "semantic": semantic.DETECT.unload(reason).get("freed"),
        "shingle": shingle.SHINGLES.unload().get("freed"),
        "rerank": rerank.RERANKER.unload().get("freed"),
    }
    canon.release()
    return {"ok": True, "freed": freed, "rss_mb": round(semantic.rss_mb(), 1)}
