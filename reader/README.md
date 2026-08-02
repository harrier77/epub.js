# EPUB Reader (Flask + epub.js)

EPUB ebook reader served by Flask and rendered in the browser with
[epub.js](https://github.com/futurepress/epub.js). The goal is to get closer
to the experience of EPUB editors such as [Sigil](https://sigil-ebook.com),
replicating some of their features that are useful for reading and inspecting
files: server-side library, view controls and an EPUB package browser.

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

### Navigation
- **‹ Previous / Next ›** buttons
- **← / →** arrow keys

## Structure

```
app.py           Flask server: library, /api/books endpoint, title extraction
static/          .epub books and web assets
  index.html     UI (toolbar, viewer, sidebar)
  epub.js        epub.js library
  jszip.min.js   epub.js dependency (loaded BEFORE epub.js)
```

Note: `jszip.min.js` must be loaded before `epub.js` because the epub.js build
treats it as an external dependency.
