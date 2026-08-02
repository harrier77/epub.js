#!/usr/bin/env python3
"""Piccolo lettore EPUB basato su epub.js servito da Flask.

Uso:
    python3 app.py            # avvia il server su http://127.0.0.1:5000
    python3 app.py --port 8080

Al primo avvio scarica un libro di esempio (Alice nel Paese delle
Meraviglie) da https://s3.amazonaws.com/epubjs/books/alice.epub e lo
salva in static/book.epub. Per leggere un altro libro, sostituisci
static/book.epub con il tuo file .epub oppure usa il pulsante "apri
file" nella pagina.
"""

import argparse
import os
import sys
import urllib.request

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
