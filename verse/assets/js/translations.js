/* Verse — the translations this build ships with.
 *
 * `file` is the script that registers the text under window.VERSE_CANONS[id];
 * it is only fetched when someone picks that translation, so opening the app
 * costs the KJV alone. `kjv` has no file because its text is the one index.html
 * loads as window.CANON_DATA.
 *
 * Every entry must match a notice in BIBLES.md. Do not add a licensed Bible
 * (NIV, NKJV, ESV, NASB…) here: those have to be imported from the owner's own
 * copy with tools/build_translation.py --json, into a build kept for their use.
 */
window.VERSE_TRANSLATIONS = [
  {
    id: "kjv",
    short: "KJV",
    title: "King James Version",
    language: "English",
    licence: "Public domain",
    file: null,
    verses: 31102,
    notice: "The King James Version (1611), public domain. Text via farskipper/kjv.",
  },
  {
    id: "web",
    short: "WEB",
    title: "World English Bible",
    language: "English",
    licence: "Public domain",
    file: "assets/js/data.web.js",
    verses: 31098,
    notice: "The World English Bible (WEB), public domain, from eBible.org (engwebp).",
  },
  {
    id: "yor",
    short: "YOR",
    title: "Biblica Open Yoruba Contemporary Bible",
    language: "Yorùbá",
    licence: "CC BY-SA 4.0",
    file: "assets/js/data.yor.js",
    verses: 31087,
    notice:
      "Biblica® ní oore ọ̀fẹ́ láti lo Bíbélì Mímọ́ ní Èdè Yorùbá Òde-Òní™ — " +
      "Copyright © 2009, 2017 Biblica, Inc. This work is made available under the " +
      "Creative Commons Attribution-ShareAlike 4.0 International License (CC BY-SA 4.0). " +
      "The original work by Biblica, Inc. is available for free at www.biblica.com and open.bible. " +
      "Distributed here unmodified.",
  },
  {
    id: "ibo",
    short: "IGB",
    title: "Biblica Open Igbo Contemporary Bible",
    language: "Igbo",
    licence: "CC BY-SA 4.0",
    file: "assets/js/data.ibo.js",
    verses: 31103,
    notice:
      "Biblica® Baịbụlụ Nsọ nʼIgbo Ndị Ugbu a nke dịrị onye ọbụla ịgụ™ — " +
      "Copyright © 1980, 1988, 2019, 2020 Biblica, Inc. This work is made available " +
      "under the Creative Commons Attribution-ShareAlike 4.0 International License " +
      "(CC BY-SA 4.0). The original work by Biblica, Inc. is available for free at " +
      "www.biblica.com and open.bible. Distributed here unmodified.",
  },
];
