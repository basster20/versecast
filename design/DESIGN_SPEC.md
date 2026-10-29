# Pewbeam → clone design spec (pass 1: shots 1–8)

Source: 8 screenshots of **Pewbeam** (worship presentation app), captured 2026-10-22.
All hex values below were **sampled from the pixels** with `design/sample_colors.py` and
`design/measure.py` (not eyeballed). Fractions of a screen are exact fills where noted.

> Status: this workspace currently holds only the VerseListener analysis. No clone code exists
> on disk yet — this document is the target spec for building it.

---

## 1. Palette (sampled)

| Token | Hex | Where it appears | Confidence |
|---|---|---|---|
| `bg.deep` | `#0c0b0b` | gallery canvas behind modal, theme-card caption strip (99.9% fill) | exact |
| `bg.app` | `#111010` | main canvas of Theme Designer, app shell | exact |
| `bg.backdrop` | `#131111` | dimmed content behind the Settings modal | exact |
| `bg.panel` | `#161414` | inspector panel, library sidebar, settings right pane (72–99% fill) | exact |
| `surface.1` | `#1e1c1c` | inputs, dropdowns, cards, search fields, secondary buttons, modal card | exact |
| `surface.2` | `#252323` | divider/1px lines, hover, idle segment of a control | exact |
| `surface.3` | `#312f2d` | selected segment chip, pressed state | exact |
| `border.subtle` | `#413e3c` | faint 1px outline on raised controls | exact |
| `text.primary` | `#ffffff` | headings, labels, CTA text | exact |
| `text.secondary` | `#b7b3b0` | row descriptions, "ALL THEMES (7)" | exact |
| `text.tertiary` | `#908d8a` | input placeholders ("Search themes") | exact |
| `text.disabled` | `#706f6f` | inactive nav/labels | exact |
| `accent` | `#ff5700` | primary CTA, active nav, selected tab underline, toggle-on | exact (80% flat fill in the Auto chip) |
| `accent.press` | `#e04d00` | pressed CTA ("Publish to Pewnote" fill) | exact |
| `accent.disabled` | `#7b310a` | "Save changes" when unchanged (shot 6) | sampled |
| `slide.text` | `#f0f4f9` | verse text rendered on the slide (cool white, not pure white) | exact |
| `theme.blue` | `#002fc6` | Selah theme slide background | exact |
| `theme.green` | `#154e3b` | third theme thumbnail | exact |
| `theme.gradient` | `#cda76f → #a8753c` | "Motion 1" theme (warm gradient) | sampled, approximate |

Rule of thumb: the UI is monochrome charcoal + **one** orange. Never introduce a second accent;
semantic states use opacity/`surface.*` steps, not new hues.

## 2. Type

- Family: geometric sans with a single-storey `a` in the UI chrome; the rendering is consistent
  with **Poppins / Inter-class** faces. *Not confirmed* — would need the app's font files.
- Slide typography is separately configurable (Font / Weight / Size / Line height / Letter
  spacing), i.e. a **title+body pair** rendered inside a text box.
- Observed scale (shots are 1:1 px, ~1900×1000 window):
  page/window title 22–24 px semibold · section header 16–17 px medium · row label 15 px medium ·
  row description 13.5 px regular in `text.secondary` · control value 14 px · caption/table head
  11 px uppercase with ~0.06em tracking in `text.tertiary`.

## 3. Geometry (measured)

| Element | Size | Notes |
|---|---|---|
| Primary CTA ("Save changes") | **164 × 60** | radius ~12, label 15 px semibold |
| Publish CTA | **227 × 45** | radius ~12 |
| Segmented chip ("Auto") | **73 × 47** | radius ~10–12, active = `accent` + white text |
| Toggle switch | **75 × 40** | fully rounded pill, knob white, on = `accent` |
| Input / dropdown | height **52** | radius 10, fill `surface.1`, no visible border until focus |
| Number field | height 52 | inline prefix letter (`X`, `Y`, `W`, `H`) in `text.tertiary` at 24 px inset |
| Sidebar width | ~300 px | library column |
| Inspector width | ~460 px | right column, scrollable |
| Card | ~420 × 300 thumbnail + 56 px caption row | selected = 1–2 px `accent` ring, radius ~10 |
| Section header | 56 px tall | title left, chevron right, optional eye (visibility) icon |
| Spacing grid | 8 / 12 / 16 / 24 / 32 | section padding 24 |

## 4. Component inventory to build

1. **AccordionSection** — title + chevron + optional eye toggle, 1px `surface.2` separator.
2. **SegmentedControl** — icon or text segments in a `surface.1` trough; active segment `surface.3`
   (inspector layout) or `accent` (Settings Auto/Manual). Two visual variants; keep both.
