#!/usr/bin/env python3
"""Piccolo lettore EPUB basato su epub.js servito da Flask.

Uso:
    python3 app.py            # avvia il server su http://127.0.0.1:5000
    python3 app.py --port 8080

Al primo avvio scarica un libro di esempio (Alice nel Paese delle
Meraviglie) da https://s3.amazonaws.com/epubjs/books/alice.epub e lo
salva in static/book.epub. Per leggere altri libri, metti i file
.epub nella cartella static/: compariranno nel menu "Libreria" della
pagina.
"""

import argparse
import os
import sys
import urllib.request
import zipfile
import xml.etree.ElementTree as ET

from flask import Flask, jsonify, send_from_directory

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
STATIC_DIR = os.path.join(BASE_DIR, "static")
SAMPLE_URL = "https://s3.amazonaws.com/epubjs/books/alice.epub"
SAMPLE_FILE = os.path.join(STATIC_DIR, "book.epub")

app = Flask(__name__, static_folder=STATIC_DIR)


@app.route("/")
def index():
    return send_from_directory(STATIC_DIR, "index.html")


@app.route("/<path:filename>")
def static_files(filename):
    return send_from_directory(STATIC_DIR, filename)


@app.route("/api/health")
def health():
    return jsonify(status="ok")


@app.route("/api/books")
def list_books():
    """Elenca i file .epub presenti nella cartella static/."""
    books = []
    os.makedirs(STATIC_DIR, exist_ok=True)
    for name in sorted(os.listdir(STATIC_DIR)):
        if name.lower().endswith(".epub"):
            path = os.path.join(STATIC_DIR, name)
            books.append(
                {
                    "name": name,
                    "title": epub_title(path) or os.path.splitext(name)[0],
                    "url": "/" + name,
                    "size": os.path.getsize(path),
                }
            )
    return jsonify(books)


def epub_title(path):
    """Estrae il titolo da un .epub leggendone i metadati OPF."""
    try:
        with zipfile.ZipFile(path) as zf:
            container = ET.fromstring(zf.read("META-INF/container.xml"))
            ns = {"c": "urn:oasis:names:tc:opendocument:xmlns:container"}
            rootfile = container.find(".//c:rootfile", ns)
            if rootfile is None:
                return None
            opf_path = rootfile.get("full-path")
            opf = ET.fromstring(zf.read(opf_path))
            title = opf.find(".//{http://purl.org/dc/elements/1.1/}title")
            if title is not None and title.text and title.text.strip():
                return title.text.strip()
    except Exception:  # noqa: BLE001
        pass
    return None


def ensure_sample_book():
    """Scarica il libro di esempio se non esiste già."""
    if os.path.exists(SAMPLE_FILE):
        print(f"Libro di esempio già presente: {SAMPLE_FILE}")
        return
    os.makedirs(STATIC_DIR, exist_ok=True)
    print(f"Scaricamento libro di esempio da {SAMPLE_URL} ...")
    try:
        urllib.request.urlretrieve(SAMPLE_URL, SAMPLE_FILE)
        size = os.path.getsize(SAMPLE_FILE)
        print(f"Fatto ({size / 1024:.0f} KB).")
    except Exception as exc:  # noqa: BLE001
        print(
            f"AVVISO: impossibile scaricare il libro di esempio: {exc}\n"
            f"  Metti un file 'book.epub' in {STATIC_DIR} e riavvia.",
            file=sys.stderr,
        )


def main():
    parser = argparse.ArgumentParser(description="Lettore EPUB con epub.js")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=5000)
    parser.add_argument("--debug", action="store_true")
    args = parser.parse_args()

    ensure_sample_book()
    print(f"\nApri il browser su: http://{args.host}:{args.port}\n")
    app.run(host=args.host, port=args.port, debug=args.debug)


if __name__ == "__main__":
    main()
