/* Node test for engine.js: detector cases from the VerseListener analysis,
 * reference parsing, clamping, and TF-IDF keyword search.  Run: node tools/test_engine.js
 */
const fs = require("fs");
const path = require("path");
const vm = require("vm");

const root = path.resolve(__dirname, "..");
const sandbox = { window: {} };
vm.createContext(sandbox);
vm.runInContext(fs.readFileSync(path.join(root, "assets/js/data.js"), "utf8"), sandbox);
const Engine = require(path.join(root, "assets/js/engine.js"));
Engine.setCanon(sandbox.window.CANON_DATA);

let failures = 0;
function eq(label, actual, expected) {
  const a = JSON.stringify(actual);
  const e = JSON.stringify(expected);
  const ok = a === e;
  if (!ok) failures++;
  console.log(`${ok ? "PASS" : "FAIL"}  ${label}${ok ? "" : `\n      got ${a}\n      want ${e}`}`);
}

console.log("— detector (VerseListener parity)");
const detectCases = [
  ["let's go to Genesis 5 verse 2", ["Genesis 5:2"]],
  ["Romans 8:28 through 30", ["Romans 8:28-30"]],
  ["first Corinthians 13", ["1 Corinthians 13"]],
  ["Psalm 23", ["Psalms 23"]],
  ["and John 3:16-17", ["John 3:16-17"]],
  ["turn with me to 1 Thessalonians 4:16", ["1 Thessalonians 4:16"]],
  ["i samuel 17:45", ["1 Samuel 17:45"]],
  ["read the book of Hebrews chapter 11 verse 1", ["Hebrews 11:1"]],
  ["Genesis 1:1 and later Romans 8:28", ["Genesis 1:1", "Romans 8:28"]],
  ["John Cena 5", []],
  ["nothing to see here", []],
  ["Song of Solomon 2:1", ["Song of Solomon 2:1"]],
  ["ps 119:105", ["Psalms 119:105"]],
  // Accented-speech spellings and ordinals a recogniser writes.
  ["2nd Timothy 3:16", ["2 Timothy 3:16"]],
  ["romas chapter 8 verse 28", ["Romans 8:28"]],
  ["revalation 21 verse 4", ["Revelation 21:4"]],
  ["deuteronomi chapter thirty four verse twenty", ["Deuteronomy 34:20"]],
  ["First Corinthians 13:4 and 2 Timothy 3:16", ["1 Corinthians 13:4", "2 Timothy 3:16"]],
];
for (const [text, want] of detectCases) {
  eq(text, Engine.detect(text).map((m) => m.reference), want);
}

console.log("\n— dedupe");
eq(
  "same reference twice",
  Engine.detect("John 3:16 ... and again John 3:16", { dedupe: true }).map((m) => m.reference),
  ["John 3:16"]
);

console.log("\n— streaming partials");
const open = (text) =>
  Engine.detect(text, { partial: true }).map((m) => m.reference + (m.open ? " (open)" : ""));
// A partial is a snapshot: the next word can still extend a reference.
eq("chapter on the last word is unfinished", open("turn with me to romans chapter eight"), ["Romans 8 (open)"]);
eq("tens on the last word is unfinished", open("romans chapter eight verse twenty"), ["Romans 8:20 (open)"]);
eq("a finished verse is safe", open("romans chapter eight verse twenty eight"), ["Romans 8:28"]);
eq("anything after the reference makes it safe", open("romans chapter eight verse twenty eight. let us read"), ["Romans 8:28"]);
eq("a number that cannot grow is safe", open("john three verse sixteen"), ["John 3:16"]);

console.log("\n— bare chapter/verse (book said earlier)");
const bare = (text, book, chapter) => {
  const ref = Engine.bareReference(text, book, chapter);
  return ref && ref.reference;
};
eq("chapter 34 verse 20", bare("now chapter thirty four, verse twenty", "Deuteronomy", 1), "Deuteronomy 34:20");
eq("bare verse keeps the chapter", bare("read verse twenty three", "Romans", 8), "Romans 8:23");
eq("a long sermon sentence is not a reference",
  bare("in this chapter 3 we learn that the church grew and many people believed the message", "Acts", 2), null);
eq("nothing without chapter/verse", bare("we have 3 points today", "Romans", 8), null);

console.log("\n— reference parsing / clamping");
eq("asReference('john 3:16')", Engine.asReference("john 3:16").reference, "John 3:16");
eq("asReference('2 tim 3 16')", Engine.asReference("2 tim 3 16").reference, "2 Timothy 3:16");
eq("asReference('genesis') chapter", Engine.asReference("genesis").chapter, 1);
eq("asReference('hello world')", Engine.asReference("hello world"), null);
eq("clamp John 3:999", Engine.clamp(Engine.asReference("John 3:999")).reference, "John 3:36");
eq("clamp Psalm 200", Engine.clamp(Engine.asReference("Psalm 200")).reference, "Psalms 150");

console.log("\n— canon");
eq("books", Engine.books().length, 66);
eq("Genesis 1 verse count", Engine.verseNumbers("Genesis", 1).length, 31);
eq("Genesis 1:1", Engine.verseText("Genesis", 1, 1), "In the beginning God created the heaven and the earth.");
eq("Psalms 117 verses", Engine.verseNumbers("Psalms", 117).length, 2);

console.log("\n— keyword search");
const t0 = Date.now();
Engine.ensureIndex();
console.log(`  index built in ${Date.now() - t0} ms`);

// KJV John 3:15 and 3:16 share the same clause, so either may win on length
// normalisation; the quote must still surface John 3:16 in the top 3.
const s1 = Engine.search("whosoever believeth in him should not perish", 5);
eq("quote surfaces John 3:16", s1.slice(0, 3).map((r) => r.reference).includes("John 3:16"), true);
console.log("   top5:", s1.map((r) => `${r.reference} ${r.score.toFixed(3)}`).join(" | "));

const s2 = Engine.search("the Lord is my shepherd", 3);
eq("Psalm 23:1 ranks first", s2[0].reference, "Psalms 23:1");
console.log("   top3:", s2.map((r) => `${r.reference} ${r.score.toFixed(3)}`).join(" | "));

const s3 = Engine.search("in the beginning was the word", 3);
eq("John 1:1 ranks first", s3[0].reference, "John 1:1");
console.log("   top3:", s3.map((r) => `${r.reference} ${r.score.toFixed(3)}`).join(" | "));

eq("query('genesis 1:1') type", Engine.query("genesis 1:1").type, "reference");
eq("query('zzzz qqqq')", Engine.query("zzzz qqqq").type, "empty");

console.log(failures ? `\n${failures} FAILURE(S)` : "\nALL PASS");
process.exit(failures ? 1 : 0);