3. **LabeledField** — label above, control below; two-column grid for X/Y and W/H.
4. **NumberField** — prefix glyph + value, right-aligned unit (`px`).
5. **ColorField** — swatch (rounded 6) + `#hex` + separate opacity `%` sub-field, joined into one
   `surface.1` bar with a vertical divider.
6. **ToggleSwitch** — custom-painted; knob animates 120 ms.
7. **Slider** — 6 px `surface.2` track, thin ticks every 1/10, white handle with value bubble
   on the right; value also printed at the track end.
8. **ThemeCard** — thumbnail with centered verse preview + caption row (`#0c0b0b`) with name and
   a `⋯` menu button; lock badge for non-editable themes.
9. **TabBar** — text tabs, active gets 2 px `accent` underline spanning the label.
10. **GalleryTile** — icon-on-top + uppercase wrapped caption (`Content Studio`), `surface.1`.
11. **PrimaryButton / SecondaryButton / IconButton / PillBadge** (plan badge: white pill, dark text).
12. **SettingsRow** — label + description left, control right, 1px `surface.2` divider, 64–72 px.

## 5. Screen anatomy (what to replicate)

**Theme Designer (shots 1, 6)** — native Windows title bar + menu bar (`File Edit View Audio
Window Help`), then a custom header: title bottom-left, `Save changes` + `Close` top-right.
Three columns: left = `New / Import / Export` button row, "ALL THEMES (7)", search field, card
list (scrolling); center = `#111010` canvas with a subtle dot grid, floating toolbar pill
(undo, redo, separator, T, layers, fill, person, grid), the slide preview with a blue selection
frame + 8 handles, and a zoom pill at the bottom (zoom-out, scrubber, zoom-in); right = inspector.

**Inspector (shots 2–5)** — `Verse 🔗` header (the 🔗 links the slide to the verse reference),
then `Layout` (Alignment: 6 icon buttons — 3 horizontal + 3 vertical in two troughs; Position X/Y;
Dimension W/H; Reference gap; `Lock aspect ratio` checkbox in accent) → `Scripture` (Font, Weight,
Size, Line height, Letter spacing, Color+opacity, horizontal+vertical text alignment) → `Effects`
(Drop Shadow: position, blur, color+opacity, eye toggle per effect; Outline: position
Outside/Center/Inside, width px, style, color) → `Reference` (collapsed in these shots; **content
not captured** — needs a follow-up screenshot).

**Content Studio (shot 7)** — header `Content Studio` + `Close`; left column: "What will you like
to create today?", five gallery tiles (Sermon note, Newsletter, Daily devotional, Tract material,
Church publication), then `Contents | Transcripts` tabs with `Publish to Pewnote` CTA on the same
row, a search field, then a table (`TITLE` / `DATE CREATED`) — empty state uses uppercase headers
in `text.tertiary`.

**Settings (shot 8)** — modal sheet over a dimmed `#131111` backdrop; left nav with outline icons
(Account, Scripture, Audio, Language, Usage, Referrals, Help, Send feedback), active item is
`accent` icon + text; bottom plan card (`Free Plan` + white `Upgrade` pill) and `version 2.6.14`;
right pane = rows: `Verse display Mode` (Auto/Manual segmented), `Primary translation` (dropdown,
rendered empty in this shot), `Original Languages word study` (toggle on), `Follow the service`
(description + `Suggest` dropdown), `Bible translations` (row + link).

## 6. Gap analysis — what the clone must change

| Area | Current clone state | Target |
|---|---|---|
| Colors | VerseListener's own theme (navy/`#d4d8e8`, gold `#fbbf24` highlight) | Pewbeam charcoal ramp above, single `#ff5700` accent |
| Highlight of a spoken reference | gold pill behind the reference | keep the *idea*, restyle: `accent` at 18% alpha + 2 px left bar, or accent underline |
| Layout | single-window transcript + queue | 3-pane shell: library / canvas / inspector, header with CTA + Close |
| Controls | stock QSS buttons and inputs | custom-painted toggle, slider, segmented control, color field |
| Typography | default Qt font stack | one family, 5-step scale, uppercase tracked captions |
| Icons | none / text glyphs | 1.5 px stroke outline set at 20–24 px |
| Theme system | hardcoded hexes | `tokens.py` → QSS generator; light theme derivable later |
| Slide preview | plain `QTextEdit` | canvas with dot grid, selection handles, zoom pill |
| Settings | tabs in a dialog | modal sheet with left nav + row layout and plan footer |
| Copy tone | "Verse detected" | sentence-case titles, `text.secondary` descriptions under every setting |

## 7. Still needed from the follow-up screenshots

1. `Reference` inspector section (collapsed here) — fields and defaults.
2. The main **live** screen: scripture search/list, detected-verse queue, "follow the service"
   suggestion UI (the closest analogue to our detector output).
