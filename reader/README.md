# EPUB Reader (Flask + epub.js)

EPUB ebook reader served by Flask and rendered in the browser with
[epub.js](https://github.com/futurepress/epub.js). The goal is to get closer
to the experience of EPUB editors such as [Sigil](https://sigil-ebook.com),
replicating some of their features that are useful for reading and inspecting
files: server-side library, view controls, an EPUB package browser and an
HTML editor for the chapters (same features as the standalone Nim/WebView2
version in `Nimcode/epub_editor`, with the Flask backend replacing the bridge).

## Run

```bash
python3 app.py            # http://127.0.0.1:5000
python3 app.py --port 8080
python3 app.py --debug
```

On first start a sample book (*Alice's Adventures in Wonderland*) is downloaded
and saved to `static/book.epub`.

## Features

### Server-side library (no client file picker)
Books are not opened from the client's disk: the server exposes
`GET /api/books`, which lists the `.epub` files in `static/`. The **Library**
button in the toolbar opens a left sidebar listing the books (title extracted
from each EPUB's OPF metadata, size and filename); clicking a book opens it
and the current book is highlighted. Just drop an `.epub` into `static/` and
reload the page to see it appear.

### Single page / two-page spread
The **Single page / Two pages** button switches at runtime between
`rendition.spread("none")` and `rendition.spread("auto")`, without reloading
the book.

### Container max width
The **Max page width** selector sets the reading area's max width as a
percentage of the screen (40% to 100%), to avoid overly long lines on very
wide monitors or tablets. The layout is recalculated immediately via
`rendition.resize()`.

### EPUB package browser (Sigil-style)
The **Files** button opens a sidebar listing all files included in the EPUB's
manifest, grouped by type (Documents, Styles, Images, Fonts, Scripts,
Audio/Video, Other):

- documents that are part of the **spine** (reading order) are clickable:
  clicking one navigates to that document in the reader;
- the current file is highlighted automatically on every page change;
- the sidebar closes with the ✕ button or with `Esc`.

### Chapter HTML editor
Two tabs, **📖 Read** and **✏️ Edit HTML**, switch between the paginated viewer
and a code editor showing the current chapter's source (loaded from the EPUB
archive in memory via `book.archive.request`). The toolbar also has a **Pad %**
input that overrides the default padding with a percentage of the page width
(re-applied with a MutationObserver whenever epub.js rewrites the inline style).

- **Save** (`POST /api/save_chapter`) rewrites the `.epub` on disk, replacing
  the current chapter entry with the edited content (zip rebuilt preserving the
  other entries' metadata, atomic write via `.tmp` + `os.replace`);
- after a successful save the chapter is re-rendered in the viewer **without
  reloading the book**: the client patches the in-memory `book.archive` and
  invalidates the section/view caches (`updateChapterDom()`), the same trick
  used by `updateChapterDomJs` in the Nim version;
- the server validates the book name (basename only) and the entry path (no
  `..` traversal) before touching the file.

### Content zoom (A+ / A− / 100%)
The **A+**, **A−** and **100%** buttons zoom the EPUB reading content without
enlarging the browser chrome (toolbar, tabs, sidebars) or overflowing the
viewport.

The original implementation applied CSS `zoom` to `documentElement`
(`:root`), which scaled the **entire page** including `<body>` (whose
`height:100dvh` also scaled), forcing the viewer to grow beyond the screen.
A counter-zoom (`zoom:1/Z`) was applied to every chrome element to keep them
visually unchanged — it worked, but the layout viewport still overflowed on
zoom-in because the body's CSS-pixel height grew with the zoom factor.

The fix moves the CSS `zoom` from `:root` to the `#viewer` element only.
Because `#viewer` is a flex child with `flex:1`, its layout box is determined
by the flex algorithm and **does not change** when CSS `zoom` is applied to
it — `zoom` only affects visual rendering, not the element's own layout
metrics (`clientWidth`/`offsetWidth`).  The chrome elements are never zoomed
and need no counter-zoom.  `#viewer` uses `overflow:auto`, so any content
that extends beyond the viewer box after zoom-in can be scrolled.

epub.js measures the container via `clientWidth`/`offsetWidth`, which return
CSS-pixel dimensions **before** the element's own CSS `zoom` is applied, so
column pagination remains correct at every zoom level.

### In-chapter text search
The **lens** button opens a search bar that scans the current chapter and
wraps every match in a `<mark>` element, listing results as `n/total` with
previous/next navigation.

## Critical fixes

These fixes address deep interactions between the UI layer and epub.js's
internals; they are documented here because regressing any of them would
subtly break reading-position or pagination behaviour.

### Search-result navigation must go through epub.js (CFI-first) — FUNDAMENTAL

**Symptom.** Clicking a search result scrolled the view to the match, but in
two-page spread mode the viewport showed two full pages *plus a sliver of a
third*, and epub.js's internal location state desynced from what was on
screen.

**Root cause.** The old implementation used `mark.scrollIntoView()` directly
on the iframe's document. In spread mode epub.js does not create two iframes:
it renders the chapter as a single multi-column layout and "turns pages" by
shifting that document horizontally in exact `(columnWidth + gap)` steps.
A raw `scrollIntoView()` scrolls by an arbitrary amount that is **not snapped
to the column grid**, leaving the content half-shifted between columns — two
pages plus the edge of the next one. It also bypasses the view manager, so
epub.js no longer knew which page was actually displayed.

**Fix (`scrollToMatch`).** Navigate with `rendition.display(match.cfi)` so
epub.js computes the scroll itself, perfectly aligned with its own column
grid. This is safe even with highlights applied because the per-match CFI is
generated with `section.cfiFromElement(blockEl)` and targets a **block
element** (`p`, `h2`, …), not a text-node offset: inserting `<mark>` splits
text nodes *inside* the paragraph but never changes the paragraph's index
among its siblings, so element-level CFIs stay valid. If the chapter is
already rendered (the normal case) `display(cfi)` only scrolls, so the
"active" highlight survives. Degraded fallbacks keep the old
`scrollIntoView()` if the CFI is unavailable or display fails.

### `<mark>` highlights break text-offset CFIs

**Root cause.** Wrapping matched text in `<mark>` splits one text node into
three (`before / mark / after`). epub.js encodes CFIs as child indices plus
text-node offsets, so a CFI like `/4/2/1:285` computed against the pristine
tree may reference an offset that no longer exists once marks are present,
making `EpubCFI.toRange()` throw `IndexSizeError` inside
`Contents.locationOf()` — asynchronously, outside any promise chain, hence
uncatchable by `.catch()` or `try/catch`.

**Fix.** `clearSearchHighlights()` removes all marks and calls
`parent.normalize()` to merge the text nodes back to their original shape.
It MUST run before anything that triggers CFI resolution: zoom/
`rendition.resize()`, re-render, opening another book. Highlights are then
re-applied afterwards. For the same reason, saved-reading-position CFIs are
only persisted through epub.js's own relocation events (never computed while
highlights are mid-mutation).

### Saved-position restore: href first, CFI as refinement

**Goal.** Reopen the book exactly at the last-read text position (not merely
at the top of the chapter).

**Design.** On every debounced `'relocated'` event the reader persists
CFI + chapter href to the backend (`/api/save_position`, plus a
`navigator.sendBeacon` safety net on page unload). On open,
`restoreSavedPosition()` navigates in two steps:

1. `rendition.display(p.href)` — chapter-level jump, CFI-free, immune to
   invalid-offset errors;
2. `rendition.display(p.cfi)` chained **after** step 1, guarded by
   try/catch + `.catch()`. Applying the CFI even when the href exists is the
   key correctness point: skipping it would stop at the chapter start.

The fallback ladder is exact CFI → chapter start → book start; the function
always resolves so the `openBook()` chain continues. A `posReady` flag gates
all saving until the restore completes, otherwise the initial display's own
`'relocated'` would overwrite the stored position with page 1.

### Navigation
- **‹ Previous / Next ›** buttons
- **← / →** arrow keys

## Structure

```
app.py           Flask server: library, /api/books + /api/save_chapter endpoints, title extraction
static/          .epub books and web assets
  index.html     UI (toolbar, viewer, tabs, HTML editor, sidebars)
  epub.js        epub.js library
  jszip.min.js   epub.js dependency (loaded BEFORE epub.js)
```

Note: `jszip.min.js` must be loaded before `epub.js` because the epub.js build
treats it as an external dependency.
