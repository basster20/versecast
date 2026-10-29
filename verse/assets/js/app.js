/* Verse — application logic. */
(function () {
  "use strict";

  const E = window.Engine;
  E.setCanon(window.CANON_DATA);

  // Bundled Bibles. Each non-KJV text is a separate script loaded the first
  // time it is chosen, so the app still opens on one file (see translations.js).
  const TRANSLATIONS = window.VERSE_TRANSLATIONS || [
    { id: "kjv", short: "KJV", title: "King James Version", language: "English", licence: "Public domain", file: null },
  ];
  const translationFor = (id) =>
    TRANSLATIONS.find((t) => t.id === id) || TRANSLATIONS.find((t) => t.id === "kjv") || TRANSLATIONS[0];
  const translationShort = () => translationFor(state.settings.translation).short || "KJV";

  // What people call each Bible out loud. The recogniser writes plain English,
  // so "change the Bible to Yoruba" arrives as those exact words.
  const VERSION_WORDS = {
    kjv: ["kjv", "king james", "king james version", "authorised", "authorized", "authorised version", "authorized version"],
    web: ["web", "world english", "world english bible"],
    yor: ["yor", "yoruba", "yoruba contemporary"],
    ibo: ["ibo", "igbo", "igbo contemporary"],
  };

  function translationFromSpeech(name) {
    const clean = (s) =>
      String(s || "")
        .toLowerCase()
        .normalize("NFD")
        .replace(/[\u0300-\u036f]/g, "")
        .replace(/[^a-z0-9 ]+/g, " ")
        .replace(/\s+/g, " ")
        .trim();
    const q = clean(name)
      .replace(/\b(the|bible|version|translation|holy|scriptures)\b/g, " ")
      .replace(/\s+/g, " ")
      .trim();
    if (!q) return null;
    for (const t of TRANSLATIONS) {
      const title = clean(t.title);
      if (q === t.id || q === clean(t.short) || q === title || title.includes(q)) return t;
    }
    for (const [id, words] of Object.entries(VERSION_WORDS)) {
      if (words.some((w) => q === w || q.includes(w))) return translationFor(id);
    }
    return null;
  }

  const PENDING = {};
  function loadTranslation(id) {
    if (id === "kjv") return Promise.resolve(window.CANON_DATA);
    const store = window.VERSE_CANONS || {};
    if (store[id]) return Promise.resolve(store[id]);
    if (PENDING[id]) return PENDING[id];

    const meta = TRANSLATIONS.find((t) => t.id === id);
    if (!meta || !meta.file) return Promise.reject(new Error("That translation has no text file"));
    PENDING[id] = new Promise((resolve, reject) => {
      const tag = document.createElement("script");
      // Same version tag as the page: a rebuilt translation is fetched fresh,
      // an unchanged one comes from the window's cache.
      const buildTag = new URLSearchParams(location.search).get("v") || "0";
      tag.src = `${meta.file}?v=${buildTag}`;
      tag.onload = () => {
        const canon = (window.VERSE_CANONS || {})[id];
        if (canon) resolve(canon);
        else reject(new Error(`${meta.short} loaded but carried no text`));
      };
      tag.onerror = () => reject(new Error(`Could not load ${meta.short}`));
      document.head.appendChild(tag);
    });
    return PENDING[id];
  }

  function normaliseTranslation() {
    const id = String(state.settings.translation || "").toLowerCase();
    state.settings.translation = TRANSLATIONS.some((t) => t.id === id) ? id : TRANSLATIONS[0].id;
  }

  function syncTranslationSelect() {
    const select = $("#translationSelect");
    if (!select) return;
    select.innerHTML = TRANSLATIONS.map(
      (t) =>
        `<option value="${esc(t.id)}" title="${esc(t.title)}"${t.id === state.settings.translation ? " selected" : ""}>${esc(t.short)}</option>`
    ).join("");
  }

  // Switching swaps the canon under the engine, then re-clamps everything that
  // was pointing at a verse: Yoruba has no Psalm 151, the WEB splits a few
  // verses the KJV keeps together, and the operator should never see a blank
  // slide because of that.
  function selectTranslation(id, opts) {
    opts = opts || {};
    const meta = translationFor(id);
    const select = $("#translationSelect");
    if (select) select.disabled = true;

    return loadTranslation(meta.id)
      .then((canon) => {
        E.setCanon(canon);
        state.settings.translation = meta.id;
        state.results = null;
        state.resultsQuery = "";
        if (state.selection) state.selection = E.clamp(state.selection);
        if (state.preview) state.preview = E.clamp(state.preview);
        const wasOnAir = !!state.onAir;
        if (state.onAir) state.onAir = E.clamp(state.onAir);
        save();
        renderAll();
        renderPreview();
        renderOutput();
        if (wasOnAir) syncOutput();
        if (state.sheet) renderSheet();
        if (!opts.quiet) toast(`${meta.short} — ${meta.title}`);
        return meta;
      })
      .catch((err) => {
        delete PENDING[meta.id];
        toast((err && err.message) || "Could not load that translation");
        return null;
      })
      .finally(() => {
        if (select) select.disabled = false;
        syncTranslationSelect();
      });
  }

  const $ = (sel, root) => (root || document).querySelector(sel);
  const $$ = (sel, root) => Array.from((root || document).querySelectorAll(sel));
  const esc = (s) =>
    String(s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

  const PRESETS = [
    { id: "selah", name: "Selah", bg: "#002fc6", fg: "#f0f4f9", size: 42, weight: 700, gap: 48, shadow: true, numbers: true, case: "none" },
    { id: "forest", name: "Forest", bg: "#154e3b", fg: "#eaf4ec", size: 40, weight: 700, gap: 40, shadow: true, numbers: true, case: "none" },
    { id: "ember", name: "Ember", bg: "linear-gradient(160deg,#cda76f 0%,#a8753c 55%,#5a2a12 100%)", fg: "#fff6e8", size: 40, weight: 700, gap: 44, shadow: true, numbers: true, case: "none" },
    { id: "charcoal", name: "Charcoal", bg: "#161414", fg: "#ffffff", size: 40, weight: 600, gap: 36, shadow: false, numbers: true, case: "none" },
    { id: "paper", name: "Paper", bg: "#f3efe6", fg: "#1b1a18", size: 40, weight: 700, gap: 40, shadow: false, numbers: true, case: "uppercase" },
  ];

  const DEFAULTS = {
    theme: Object.assign({}, PRESETS[0]),
    settings: {
      displayMode: "auto",
      translation: "kjv",
      refFormat: "full",
      sttEngine: "local",
      localEngine: "whisper",
      voiceCommands: true,
      micDevice: -1,
      // Two pipelines: tiny.en answers while the sentence is still being
      // spoken, base.en replaces it with the accurate reading. Off until the
      // fast model is installed, and switchable off at any time.
      instantPipeline: true,
      // Find verses that are never named out loud — the semantic tier. Named
      // references are handled in the page and never wait for this.
      detectNamed: true,
      detectStrictness: "balanced",
      releaseWhenIdle: true,
      autoLive: false,
      outputMode: "window",
      ndiName: "Verse",
      display: 0,
    },
  };

  const state = {
    book: "Genesis",
    chapter: 1,
    selection: { book: "Genesis", chapter: 1, verseStart: 1, verseEnd: null, reference: "Genesis 1:1" },
    preview: { book: "Genesis", chapter: 1, verseStart: 1, verseEnd: null, reference: "Genesis 1:1" },
    onAir: null,
    black: false,
    live: false,
    queue: [],
    recent: [],
    results: null,
    resultsQuery: "",
    theme: Object.assign({}, DEFAULTS.theme),
    settings: Object.assign({}, DEFAULTS.settings),
    view: "scriptures",
    sheet: null,
    stt: { running: false, heard: "", final: false, status: "idle", note: "", level: 0 },
    model: { ready: false, mb: 0, downloading: false, progress: 0, name: "Whisper base.en", expected: 145 },
    instant: { ready: false, mb: 0, name: "Whisper tiny.en", expected: 78, active: false },
    detect: null,
    detectProgress: null,
    indexProgress: null,
    warm: null,
    perf: null,
    memory: null,
    ndi: null,
    devices: [],
    displays: [],
  };

  // Speech state lives above the rendering functions: jumpTo() records the book
  // for a later bare "verse 23", and it can run before the listening section.
  const STT = {
    wanted: false,
    browser: null,
    restartTimer: null,
    lastReference: "",
    lastReferenceAt: 0,
    // The last book heard, so "chapter 34 verse 20" a moment later still lands
    // in the right place. Cleared by nothing but time.
    lastBook: "",
    lastChapter: 1,
    lastBookAt: 0,
    lastCommand: "",
    lastCommandAt: 0,
    // The host-side ladder: the last sentence sent to it, and when, so the same
    // utterance is not searched twice while it is still arriving.
    asked: "",
    askedAt: 0,
    asking: false,
    // When the last final transcript arrived, for the end-to-end figure.
    finalAt: 0,
  };

  /* How sure the ladder has to be before it touches the screen itself.
   * The tiers report calibrated confidence, not a raw score: a repeated
   * quotation lands near 1.0, an honest paraphrase around 0.5, and a sentence
   * that merely shares vocabulary is rejected before it reaches this filter. */
  const STRICTNESS = { strict: 0.62, balanced: 0.4, eager: 0.24 };

  /* ─────────── persistence ─────────── */

  function save() {
    try {
      localStorage.setItem(
        "verse.prefs",
        JSON.stringify({ theme: state.theme, settings: state.settings })
      );
    } catch (e) { /* private mode */ }
  }

  function load() {
    try {
      const raw = localStorage.getItem("verse.prefs");
      if (!raw) return;
      const data = JSON.parse(raw);
      if (data.theme) state.theme = Object.assign({}, DEFAULTS.theme, data.theme);
      if (data.settings) state.settings = Object.assign({}, DEFAULTS.settings, data.settings);
    } catch (e) { /* ignore */ }
  }

  /* ─────────── references ─────────── */

  function makeRef(book, chapter, verseStart, verseEnd) {
    const ref = { book, chapter, verseStart, verseEnd: verseEnd == null ? null : verseEnd };
    ref.reference = E.formatReference(ref);
    return ref;
  }

  function verseRange(ref) {
    if (ref.verseStart == null) return E.verseNumbers(ref.book, ref.chapter);
    const end = ref.verseEnd == null ? ref.verseStart : ref.verseEnd;
    const out = [];
    for (let v = ref.verseStart; v <= end; v++) out.push(v);
    return out;
  }

  // The KJV source marks paragraph breaks with a leading "# "; strip it.
  function clean(text) {
    return String(text || "").replace(/^\s*#\s*/, "").trim();
  }

  function refPlain(ref) {
    return verseRange(ref)
      .map((v) => clean(E.verseText(ref.book, ref.chapter, v)))
      .filter(Boolean)
      .join(" ");
  }

  function refHTML(ref) {
    const verses = verseRange(ref);
    const nums = state.theme.numbers;
    return verses
      .map((v) => (nums ? `<sup>${v}</sup>` : "") + esc(clean(E.verseText(ref.book, ref.chapter, v))))
      .join(" ");
  }

  function refLabel(ref) {
    return E.formatReference(ref);
  }

  function slideHTML(ref, preset) {
    if (!ref) return "";
    const t = preset || state.theme;
    const style = [
      `--slide-bg:${t.bg}`,
      `--slide-fg:${t.fg}`,
      `--verse-size:${t.size}`,
      `--verse-weight:${t.weight}`,
      `--ref-gap:${t.gap}`,
      `--ref-case:${t.case || "none"}`,
      `--verse-shadow:${t.shadow ? "0 2px 18px rgba(0,0,0,.45)" : "none"}`,
    ].join(";");
    const label =
      state.settings.refFormat === "short"
        ? refLabel(ref)
        : `${refLabel(ref)} (${translationShort()})`;
    return (
      `<div class="slide" style="${style}">` +
      `<div class="slide-verse">${refHTML(ref)}</div>` +
      `<div class="slide-ref">${esc(label)}</div>` +
      `</div>`
    );
  }

  /* ─────────── actions ─────────── */

  function pushRecent(ref) {
    state.recent = [
      { ref, at: Date.now() },
      ...state.recent.filter((r) => r.ref.reference !== ref.reference),
    ].slice(0, 12);
    renderRecent();
  }

  function goLive(ref) {
    if (!ref) return;
    state.onAir = ref;
    state.black = false;
    state.live = true;
    $("#liveBtn").classList.add("is-on");
    pushRecent(ref);
    addToQueue(ref);
    renderDisplay();
    renderOutput();
    renderQueue();
    syncOutput();
  }

  function stage(ref, opts) {
    state.preview = ref;
    renderPreview();
    renderCanvas();
    if (opts && opts.silent) return;
    if (state.live && !state.black && state.settings.displayMode === "auto") goLive(ref);
  }

  function addToQueue(ref) {
    if (!state.queue.some((r) => r.reference === ref.reference)) {
      state.queue.push(ref);
      renderQueue();
    }
  }

  function clearQueue() {
    state.queue = [];
    renderQueue();
  }

  function blackout() {
    state.black = true;
    state.onAir = null;
    renderDisplay();
    renderOutput();
    syncOutput();
  }

  function clearOutput() {
    state.onAir = null;
    state.black = false;
    renderDisplay();
    renderOutput();
    syncOutput();
  }

  function jumpTo(ref) {
    ref = E.clamp(ref);
    state.book = ref.book;
    state.chapter = ref.chapter;
    // A manually opened chapter is also "the book we are in", so a later bare
    // "verse 23" spoken at the microphone follows it.
    if (ref.book) {
      STT.lastBook = ref.book;
      STT.lastChapter = ref.chapter;
      STT.lastBookAt = Date.now();
    }
    state.results = null;
    state.resultsQuery = "";
    if (ref.verseStart != null) {
      state.selection = ref;
      state.preview = ref;
    } else {
      state.selection = null;
    }
    if (document.activeElement !== input) input.value = ref.verseStart != null ? ref.reference : `${ref.book} ${ref.chapter}`;
    renderChapter();
    renderList();
    renderPreview();
    renderCanvas();
    revealSelection();
  }

  function revealSelection() {
    const row = $("#verseList .verse-row.on");
    if (row) row.scrollIntoView({ block: "nearest" });
  }

  function selectVerse(verse) {
    const ref = makeRef(state.book, state.chapter, verse, null);
    state.selection = ref;
    stage(ref);
    renderList();
    revealSelection();
  }

  /* ─────────── render: live display ─────────── */

  function renderDisplay() {
    const panel = $("#displayPanel");
    const body = $("#displayBody");
    if (!state.onAir || state.black) {
      panel.classList.remove("onair");
      body.innerHTML =
        `<div class="empty">` +
        `<svg width="34" height="34" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.4" stroke-linecap="round" stroke-linejoin="round"><rect x="2.5" y="4" width="19" height="13" rx="2"/><path d="M8.5 21h7M12 17.5V21"/></svg>` +
        `<p>${state.black ? "Output is black" : "Nothing on screen"}</p>` +
        `<p>Select a verse and press <kbd>Enter</kbd> to send it to the output.</p>` +
        `</div>`;
      return;
    }
    panel.classList.add("onair");
    const label = state.settings.refFormat === "short" ? refLabel(state.onAir) : `${refLabel(state.onAir)} (${translationShort()})`;
    body.innerHTML =
      `<div class="onair-card">` +
      `<div class="onair-ref">${esc(label)}</div>` +
      `<div class="onair-text">${esc(refPlain(state.onAir))}</div>` +
      `</div>`;
  }

  /* ─────────── render: output thumb + preview ─────────── */

  function renderOutput() {
    const thumb = $("#outputThumb");
    $("#outputTranslation").textContent = translationShort();
    if (state.onAir && !state.black) {
      thumb.innerHTML = slideHTML(state.onAir);
    } else {
      thumb.innerHTML = "";
    }
  }

  function renderPreview() {
    const wrap = $("#previewWrap");
    if (!state.preview) {
      wrap.innerHTML = `<div class="empty"><p>Nothing to preview</p></div>`;
      return;
    }
    wrap.innerHTML = `<div class="preview-frame">${slideHTML(state.preview)}</div>`;
    fitPreview();
  }

  // A 16:9 box sized by width is taller than the panel on a short window, and
  // the overflow used to cover the panel heading. Scale it down to fit instead
  // of cropping the verse.
  function fitPreview() {
    const wrap = $("#previewWrap");
    const frame = wrap && wrap.querySelector(".preview-frame");
    if (!frame) return;
    frame.style.transform = "";
    const box = frame.getBoundingClientRect();
    const room = wrap.clientHeight - 18;
    if (!box.height || box.height <= room) return;
    const scale = Math.max(0.2, room / box.height);
    frame.style.transform = `scale(${scale.toFixed(4)})`;
  }

  addEventListener("resize", fitPreview);

  function renderCanvas() {
    const canvas = $("#themeCanvas");
    if (!canvas) return;
    canvas.innerHTML = slideHTML(state.preview || makeRef("Genesis", 1, 1, null));
  }

  /* ─────────── render: queue ─────────── */

  function renderQueue() {
    const list = $("#queueList");
    if (!state.queue.length) {
      list.innerHTML = `<div class="empty"><p>Queue is empty</p><p>Detected or searched verses collect here.</p></div>`;
      return;
    }
    list.innerHTML = state.queue
      .map((ref, i) => {
        const on = state.onAir && state.onAir.reference === ref.reference && !state.black;
        const sub = refPlain(ref).slice(0, 70);
        return (
          `<div class="queue-item${on ? " on" : ""}">` +
          `<div class="queue-main" data-qselect="${i}">` +
          `<div class="queue-ref">${esc(ref.reference)}</div>` +
          `<div class="queue-sub">${esc(sub)}${sub.length >= 70 ? "…" : ""}</div>` +
          `</div>` +
          `<button class="queue-go" data-qgo="${i}">Go</button>` +
          `</div>`
        );
      })
      .join("");
  }

  /* ─────────── render: recent ─────────── */

  function when(ts) {
    const s = Math.round((Date.now() - ts) / 1000);
    if (s < 60) return "just now";
    const m = Math.round(s / 60);
    if (m < 60) return m + " min";
    return Math.round(m / 60) + " hr";
  }

  function renderRecent() {
    const list = $("#recentList");
    if (!state.recent.length) {
      list.innerHTML = `<div class="empty"><p>No references yet</p><p>Verses you send live appear here.</p></div>`;
      return;
    }
    list.innerHTML = state.recent
      .map(
        (r, i) =>
          `<button class="recent-row" data-recent="${i}">` +
          `<span class="recent-ref">${esc(r.ref.reference)}</span>` +
          `<span class="recent-when">${when(r.at)}</span>` +
          `</button>`
      )
      .join("");
  }

  /* ─────────── render: chapter + list ─────────── */

  function renderChapter() {
    const head = $("#chapterHead");
    head.innerHTML =
      `<button class="chapter-open" id="chapterJump" title="Choose a chapter of ${esc(state.book)}">` +
      `<span>${esc(state.book)} ${state.chapter}</span>` +
      `<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round"><path d="m6 9 6 6 6-6"/></svg>` +
      `</button>` +
      `<span class="count">${E.verseNumbers(state.book, state.chapter).length} verses</span>` +
      `<span class="spacer"></span>` +
      `<button class="ghost-link" id="bookJump" title="Choose any book">All books</button>`;
    $("#chapterJump").onclick = () => openChapters();
    $("#bookJump").onclick = () => openBooks();
  }

  function highlight(text, terms) {
    let html = esc(text);
    if (!terms || !terms.length) return html;
    const pattern = terms
      .map((t) => t.replace(/[.*+?^${}()|[\]\\]/g, "\\$&"))
      .join("|");
    if (!pattern) return html;
    return html.replace(new RegExp(`\\b(${pattern})[a-z]*\\b`, "gi"), "<mark>$&</mark>");
  }

  function renderList() {
    const list = $("#verseList");
    if (state.results) {
      if (!state.results.length) {
        list.innerHTML = `<div class="empty"><p>No verses match “${esc(state.resultsQuery)}”</p></div>`;
        $("#chapterHead").innerHTML = `<span>Search</span>`;
        return;
      }
      const terms = E.tokenize(state.resultsQuery);
      $("#chapterHead").innerHTML =
        `<span>Results</span><span class="count">${state.results.length} verses for “${esc(state.resultsQuery)}”</span>`;
      list.innerHTML = state.results
        .map(
          (r, i) =>
            `<button class="verse-row" data-result="${i}">` +
            `<span class="verse-num">${r.verse}</span>` +
            `<span class="verse-text">${highlight(clean(r.text), terms)}</span>` +
            `</button>`
        )
        .join("");
      return;
    }

    const verses = E.verseNumbers(state.book, state.chapter);
    list.innerHTML = verses
      .map((v) => {
        const on = state.selection && state.selection.book === state.book && state.selection.chapter === state.chapter && state.selection.verseStart === v && state.selection.verseEnd == null;
        return (
          `<button class="verse-row${on ? " on" : ""}" data-verse="${v}">` +
          `<span class="verse-num">${v}</span>` +
          `<span class="verse-text">${esc(clean(E.verseText(state.book, state.chapter, v)))}</span>` +
          `</button>`
        );
      })
      .join("");
  }

  /* ─────────── output window ─────────── */

  let outWin = null;

  // The desktop host injects window.pywebview shortly after first paint.
  function nativeBridge() {
    return (window.pywebview && window.pywebview.api) || null;
  }

  function openOutput() {
    // Inside the desktop app the projection is a real window owned by the host
    // process, so it cannot be blocked and never lands in a browser tab.
    const bridge = nativeBridge();
    if (bridge && bridge.open_output) {
      bridge.open_output();
      setTimeout(syncOutput, 250);
      return;
    }

    outWin = window.open("output.html", "verse-output", "width=1280,height=720");
    if (!outWin) {
      toast("Pop-up blocked — open output.html in a second window; it syncs automatically");
      return;
    }
    outWin.focus();
    setTimeout(syncOutput, 250);
  }

  function syncOutput() {
    const blank = !state.onAir || state.black;
    const payload = blank ? { black: true } : { html: slideHTML(state.onAir) };
    // Mirror through localStorage as well: a pop-up blocker then costs nothing,
    // because output.html opened in any window picks the slide up by itself.
    try {
      localStorage.setItem("verse.output", JSON.stringify(payload));
    } catch (e) { /* ignore */ }
    if (outWin && !outWin.closed) {
      outWin.postMessage(blank ? { type: "black" } : { type: "render", html: payload.html }, "*");
    }
  }

  addEventListener("message", (e) => {
    if (e.data && e.data.type === "output-ready") syncOutput();
  });

  /* ─────────── listening ─────────── */

  function setListening(on) {
    state.stt.running = on;
    STT.wanted = on;
    const btn = $("#sttBtn");
    if (btn) {
      btn.classList.toggle("listening", on);
      $("#sttBtnLabel").textContent = on ? "Listening" : "Listen";
    }
    if (!on) {
      state.stt.heard = "";
      STT.lastReference = "";
      STT.lastBook = "";
    }
    renderHeard();
  }

  function renderHeard() {
    const line = $("#heardLine");
    if (!line) return;
    const show = state.stt.running || !!state.stt.heard;
    line.classList.toggle("hidden", !show);
    line.classList.toggle("live", state.stt.running);
    const waiting = state.stt.status === "loading"
      ? (state.stt.note || "Loading speech model…")
      : state.stt.status === "working"
        ? "Transcribing…"
        : "Listening — waiting for a reference";
    $("#heardText").textContent = state.stt.heard || (state.stt.running ? waiting : "");
    if (!state.stt.running) paintLevel(0);
  }

  function paintLevel(level) {
    const bar = $("#heardLevel");
    if (!bar) return;
    const value = Math.max(0, Math.min(1, Number(level) || 0));
    bar.style.width = Math.round(value * 100) + "%";
    bar.classList.toggle("hot", value > 0.25);
  }

  function startListening() {
    if (state.settings.sttEngine === "browser") {
      if (startBrowserSpeech()) setListening(true);
      return;
    }
    const api = nativeBridge();
    if (!api || !api.stt_start) {
      toast("Listening needs the desktop app window");
      return;
    }
    api.stt_start().then((res) => {
      if (res && res.ok) {
        setListening(true);
      } else if (res && res.error === "model-missing") {
        toast("Download the speech model first");
        openSheet("transcription");
      } else if (res && res.error) {
        toast(String(res.error));
      }
    }).catch(() => toast("Could not start listening"));
  }

  function stopListening() {
    setListening(false);
    stopBrowserSpeech();
    const api = nativeBridge();
    if (api && api.stt_stop) api.stt_stop().catch(() => {});
  }

  function startBrowserSpeech() {
    const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
    if (!SR) {
      toast("This window has no speech engine — use Local");
      return false;
    }
    stopBrowserSpeech();
    const rec = new SR();
    rec.lang = "en-US";
    rec.continuous = true;
    rec.interimResults = true;

    rec.onresult = (event) => {
      let text = "";
      for (let i = event.resultIndex; i < event.results.length; i++) {
        text += event.results[i][0].transcript + " ";
      }
      const final = event.results[event.results.length - 1].isFinal;
      handleHeard(text.trim(), final);
    };

    rec.onerror = (event) => {
      const err = event.error || "";
      if (err === "not-allowed" || err === "service-not-allowed") {
        toast("Microphone permission denied");
        stopListening();
      } else if (err === "network") {
        toast("Browser speech needs internet — switch to Local in Settings");
        stopListening();
      }
    };

    // Chromium ends a continuous session after a pause; start it again unless
    // the operator stopped on purpose.
    rec.onend = () => {
      if (!STT.wanted || STT.browser !== rec) return;
      clearTimeout(STT.restartTimer);
      STT.restartTimer = setTimeout(() => {
        if (!STT.wanted) return;
        try { rec.start(); } catch (err) { /* already starting */ }
      }, 400);
    };

    try {
      rec.start();
    } catch (err) {
      toast("Could not start the browser speech engine");
      return false;
    }
    STT.browser = rec;
    return true;
  }

  function stopBrowserSpeech() {
    STT.wanted = false;
    clearTimeout(STT.restartTimer);
    const rec = STT.browser;
    STT.browser = null;
    if (rec) {
      try { rec.stop(); } catch (err) { /* ignore */ }
    }
  }

  /* ── voice navigation ── */

  function parseCommand(text) {
    const t = String(text || "")
      .toLowerCase()
      .replace(/[.,!?;:"']/g, " ")
      .replace(/\s+/g, " ")
      .trim();

    // Deliberately exact: "let's go to the next verse" is preaching, while a
    // bare "next verse" is an instruction. Anything longer is ignored.
    let m = /^(?:please\s+)?(next|previous|last|back)\s+(verse|chapter)$/.exec(t);
    if (m) return { kind: m[2], dir: m[1] === "next" ? 1 : -1 };

    m = /^(?:please\s+)?(?:change|switch|set)\s+(?:the\s+)?(?:bible|version|translation)\s+(?:to\s+)?(.+)$/.exec(t);
    if (!m) m = /^(?:please\s+)?use\s+(?:the\s+)?(.+?)\s+(?:bible|version|translation)$/.exec(t);
    if (!m) {
      // "switch to King James" only counts when it names a Bible we have, so it
      // cannot be triggered by ordinary speech.
      m = /^(?:please\s+)?(?:switch|change)\s+to\s+(.+)$/.exec(t);
      const tr = m && translationFromSpeech(m[1]);
      return tr ? { kind: "version", id: tr.id } : null;
    }
    if (m) {
      const tr = translationFromSpeech(m[1]);
      return tr ? { kind: "version", id: tr.id } : { kind: "unknown-version", name: m[1].trim() };
    }
    return null;
  }

  function stepVerse(ref, dir) {
    let chapter = ref.chapter;
    let verses = E.verseNumbers(ref.book, chapter);
    if (!verses.length) return null;
    let index = ref.verseStart != null ? verses.indexOf(ref.verseStart) : 0;
    if (index < 0) index = 0;
    let target = index + dir;
    if (target < 0) {
      const chapters = E.chapters(ref.book);
      const at = chapters.indexOf(chapter);
      if (at <= 0) return null;
      chapter = chapters[at - 1];
      verses = E.verseNumbers(ref.book, chapter);
      target = verses.length - 1;
    } else if (target >= verses.length) {
      const chapters = E.chapters(ref.book);
      const at = chapters.indexOf(chapter);
      if (at < 0 || at >= chapters.length - 1) return null;
      chapter = chapters[at + 1];
      verses = E.verseNumbers(ref.book, chapter);
      target = 0;
    }
    if (!verses.length) return null;
    return makeRef(ref.book, chapter, verses[target], null);
  }

  function stepChapterRef(ref, dir) {
    const chapters = E.chapters(ref.book);
    const at = chapters.indexOf(ref.chapter) + dir;
    if (at < 0 || at >= chapters.length) return null;
    const chapter = chapters[at];
    const verses = E.verseNumbers(ref.book, chapter);
    return makeRef(ref.book, chapter, verses[0] || null, null);
  }

  function runVoiceCommand(cmd) {
    if (!cmd) return false;
    if (cmd.kind === "unknown-version") {
      toast(`No Bible called “${cmd.name}”`);
      return true;
    }

    // Guard only against a duplicated final callback from a speech engine; a
    // second "next verse" a moment later is a real instruction.
    const key = cmd.kind + (cmd.dir || cmd.id || "");
    const now = Date.now();
    if (STT.lastCommand === key && now - STT.lastCommandAt < 350) return true;
    STT.lastCommand = key;
    STT.lastCommandAt = now;

    if (cmd.kind === "version") {
      selectTranslation(cmd.id);
      toast(`Voice: ${translationFor(cmd.id).short}`);
      return true;
    }

    // What the operator last saw, not the verse the app opened on: a heard
    // reference stages into preview without touching the manual selection.
    const base = state.preview || state.selection || state.onAir;
    if (!base) {
      toast("Voice: open a verse first");
      return true;
    }
    const ref = cmd.kind === "verse" ? stepVerse(base, cmd.dir) : stepChapterRef(base, cmd.dir);
    if (!ref) {
      toast(cmd.dir > 0 ? "Voice: nothing after this" : "Voice: nothing before this");
      return true;
    }
    jumpTo(ref);
    if (state.onAir && state.live && !state.black) goLive(ref);
    STT.lastBook = ref.book;
    STT.lastChapter = ref.chapter;
    STT.lastBookAt = Date.now();
    toast(`Voice: ${ref.reference}`);
    return true;
  }

  // The one figure the host cannot measure: last word heard -> verse ready to
  // show. Sent back so the Performance page reports the whole path, not just
  // the half that happens in Python.
  function noteEndToEnd() {
    const from = STT.finalAt;
    if (!from) return;
    STT.finalAt = 0;
    const ms = performance.now() - from;
    if (!(ms > 0 && ms < 15000)) return;
    const api = nativeBridge();
    if (api && api.perf_note) api.perf_note("e2e_ms", ms).catch(() => {});
  }

  // Everything a verse does once it has been decided, whichever tier found it.
  function takeReference(ref, note) {
    if (!ref || !ref.reference) return false;
    // A partial and its final arrive milliseconds apart; the same verse said
    // again a few seconds later is a new instruction.
    if (ref.reference === STT.lastReference && Date.now() - STT.lastReferenceAt < 4000) return false;
    STT.lastReference = ref.reference;
    STT.lastReferenceAt = Date.now();
    STT.lastBook = ref.book;
    STT.lastChapter = ref.chapter;
    STT.lastBookAt = Date.now();
    pushRecent(ref);
    if (state.settings.autoLive) goLive(ref);
    else stage(ref, { silent: true });
    noteEndToEnd();
    toast(note || `Heard ${ref.reference}`);
    return true;
  }

  /* Ask the host when nothing was named out loud.
   *
   * The cheapest tiers answer first there too — an exact five-word quotation
   * needs no model at all — so this is skipped entirely when the sentence
   * contains no scripture, which is most of a sermon. */
  function askDetection(text) {
    if (state.settings.detectNamed === false) return;
    const api = nativeBridge();
    if (!api || !api.detect_text) return;
    if (STT.asking) return;
    if (text === STT.asked && Date.now() - STT.askedAt < 6000) return;
    STT.asked = text;
    STT.askedAt = Date.now();
    STT.asking = true;
    api.detect_text(text, state.settings.translation || "kjv")
      .then((res) => {
        if (!res) return;
        state.detectLast = res;
        if (!res.ok || !res.decision) {
          // Remember that the ladder looked and declined, so the page can say
          // why nothing moved instead of leaving it a mystery.
          state.detectLast = Object.assign({}, res, { suppressed: true });
          return;
        }
        const floor = STRICTNESS[state.settings.detectStrictness] || STRICTNESS.balanced;
        const confidence = Number(res.confidence) || 0;
        if (confidence < floor) {
          state.detectLast = Object.assign({}, res, { suppressed: true });
          return;
        }
        const ref = E.clamp(res.decision);
        takeReference(ref, `Found ${ref.reference} · ${res.tier} ${Math.round(confidence * 100)}%`);
      })
      .catch(() => {})
      .finally(() => { STT.asking = false; });
  }

  // Both engines land here, so a detected reference behaves identically
  // whichever one heard it.
  function handleHeard(text, final) {
    const cleaned = String(text || "").trim();
    if (!cleaned) return;
    state.stt.heard = cleaned;
    state.stt.final = !!final;
    if (final) STT.finalAt = performance.now();
    renderHeard();

    if (final && state.settings.voiceCommands !== false && runVoiceCommand(parseCommand(cleaned))) {
      return;
    }

    const hits = (E.detect && E.detect(cleaned, { partial: !final })) || [];
    let hit = hits.length ? hits[hits.length - 1] : null;

    if (hit) {
      const known = E.clamp(hit);
      if (known && known.book) {
        STT.lastBook = known.book;
        STT.lastChapter = known.chapter;
        STT.lastBookAt = Date.now();
      }
    } else if (final && STT.lastBook && Date.now() - STT.lastBookAt < 180000) {
      // "turn to Deuteronomy … chapter thirty four, verse twenty": the book was
      // said once, so a bare chapter/verse is resolved against it. Only short
      // utterances qualify, so a number in a sermon stays a number.
      const words = cleaned.split(/\s+/).filter(Boolean).length;
      if (words <= 10) hit = E.bareReference(cleaned, STT.lastBook, STT.lastChapter);
    }

    if (!hit) {
      // Nothing was named out loud. Hand the sentence to the host, which runs
      // the tiers this side cannot: exact quotation, then embeddings, then the
      // reranker. Only complete sentences qualify — an interim transcript is
      // half a sentence by definition, and searching it would waste the work.
      if (final) askDetection(cleaned);
      return;
    }

    // Local speech is streamed while the sentence is still being spoken, which
    // is what makes it feel instant — but "Romans 8" is also the first half of
    // "Romans 8:28", and "verse twenty" of "verse twenty eight". Acting on an
    // unfinished reference would put the wrong slide up for a fraction of a
    // second. Only a finished verse goes live mid-sentence; a chapter waits for
    // the final, because the next word may name a verse in it.
    if (!final && (hit.open || hit.verseStart == null)) return;
    const ref = E.clamp(hit);
    if (!ref || !ref.reference) return;
    takeReference(ref, null);
  }

  function trimMemory(level) {
    if (E.releaseIndex) E.releaseIndex();
    state.results = null;
    state.recent = state.recent.slice(0, 8);
    state.queue = state.queue.slice(-24);
    renderAll();
    if (level === "manual") toast("Memory released");
  }

  /* ─────────── search ─────────── */

  const input = $("#searchInput");
  let timer = null;

  function runQuery(q) {
    const direct = E.asReference(q);
    if (direct) {
      jumpTo(direct);
      input.value = E.clamp(direct).reference;
      return;
    }
    const hits = E.detect(q);
    if (hits.length === 1 && hits[0].raw.length >= q.length * 0.5) {
      jumpTo(hits[0]);
      input.value = E.clamp(hits[0]).reference;
      return;
    }
    state.results = E.search(q, 40);
    state.resultsQuery = q;
    renderList();
  }

  input.addEventListener("input", () => {
    const q = input.value.trim();
    clearTimeout(timer);
    if (!q) {
      state.results = null;
      renderChapter();
      renderList();
      return;
    }
    timer = setTimeout(() => runQuery(q), 180);
  });

  input.addEventListener("keydown", (e) => {
    if (e.key === "Enter") {
      e.preventDefault();
      sendCurrent();
    }
  });

  function sendCurrent() {
    if (state.results && state.results.length) {
      const r = state.results[0];
      const ref = makeRef(r.book, r.chapter, r.verse, null);
      state.book = r.book;
      state.chapter = r.chapter;
      jumpTo(ref);
      goLive(ref);
      return;
    }
    if (state.selection) {
      goLive(state.selection);
      return;
    }
    if (state.preview) goLive(state.preview);
  }

  /* ─────────── chapter stepping ─────────── */

  function stepChapter(dir) {
    const books = E.books();
    let bi = books.indexOf(state.book);
    let chapters = E.chapters(state.book);
    let ci = chapters.indexOf(state.chapter) + dir;
    if (ci < 0) {
      bi = (bi - 1 + books.length) % books.length;
      chapters = E.chapters(books[bi]);
      ci = chapters.length - 1;
    } else if (ci >= chapters.length) {
      bi = (bi + 1) % books.length;
      chapters = E.chapters(books[bi]);
      ci = 0;
    }
    state.book = books[bi];
    state.chapter = chapters[ci];
    state.selection = null;
    state.results = null;
    renderChapter();
    renderList();
  }

  /* ─────────── books popover ─────────── */

  let bookMenu = null;

  function closeBooks() {
    if (bookMenu) {
      bookMenu.remove();
      bookMenu = null;
    }
  }

  function openBooks() {
    closeBooks();
    closeChapters();
    const btn = $("#bookBtn").getBoundingClientRect();
    const menu = document.createElement("div");
    menu.className = "bookmenu";
    menu.innerHTML = E.books()
      .map((b) => `<button data-book="${esc(b)}" class="${b === state.book ? "on" : ""}">${esc(b)}</button>`)
      .join("");
    document.body.appendChild(menu);
    const h = Math.min(420, window.innerHeight - 160);
    menu.style.height = h + "px";
    menu.style.left = Math.max(8, Math.min(btn.left, window.innerWidth - 420)) + "px";
    menu.style.top = Math.max(8, btn.top - h - 10) + "px";
    menu.querySelectorAll("[data-book]").forEach((b) => {
      b.onclick = () => {
        openBook(b.dataset.book);
        closeBooks();
      };
    });
    // The current book is the useful starting point in a list of 66.
    const active = menu.querySelector("[data-book].on");
    if (active) active.scrollIntoView({ block: "center" });
    bookMenu = menu;
  }

  /* ─────────── chapter popover ─────────── */

  let chapterMenu = null;

  function closeChapters() {
    if (chapterMenu) {
      chapterMenu.remove();
      chapterMenu = null;
    }
  }

  function openChapters() {
    closeChapters();
    closeBooks();
    const anchor = $("#chapterJump").getBoundingClientRect();
    const menu = document.createElement("div");
    menu.className = "chapmenu";
    menu.innerHTML = E.chapters(state.book)
      .map((c) => `<button data-chapter="${c}" class="${c === state.chapter ? "on" : ""}">${c}</button>`)
      .join("");
    document.body.appendChild(menu);
    // The heading sits in the lower half of the window, so the grid usually has
    // to open upwards to stay on screen.
    const below = window.innerHeight - anchor.bottom - 16;
    const above = anchor.top - 16;
    const openUp = below < 260 && above > below;
    const h = Math.min(320, Math.max(160, openUp ? above : below));
    menu.style.height = h + "px";
    menu.style.left = Math.max(8, Math.min(anchor.left - 12, window.innerWidth - 348)) + "px";
    menu.style.top = (openUp ? Math.max(8, anchor.top - h - 8) : anchor.bottom + 8) + "px";
    menu.querySelectorAll("[data-chapter]").forEach((b) => {
      b.onclick = () => {
        openChapter(Number(b.dataset.chapter));
        closeChapters();
      };
    });
    const active = menu.querySelector("button.on");
    if (active) active.scrollIntoView({ block: "center" });
    chapterMenu = menu;
  }

  // Manual browsing: pick a book, pick a chapter, click a verse. No typing and
  // no arrows needed, which is what an operator wants mid-service.
  function openBook(book) {
    const chapters = E.chapters(book);
    jumpTo(makeRef(book, chapters.length ? chapters[0] : 1, null, null));
    $("#verseList").scrollTop = 0;
  }

  function openChapter(number) {
    state.chapter = number;
    state.selection = null;
    state.results = null;
    state.resultsQuery = "";
    if (document.activeElement !== input) input.value = `${state.book} ${number}`;
    renderChapter();
    renderList();
    $("#verseList").scrollTop = 0;
  }

  /* ─────────── toast ─────────── */

  let toastTimer = null;
  function toast(msg) {
    const el = $("#toast");
    el.textContent = msg;
    el.classList.add("show");
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => el.classList.remove("show"), 1900);
  }

  /* ─────────── settings sheet ─────────── */

  function row(label, desc, control) {
    return (
      `<div class="row"><div class="row-main">` +
      `<div class="row-label">${label}</div>` +
      (desc ? `<div class="row-desc">${desc}</div>` : "") +
      `</div><div class="row-ctl">${control}</div></div>`
    );
  }

  function seg(name, options, value, accent) {
    return (
      `<div class="seg${accent ? " accent" : ""}" data-seg="${name}">` +
      options
        .map(
          (o) =>
            `<button data-value="${o.value}" class="${o.value === value ? "active" : ""}">${o.label}</button>`
        )
        .join("") +
      `</div>`
    );
  }

  function toggleEl(name, on) {
    return `<div class="toggle${on ? " on" : ""}" data-toggle="${name}"></div>`;
  }

  const SHEETS = {
    scripture() {
      return (
        row(
          "Verse display mode",
          "Send the selected verse to the output automatically, or preview it until you press Enter.",
          seg(
            "displayMode",
            [
              { value: "auto", label: "Auto" },
              { value: "manual", label: "Manual" },
            ],
            state.settings.displayMode,
            true
          )
        ) +
        row(
          "Primary translation",
          "Default Bible translation for verse display. Switching re-renders anything already on air.",
          `<select class="sel" data-setting="translation">
             ${TRANSLATIONS.map(
               (t) =>
                 `<option value="${esc(t.id)}"${t.id === state.settings.translation ? " selected" : ""}>${esc(t.short)} · ${esc(t.title)}</option>`
             ).join("")}
           </select>`
        ) +
        row(
          "Reference format",
          "What appears under the verse on the slide",
          seg(
            "refFormat",
            [
              { value: "full", label: "Genesis 1:1 (KJV)" },
              { value: "short", label: "Genesis 1:1" },
            ],
            state.settings.refFormat,
            false
          )
        ) +
        row(
          "Slide theme",
          "Background and typography for the output",
          `<select class="sel" data-setting="theme">
             ${PRESETS.map(
               (p) => `<option value="${p.id}"${p.id === state.theme.id ? " selected" : ""}>${p.name}</option>`
             ).join("")}
           </select>`
        )
      );
    },

    translations() {
      const installed = TRANSLATIONS.map((t) =>
        row(
          `${t.short} · ${t.title}`,
          `${t.language} · ${t.licence} · ${(t.verses || 0).toLocaleString()} verses`,
          t.id === state.settings.translation
            ? `<button class="btn small" data-action="useTranslation" data-id="${esc(t.id)}" disabled>In use</button>`
            : `<button class="btn small" data-action="useTranslation" data-id="${esc(t.id)}">Use</button>`
        )
      ).join("");
      return (
        `<div class="section-label">Installed</div>` +
        installed +
        `<div class="section-label">Add your own</div>` +
        `<p class="row-desc" style="margin:0 0 12px">Verse ships only Bibles it may redistribute: public-domain texts and Biblica's CC BY-SA editions. NIV, NKJV, ESV and most modern English Bibles are licensed, so they cannot be bundled — import the copy you own instead.</p>` +
        `<pre class="codeblock">python tools/build_translation.py --json my-bible.json \\
  --id niv --short NIV --title "New International Version" \\
  --language English --licence "Used under licence" --source "my copy"</pre>` +
        `<p class="row-desc" style="margin:0 0 12px">The JSON is one entry per verse, keyed by “Book Chapter:Verse”. The command writes <code>assets/js/data.niv.js</code>; add the matching entry to <code>assets/js/translations.js</code> and it appears in this list. Keep such a build for your own use — do not redistribute it.</p>` +
        row(
          "Bundled notices",
          "Sources and copyright lines for every bundled translation are in BIBLES.md, next to the app.",
          ""
        )
      );
    },

    transcription() {
      const model = state.model;
      const fast = state.instant || {};
      const instant = state.settings.instantPipeline !== false;
      const engine = state.settings.sttEngine;
      const local = state.settings.localEngine === "vosk" ? "vosk" : "whisper";
      const localName = local === "vosk" ? "Vosk small en-US" : "Whisper base.en";
      const expected = local === "vosk" ? 40 : (model.expected || 145);
      return (
        row(
          "Engine",
          "Local is offline and never sends audio anywhere. Browser uses this window's speech service — needs internet, and may be blocked here; if nothing is heard, use Local.",
          seg(
            "sttEngine",
            [
              { value: "local", label: "Local" },
              { value: "browser", label: "Browser" },
            ],
            engine,
            true
          )
        ) +
        (engine === "local"
          ? row(
              "Local model",
              local === "whisper"
                ? "Whisper reads a whole sentence at once, so it copes with Nigerian and other accents that Vosk's small US-English model misses. It waits about a second after the speaker pauses before it shows the verse."
                : "Vosk streams every word as it is spoken and loads in under a second, but it was trained on read US speech: on accented preaching it will miss many references.",
              seg(
                "localEngine",
                [
                  { value: "whisper", label: "Whisper" },
                  { value: "vosk", label: "Vosk" },
                ],
                local,
                true
              )
            )
          : "") +
        row(
          "Microphone",
          state.devices.length
            ? (Number(state.settings.micDevice) < 0
                ? `Automatic is using ${esc(state.stt.deviceName || "the system default")}. The meter beside Live display moves when you speak.`
                : "Which input the local engine records. While listening, the meter beside Live display should move when you speak.")
            : "No recording device was found. Plug a microphone in, then reopen this page.",
          `<select class="sel" data-setting="micDevice">` +
            `<option value="-1"${Number(state.settings.micDevice) < 0 ? " selected" : ""}>Automatic (recommended)</option>` +
            state.devices
              .map(
                (d) =>
                  `<option value="${d.index}"${Number(state.settings.micDevice) === d.index ? " selected" : ""}>${esc(d.name)}${d.default ? " (default)" : ""}</option>`
              )
              .join("") +
            `</select>`
        ) +
        row(
          "Speech model",
          model.ready
            ? `${esc(model.name || localName)} · installed · ${model.mb} MB on disk · loaded only while listening`
            : `${localName} · about ${expected} MB, downloaded once from the internet. It stays on this machine.`,
          model.ready
            ? `<span class="tag-ok">Ready</span>`
            : `<button class="btn small" data-action="downloadModel"${model.downloading ? " disabled" : ""}>${
                model.downloading ? Math.round(model.progress * 100) + "%" : "Download"
              }</button>`
        ) +
        (model.downloading
          ? `<div class="progress"><div class="progress-fill" style="width:${Math.round(model.progress * 100)}%"></div></div>`
          : "") +
        (local === "whisper"
          ? row(
              "Instant pipeline",
              fast.ready
                ? `${esc(fast.name || "Whisper tiny.en")} · installed · ${fast.mb} MB · reads the same audio a second in, ` +
                  "while the sentence is still being spoken, so a reference can appear before the speaker stops. The " +
                  "model above replaces it with the accurate reading once the room goes quiet." +
                  (instant && !fast.active && state.stt.running ? " Not running — restart Listen to pick it up." : "")
                : `${esc(fast.name || "Whisper tiny.en")} · about ${fast.expected_mb || 78} MB, downloaded once. A second, ` +
                  "much smaller model beside the accurate one: it answers in about a fifth of the time, on the same audio.",
              fast.ready
                ? toggleEl("instantPipeline", instant)
                : `<button class="btn small" data-action="downloadInstant"${
                    model.downloading ? " disabled" : ""
                  }>Download</button>`
            ) +
            (instant && fast.ready && !fast.active && state.stt.running
              ? `<p class="row-desc" style="margin:6px 0 0">The fast pass stands down while the accurate one is ` +
                `transcribing, so the two never compete for the same cores.</p>`
              : "")
          : "") +
        row(
          "Detected references",
          "Send a reference straight to the output as soon as it is heard, instead of leaving it in the preview.",
          toggleEl("autoLive", state.settings.autoLive)
        ) +
        row(
          "Voice commands",
          "Say “next verse”, “previous verse”, “next chapter”, “previous chapter”, or “change the Bible to Yoruba”. Commands must be the whole sentence, so preaching about “the next verse” does not move the screen.",
          toggleEl("voiceCommands", state.settings.voiceCommands !== false)
        ) +
        row(
          "Last heard",
          state.stt.heard ? `“${esc(state.stt.heard)}”` : "Nothing yet — press Listen, or M.",
          ""
        )
      );
    },

    detection() {
      const d = state.detect || {};
      const stack = d.stack || {};
      const semantic = stack.semantic || {};
      const model = semantic.model || {};
      const borrowed = semantic.borrowed || {};
      const rerank = stack.rerank || {};
      const shingle = stack.shingle || {};
      const progress = state.detectProgress;
      const index = state.indexProgress;
      const warm = state.warm;

      const bar = (fraction) =>
        `<div class="progress"><div class="progress-fill" style="width:${Math.round((fraction || 0) * 100)}%"></div></div>`;

      const modelRow =
        row(
          "Embedding model",
          model.ready
            ? `EmbeddingGemma-300m · installed · ${model.mb} MB · read from ` +
              (model.source === "pewbeam" ? "the Pewbeam install on this machine" : "this app's own model folder") +
              ". Run through ONNX Runtime on the CPU: one query is about 35 ms once loaded."
            : "Embeds a sentence so verses that are never named out loud can still be found. " +
              `${model.expected_mb || 209} MB, downloaded once from Hugging Face, and it never leaves the machine.`,
          model.ready
            ? `<span class="tag-ok">Ready</span>`
            : `<button class="btn small" data-action="installDetect" data-kind="semantic"${
                progress && progress.kind === "semantic" ? " disabled" : ""
              }>${progress && progress.kind === "semantic" ? Math.round(progress.fraction * 100) + "%" : "Install"}</button>`
        ) + (progress && progress.kind === "semantic" ? bar(progress.fraction) : "");

      const rerankRow = row(
        "Cross-encoder",
        rerank.ready
          ? `MiniLM-L6 int8 · installed · ${rerank.mb} MB · reads the shortlist against the sentence to tell ` +
            `near-misses apart (1 Samuel 2:31 against Ephesians 4:22). Optional: without it, candidates keep their order.`
          : `Optional. ${rerank.expected_mb || 23} MB. Without it, two verses that share wording cannot be separated — ` +
            `the embedding scores them within 0.01 of each other.`,
        rerank.ready
          ? `<span class="tag-ok">Ready</span>`
          : `<button class="btn small" data-action="installDetect" data-kind="rerank"${
              progress && progress.kind === "rerank" ? " disabled" : ""
            }>${progress && progress.kind === "rerank" ? Math.round(progress.fraction * 100) + "%" : "Install"}</button>`
      ) + (progress && progress.kind === "rerank" ? bar(progress.fraction) : "");

      const built = new Set((semantic.indexes || []).map((entry) => entry.translation));
      const indexRows = (shingle.available || []).map((id) => {
        const entry = (semantic.indexes || []).find((e) => e.translation === id);
        const building = index && index.translation === id;
        const title = TRANSLATIONS.find((t) => t.id === id);
        return row(
          `${(title && title.short) || id.toUpperCase()} · verse vectors`,
          building
            ? `${index.done.toLocaleString()} of ${index.total.toLocaleString()} verses · ${index.rate}/s` +
              (index.eta > 0 ? ` · about ${Math.ceil(index.eta / 60)} min left` : "") +
              " · resumable: stopping and starting again continues from here"
            : entry
              ? `${entry.verses.toLocaleString()} verses · ${entry.mb} MB · this app's own vectors, built from its own text`
              : borrowed.ready && id === state.settings.translation
                ? `Not built. Until it is, English search borrows the ${borrowed.verses.toLocaleString()}-verse index ` +
                  `already on this machine. Yoruba and Igbo have nothing to borrow — their words only match their own language.`
                : "Not built. Verses quoted in this language cannot be found until it is.",
          building
            ? `<button class="btn small" data-action="cancelIndex">Stop</button>`
            : entry
              ? `<span class="tag-ok">Built</span>`
              : `<button class="btn small" data-action="buildIndex" data-id="${esc(id)}"${
                  index ? " disabled" : ""
                }>Build</button>`
        ) + (building ? bar(index.fraction) : "");
      }).join("");

      return (
        (semantic.deps === false
          ? `<p class="advisor">The semantic tier needs onnxruntime and tokenizers, which are not ` +
            `installed for this Python. Run <code>.venv\\Scripts\\pip install -r requirements.txt</code>. ` +
            `Until then the verbatim tier still works, and any reference said out loud is unaffected.</p>`
          : "") +
        row(
          "Find verses that are not named",
          "A reference said out loud is already handled in the page, instantly. This adds the three tiers that find a verse " +
          "nobody named: an exact five-word quotation (0.2 ms), then embeddings (about 35 ms), then the cross-encoder. " +
          "Each tier only runs when the cheaper one is not sure.",
          toggleEl("detectNamed", state.settings.detectNamed !== false)
        ) +
        row(
          "How sure is sure",
          "Confidence the ladder needs before it moves a verse to the preview on its own. Balanced is tuned from the " +
          "measurements on this machine; Strict wants a near-quotation, Eager will show a guess.",
          seg(
            "detectStrictness",
            [
              { value: "strict", label: "Strict" },
              { value: "balanced", label: "Balanced" },
              { value: "eager", label: "Eager" },
            ],
            state.settings.detectStrictness || "balanced",
            true
          )
        ) +
        `<div class="section-label">Models</div>` +
        modelRow +
        rerankRow +
        row(
          "Release when listening stops",
          "Frees the model and its 91 MB matrix when the microphone is off, and loads them again in about two seconds " +
          "when Listen is pressed. This is the difference between an idle app of 460 MB and one of 750 MB.",
          toggleEl("releaseWhenIdle", state.settings.releaseWhenIdle !== false)
        ) +
        row(
          "Memory now",
          `${(d.memory && d.memory.total_mb) || 0} MB in ${(d.memory && d.memory.processes) || 1} processes · ` +
            (stack.semantic && stack.semantic.loaded ? "detection stack loaded" : "detection stack released") +
            (warm && warm.ok ? ` · last load ${warm.seconds.toFixed(2)} s` : "") +
            (d.prewarming ? " · loading…" : ""),
          `<button class="btn small" data-action="unloadDetect">Release</button>`
        ) +
        `<div class="section-label">Verbatim index</div>` +
        `<p class="row-desc" style="margin:0 0 10px">Built from this app's own Bible text in about a second per translation ` +
          `and about 6 MB, cached next to the app. It is what makes a quoted verse exact and instant.</p>` +
        (indexRows || `<p class="row-desc">No Bibles found.</p>`) +
        row(
          "Where the models live",
          `${esc((model.path || "not installed").split("\\").slice(0, -3).join("\\") || "—")}`,
          ""
        )
      );
    },

    performance() {
      const p = state.perf || {};
      const summary = p.summary || {};
      const latency = summary.latency_metrics || {};
      const system = summary.system_metrics || {};
      const counters = summary.counters || {};
      const memory = p.memory || {};
      const stages = Object.keys(latency).sort();
      const table = stages.length
        ? `<table class="perf-table"><thead><tr><th>Stage</th><th>avg</th><th>p95</th><th>max</th><th>n</th></tr></thead><tbody>` +
          stages
            .map(
              (name) =>
                `<tr><td>${esc(name)}</td><td>${latency[name].avg} ms</td><td>${latency[name].p95}</td>` +
                `<td>${latency[name].max}</td><td>${latency[name].count}</td></tr>`
            )
            .join("") +
          `</tbody></table>`
        : `<p class="row-desc">Nothing measured yet. Press Listen and speak a reference.</p>`;
      const counted = Object.keys(counters).sort()
        .map((k) => `${esc(k)} ${counters[k]}`)
        .join(" · ");
      return (
        row(
          "Grade",
          summary.uptime_seconds
            ? `Running for ${Math.round(summary.uptime_seconds / 60)} minutes · ${summary.total_events || 0} events measured. ` +
              "The grade is set by the slowest stage: A means a verse reaches the screen under a second after the last word."
            : "No measurements yet.",
          `<span class="grade">${esc(summary.performance_grade || "—")}</span>`
        ) +
        `<div class="section-label">Latency per stage</div>` +
        table +
        `<div class="section-label">Memory</div>` +
        row(
          "Whole app",
          `${memory.total_mb || system.memory_usage_mb || 0} MB across ${memory.processes || system.processes || 1} processes · ` +
            `peak ${memory.peak_mb || system.memory_peak_mb || 0} MB · trims caches at ${memory.soft_mb || 900} MB, ` +
            `and releases the detection model at ${memory.hard_mb || 1500} MB`,
          `<button class="btn small" data-action="trimMemory">Release now</button>`
        ) +
        row("Counters", counted ? esc(counted) : "Nothing yet.", "") +
        `<div class="section-label">Recommendations</div>` +
        (p.recommendations || [])
          .map((line) => `<p class="advisor">${esc(line)}</p>`)
          .join("") +
        row(
          "Reset",
          "Clears the measurements and starts again — useful before a service, so the numbers describe that service.",
          `<button class="btn small" data-action="clearPerf">Clear</button>`
        )
      );
    },

    output() {
      const ndi = state.ndi || { running: false };
      const displays = state.displays || [];
      return (
        row(
          "Projection",
          "Where the slide goes when you send a verse live or press O.",
          seg(
            "outputMode",
            [
              { value: "window", label: "Window" },
              { value: "fullscreen", label: "Fullscreen" },
              { value: "ndi", label: "NDI" },
            ],
            state.settings.outputMode,
            true
          )
        ) +
        row(
          "Monitor",
          displays.length > 1
            ? "The display used for fullscreen output."
            : "One display connected — plug in a second one to send fullscreen there.",
          `<select class="sel" data-setting="display">${displays
            .map(
              (d, i) =>
                `<option value="${i}"${Number(state.settings.display) === i ? " selected" : ""}>Display ${i + 1} · ${d.width}×${d.height}</option>`
            )
            .join("")}</select>`
        ) +
        row(
          "NDI source name",
          "The name receivers see in vMix, OBS, Studio Monitor, a hardware encoder, or another machine on the network.",
          `<input class="text-input" data-setting="ndiName" value="${esc(state.settings.ndiName)}" spellcheck="false">`
        ) +
        row(
          "NDI stream",
          ndi.running
            ? `Sending · ${ndi.width}×${ndi.height} · ${ndi.fps} fps · ${ndi.frames} frames`
            : "Not sending. NDI carries the projection window itself, so blackouts and theme changes go out too.",
          `<button class="btn small" data-action="toggleNdi">${ndi.running ? "Stop" : "Start"}</button>`
        ) +
        row(
          "Other receivers",
          "The output is a normal window: open output.html anywhere, or capture it with OBS as a window source. It syncs by itself.",
          ""
        )
      );
    },

    usage() {
      const m = state.memory || {};
      return (
        row(
          "Memory in use",
          m.total_mb ? `${m.total_mb} MB across ${m.processes} processes` : "Measuring…",
          `<button class="btn small" data-action="trimMemory">Release</button>`
        ) +
        row("Peak this session", m.peak_mb ? `${m.peak_mb} MB` : "—", "") +
        row(
          "Guard rails",
          `At ${m.soft_mb || 900} MB the app drops the keyword index and old queue entries. At ${m.hard_mb || 1500} MB it releases everything it can and says so, rather than growing until Windows kills it.`,
          ""
        ) +
        row(
          "Keyword index",
          E.indexBuilt && E.indexBuilt()
            ? "Built — released automatically when memory gets high"
            : "Not built; rebuilt on the next phrase search",
          ""
        )
      );
    },

    help() {
      const keys = [
        ["Focus the search field", ["Tab"]],
        ["Toggle live output", ["L"]],
        ["Clear output and queue", ["C"]],
        ["Black the output", ["B"]],
        ["Previous / next chapter", ["←", "→"]],
        ["Send the preview live", ["Enter"]],
        ["Start or stop listening", ["M"]],
        ["Open the projection window", ["O"]],
        ["Fullscreen the projection (app window)", ["F11"]],
      ];
      return (
        `<div class="section-label">Keyboard shortcuts</div>` +
        keys
          .map(
            ([label, caps]) =>
              `<div class="row" style="padding:14px 0">` +
              `<div class="row-main"><div class="row-label" style="font-weight:500">${label}</div></div>` +
              `<div class="row-ctl">${caps.map((c) => `<span class="keycap">${c}</span>`).join("")}</div>` +
              `</div>`
          )
          .join("") +
        `<div class="section-label">Voice commands</div>` +
        [
          ["Next / previous verse", "“next verse”, “previous verse”"],
          ["Next / previous chapter", "“next chapter”, “previous chapter”"],
          ["Change Bible", "“change the Bible to Yoruba”, “switch to King James”"],
        ]
          .map(
            ([label, phrase]) =>
              `<div class="row" style="padding:14px 0">` +
              `<div class="row-main"><div class="row-label" style="font-weight:500">${label}</div>` +
              `<div class="row-desc">${phrase}</div></div>` +
              `</div>`
          )
          .join("") +
        `<p class="row-desc" style="margin:0 0 8px">Commands must be the whole sentence — “let us go to the next verse” is treated as preaching, not as an instruction.</p>` +
        `<div class="section-label">About</div>` +
        `<p class="row-desc" style="margin:0">Verse 1.0.0 — a free, offline scripture presenter. KJV text is public domain (via farskipper/kjv). Reference detection is adapted from the GPL-3.0 VerseListener project, so this app is distributed under the same licence. No accounts, no licences, no upsells.</p>`
      );
    },
  };

  function openSheet(page) {
    state.sheet = page || "scripture";
    renderSheet();
    $("#backdrop").classList.add("show");
    $("#sheet").classList.add("show");
    // Nothing in a sheet should read "Download" or "Measuring…" for two
    // seconds because it opened between polls.
    refreshStatus();
  }

  function closeSheet() {
    state.sheet = null;
    $("#backdrop").classList.remove("show");
    $("#sheet").classList.remove("show");
  }

  function renderSheet() {
    const page = state.sheet || "scripture";
    $$(".nav-item[data-sheet]").forEach((b) => b.classList.toggle("active", b.dataset.sheet === page));
    $("#sheetTitle").textContent = page.charAt(0).toUpperCase() + page.slice(1);
    $("#sheetBody").innerHTML = SHEETS[page]();
    wireSheet();
  }

  function wireSheet() {
    const body = $("#sheetBody");

    $$(".nav-item[data-sheet]").forEach((b) => {
      b.onclick = () => {
        state.sheet = b.dataset.sheet;
        renderSheet();
      };
    });

    $$("[data-seg]", body).forEach((group) => {
      group.querySelectorAll("button").forEach((b) => {
        b.onclick = () => {
          const key = group.dataset.seg;
          const value = b.dataset.value;
          state.settings[key] = value;
          save();

          const api = nativeBridge();
          if (key === "sttEngine") {
            if (state.stt.running) stopListening();
            if (api && api.stt_set_engine) api.stt_set_engine(value).catch(() => {});
            if (value === "local" && api && api.stt_set_local_engine) {
              api.stt_set_local_engine(state.settings.localEngine || "whisper").catch(() => {});
            }
          }
          if (key === "localEngine") {
            if (state.stt.running) stopListening();
            if (api && api.stt_set_local_engine) {
              api.stt_set_local_engine(value)
                .then(() => refreshStatus())
                .catch(() => {});
            }
          }
          if (key === "outputMode" && api && api.set_output_mode) {
            api.set_output_mode(value, Number(state.settings.display) || 0).catch(() => {});
          }

          renderSheet();
          toast(key === "displayMode" ? `Display mode: ${value}` : "Saved");
        };
      });
    });

    $$("[data-action]", body).forEach((btn) => {
      btn.onclick = () => {
        const action = btn.dataset.action;
        const api = nativeBridge();
        if (action === "useTranslation") {
          selectTranslation(btn.dataset.id);
        } else if (action === "downloadModel") {
          state.model.downloading = true;
          state.model.progress = 0;
          renderSheet();
          if (api && api.stt_download) api.stt_download().catch(() => {});
        } else if (action === "downloadInstant") {
          state.model.downloading = true;
          state.model.progress = 0;
          renderSheet();
          if (api && api.stt_download) api.stt_download("instant").catch(() => {});
        } else if (action === "trimMemory") {
          trimMemory("manual");
          if (api && api.memory_trim) api.memory_trim().catch(() => {});
          refreshStatus();
        } else if (action === "installDetect") {
          const kind = btn.dataset.kind || "semantic";
          state.detectProgress = { kind, fraction: 0, note: "download" };
          renderSheet();
          if (api && api.detection_install) {
            api.detection_install(kind).catch(() => toast("Could not start the download"));
          }
        } else if (action === "buildIndex") {
          const id = btn.dataset.id;
          state.indexProgress = { translation: id, fraction: 0, note: "starting", done: 0, total: 0, rate: 0, eta: -1 };
          renderSheet();
          if (api && api.index_build) {
            api.index_build(id).catch(() => toast("Could not start building"));
          }
        } else if (action === "cancelIndex") {
          if (api && api.index_cancel) api.index_cancel().then(() => toast("Stopping after this batch")).catch(() => {});
        } else if (action === "unloadDetect") {
          if (api && api.detection_unload) {
            api.detection_unload().then((res) => {
              toast(res && res.freed ? "Detection model released" : "Nothing was loaded");
              refreshStatus();
            }).catch(() => {});
          }
        } else if (action === "clearPerf") {
          if (api && api.perf_clear) {
            api.perf_clear().then(() => {
              toast("Measurements cleared");
              refreshStatus();
            }).catch(() => {});
          }
        } else if (action === "toggleNdi") {
          const starting = !(state.ndi && state.ndi.running);
          if (api && api.ndi_start) {
            (starting ? api.ndi_start() : api.ndi_stop())
              .then(refreshStatus)
              .catch(() => toast("NDI is only available in the desktop app"));
          }
          if (starting && state.settings.outputMode !== "ndi") {
            state.settings.outputMode = "ndi";
            save();
          }
          renderSheet();
        }
      };
    });

    $$("[data-toggle]", body).forEach((t) => {
      t.onclick = () => {
        t.classList.toggle("on");
        const key = t.dataset.toggle;
        const on = t.classList.contains("on");
        state.settings[key] = on;
        save();

        const api = nativeBridge();
        if (key === "instantPipeline") {
          // The fast pass needs tiny.en. Ask for it rather than failing quietly
          // the next time somebody presses Listen.
          if (on && !state.instant.ready && api && api.stt_download) {
            state.model.downloading = true;
            state.model.progress = 0;
            toast("Downloading the fast model (75 MB)…");
            api.stt_download("instant").catch(() => {});
          } else if (api && api.stt_set_instant) {
            api.stt_set_instant(on).catch(() => {});
          }
        }
        if (key === "releaseWhenIdle" && api && api.detection_set_idle_release) {
          api.detection_set_idle_release(on).catch(() => {});
        }
        if (key === "autoLive" || key === "voiceCommands") {
          toast(on ? "On" : "Off");
        }
        renderSheet();
      };
    });

    $$("[data-setting]", body).forEach((el) => {
      el.onchange = () => {
        const key = el.dataset.setting;
        const api = nativeBridge();
        if (key === "theme") {
          const preset = PRESETS.find((p) => p.id === el.value);
          if (preset) applyPreset(preset);
        } else if (key === "micDevice") {
          state.settings.micDevice = Number(el.value);
          if (api && api.stt_set_device) {
            api.stt_set_device(state.settings.micDevice)
              .then((res) => {
                if (res && res.restarted) toast("Listening on the new microphone");
              })
              .catch(() => {});
          }
        } else if (key === "translation") {
          selectTranslation(el.value);
          return;
        } else if (key === "ndiName") {
          state.settings.ndiName = el.value.trim() || "Verse";
          if (api && api.ndi_set_name) api.ndi_set_name(state.settings.ndiName).catch(() => {});
        } else if (key === "display") {
          state.settings.display = Number(el.value) || 0;
          if (api && api.set_output_mode && state.settings.outputMode === "fullscreen") {
            api.set_output_mode("fullscreen", state.settings.display).catch(() => {});
          }
        } else {
          state.settings[key] = el.value;
        }
        save();
        renderAll();
      };
    });
  }

  /* ─────────── themes screen ─────────── */

  function applyPreset(preset) {
    state.theme = Object.assign({}, preset);
    applyThemeVars();
    renderAll();
    renderInspector();
    save();
  }

  function applyThemeVars() {
    const t = state.theme;
    const root = document.documentElement.style;
    root.setProperty("--slide-bg", t.bg);
    root.setProperty("--slide-fg", t.fg);
    root.setProperty("--verse-size", t.size);
    root.setProperty("--verse-weight", t.weight);
    root.setProperty("--ref-gap", t.gap);
    root.setProperty("--ref-case", t.case || "none");
    root.setProperty("--verse-shadow", t.shadow ? "0 2px 18px rgba(0,0,0,.45)" : "none");
  }

  function renderThemeList() {
    const list = $("#themeList");
    list.innerHTML = PRESETS.map(
      (p) =>
        `<button class="theme-card${p.id === state.theme.id ? " on" : ""}" data-theme="${p.id}">` +
        slideHTML(makeRef("Genesis", 1, 1, null), p) +
        `<div class="theme-card-foot">${p.name}</div>` +
        `</button>`
    ).join("");
  }

  function renderInspector() {
    $$("[data-theme-color]").forEach((holder) => {
      const key = holder.dataset.themeColor;
      const value = state.theme[key];
      const solid = typeof value === "string" && value.startsWith("#") ? value : "#002fc6";
      holder.innerHTML =
        `<span class="swatch"><input type="color" value="${solid}"></span>` +
        `<input class="hex" value="${solid.toUpperCase()}" spellcheck="false">`;
      const color = holder.querySelector('input[type="color"]');
      const hex = holder.querySelector(".hex");
      color.oninput = () => {
        state.theme[key] = color.value;
        hex.value = color.value.toUpperCase();
        applyThemeVars();
        renderCanvas();
        renderOutput();
        renderPreview();
        save();
      };
      hex.onchange = () => {
        let v = hex.value.trim();
        if (!v.startsWith("#")) v = "#" + v;
        if (/^#[0-9a-f]{6}$/i.test(v)) {
          state.theme[key] = v.toLowerCase();
          color.value = v;
          applyThemeVars();
          renderCanvas();
          renderOutput();
          renderPreview();
          save();
        } else {
          hex.value = state.theme[key].toUpperCase();
        }
      };
    });

    $("#themeSize").value = state.theme.size;
    $("#themeSizeValue").textContent = state.theme.size;
    $("#themeWeight").value = String(state.theme.weight);
    $("#themeGap").value = state.theme.gap;
    $("#themeCase").value = state.theme.case || "none";
    $("#themeNumbers").classList.toggle("on", !!state.theme.numbers);
    $("#themeShadow").classList.toggle("on", !!state.theme.shadow);
  }

  function wireInspector() {
    $("#themeSize").oninput = (e) => {
      state.theme.size = Number(e.target.value);
      $("#themeSizeValue").textContent = state.theme.size;
      applyThemeVars();
      renderCanvas();
      renderOutput();
      renderPreview();
      save();
    };
    $("#themeWeight").onchange = (e) => {
      state.theme.weight = Number(e.target.value);
      applyThemeVars();
      renderCanvas();
      renderOutput();
      renderPreview();
      save();
    };
    $("#themeGap").onchange = (e) => {
      state.theme.gap = Number(e.target.value);
      applyThemeVars();
      renderCanvas();
      renderOutput();
      renderPreview();
      save();
    };
    $("#themeCase").onchange = (e) => {
      state.theme.case = e.target.value;
      applyThemeVars();
      renderCanvas();
      renderOutput();
      renderPreview();
      save();
    };
    $("#themeNumbers").onclick = () => {
      state.theme.numbers = !state.theme.numbers;
      $("#themeNumbers").classList.toggle("on", state.theme.numbers);
      renderCanvas();
      renderOutput();
      renderPreview();
      save();
    };
    $("#themeShadow").onclick = () => {
      state.theme.shadow = !state.theme.shadow;
      $("#themeShadow").classList.toggle("on", state.theme.shadow);
      applyThemeVars();
      renderCanvas();
      renderOutput();
      renderPreview();
      save();
    };
  }

  /* ─────────── view switching ─────────── */

  function setView(view) {
    state.view = view;
    $$(".view-pill").forEach((b) => b.classList.toggle("active", b.dataset.view === view));
    const themes = view === "themes";
    $("#stage").classList.toggle("hidden", themes);
    $("#lower").classList.toggle("hidden", themes);
    $("#themesView").classList.toggle("hidden", !themes);
    if (themes) {
      renderThemeList();
      renderCanvas();
      renderInspector();
    }
  }

  function renderAll() {
    renderDisplay();
    renderOutput();
    renderPreview();
    renderQueue();
    renderRecent();
    renderChapter();
    renderList();
    if (state.view === "themes") {
      renderThemeList();
      renderCanvas();
    }
  }

  /* ─────────── wiring ─────────── */

  function wire() {
    $$(".view-pill").forEach((b) => (b.onclick = () => setView(b.dataset.view)));

    $("#sttBtn").onclick = () => (state.stt.running ? stopListening() : startListening());

    const translationSelect = $("#translationSelect");
    if (translationSelect) {
      translationSelect.onchange = () => selectTranslation(translationSelect.value);
    }

    const liveBtn = $("#liveBtn");
    liveBtn.onclick = () => {
      state.live = !state.live;
      liveBtn.classList.toggle("is-on", state.live);
      if (state.live) {
        if (state.preview && !state.onAir) goLive(state.preview);
        toast("Live output on");
      } else {
        state.onAir = null;
        renderDisplay();
        renderOutput();
        syncOutput();
        toast("Live output off");
      }
    };

    $("#blackBtn").onclick = blackout;
    $("#clearBtn").onclick = () => {
      clearQueue();
      clearOutput();
      toast("Cleared");
    };
    $("#outputBtn").onclick = openOutput;
    $("#outputOpen").onclick = openOutput;
    $("#displayExpand").onclick = openOutput;
    $("#previewExpand").onclick = openOutput;
    $("#settingsBtn").onclick = () => openSheet("scripture");
    $("#helpBtn").onclick = () => openSheet("help");
    $("#sheetClose").onclick = closeSheet;
    $("#backdrop").onclick = closeSheet;
    $("#queueClear").onclick = clearQueue;
    $("#recentClear").onclick = () => {
      state.recent = [];
      renderRecent();
    };

    $("#goBtn").onclick = sendCurrent;
    $("#prevChapter").onclick = () => stepChapter(-1);
    $("#nextChapter").onclick = () => stepChapter(1);
    $("#bookBtn").onclick = (e) => {
      e.stopPropagation();
      if (bookMenu) closeBooks();
      else openBooks();
    };
    $("#historyBtn").onclick = () => {
      if (state.selection) jumpTo(state.selection);
      else renderList();
    };

    $("#verseList").addEventListener("click", (e) => {
      const v = e.target.closest("[data-verse]");
      if (v) return selectVerse(Number(v.dataset.verse));
      const r = e.target.closest("[data-result]");
      if (r) {
        const res = state.results[Number(r.dataset.result)];
        jumpTo(makeRef(res.book, res.chapter, res.verse, null));
        state.selection = makeRef(res.book, res.chapter, res.verse, null);
        stage(state.selection, { silent: true });
        renderList();
        return;
      }
    });

    $("#queueList").addEventListener("click", (e) => {
      const go = e.target.closest("[data-qgo]");
      if (go) {
        goLive(state.queue[Number(go.dataset.qgo)]);
        return;
      }
      const sel = e.target.closest("[data-qselect]");
      if (sel) {
        const ref = state.queue[Number(sel.dataset.qselect)];
        jumpTo(ref);
        stage(ref, { silent: true });
      }
    });

    $("#recentList").addEventListener("click", (e) => {
      const btn = e.target.closest("[data-recent]");
      if (!btn) return;
      const ref = state.recent[Number(btn.dataset.recent)].ref;
      jumpTo(ref);
      stage(ref, { silent: true });
    });

    $("#outputThumb").onclick = () => {
      if (state.onAir) openOutput();
    };

    $("#themeList").addEventListener("click", (e) => {
      const card = e.target.closest("[data-theme]");
      if (!card) return;
      const preset = PRESETS.find((p) => p.id === card.dataset.theme);
      if (preset) {
        applyPreset(preset);
        renderThemeList();
      }
    });

    document.addEventListener("click", (e) => {
      if (bookMenu && !bookMenu.contains(e.target) && !e.target.closest("#bookBtn")) closeBooks();
      if (chapterMenu && !chapterMenu.contains(e.target) && !e.target.closest("#chapterJump")) closeChapters();
    });

    document.addEventListener("keydown", (e) => {
      const typing = /^(INPUT|SELECT|TEXTAREA)$/.test(document.activeElement.tagName);

      if (e.key === "Escape") {
        if (state.sheet) closeSheet();
        closeBooks();
        closeChapters();
        return;
      }
      if (e.key === "Tab") {
        e.preventDefault();
        input.focus();
        input.select();
        return;
      }
      if (typing) return;

      const k = e.key.toLowerCase();
      if (k === "l") { $("#liveBtn").click(); }
      else if (k === "m") { $("#sttBtn").click(); }
      else if (k === "b") { blackout(); }
      else if (k === "c") { clearQueue(); clearOutput(); toast("Cleared"); }
      else if (k === "o") { openOutput(); }
      else if (e.key === "ArrowLeft") { stepChapter(-1); }
      else if (e.key === "ArrowRight") { stepChapter(1); }
      else if (e.key === "Enter") { sendCurrent(); }
      else if (e.key === "F11") {
        e.preventDefault();
        const bridge = nativeBridge();
        if (bridge && bridge.output_fullscreen) bridge.output_fullscreen();
      }
    });
  }

  /* ─────────── host bridge ─────────── */

  // Called by the desktop host: both speech engines converge on these.
  window.verseHeard = (text, final) => handleHeard(text, !!final);

  window.verseSttState = (status, note) => {
    state.stt.status = status || "idle";
    state.stt.note = note || "";
    if (status === "error") {
      toast(note || "Speech engine error");
      setListening(false);
    }
    if (status === "loading" || status === "working" || status === "listening") {
      if (status === "loading") state.stt.heard = "";
      renderHeard();
    }
    // The host stopped by itself (mic unplugged, model gone): keep the button
    // honest instead of showing "Listening" over a dead engine.
    if (status === "stopped" && state.stt.running) setListening(false);
  };

  window.verseSttError = (message) => {
    toast(String(message || "Speech engine unavailable"));
    setListening(false);
  };

  window.verseLevel = (value) => {
    state.stt.level = Number(value) || 0;
    paintLevel(state.stt.level);
  };

  window.verseModelProgress = (fraction, note) => {
    state.model.downloading = fraction < 1;
    state.model.progress = Number(fraction) || 0;
    if (state.sheet === "transcription") renderSheet();
  };

  window.verseModelDone = (ok, error) => {
    state.model.downloading = false;
    state.model.progress = ok ? 1 : 0;
    toast(ok ? "Speech model ready" : `Download failed: ${error || "unknown error"}`);
    // A finished fast-model download is what the instant pipeline was waiting
    // for; tell the host now rather than at the next Listen.
    const api = nativeBridge();
    if (ok && state.settings.instantPipeline !== false && api && api.stt_set_instant) {
      api.stt_set_instant(true).catch(() => {});
    }
    refreshStatus();
  };

  window.verseNdiState = (status) => {
    refreshStatus();
    if (status === "sending") toast("NDI stream started");
    if (status === "error") toast("NDI could not start — see Settings → Output");
  };

  // The host's memory watchdog calls these.
  window.verseTrim = (level) => trimMemory(level);
  window.versePressure = (level) => {
    if (level === "hard") toast("Memory high — released caches");
  };
  window.verseNotice = (text) => toast(String(text || ""));

  window.verseWarm = (ok, seconds, note) => {
    state.warm = { ok: !!ok, seconds: Number(seconds) || 0, note: note || "" };
    if (state.sheet === "detection") liveSheet();
  };

  window.verseDetectProgress = (kind, fraction, note) => {
    state.detectProgress = { kind, fraction: Number(fraction) || 0, note: note || "" };
    if (state.sheet === "detection") liveSheet();
  };

  window.verseDetectDone = (kind, ok, note) => {
    state.detectProgress = null;
    toast(ok ? `${kind === "rerank" ? "Cross-encoder" : "Embedding model"} installed` : `Install failed: ${note}`);
    refreshStatus();
  };

  window.verseIndexProgress = (translation, fraction, note, done, total, rate, eta) => {
    state.indexProgress = {
      translation,
      fraction: Number(fraction) || 0,
      note: note || "",
      done: Number(done) || 0,
      total: Number(total) || 0,
      rate: Number(rate) || 0,
      eta: Number(eta),
    };
    if (state.sheet === "detection") liveSheet();
  };

  window.verseIndexDone = (translation, ok, note) => {
    state.indexProgress = null;
    toast(ok ? `${translation.toUpperCase()} verses are ready to search` : `Build failed: ${note}`);
    refreshStatus();
  };

  function refreshStatus() {
    const api = nativeBridge();
    if (!api) return;

    if (api.stt_status) {
      api.stt_status()
        .then((s) => {
          if (!s) return;
          state.model.ready = !!s.model;
          state.model.mb = s.model_mb || 0;
          state.model.downloading = !!s.downloading;
          if (s.model_name) state.model.name = s.model_name;
          if (s.model_expected_mb) state.model.expected = s.model_expected_mb;
          state.instant.ready = !!s.instant_ready;
          state.instant.mb = s.instant_mb || 0;
          state.instant.active = !!s.instant_active;
          if (s.instant_name) state.instant.name = s.instant_name;
          if (s.instant_expected_mb) state.instant.expected = s.instant_expected_mb;
          state.stt.deviceName = s.device_name || "";
          // The host starts on Whisper; a saved Vosk choice has to be told to it
          // once, and never while a session is running.
          if (
            s.local_engine && api.stt_set_local_engine && !s.running &&
            s.local_engine !== (state.settings.localEngine || "whisper")
          ) {
            api.stt_set_local_engine(state.settings.localEngine || "whisper").catch(() => {});
          }
          if (state.sheet && ["transcription", "usage"].includes(state.sheet)) liveSheet();
        })
        .catch(() => {});
    }

    if (api.memory_report) {
      api.memory_report()
        .then((m) => {
          state.memory = m;
          if (state.sheet === "usage") liveSheet();
        })
        .catch(() => {});
    }

    if (api.stt_devices) {
      api.stt_devices()
        .then((d) => {
          if (!d || !d.devices) return;
          state.devices = d.devices;
          if (state.sheet === "transcription") liveSheet();
        })
        .catch(() => {});
    }

    if (api.ndi_status) {
      api.ndi_status()
        .then((n) => {
          state.ndi = n;
          if (state.sheet === "output") liveSheet();
        })
        .catch(() => {});
    }

    if (api.detection_status) {
      api.detection_status()
        .then((d) => {
          state.detect = d;
          if (state.sheet === "detection") liveSheet();
        })
        .catch(() => {});
    }

    if (api.perf_report && state.sheet === "performance") {
      api.perf_report()
        .then((p) => {
          state.perf = p;
          liveSheet();
        })
        .catch(() => {});
    }
  }

  // Re-render a settings page only when its numbers actually changed and the
  // user is not typing in one of its fields.
  let lastSheetSignature = "";
  function liveSheet() {
    if (!state.sheet || document.activeElement && /INPUT|TEXTAREA|SELECT/.test(document.activeElement.tagName)) return;
    const signature = JSON.stringify({
      page: state.sheet,
      model: state.model,
      stt: state.stt.heard,
      mem: state.memory && [state.memory.total_mb, state.memory.peak_mb],
      ndi: state.ndi && [state.ndi.running, state.ndi.fps, state.ndi.frames],
      instant: state.instant,
      detect: state.detectProgress || (state.detect && [
        state.detect.stack && state.detect.stack.semantic && state.detect.stack.semantic.loaded,
        state.detect.release_when_idle,
        state.detect.prewarming,
        state.detect.installing,
        state.detect.building,
      ]),
      warm: state.warm,
      perf: state.perf && state.perf.summary && [
        state.perf.summary.performance_grade,
        state.perf.summary.total_events,
        state.perf.recommendations && state.perf.recommendations.length,
      ],
    });
    if (signature === lastSheetSignature) return;
    lastSheetSignature = signature;
    renderSheet();
  }

  let statusTimer = null;
  function watchStatus() {
    clearInterval(statusTimer);
    statusTimer = setInterval(() => {
      if (state.sheet || state.stt.running) refreshStatus();
    }, 2500);
  }

  // pywebview injects its API after first paint.
  window.addEventListener("pywebviewready", () => {
    const api = nativeBridge();
    if (!api) return;
    if (api.stt_set_engine) api.stt_set_engine(state.settings.sttEngine).catch(() => {});
    if (api.stt_set_local_engine) {
      api.stt_set_local_engine(state.settings.localEngine || "whisper").catch(() => {});
    }
    if (api.stt_set_device) {
      // 0 is a valid device index; `|| -1` would quietly turn it into automatic.
      const mic = Number(state.settings.micDevice);
      api.stt_set_device(Number.isFinite(mic) ? mic : -1).catch(() => {});
    }
    if (api.ndi_set_name) api.ndi_set_name(state.settings.ndiName).catch(() => {});
    if (api.stt_set_instant) {
      api.stt_set_instant(state.settings.instantPipeline !== false).catch(() => {});
    }
    if (api.detection_set_idle_release) {
      api.detection_set_idle_release(state.settings.releaseWhenIdle !== false).catch(() => {});
    }
    if (api.set_output_mode) api.set_output_mode(state.settings.outputMode, Number(state.settings.display) || 0).catch(() => {});
    if (api.stt_status) {
      api.stt_status()
        .then((s) => {
          if (!s) return;
          state.model.ready = !!s.model;
          state.model.mb = s.model_mb || 0;
          state.stt.deviceName = s.device_name || "";
        })
        .catch(() => {});
    }
    refreshStatus();
  });

  /* ─────────── boot ─────────── */

  load();
  normaliseTranslation();
  applyThemeVars();
  wire();
  syncTranslationSelect();
  watchStatus();
  wireInspector();
  renderAll();
  renderThemeList();
  input.value = "";

  // Deep links: ?ref=John%203:16&live=1 and ?view=themes
  const params = new URLSearchParams(location.search);
  const view = params.get("view");
  if (view === "themes") setView("themes");
  const refParam = params.get("ref");
  if (refParam) {
    const hit = E.asReference(refParam) || E.detect(refParam)[0];
    if (hit) {
      const ref = E.clamp(hit);
      jumpTo(ref);
      if (ref.verseStart != null) stage(ref, { silent: true });
      if (params.get("live") === "1") goLive(ref);
    }
  }

  // A translation remembered from last time is fetched now, in the background:
  // the KJV is already on screen, so nothing waits for it.
  if (state.settings.translation !== "kjv") {
    selectTranslation(state.settings.translation, { quiet: true });
  }

  setTimeout(() => input.focus(), 60);

  window.VerseApp = {
    state, E, goLive, jumpTo, selectVerse, slideHTML, selectTranslation,
    refreshStatus, TRANSLATIONS,
  };
})();
