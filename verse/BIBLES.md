# Bibles bundled with Verse

Verse only ships Bibles it is allowed to redistribute. Each entry below names the
edition, its source and its copyright line. The same notices appear in Settings →
Translations, because that is where most people will look.

If you redistribute this folder, keep this file with it.

---

## King James Version — KJV — English

The Authorised (King James) Version, 1611. **Public domain.**

Text via [farskipper/kjv](https://github.com/farskipper/kjv), as bundled with VerseListener.
File: `assets/js/data.js`.

---

## World English Bible — WEB — English

The World English Bible (Protestant edition, `engwebp`). **Public domain.**

Source: [ebible.org/engwebp](https://ebible.org/engwebp/).
File: `assets/js/data.web.js`.

---

## Biblica® Open Yoruba Contemporary Bible — YOR — Yorùbá

> Biblica® ní oore ọ̀fẹ́ láti lo Bíbélì Mímọ́ ní Èdè Yorùbá Òde-Òní™
> Copyright © 2009, 2017 Biblica, Inc.
>
> Biblica® Open Yoruba Contemporary Bible™
> Copyright © 2009, 2017 by Biblica, Inc.
>
> “Biblica” is a trademark registered in the United States Patent and Trademark
> Office by Biblica, Inc. Used with permission.
>
> This work is made available under the Creative Commons
> Attribution-ShareAlike 4.0 International License (CC BY-SA 4.0). To view a copy
> of this license, visit <https://creativecommons.org/licenses/by-sa/4.0/>.
> The original work by Biblica, Inc. is available for free at
> [www.biblica.com](https://www.biblica.com) and [open.bible](https://open.bible).

Distributed **unmodified** — the text is converted from eBible.org's
verse-per-line edition (`yor_vpl.zip`, <https://ebible.org/find/details.php?id=yor>)
with no wording changes. The Biblica® trademark is retained because the text is
unmodified, as the licence requires.

File: `assets/js/data.yor.js`.

---

## Biblica® Open Igbo Contemporary Bible — IGB — Igbo

> Biblica® Baịbụlụ Nsọ nʼIgbo Ndị Ugbu a nke dịrị onye ọbụla ịgụ™
> Ndị Biblica, Inc. degharịrị ya nʼafọ © 1980, 1988, 2019, 2020
>
> Biblica® Open Igbo Contemporary Bible™
> Copyright © 1980, 1988, 2019, 2020 by Biblica, Inc.
>
> “Biblica” is a trademark registered in the United States Patent and Trademark
> Office by Biblica, Inc. Used with permission.
>
> This work is made available under the Creative Commons
> Attribution-ShareAlike 4.0 International License (CC BY-SA 4.0). To view a copy
> of this license, visit <https://creativecommons.org/licenses/by-sa/4.0/>.
> The original work by Biblica, Inc. is available for free at
> [www.biblica.com](https://www.biblica.com) and [open.bible](https://open.bible).

Distributed **unmodified**, converted from
`ibo_vpl.zip` (<https://ebible.org/details.php?id=ibo>).

File: `assets/js/data.ibo.js`.

---

## Bibles that are *not* bundled — NIV, NKJV, ESV, NASB, NLT…

These are copyrighted and licensed per publisher. They may not be copied into
this project or handed on to anyone else, so Verse cannot ship them. If you own
a licence and have the text in a file, import it into **your own build**:

```bash
python tools/build_translation.py --json my-bible.json \
  --id niv --short NIV --title "New International Version" \
  --language English --licence "Used under my own licence" --source "my copy"
```

`my-bible.json` is a flat map — `{"Genesis 1:1": "In the beginning…", …}` — one
entry per verse, `Book Chapter:Verse` keys, 66 books. The command writes
`assets/js/data.niv.js`; add an entry for it to `assets/js/translations.js` and it
appears in the translation picker. Keep that build to yourself: distributing it
would breach the publisher's licence.

Deleting the generated `data.<id>.js`, its `translations.js` entry and this file's
record removes the translation cleanly.

---

## Where the texts came from

All four bundled editions were downloaded from [eBible.org](https://ebible.org/),
which publishes public-domain and Creative-Commons Bibles in USFM, VPL and other
formats, and converted with `tools/build_translation.py`. The converter only
reads the 66-book canon; superscription lines and any deuterocanonical books in a
source file are skipped.
