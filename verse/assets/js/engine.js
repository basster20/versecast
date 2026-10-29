/* Verse — reference detection + scripture search.
 *
 * The detector is a direct port of VerseListener's core/bible_detector.py:
 * one compiled pattern over a 66-book alias table, aliases matched longest-first,
 * an unknown group-1 word aborts the match (so "John Cena 5" never matches).
 */
(function (root, factory) {
  const api = factory();
  if (typeof module === "object" && module.exports) module.exports = api;
  if (root) root.Engine = api;
})(typeof globalThis !== "undefined" ? globalThis : this, function () {
  "use strict";

  const BOOKS = [
    ["Genesis", ["genesis", "gen", "ge", "gn"]],
    ["Exodus", ["exodus", "exo", "ex", "exod"]],
    ["Leviticus", ["leviticus", "lev", "le", "lv"]],
    ["Numbers", ["numbers", "num", "nu", "nb"]],
    ["Deuteronomy", ["deuteronomy", "deut", "deu", "dt", "de"]],
    ["Joshua", ["joshua", "josh", "jos", "jsh"]],
    ["Judges", ["judges", "judg", "jdg", "jg", "jdgs"]],
    ["Ruth", ["ruth", "rut", "rth"]],
    ["1 Samuel", ["1 samuel", "1samuel", "1sam", "1sa", "1sm", "i samuel", "first samuel"]],
    ["2 Samuel", ["2 samuel", "2samuel", "2sam", "2sa", "2sm", "ii samuel", "second samuel"]],
    ["1 Kings", ["1 kings", "1kings", "1kgs", "1ki", "i kings", "first kings"]],
    ["2 Kings", ["2 kings", "2kings", "2kgs", "2ki", "ii kings", "second kings"]],
    ["1 Chronicles", ["1 chronicles", "1chronicles", "1chr", "1ch", "i chronicles", "first chronicles"]],
    ["2 Chronicles", ["2 chronicles", "2chronicles", "2chr", "2ch", "ii chronicles", "second chronicles"]],
    ["Ezra", ["ezra", "ezr"]],
    ["Nehemiah", ["nehemiah", "neh", "ne"]],
    ["Esther", ["esther", "est", "esth"]],
    ["Job", ["job", "jb"]],
    ["Psalms", ["psalms", "psalm", "psa", "ps", "pss"]],
    ["Proverbs", ["proverbs", "prov", "pro", "prv", "pv"]],
    ["Ecclesiastes", ["ecclesiastes", "eccl", "ecc", "qoh", "eccles"]],
    ["Song of Solomon", ["song of solomon", "song of songs", "song", "sos", "ss", "cant", "canticles"]],
    ["Isaiah", ["isaiah", "isa", "is"]],
    ["Jeremiah", ["jeremiah", "jer", "je", "jr"]],
    ["Lamentations", ["lamentations", "lam", "la"]],
    ["Ezekiel", ["ezekiel", "ezek", "eze", "ezk"]],
    ["Daniel", ["daniel", "dan", "da", "dn"]],
    ["Hosea", ["hosea", "hos", "ho"]],
    ["Joel", ["joel", "jol", "joe", "jl"]],
    ["Amos", ["amos", "amo", "am"]],
    ["Obadiah", ["obadiah", "obad", "oba", "ob"]],
    ["Jonah", ["jonah", "jon", "jnh"]],
    ["Micah", ["micah", "mic", "mi"]],
    ["Nahum", ["nahum", "nah", "na"]],
    ["Habakkuk", ["habakkuk", "hab", "hb"]],
    ["Zephaniah", ["zephaniah", "zeph", "zep", "zp"]],
    ["Haggai", ["haggai", "hag", "hg"]],
    ["Zechariah", ["zechariah", "zech", "zec", "zc"]],
    ["Malachi", ["malachi", "mal", "ml"]],
    ["Matthew", ["matthew", "matt", "mat", "mt"]],
    ["Mark", ["mark", "mrk", "mar", "mk", "mr"]],
    ["Luke", ["luke", "luk", "lk"]],
    ["John", ["john", "joh", "jn", "jhn"]],
    ["Acts", ["acts", "act", "ac"]],
    ["Romans", ["romans", "rom", "ro", "rm"]],
    ["1 Corinthians", ["1 corinthians", "1corinthians", "1cor", "1co", "i corinthians", "first corinthians"]],
    ["2 Corinthians", ["2 corinthians", "2corinthians", "2cor", "2co", "ii corinthians", "second corinthians"]],
    ["Galatians", ["galatians", "gal", "ga"]],
    ["Ephesians", ["ephesians", "eph", "ephes"]],
    ["Philippians", ["philippians", "phil", "php", "pp"]],
    ["Colossians", ["colossians", "col", "co"]],
    ["1 Thessalonians", ["1 thessalonians", "1thessalonians", "1thess", "1th", "i thessalonians", "first thessalonians"]],
    ["2 Thessalonians", ["2 thessalonians", "2thessalonians", "2thess", "2th", "ii thessalonians", "second thessalonians"]],
    ["1 Timothy", ["1 timothy", "1timothy", "1tim", "1ti", "i timothy", "first timothy"]],
    ["2 Timothy", ["2 timothy", "2timothy", "2tim", "2ti", "ii timothy", "second timothy"]],
    ["Titus", ["titus", "tit", "ti"]],
    ["Philemon", ["philemon", "phlm", "phm", "pm"]],
    ["Hebrews", ["hebrews", "heb", "he"]],
    ["James", ["james", "jas", "jm"]],
    ["1 Peter", ["1 peter", "1peter", "1pet", "1pe", "i peter", "first peter"]],
    ["2 Peter", ["2 peter", "2peter", "2pet", "2pe", "ii peter", "second peter"]],
    ["1 John", ["1 john", "1john", "1jn", "1jo", "i john", "first john"]],
    ["2 John", ["2 john", "2john", "2jn", "2jo", "ii john", "second john"]],
    ["3 John", ["3 john", "3john", "3jn", "3jo", "iii john", "third john"]],
    ["Jude", ["jude", "jud", "jd"]],
    ["Revelation", ["revelation", "revelations", "rev", "re", "rv", "the revelation"]],
  ];

  const BOOK_NAMES = BOOKS.map((b) => b[0]);
  const ALIAS = new Map();
  for (const [book, aliases] of BOOKS) for (const a of aliases) ALIAS.set(a, book);

  const escaped = [...ALIAS.keys()]
    .sort((a, b) => b.length - a.length)
    .map((a) => a.replace(/[.*+?^${}()|[\]\\]/g, "\\$&"))
    .join("|");

  const REF_SRC =
    "(?<!\\w)(?:book\\s+of\\s+)?(" +
    escaped +
    ")[\\s,]+(?:chapter|chap|ch\\.?)?\\s*(\\d+)(?:(?:\\s*:\\s*|\\s+(?:verses?|ver\\.?|v\\.?)\\s*)(\\d+)(?:\\s*[-\u2013\u2014]\\s*(\\d+)|\\s+(?:through|thru|to|and)\\s+(\\d+(?!\\s+[a-z])(?!\\d)))?)?";

  const REF_RE = new RegExp(REF_SRC, "gi");
  const REF_ANCHORED = new RegExp("^\\s*" + REF_SRC + "\\s*$", "i");
  // Typed queries are looser than transcripts: "john 3 16" is accepted here,
  // while detect() keeps VerseListener's exact behaviour (colon or "verse").
  const SPOKEN_ANCHORED = new RegExp(
    "^\\s*(?:book\\s+of\\s+)?(" + escaped + ")\\s+(\\d+)\\s+(\\d+)(?:\\s*[-\\u2013\\u2014]\\s*(\\d+))?\\s*$",
    "i"
  );

  let CANON = null;
  let INDEX = null;

  function setCanon(data) {
    CANON = data;
    INDEX = null;
  }

  function hasCanon() {
    return !!CANON;
  }

  function books() {
    return CANON ? CANON.books.slice() : BOOK_NAMES.slice();
  }

  function chapters(book) {
    const c = CANON && CANON.canon[book];
    return c ? Object.keys(c).map(Number).sort((a, b) => a - b) : [];
  }

  function verseNumbers(book, chapter) {
    const c = CANON && CANON.canon[book] && CANON.canon[book][String(chapter)];
    return c ? Object.keys(c).map(Number).sort((a, b) => a - b) : [];
  }

  function verseText(book, chapter, verse) {
    const c = CANON && CANON.canon[book] && CANON.canon[book][String(chapter)];
    return (c && c[String(verse)]) || "";
  }

  function formatReference(m) {
    let ref = m.book + " " + m.chapter;
    if (m.verseStart != null) ref += ":" + m.verseStart;
    if (m.verseEnd != null) ref += "-" + m.verseEnd;
    return ref;
  }

  /* ── spoken numbers ──────────────────────────────────────────────────────
   * A pastor says "Romans chapter eight, verse twenty eight", never "Romans
   * 8:28". Speech engines transcribe words, so the detector would see nothing
   * without this step. Only the matching copy is normalised; displayed text is
   * left exactly as it was heard.
   */

  const NUMBER_WORDS = {
    zero: 0, one: 1, two: 2, three: 3, four: 4, five: 5, six: 6, seven: 7,
    eight: 8, nine: 9, ten: 10, eleven: 11, twelve: 12, thirteen: 13,
    fourteen: 14, fifteen: 15, sixteen: 16, seventeen: 17, eighteen: 18,
    nineteen: 19, twenty: 20, thirty: 30, forty: 40, fifty: 50, sixty: 60,
    seventy: 70, eighty: 80, ninety: 90,
  };

  const ORDINAL_WORDS = { first: "1", second: "2", third: "3" };

  /**
   * Turn a run of number words into separate numbers, merging only where
   * English merges: "twenty eight" is 28, but "thirteen four" is 13 then 4
   * (chapter thirteen, verse four) — never 17.
   */
  function wordsToNumbers(words) {
    const out = [];
    let current = null;
    let last = null;

    for (const word of words) {
      if (word === "hundred") {
        current = (current == null ? 1 : current) * 100;
        last = 100;
        continue;
      }
      const value = NUMBER_WORDS[word];
      if (value == null) continue;
      if (current == null) {
        current = value;
        last = value;
        continue;
      }
      const merges = last === 100 || (last >= 20 && last % 10 === 0 && value < 10);
      if (merges) {
        current += value;
        last = value;
      } else {
        out.push(current);
        current = value;
        last = value;
      }
    }
    if (current != null) out.push(current);
    return out;
  }

  // "1 Corinthians 13 4" -> "1 Corinthians 13:4": speech rarely says "verse".
  const SPOKEN_PAIR = new RegExp(
    "\\b(" + escaped + ")\\s+(\\d{1,3})\\s+(\\d{1,3})(?!\\d)",
    "gi"
  );

  function normalizeSpoken(text) {
    if (!text) return "";

    // "first corinthians" -> "1 corinthians"; "third john" -> "3 john".
    // Speech engines also write "2nd Timothy" and "3rd John".
    const withOrdinals = String(text)
      .replace(/\b([123])(?:st|nd|rd)\b\.?/gi, "$1")
      .replace(/\b(first|second|third)\b/gi, (match) => {
        return ORDINAL_WORDS[match.toLowerCase()] || match;
      });

    // Join hyphenated number words ("twenty-eight") but never touch a numeric
    // range like 3:16-17.
    const tokens = withOrdinals.replace(/([a-z])[\u2013\u2014-]([a-z])/gi, "$1 $2").split(/\s+/);
    const out = [];
    let run = [];

    const flush = () => {
      if (!run.length) return;
      for (const value of wordsToNumbers(run)) out.push(String(value));
      run = [];
    };

    for (const token of tokens) {
      const word = token.toLowerCase().replace(/[^a-z]/g, "");
      if (NUMBER_WORDS[word] != null || word === "hundred") {
        run.push(word);
        continue;
      }
      if (word === "and" && run.length) {
        // "one hundred and twenty" — the conjunction is part of the number.
        continue;
      }
      flush();
      out.push(token);
    }
    flush();

    return out
      .filter(Boolean)
      .join(" ")
      .replace(SPOKEN_PAIR, (match, book, chapter, verse) => `${book} ${chapter}:${verse}`);
  }

  /**
   * Rescue a book name the recogniser spelled almost right.
   *
   * Accented speech is where small models produce "romas chapter 8" or
   * "revalation 21". Only a word that is followed by a number or "chapter" is
   * considered, and it must be one edit away from a real alias, so ordinary
   * sermon vocabulary is left untouched.
   */
  const FUZZY_WORDS = [...ALIAS.keys()].filter((a) => /^[a-z]+$/.test(a) && a.length >= 5);

  function editDistance(a, b, limit) {
    if (Math.abs(a.length - b.length) > limit) return limit + 1;
    let prev = Array.from({ length: b.length + 1 }, (_, i) => i);
    for (let i = 1; i <= a.length; i++) {
      const row = [i];
      for (let j = 1; j <= b.length; j++) {
        const cost = a[i - 1] === b[j - 1] ? 0 : 1;
        row[j] = Math.min(prev[j] + 1, row[j - 1] + 1, prev[j - 1] + cost);
      }
      prev = row;
    }
    return prev[b.length];
  }

  function rescueBooks(text) {
    const words = text.split(" ");
    for (let i = 0; i < words.length - 1; i++) {
      const raw = words[i].replace(/[^A-Za-z]/g, "");
      if (raw.length < 5 || ALIAS.has(raw.toLowerCase())) continue;
      const next = words[i + 1].replace(/[^A-Za-z0-9:]/g, "").toLowerCase();
      if (!/^\d/.test(next) && next !== "chapter" && next !== "ch") continue;

      const lower = raw.toLowerCase();
      let best = null;
      let bestDistance = 2;
      for (const alias of FUZZY_WORDS) {
        if (alias[0] !== lower[0]) continue;
        const distance = editDistance(lower, alias, 1);
        if (distance < bestDistance) {
          best = alias;
          bestDistance = distance;
        }
      }
      if (best) words[i] = words[i].replace(raw, best);
    }
    return words.join(" ");
  }

  /** Detect every spoken/typed reference in a string. */
  function detect(text, opts) {
    if (!text) return [];
    text = normalizeSpoken(text);
    if (!opts || opts.fuzzy !== false) text = rescueBooks(text);
    // Where the words actually end: a partial transcript is a snapshot, so a
    // reference sitting on the last word may still grow ("verse twenty" ->
    // "verse twenty eight", "Romans 8" -> "Romans 8:28").
    const tail = text.replace(/[\s.,!?;:]+$/, "").length;
    const seen = new Set();
    const out = [];
    REF_RE.lastIndex = 0;
    let m;
    while ((m = REF_RE.exec(text)) !== null) {
      const book = ALIAS.get(m[1].toLowerCase());
      if (!book) continue;
      const vm = {
        book,
        chapter: Number(m[2]),
        verseStart: m[3] != null ? Number(m[3]) : null,
        verseEnd: m[4] != null ? Number(m[4]) : m[5] != null ? Number(m[5]) : null,
        raw: m[0].trim(),
        start: m.index,
        end: m.index + m[0].length,
      };
      vm.reference = formatReference(vm);
      if (opts && opts.partial) {
        const trailing = vm.end >= tail;
        const last = vm.verseEnd != null ? vm.verseEnd : vm.verseStart;
        // A chapter on its own may still gain a verse; a round ten may still
        // gain its unit ("twenty" + "eight"). Anything else is complete.
        vm.open = trailing && (last == null || (last >= 20 && last % 10 === 0));
        vm.trailing = trailing;
      }
      if (opts && opts.dedupe) {
        if (seen.has(vm.reference)) continue;
        seen.add(vm.reference);
      }
      out.push(vm);
    }
    return out;
  }

  /**
   * Resolve a reference that names only the chapter or verse.
   *
   * Preachers say the book once ("turn to Deuteronomy") and then "chapter
   * thirty four, verse twenty". The page remembers the last book, so those
   * follow-ups land on the right slide. Callers must keep this to a short
   * utterance: a number in the middle of a sermon is not a reference.
   */
  function bareReference(text, book, chapter) {
    if (!text || !book) return null;
    const t = normalizeSpoken(text)
      .replace(/[.,!?;]+/g, " ")
      .replace(/\s+/g, " ")
      .trim();
    if (!/\b(chapter|chap|ch|verse|ver|vs)\b/i.test(t)) return null;

    const withChapter = /\b(?:chapter|chap|ch)\.?\s*(\d{1,3})(?:\s*(?:and|,)?\s*(?:verses?|ver\.?|vs\.?)\s*(\d{1,3}))?/i.exec(t);
    const onlyVerse = /\b(?:verses?|ver\.?|vs\.?)\s*(\d{1,3})/i.exec(t);
    if (!withChapter && !onlyVerse) return null;

    const ch = withChapter ? Number(withChapter[1]) : Number(chapter || 1);
    let verse = withChapter && withChapter[2] != null
      ? Number(withChapter[2])
      : onlyVerse
        ? Number(onlyVerse[1])
        : null;

    // A chapter on its own is only trusted when it is most of what was said.
    if (withChapter && verse == null) {
      const rest = t.replace(withChapter[0], " ").trim();
      if (rest.split(/\s+/).filter(Boolean).length > 3) return null;
    }

    const ref = { book, chapter: ch, verseStart: verse, verseEnd: null };
    ref.reference = formatReference(ref);
    return ref;
  }

  /** Parse a whole query as a reference, or return null. */
  function asReference(query) {
    // "2 tim 3 16" -> try the spaced alias first, then the glued one ("2tim").
    let q = normalizeSpoken(query || "");
    if (!REF_ANCHORED.test(q) && !SPOKEN_ANCHORED.test(q)) {
      const glued = q.replace(/^\s*([1-3])\s+/, "$1");
      if (glued !== q && (REF_ANCHORED.test(glued) || SPOKEN_ANCHORED.test(glued))) q = glued;
    }
    const spoken = SPOKEN_ANCHORED.exec(q);
    if (spoken) {
      const vm = {
        book: ALIAS.get(spoken[1].toLowerCase()),
        chapter: Number(spoken[2]),
        verseStart: Number(spoken[3]),
        verseEnd: spoken[4] != null ? Number(spoken[4]) : null,
      };
      vm.reference = formatReference(vm);
      return vm;
    }
    const m = REF_ANCHORED.exec(q);
    if (!m) {
      const bare = /^\s*([1-3]?\s?[a-z ]+?)\s*$/i.exec(q);
      if (bare) {
        const book = ALIAS.get(bare[1].toLowerCase().replace(/\s+/g, " ").trim());
        if (book) return { book, chapter: 1, verseStart: null, verseEnd: null, reference: book + " 1" };
      }
      return null;
    }
    const vm = {
      book: ALIAS.get(m[1].toLowerCase()),
      chapter: Number(m[2]),
      verseStart: m[3] != null ? Number(m[3]) : null,
      verseEnd: m[4] != null ? Number(m[4]) : m[5] != null ? Number(m[5]) : null,
    };
    vm.reference = formatReference(vm);
    return vm;
  }

  /** Clamp a reference to what the canon actually contains. */
  function clamp(ref) {
    if (!CANON || !ref) return ref;
    const book = CANON.canon[ref.book] ? ref.book : null;
    if (!book) return ref;
    const chs = chapters(book);
    if (!chs.length) return ref;
    const chapter = Math.min(Math.max(ref.chapter || 1, chs[0]), chs[chs.length - 1]);
    const vs = verseNumbers(book, chapter);
    let start = ref.verseStart;
    let end = ref.verseEnd;
    if (start != null && vs.length) {
      start = Math.min(Math.max(start, vs[0]), vs[vs.length - 1]);
      if (end != null) end = Math.min(Math.max(end, start), vs[vs.length - 1]);
    }
    const out = { book, chapter, verseStart: start, verseEnd: end };
    out.reference = formatReference(out);
    return out;
  }

  const STOPWORDS = new Set(
    ("a an the and or but if then than that this these those of to in on at by for with from as is are was were be been being am " +
      "i you he she it we they me him her us them my your his its our their mine thine thee thou thy ye " +
      "shall shalt will would should could can may might must do does did done have has had having " +
      "not no nor neither so yet also even very own same such too only just now here there when while because " +
      "who whom which what why how all any both each few more most other some up down out over under again " +
      "unto upon into through about after before against between during above below off once "
    ).split(/\s+/)
  );

  function tokenize(text) {
    const raw = String(text).toLowerCase().match(/[a-z']+/g) || [];
    const out = [];
    for (const t of raw) {
      const w = t.replace(/^'+|'+$/g, "");
      if (w.length < 3 || STOPWORDS.has(w)) continue;
      out.push(w);
    }
    return out;
  }

  /** Build the TF-IDF index over every verse. Runs once, lazily. */
  function ensureIndex() {
    if (INDEX || !CANON) return INDEX;
    const docs = []; // {book, chapter, verse, text, norm}
    const df = new Map();
    const postings = new Map(); // term -> [docIdx, tf, ...]

    for (const book of CANON.books) {
      const chaptersObj = CANON.canon[book];
      for (const chKey of Object.keys(chaptersObj)) {
        const versesObj = chaptersObj[chKey];
        for (const vKey of Object.keys(versesObj)) {
          const text = versesObj[vKey];
          const tf = new Map();
          for (const tok of tokenize(text)) tf.set(tok, (tf.get(tok) || 0) + 1);
          const idx = docs.length;
          docs.push({ book, chapter: Number(chKey), verse: Number(vKey), text, norm: 0 });
          for (const [tok, n] of tf) {
            df.set(tok, (df.get(tok) || 0) + 1);
            let arr = postings.get(tok);
            if (!arr) postings.set(tok, (arr = []));
            arr.push(idx, n);
          }
        }
      }
    }

    const N = docs.length;
    const idf = new Map();
    for (const [tok, n] of df) idf.set(tok, Math.log(N / n));

    // Document norms use the same (1 + log tf) * idf weights as the query side.
    for (const [tok, arr] of postings) {
      const w = idf.get(tok);
      for (let i = 0; i < arr.length; i += 2) {
        const idx = arr[i];
        const tf = arr[i + 1];
        const weight = (1 + Math.log(tf)) * w;
        docs[idx].norm += weight * weight;
      }
    }
    for (const d of docs) d.norm = Math.sqrt(d.norm) || 1;

    INDEX = { docs, postings, idf, N };
    return INDEX;
  }

  /**
   * Drop the keyword index. It is the single largest allocation in the page
   * (every verse tokenised into postings), so the memory watchdog releases it
   * under pressure; the next phrase search simply rebuilds it.
   */
  function releaseIndex() {
    INDEX = null;
  }

  /** Keyword search: TF-IDF cosine over all 31,102 verses. */
  function search(query, limit) {
    const idx = ensureIndex();
    if (!idx) return [];
    const terms = tokenize(query);
    if (!terms.length) return [];

    const qtf = new Map();
    for (const t of terms) qtf.set(t, (qtf.get(t) || 0) + 1);

    const scores = new Map();
    let qnorm = 0;
    for (const [term, tf] of qtf) {
      const idf = idx.idf.get(term);
      if (!idf) continue;
      const w = (1 + Math.log(tf)) * idf;
      qnorm += w * w;
      const arr = idx.postings.get(term);
      if (!arr) continue;
      for (let i = 0; i < arr.length; i += 2) {
        const docIdx = arr[i];
        scores.set(docIdx, (scores.get(docIdx) || 0) + w * (1 + Math.log(arr[i + 1])) * idf);
      }
    }
    qnorm = Math.sqrt(qnorm) || 1;

    // Exact-quote bonus: a verse that literally contains what was typed should
    // outrank one that merely shares vocabulary, which is what people expect
    // when they paste a line of scripture into the search field.
    const phrase = terms.length > 2 ? terms.join(" ") : "";

    const ranked = [...scores.entries()]
      .map(([docIdx, dot]) => {
        const doc = idx.docs[docIdx];
        let score = dot / (qnorm * doc.norm);
        if (phrase && doc.text.toLowerCase().replace(/[^a-z' ]+/g, " ").replace(/\s+/g, " ").includes(phrase)) {
          score *= 1.6;
        }
        return { doc, score };
      })
      .sort((a, b) => b.score - a.score)
      .slice(0, limit || 40);

    return ranked.map((r) => ({
      book: r.doc.book,
      chapter: r.doc.chapter,
      verse: r.doc.verse,
      text: r.doc.text,
      score: r.score,
      reference: r.doc.book + " " + r.doc.chapter + ":" + r.doc.verse,
    }));
  }

  /** Unified query entry point used by the search field. */
  function query(q) {
    const ref = asReference(q);
    if (ref) return { type: "reference", reference: clamp(ref) };
    const results = search(q, 40);
    return { type: results.length ? "keyword" : "empty", results };
  }

  return {
    BOOKS,
    BOOK_NAMES,
    setCanon,
    hasCanon,
    books,
    chapters,
    verseNumbers,
    verseText,
    detect,
    bareReference,
    normalizeSpoken,
    asReference,
    clamp,
    formatReference,
    tokenize,
    search,
    query,
    ensureIndex,
    releaseIndex,
    indexBuilt: () => !!INDEX,
  };
});