3. Slide/live output view and how a verse is searched by reference (the actual search field).
4. Hover/pressed/disabled states, focus rings, and any light theme.
5. Dropdown menus and the `⋯` card menu (items + styling).
6. Window at a smaller size — whether the inspector collapses.
7. Font names if visible (Settings → Language or a font dropdown open).

---

# Pass 2 (shots 9–15): the live screen + settings sub-pages

Sampled with `design/sample_pass2.py` and `design/measure_pass2.py`.

## 8. New tokens

| Token | Hex | Evidence |
|---|---|---|
| `signal.live` | `#ff383c` | LIVE button, 90% flat fill |
| `signal.success` | `#00e05f` | "Start transcribing" label (`#08ec66` / `#00de3e` pixels) |
| `surface.onAir` | `#331100` | Live-display block **and** the selected verse row — 84–93% flat |
| `surface.keycap` | `#252323` | shortcut key badges |
| `text.onKeycap` | `#e3e0de` | keycap and voice-command chip labels |
| `text.disabledBtn` | `#787777` | `+ Add` when no phrase entered |
| `panel.gutter` | `#111010`, **6–7 px** | the space *between* panels, not a border |

Still exactly one orange (`#ff5700`) for interaction, plus two **semantic** colors that are not
accent: red `#ff383c` = live/on-air, green `#00e05f` = start/health. The on-air tint `#331100` is
a fixed burnt-orange surface (it is not accent-at-alpha — sampled flat).

## 9. Main screen anatomy (shot 15, 1919×1079)

Measured column boundaries at y=0.30H: panels sit at **x 8–324, 334–727, 736–1428, 1437–1912**
with 6–7 px gutters of `#111010`; every panel is `#161414` with rounded corners (~10 px) and
**no border** — separation comes from the gutter alone.

**Top bar** — left: `Scriptures` (active, `#ff5700` pill, radius ~14) `Slides` `Songs` at 22 px
semibold; centre: `● LIVE` (red `#ff383c`) `BLACK` `CLEAR` (`#312f2d`, uppercase, radius ~14);
right: six icon-above-label buttons (Outputs, Themes, Studio, Alerts, Get help, Settings), icon
~22 px, caption ~10 px in `#b7b3b0`, group background `#201e1e`.

**Panel 1 — Live transcript**: title 17 px white + expand icon; empty body; footer
`🌿 Start transcribing` in green + a 44 px circular stop button (`#1a1818`, white 12 px square).

**Panel 2 — Recent detections**: title + `× Clear all` tertiary link. This is the direct analogue
of our verse queue.

**Panel 3 — Live display**: the on-air block is `#331100` with a 2 px accent line under it;
reference `GENESIS 1:1 (NIV)` uppercase ~12 px tracked, body 16 px white, 24 px padding.

**Panel 4 — right column**: `Main Output ⌄` + `TRADITIONAL` in `#6e6b68` uppercase 11 px;
16:9 slide thumbnail with black letterbox; `Lexicon` button with prev/next chevrons; then a
`Queue` panel with `× Clear all`.

**Bottom row** — reference search: translation dropdown (`#252323`, 60 px, chevron), two square
icon buttons (book, history), the input (`#252323`, 60 px, radius 10) holding `Genesis 1:1`,
prev chevron, and a **white filled circular next** button. Below: `GENESIS 1` in `#b7b3b0`
uppercase; verse rows are 60 px `#161414` rounded cards; the selected row is `#331100` with a
1 px `#ff5700` outline and white text; truncated rows end with `…`.

**Preview panel** — same 16:9 slide as Main Output, header `Preview` + expand icon.

**Help → Keyboard shortcuts (shot 14)**: `Toggle search mode → Tab`, `LIVE toggle → L`,
`Clear output → C`, `Blackout → B`, `Previous/next chapter → ‹ / ›`, `Go live → Enter ×2`.
Keycaps: `#252323`, radius 6, 1 px `#312f2d` border, label `#e3e0de`.

## 10. Settings sub-pages (shots 9–13)- **Shell** (corrected in pass 3, shot 16): left nav is the *darker* surface `#161414`, the content
  pane is one step *lighter* `#1e1c1c`. Backdrop behind the sheet is a flat `#131111`.
- **Rows** are 88–100 px: label 15 px white + description 13.5 px `#b7b3b0`, control right-aligned,
  divider one step lighter than the pane (`#252323` on `#1e1c1c`).
- **Segmented** (`Cloud` / `On-device`): trough `#252323`, active chip `#ff5700` radius 10, inactive
  label `#d6d3d0`.
- **Translation groups**: `#1e1c1c` card, flag emoji + language name, right side
  `Download all (6.5 MB)` bold white + chevron. Rows: `KJV · King James Version` left, a circular
  outline **check** when installed, a **tray/download** glyph when not. Nested card-on-card.
