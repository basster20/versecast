"""Turn a Bible text into a data file the app can load on demand.

Two inputs are accepted:

  --vpl  eBible.org "verse per line" text:   GEN 1:1 In the beginning ...
  --json a flat map:                         {"Genesis 1:1": "In the beginning ..."}

Either way the output is `assets/js/data.<id>.js`, which registers itself under
`window.VERSE_CANONS[id]` so app.js can fetch it the first time someone picks
that translation.

    python tools/build_translation.py --vpl yor_vpl.txt --id yor --short YOR \
        --title "Biblica Open Yoruba Contemporary Bible" --language Yoruba \
        --licence "CC BY-SA 4.0" --source https://ebible.org/find/details.php?id=yor

Only ship text you have the right to distribute. Public-domain and
Creative-Commons translations can be bundled; NIV, NKJV, ESV, NASB and most
modern English Bibles are licensed and must be imported by the person who owns
that licence (the same command, --json, from their own copy).
"""
import argparse
import json
import os
import re

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)

# USFM book codes -> the names the app and its detector use.
CODES = {
    "GEN": "Genesis", "EXO": "Exodus", "LEV": "Leviticus", "NUM": "Numbers",
    "DEU": "Deuteronomy", "JOS": "Joshua", "JDG": "Judges", "RUT": "Ruth",
    "1SA": "1 Samuel", "2SA": "2 Samuel", "1KI": "1 Kings", "2KI": "2 Kings",
    "1CH": "1 Chronicles", "2CH": "2 Chronicles", "EZR": "Ezra", "NEH": "Nehemiah",
    "EST": "Esther", "JOB": "Job", "PSA": "Psalms", "PRO": "Proverbs",
    "ECC": "Ecclesiastes", "SOL": "Song of Solomon", "ISA": "Isaiah",
    "JER": "Jeremiah", "LAM": "Lamentations", "EZE": "Ezekiel", "DAN": "Daniel",
    "HOS": "Hosea", "JOE": "Joel", "AMO": "Amos", "OBA": "Obadiah",
    "JON": "Jonah", "MIC": "Micah", "NAH": "Nahum", "HAB": "Habakkuk",
    "ZEP": "Zephaniah", "HAG": "Haggai", "ZEC": "Zechariah", "MAL": "Malachi",
    "MAT": "Matthew", "MAR": "Mark", "LUK": "Luke", "JOH": "John", "ACT": "Acts",
    "ROM": "Romans", "1CO": "1 Corinthians", "2CO": "2 Corinthians",
    "GAL": "Galatians", "EPH": "Ephesians", "PHI": "Philippians",
    "COL": "Colossians", "1TH": "1 Thessalonians", "2TH": "2 Thessalonians",
    "1TI": "1 Timothy", "2TI": "2 Timothy", "TIT": "Titus", "PHM": "Philemon",
    "HEB": "Hebrews", "JAM": "James", "1PE": "1 Peter", "2PE": "2 Peter",
    "1JO": "1 John", "2JO": "2 John", "3JO": "3 John", "JUD": "Jude",
    "REV": "Revelation",
}

VPL_RE = re.compile(r"^(?P<code>[1-4A-Z]{3})\s+(?P<chapter>\d+):(?P<verse>\d+)\s+(?P<text>.+)$")
JSON_RE = re.compile(r"^(?P<book>.+?)\s+(?P<chapter>\d+):(?P<verse>\d+)$")


def from_vpl(path):
    canon = {}
    skipped_codes = set()
    skipped_verses = 0
    with open(path, encoding="utf-8-sig") as fh:
        for line in fh:
            line = line.rstrip("\n")
            m = VPL_RE.match(line)
            if not m:
                continue
            book = CODES.get(m.group("code"))
            if book is None:            # apocrypha in some editions
                skipped_codes.add(m.group("code"))
                continue
            verse = int(m.group("verse"))
            if verse == 0:              # superscription, not a verse
                skipped_verses += 1
                continue
            chapter = m.group("chapter")
            canon.setdefault(book, {}).setdefault(chapter, {})[str(verse)] = m.group("text").strip()
    return canon, skipped_codes, skipped_verses


def from_json(path):
    with open(path, encoding="utf-8-sig") as fh:
        flat = json.load(fh)
    canon = {}
    for key, text in flat.items():
        m = JSON_RE.match(key)
        if not m:
            raise SystemExit(f"unparsed key: {key!r} (expected \"Book 3:16\")")
        canon.setdefault(m.group("book"), {}).setdefault(m.group("chapter"), {})[
            str(int(m.group("verse")))
        ] = str(text).strip()
    return canon, set(), 0


def main():
    ap = argparse.ArgumentParser(description="Build a Verse translation data file")
    src = ap.add_mutually_exclusive_group(required=True)
    src.add_argument("--vpl", help="eBible verse-per-line text")
    src.add_argument("--json", help='flat {"Book C:V": "text"} file')
    ap.add_argument("--id", required=True, help="short id used in settings, e.g. yor")
    ap.add_argument("--short", required=True, help="label shown on slides, e.g. YOR")
    ap.add_argument("--title", required=True)
    ap.add_argument("--language", default="English")
    ap.add_argument("--licence", default="Public domain")
    ap.add_argument("--source", default="")
    args = ap.parse_args()

    canon, skipped_codes, skipped_verses = (
        from_vpl(args.vpl) if args.vpl else from_json(args.json)
    )
    order = [name for name in CODES.values() if name in canon]
    count = sum(len(v) for book in canon.values() for v in book.values())
    if len(order) < 66:
        missing = [n for n in CODES.values() if n not in canon]
        print(f"warning: {len(order)}/66 books present, missing {missing[:6]}")

    payload = {
        "id": args.id,
        "translation": args.short,
        "title": args.title,
        "language": args.language,
        "licence": args.licence,
        "source": args.source,
        "verses": count,
        "books": order,
        "canon": {book: canon[book] for book in order},
    }

    out = os.path.join(ROOT, "assets", "js", f"data.{args.id}.js")
    with open(out, "w", encoding="utf-8") as fh:
        fh.write(f"/* {args.title} — {args.licence}.\n")
        if args.source:
            fh.write(f"   Source: {args.source}\n")
        fh.write("   Generated by tools/build_translation.py; see BIBLES.md for the notice. */\n")
        fh.write("window.VERSE_CANONS=window.VERSE_CANONS||{};")
        fh.write("window.VERSE_CANONS[" + json.dumps(args.id) + "]=")
        json.dump(payload, fh, ensure_ascii=False, separators=(",", ":"))
        fh.write(";\n")

    size = os.path.getsize(out) / 1048576
    print(f"{args.id}: books={len(order)} verses={count} -> {out} ({size:.2f} MB)")
    if skipped_codes:
        print("  skipped non-canonical books:", ", ".join(sorted(skipped_codes)))
    if skipped_verses:
        print(f"  skipped {skipped_verses} superscription lines")


if __name__ == "__main__":
    main()
