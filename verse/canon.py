"""Reading the app's own Bible files from Python.

The page loads each Bible as a JavaScript assignment (`window.CANON_DATA=…` or
`window.VERSE_CANONS["yor"]=…`) wrapping a JSON payload. The detection tiers on
this side need the same words the operator sees on screen, and the payload after
the `=` is plain JSON — so this module parses the file the page already ships
instead of keeping a second copy of scripture on disk.

Nothing here is loaded at start-up: a Bible is read only when a tier needs it,
and the parsed object is dropped with the rest of the stack.
"""
from __future__ import annotations

import json
import os
import re
import threading

# The files are `window.CANON_DATA=…` or `window.VERSE_CANONS["yor"]=…` behind a
# header comment that itself contains an `=` (a source URL), so the assignment
# has to be located, not guessed at by the first `=` in the file.
ASSIGN_RE = re.compile(r"window\.[A-Za-z_]+(?:\[\s*\"[^\"]+\"\s*\])?\s*=")

ROOT = os.path.dirname(os.path.abspath(__file__))
JS_DIR = os.path.join(ROOT, "assets", "js")

_lock = threading.Lock()
_cache: dict[str, dict] = {}


def data_files() -> dict[str, str]:
    """{translation id: file} for every Bible bundled in this build.

    Derived from the file names, so a Bible imported later with
    tools/build_translation.py is picked up without touching this file.
    """
    found: dict[str, str] = {}
    try:
        names = os.listdir(JS_DIR)
    except OSError:
        return found
    for name in names:
        if not (name.startswith("data") and name.endswith(".js")):
            continue
        key = "kjv" if name == "data.js" else name[len("data.") : -len(".js")]
        found[key] = os.path.join(JS_DIR, name)
    return found


def path_for(translation: str) -> str | None:
    return data_files().get(translation)


def load(translation: str, cache: bool = True) -> dict | None:
    if cache:
        with _lock:
            hit = _cache.get(translation)
        if hit is not None:
            return hit

    path = path_for(translation)
    if not path or not os.path.isfile(path):
        return None
    with open(path, encoding="utf-8") as fh:
        raw = fh.read()
    # Some files register themselves first (`window.VERSE_CANONS=window.VERSE_CANONS||{};`
    # then the payload), so the assignment worth reading is the one whose value
    # is an object.
    start = None
    for match in ASSIGN_RE.finditer(raw):
        if raw[match.end() :].lstrip()[:1] == "{":
            start = match.end()
            break
    end = raw.rfind(";")
    if start is None or end <= start:
        return None
    payload = json.loads(raw[start:end])
    if cache:
        with _lock:
            _cache[translation] = payload
    return payload


def release() -> None:
    with _lock:
        _cache.clear()


def verse_text(translation: str, book: str, chapter: int, verse: int) -> str:
    canon = load(translation)
    if not canon:
        return ""
    chapters = (canon.get("canon") or {}).get(book) or {}
    verses = chapters.get(str(chapter)) or {}
    return (verses.get(str(verse)) or "").strip()


def passage_text(translation: str, book: str, chapter: int, start: int, end: int | None = None) -> str:
    """The verse, or a range of them, as one string — what the reranker reads."""
    last = end or start
    parts = []
    for verse in range(start, last + 1):
        text = verse_text(translation, book, chapter, verse)
        if text:
            parts.append(text)
    return " ".join(parts)