- **Audio**: mic dropdown `#1e1c1c` with `9 devices available` as the row description; `Start test`
  and `Turn off` are secondary buttons (`#1e1c1c`, radius 10); input-volume slider is 6 px with
  tick marks and a `0 dB` readout; input-level meter is a row of thin grey ticks (`#312f2d`).
- **Premium gating**: a small lock glyph beside a row (`Noise cancellation`) instead of disabling it.
- **Voice commands**: `COMMANDS` uppercase tracked label, example chips (`give me NIV`,
  `switch to ESV`, `use King James`), then `CUSTOM COMMANDS` with phrase input + action dropdown +
  `+ Add` disabled until text is entered.
- **Language**: open dropdown is `#1e1c1c` with shadow; the selected item (`English`) is `#ff5700`.
  Language packs are `#252323` cards with flag, `LSG & OST`, and a `Download (93.1 MB)` button.
- **Plan footer**: pill row `Free Plan` + white `Upgrade` pill, `version 2.6.14` in `#6e6b68`.

## 11. Gap analysis, updated for the live screen

| Area | Target (from shot 15) |
|---|---|
| Shell | 4-column grid: transcript, detections, on-air display, output+queue; bottom-left reference browser; bottom-right preview |
| Listening control | `LIVE` red pill (dot + label) replaces our toggle; `BLACK` = clear output, `CLEAR` = clear queue |
| Detection output | "Recent detections" list + on-air block with `#331100` tint and 2 px accent underline |
| Verse search | reference field + translation dropdown + book/history buttons + prev/next; chapter header + selectable verse rows (`#331100` + accent outline) |
| Transcript | panel with expand icon, green start affordance, circular stop, partial text dimmer/italic than finals |
| Shortcuts | `Tab` search mode, `L` live, `C` clear, `B` black, `‹ ›` chapter, `Enter ×2` go live — surfaced in Help as keycaps |
| Settings | modal sheet, left icon nav with accent active item, row pattern, segmented control, keycap table, plan footer |

## 12. Still missing (send if you have them)

1. **Populated** transcript + detections (so I can see how a detected reference is styled in the
   list and how "confidence" or timing metadata looks, if any).
2. The `Slides` and `Songs` tabs.
3. `Account`, `Usage`, `Referrals` settings pages.
4. Dropdown/menu open states (`⋯` on a theme card, the translation picker).
5. Hover / focus / pressed states, and a disabled CTA example.
6. The Lexicon / original-languages panel.
7. Any light theme, if one exists.

---

# Pass 3 (shot 16): Settings → Account, and the modal shell

## 13. Modal container (measured, 1907×1027 frame)

| Property | Value |
|---|---|
| Sheet bounds | x 265→1631, y ~97→940 → **1366 × 843**, radius ~14 |
| Left nav | 435 px wide, `#161414` |
| Content pane | `#1e1c1c` |
| Backdrop | flat `#131111` (the app is dimmed, not blurred) |
| Header | 100 px: page title 22 px white left, close ✕ 22 px right, 1 px divider under |
| Nav item | 44 px tall, 24 px gutter, icon 20 px + label 15 px; active = `#ff5700` icon **and** label |
| Plan footer | outlined pill `#161414` + white `Upgrade` pill, `version 2.6.14` in `#6e6b68` |

## 14. Two rules this shot adds

1. **Fields invert against their parent surface.** On a `#161414` panel the input is `#252323`
   (search, translation dropdown); on a `#1e1c1c` pane the input is `#161414` (license key field).
   Always one step away from the parent — never a fixed field color.
2. **Disabled primary is a darkened accent, not grey.** `Activate license` fills `#80350e`
   (≈ `#ff5700` × 0.5) with a lighter orange label, and stays fully readable. Greyed-out
   `#252323` is reserved for *unavailable* controls (`+ Add` before typing), never for CTAs.

## 15. Account page pattern

Row 1 `Account` / *Sign in to connect to your church* → `Sign up` text link + `Sign in` accent
pill (116 × 45, radius 12). Row 2 `Current plan` / *Your active subscription plan* → the value
right-aligned as plain white text (`Pewbeam Free`), no control. Row 3 `License key` / *Enter
license key to unlock all features* → full-width field (65 px) with grouped placeholder
`XXXX-XXXX-XXXX-XXXX` + disabled `Activate license` beside it, then an inline sentence with an
accent underlined link: *Don't have a license key? **Get a license key***.

Note: the frames are **video-derived**, so flat fills drift ±1 ramp step between frames (the same
button reads `#ff5700`, `#f65400`, `#e04d00` across shots). Implement the ramp as sampled and
treat 7-level differences as noise.
