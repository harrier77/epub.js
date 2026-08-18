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
