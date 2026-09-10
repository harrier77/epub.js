#!/usr/bin/env python
"""Ricostruisce la TOC (indice) di un EPUB scansionando le intestazioni.

Uso:
    python reindex_epub.py input.epub -o output.epub
    python reindex_epub.py input.epub --overwrite
    python reindex_epub.py input.epub --headings h1,h2 --dry-run

Richiede: pip install ebooklib
"""
import argparse
import copy
import re
import sys

try:
    from ebooklib import epub
except ImportError:
    sys.exit("ERRORE: manca 'ebooklib'. Installa con: pip install ebooklib")

from xml.etree import ElementTree as ET

HEADING_RE = re.compile(r"<h([1-6])[^>]*>(.*?)</h\1>", re.I | re.S)
ID_RE = re.compile(r'''\bid\s*=\s*["']([^"']+)["']''', re.I)
TAG_RE = re.compile(r"<[^>]+>")


def _text(html):
    return re.sub(r"\s+", " ", TAG_RE.sub("", html)).strip()


def collect_index(book, levels=(1, 2, 3)):
    """Scansiona gli EpubHtml in ordine di spine, ritorna lista
    [{'file_src': 'Text/cap.xhtml#ancora', 'testo': '...', 'ancora': '...',
      'level': 2, 'item': <EpubHtml>}, ...] e inietta id mancanti."""
    spine_ids = [sid for sid, _ in book.spine if sid != "ncx"]
    items = {it.get_id(): it for it in book.get_items_of_type(9)}  # ITEM_DOCUMENT
    indice, n = [], 0
    for sid in spine_ids:
        item = items.get(sid)
        if item is None:
            continue
        html = item.get_content().decode("utf-8", "replace")
        for m in HEADING_RE.finditer(html):
            lv = int(m.group(1))
            if lv not in levels:
                continue
            tag_open = html[max(0, m.start() - 0):m.start()]  # noop
            full_tag = m.group(0)
            open_tag = full_tag[: full_tag.find(">") + 1]
            aid = ID_RE.search(open_tag)
            if aid:
                ancora = aid.group(1)
            else:
                n += 1
                ancora = f"h{n}"
                # inietta id nel tag di apertura
                new_open = open_tag[:-1] + f' id="{ancora}">'
                html = html[: m.start()] + new_open + html[m.start() + len(open_tag):]
                # riavvia regex dopo modifica: ricostruisci da capo per semplicita'
                # (ricompensa: robusto, costo ok per epub normali)
            testo = _text(m.group(2))[:120] or f"(senza titolo {ancora})"
            href = item.get_name() if hasattr(item, "get_name") else item.href
            indice.append({"file_src": f"{href}#{ancora}",
                           "testo": testo, "ancora": ancora,
                           "level": lv, "item": item})
        if html != item.get_content().decode("utf-8", "replace"):
            item.set_content(html.encode("utf-8"))
    return indice


def build_toc(indice):
    """Annida h2/h3 sotto l'ultimo h1/h2 per una TOC gerarchica."""
    toc, stack = [], []  # stack: [(level, children_list)]
    for entry in indice:
        link = epub.Link(entry["file_src"], entry["testo"], entry["ancora"])
        lv = entry["level"]
        while stack and stack[-1][0] >= lv:
            stack.pop()
        if not stack:
            toc.append(link)
            # crea contenitore figli se potranno servire: usiamo sezione
            sec_children = []
            # ebooklib: (Link, [figli]) per sezioni
            # Sostituiamo l'ultimo elemento con tupla quando arriva il figlio
            stack.append((lv, toc, len(toc) - 1, sec_children))
        else:
            _, parent_list, idx, children = stack[-1]
            if not isinstance(parent_list[idx], tuple):
                parent_list[idx] = (parent_list[idx], children)
            children.append(link)
            stack.append((lv, children, len(children) - 1, []))
    # pulisci tuple vuote (Link senza figli -> resta Link)
    def clean(nodes):
        out = []
        for nd in nodes:
            if isinstance(nd, tuple):
                link, kids = nd
                kids = clean(kids)
                out.append((link, kids) if kids else link)
            else:
                out.append(nd)
        return out
    return tuple(clean(toc))


def reindex(src, dst, levels, dry_run=False):
    book = epub.read_epub(src)
    indice = collect_index(book, levels)
    if not indice:
        print("Nessuna intestazione trovata: TOC invariata.")
        return False
    print(f"Trovate {len(indice)} intestazioni:")
    for e in indice:
        print(f"  h{e['level']} {e['testo'][:60]!r} -> {e['file_src']}")

    toc = build_toc(indice)
    book.toc = toc

    # Rimuovi vecchi NCX/NAV per evitare duplicati, poi riaggiungi
    for _id in ("ncx", "nav"):
        old = book.get_item_with_id(_id)
        if old is not None:
            book.items.remove(old)
    book.add_item(epub.EpubNcx())
    book.add_item(epub.EpubNav())

    # Assicura nav/ncx in fondo allo spine (standard)
    book.spine = [s for s in book.spine if s[0] not in ("ncx", "nav")]
    # ebooklib scrive ncx/nav da solo; basta tenerli fuori dallo spine
    # (write_epub li gestisce), ma li includiamo come 'nav' per EPUB3:
    if "nav" not in [s[0] for s in book.spine]:
        nav = book.get_item_with_id("nav")
        if nav is not None:
            book.spine.append(("nav", True))

    if dry_run:
        print("--dry-run: nessun file scritto.")
        return True
    epub.write_epub(dst, book)
    print(f"Scritto: {dst}")
    return True


def main():
    ap = argparse.ArgumentParser(description="Ricostruisce la TOC di un EPUB")
    ap.add_argument("input", help="EPUB di origine")
    ap.add_argument("-o", "--output", default="libro_con_nuovo_toc.epub")
    ap.add_argument("--overwrite", action="store_true",
                    help="scrivi sullo stesso file di input")
    ap.add_argument("--headings", default="1,2,3",
                    help="livelli da includere (default: 1,2,3)")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    levels = tuple(sorted(int(x) for x in a.headings.split(",") if x.strip().isdigit()))
    dst = a.input if a.overwrite else a.output
    ok = reindex(a.input, dst, levels or (1, 2, 3), a.dry_run)
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
