#!/usr/bin/env python3
"""Piccolo lettore EPUB basato su epub.js servito da Flask.

Uso:
    python3 app.py            # avvia il server su http://127.0.0.1:5000
    python3 app.py --port 8080
    python3 app.py --book-dir "C:\\percorso\\target"   # epub non impacchettato

Al primo avvio scarica un libro di esempio (Alice nel Paese delle
Meraviglie) da https://s3.amazonaws.com/epubjs/books/alice.epub e lo
salva in static/book.epub. Per leggere altri libri, metti i file
.epub nella cartella static/: compariranno nel menu "Libreria" della
pagina.

Con --book-dir puoi servire anche un EPUB NON impacchettato (la cartella
estraibile, es. l'output del translator: target/ con META-INF/ e OEBPS/):
la cartella viene esposta su /ext/ e appare come primo libro in Libreria.
I file vengono letti dal disco a ogni richiesta (Cache-Control: no-store),
quindi le modifiche salvate dal translator si vedono subito, senza dover
ricompilare l'epub. Il pulsante "⟳ Ricarica" rilegge il capitolo corrente.
"""

import argparse
import os
import re
import sys
import urllib.request
import zipfile
import xml.etree.ElementTree as ET

from flask import Flask, Response, jsonify, request, send_from_directory

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
STATIC_DIR = os.path.join(BASE_DIR, "static")

# File di configurazione dell'utente: ~/.epubreader/config.ini
# Se non esiste viene creato al primo avvio con i valori di default.
CONFIG_DIR = os.path.join(os.path.expanduser("~"), ".epubreader")
CONFIG_FILE = os.path.join(CONFIG_DIR, "config.ini")


def _load_config():
    """Crea (se manca) e legge la configurazione utente ~/.epubreader/config.ini.

    Restituisce un dict con la chiave 'book_dir' (la cartella esterna con
    l'epub non impacchettato) e 'namespace' (oggetto configparser, None se
    si e' caduti sui default a causa di un errore).
    """
    import configparser

    defaults_book_dir = r"..\translator\target"

    try:
        os.makedirs(CONFIG_DIR, exist_ok=True)
        config = configparser.ConfigParser()
        config.read(CONFIG_FILE, encoding="utf-8")

        if not config.has_section("paths"):
            config.add_section("paths")
        if not config.has_option("paths", "book_dir"):
            config["paths"]["book_dir"] = defaults_book_dir

        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            config.write(f)

        return {"book_dir": config["paths"].get("book_dir", "").strip(),
                "namespace": config}
    except Exception:  # in caso di errori cadiamo sui default iniettabili
        return {"book_dir": defaults_book_dir, "namespace": None}


# Cartella esterna con un EPUB non impacchettato (output del translator).
# Viene letta da ~/.epubreader/config.ini ed e' sovrascrivibile con
# --book-dir per questa singola esecuzione (usa --book-dir "" per
# disabilitarla).
CONFIG = _load_config()
DEFAULT_BOOK_DIR = CONFIG["book_dir"]

SAMPLE_URL = "https://s3.amazonaws.com/epubjs/books/alice.epub"
SAMPLE_FILE = os.path.join(STATIC_DIR, "book.epub")

# Chiave usata dal frontend per identificare il libro-cartella in /api/books
# e in /api/save_chapter (corrisponde alla URL "/ext/").
FOLDER_BOOK_KEY = "ext"

BOOK_DIR = None  # impostato da main() in base a --book-dir

# Cache del bundle CSS (concatenazione di tutti gli styles/*.css): chiave =
# max mtime dei file, cosi' se il translator rigenera i css il bundle si
# aggiorna da solo. I capitoli InDesign referenziano ~100 css a testa: col
# bundle ogni capitolo fa UNA richiesta invece di ~100 (rendering veloce).
_CSS_BUNDLE_CACHE = {}  # styles_dir -> (max_mtime, data)
_LINK_CSS_RE = re.compile(r'<link[^>]*href=["\']([^"\']*\.css)["\'][^>]*>', re.I)
NO_STORE = {"Cache-Control": "no-store"}

app = Flask(__name__, static_folder=STATIC_DIR)


@app.route("/")
def index():
    return send_from_directory(STATIC_DIR, "index.html")


@app.route("/<path:filename>")
def static_files(filename):
    return send_from_directory(STATIC_DIR, filename)


@app.route("/ext/<path:filename>")
def ext_files(filename):
    """Serve i file dell'epub non impacchettato (--book-dir).

    Cache-Control: no-store: i file vengono riletti dal disco a ogni
    richiesta, cosi' le traduzioni salvate dal translator si vedono subito
    (senza ricompilare l'epub). send_from_directory blocca i path traversal.

    Ottimizzazione "bundle.css": i capitoli (export InDesign) referenziano
    ~100 fogli di stile ciascuno. Qui i capitoli .xhtml vengono riscritti per
    puntare a UN solo styles/bundle.css (concatenazione di tutti i css della
    cartella styles/, stessa directory = stessi path relativi per i font),
    quindi ogni capitolo fa 1 richiesta css invece di ~100.
    """
    if not BOOK_DIR or not os.path.isdir(BOOK_DIR):
        return jsonify(ok=False, error="Cartella esterna non configurata"), 404

    # Il bundle.css e' virtuale: lo generiamo al volo (cache in memoria)
    if filename.replace("\\", "/").lower().endswith("bundle.css"):
        styles_dir = os.path.join(BOOK_DIR, os.path.dirname(filename.replace("\\", "/")))
        data = css_bundle(styles_dir)
        if data is None:
            return jsonify(ok=False, error="Bundle CSS non disponibile"), 404
        return Response(data, mimetype="text/css", headers=dict(NO_STORE))

    real = safe_join(BOOK_DIR, filename)
    if real is None or not os.path.isfile(real):
        return jsonify(ok=False, error="File non trovato: " + filename), 404

    # Capitolo XHTML: sostituisci i ~100 <link css> con un solo bundle link.
    # Con ?raw=1 (usato dall'editor) il file viene servito INTATTO, cosi' un
    # salvataggio non distrugge i link css originali del capitolo.
    if os.path.splitext(filename)[1].lower() in (".xhtml", ".html", ".htm") and not request.args.get("raw"):
        try:
            with open(real, "r", encoding="utf-8") as f:
                text = f.read()
            rewritten = rewrite_xhtml_css_links(
                text, os.path.dirname(filename.replace("\\", "/")), BOOK_DIR
            )
            if rewritten is not None:
                return Response(
                    rewritten,
                    mimetype="application/xhtml+xml",
                    headers=dict(NO_STORE),
                )
        except Exception:  # noqa: BLE001
            pass  # se fallisce, serviamo il file originale

    resp = send_from_directory(BOOK_DIR, filename)
    resp.headers["Cache-Control"] = "no-store"
    return resp


def safe_join(root, filename):
    """Ritorna il path di `filename` sotto `root` se sicuro, altrimenti None."""
    filename = filename.replace("\\", "/")
    resolved = os.path.realpath(os.path.join(root, filename))
    root_real = os.path.realpath(root)
    if resolved == root_real or resolved.startswith(root_real + os.sep):
        return resolved
    return None


def css_bundle(styles_dir):
    """Concatenazione di tutti i *.css in styles_dir (ordine alfabetico, che
    qui coincide con l'ordine dei <link> nei capitoli). Cache in memoria
    invalidata dal max mtime. Ritorna bytes oppure None se cartella assente."""
    if not os.path.isdir(styles_dir):
        return None
    try:
        files = sorted(f for f in os.listdir(styles_dir) if f.lower().endswith(".css"))
    except OSError:
        return None
    if not files:
        return b""
    max_mtime = 0.0
    for fn in files:
        try:
            max_mtime = max(max_mtime, os.path.getmtime(os.path.join(styles_dir, fn)))
        except OSError:
            pass
    cached = _CSS_BUNDLE_CACHE.get(styles_dir)
    if cached and cached[0] == max_mtime:
        return cached[1]
    parts = []
    for fn in files:
        try:
            with open(os.path.join(styles_dir, fn), "rb") as fh:
                parts.append(fh.read())
        except OSError:
            pass
    data = b"@charset \"UTF-8\";\n" + b"\n".join(parts)
    _CSS_BUNDLE_CACHE[styles_dir] = (max_mtime, data)
    return data


def rewrite_xhtml_css_links(text, chapter_dir, root):
    """Riscrive un capitolo XHTML: rimuove tutti i <link ...styles/*.css...> e
    inietta un unico <link href="<rel>/bundle.css">. Ritorna il nuovo testo,
    oppure None se il capitolo non referenzia css in una cartella styles/.
    Il bundle vive nella stessa cartella styles/, quindi i path relativi nei
    css (es. url('../fonts/...')) restano validi."""
    styles_dir = os.path.join(root, chapter_dir, "styles")
    if not os.path.isdir(styles_dir):
        return None

    def drop(m):
        href = m.group(1).strip()
        path = href.split("?", 1)[0]
        if re.search(r"(^|/)styles/[^/]*\.css$", path, re.I):
            return ""
        return m.group(0)

    new_text = _LINK_CSS_RE.sub(drop, text)
    if new_text == text:
        return None  # nessun link css da sostituire

    bundle_rel = os.path.relpath(styles_dir, os.path.join(root, chapter_dir))
    bundle_rel = bundle_rel.replace("\\", "/")
    bundle_link = (
        '<link href="' + bundle_rel + '/bundle.css" rel="stylesheet" type="text/css"/>'
    )
    new_text = re.sub(
        r"(<head[^>]*>)", r"\1\n" + bundle_link, new_text, count=1, flags=re.I
    )
    return new_text


@app.route("/api/health")
def health():
    return jsonify(status="ok")


@app.route("/api/books")
def list_books():
    """Elenca i libri leggibili: prima l'epub non impacchettato (--book-dir),
    poi i file .epub presenti nella cartella static/."""
    books = []
    os.makedirs(STATIC_DIR, exist_ok=True)

    # 1) Epub non impacchettato: cartella esterna (output del translator).
    #    url "/ext/" termina con '/' → epub.js lo apre in modalita' DIRECTORY
    #    (legge META-INF/container.xml). La mettiamo per prima cosi' e' il
    #    libro aperto all'avvio.
    if BOOK_DIR and os.path.isdir(BOOK_DIR):
        label = os.path.basename(os.path.normpath(BOOK_DIR)) + "/"
        books.append(
            {
                "name": label,
                "title": folder_title(BOOK_DIR) or label,
                "url": "/ext/",
                "size": folder_size(BOOK_DIR),
                "type": "folder",
            }
        )

    # 2) File .epub in static/
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


@app.route("/api/save_chapter", methods=["POST"])
def save_chapter():
    """Salva il contenuto modificato di una voce dentro il .epub.

    Equivalente di saveChapterIntoEpub in epub_app.nim (versione Nim):
    ricompone lo zip sostituendo la voce `href` con `content`, preservando
    i metadati delle altre voci e scrivendo in modo atomico (.tmp + replace).

    Richiesta JSON: {"book": "nome.epub", "href": "path/dentro/l\'epub",
                    "content": "<html>...", "silent": false}
    Il campo opzionale "silent" (usato dal popover di editing in-context)
    è accettato per compatibilità con il frontend condiviso ma non ha effetti
    lato server: in questa versione il ri-render del viewer è sempre client-side.
    Risposta: {"ok": true} oppure {"ok": false, "error": "..."}
    """
    data = request.get_json(silent=True)
    if not data:
        return jsonify(ok=False, error="Richiesta JSON non valida"), 400

    book_name = data.get("book", "")
    href = data.get("href", "")
    content = data.get("content", "")
    # "silent" (opzionale): salvataggio in-context dal popover del viewer.
    # In Flask il ri-render è sempre lato client, quindi il flag non ha
    # alcun effetto lato server: viene letto solo per accettarlo.
    _ = data.get("silent", False)

    # Validazione del nome libro: la chiave del libro-cartella ("/ext/") oppure
    # un basename .epub esistente in static/
    is_folder = book_name.rstrip("/") == FOLDER_BOOK_KEY
    if not book_name or (
        not is_folder
        and (
            book_name != os.path.basename(book_name)
            or "/" in book_name
            or "\\" in book_name
            or ".." in book_name
            or not book_name.lower().endswith(".epub")
        )
    ):
        return jsonify(ok=False, error="Nome libro non valido: " + book_name)

    # Validazione href (comune a entrambe le modalita'): niente path
    # traversal (nessun segmento ".."), niente path assoluti (/, \\, drive).
    href = href.lstrip("/")
    normalized = href.replace("\\", "/")
    if (
        not href
        or ".." in normalized.split("/")
        or href.startswith("\\")
        or (len(href) > 1 and href[1] == ":")
    ):
        return jsonify(ok=False, error="Percorso non valido: " + href)

    # Modalita' cartella (epub non impacchettato): scrive direttamente su disco
    if is_folder:
        if not BOOK_DIR or not os.path.isdir(BOOK_DIR):
            return jsonify(ok=False, error="Cartella esterna non configurata")
        target = resolve_in_dir(BOOK_DIR, href)
        if target is None:
            return jsonify(
                ok=False, error="Il file " + href + " non e' presente nella cartella"
            )
        tmp_path = target + ".tmp"
        try:
            with open(tmp_path, "w", encoding="utf-8") as f:
                f.write(content)
            os.replace(tmp_path, target)
        except Exception as exc:  # noqa: BLE001
            try:
                if os.path.exists(tmp_path):
                    os.remove(tmp_path)
            except OSError:
                pass
            return jsonify(ok=False, error="Errore durante la scrittura: " + str(exc))
        return jsonify(ok=True)

    book_path = os.path.join(STATIC_DIR, book_name)
    if not os.path.isfile(book_path):
        return jsonify(ok=False, error="File non trovato: " + book_name)

    try:
        with zipfile.ZipFile(book_path, "r") as zf:
            names = zf.namelist()
            infos = {zi.filename: zi for zi in zf.infolist()}
            contents = {n: zf.read(n) for n in names}
    except Exception as exc:  # noqa: BLE001
        return jsonify(ok=False, error="Impossibile aprire l'epub: " + str(exc))

    # Match case-insensitive della voce (come cmpIgnoreCase in Nim)
    target = next((n for n in names if n.lower() == href.lower()), None)
    if target is None:
        return jsonify(ok=False, error="Il file " + href + " non e' presente nell'epub")
    href = target

    # Scrittura su file temporaneo + os.replace (sostituzione atomica)
    tmp_path = book_path + ".tmp"
    try:
        with zipfile.ZipFile(tmp_path, "w") as zf:
            for name in names:
                zi = infos[name]
                if name == href:
                    zf.writestr(zi, content.encode("utf-8"))
                else:
                    zf.writestr(zi, contents[name])
        os.replace(tmp_path, book_path)
    except Exception as exc:  # noqa: BLE001
        try:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)
        except OSError:
            pass
        return jsonify(ok=False, error="Errore durante la scrittura: " + str(exc))

    return jsonify(ok=True)


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


def folder_title(root):
    """Estrae il titolo da un epub NON impacchettato: legge
    META-INF/container.xml per trovare l'OPF, poi ne legge i metadati."""
    try:
        with open(os.path.join(root, "META-INF", "container.xml"), "rb") as f:
            container = ET.fromstring(f.read())
        ns = {"c": "urn:oasis:names:tc:opendocument:xmlns:container"}
        rootfile = container.find(".//c:rootfile", ns)
        if rootfile is None:
            return None
        opf_file = os.path.join(root, rootfile.get("full-path").replace("\\", "/"))
        opf = ET.fromstring(open(opf_file, "rb").read())
        title = opf.find(".//{http://purl.org/dc/elements/1.1/}title")
        if title is not None and title.text and title.text.strip():
            return title.text.strip()
    except Exception:  # noqa: BLE001
        pass
    return None


def folder_size(root):
    """Dimensione totale (byte) di tutti i file della cartella epub."""
    total = 0
    for dirpath, _dirnames, filenames in os.walk(root):
        for fn in filenames:
            try:
                total += os.path.getsize(os.path.join(dirpath, fn))
            except OSError:
                pass
    return total


def resolve_in_dir(root, href):
    """Ritorna il path reale di `href` sotto `root`, con match case-insensitive
    (come cmpIgnoreCase usato per le voci dello zip). Ritorna None se assente
    o se il path risolto esce da `root` (sicurezza: niente traversal)."""
    href = href.replace("\\", "/").lstrip("/")
    direct = os.path.join(root, href)
    if os.path.isfile(direct):
        return _contained_realpath(root, direct)
    norm = href.lower()
    for dirpath, _dirnames, filenames in os.walk(root):
        for fn in filenames:
            rel = os.path.relpath(os.path.join(dirpath, fn), root).replace("\\", "/")
            if rel.lower() == norm:
                return _contained_realpath(root, os.path.join(dirpath, fn))
    return None


def _contained_realpath(root, path):
    """Ritorna il realpath di `path` se resta dentro `root`, altrimenti None."""
    resolved = os.path.realpath(path)
    root_real = os.path.realpath(root)
    if resolved == root_real or resolved.startswith(root_real + os.sep):
        return resolved
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
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=5000)
    parser.add_argument("--debug", action="store_true")
    parser.add_argument(
        "--book-dir",
        default=DEFAULT_BOOK_DIR,
        help=(
            "Cartella con un epub NON impacchettato (META-INF/ + OEBPS/) da "
            "servire su /ext/ e mostrare in Libreria; usa '' per disabilitare. "
            "Default: %(default)s"
        ),
    )
    args = parser.parse_args()

    global BOOK_DIR
    BOOK_DIR = (args.book_dir or "").strip() or None
    if BOOK_DIR:
        if os.path.isdir(BOOK_DIR):
            print(f"Epub da cartella: {BOOK_DIR}  (su /ext/)")
        else:
            print(
                f"AVVISO: --book-dir non trovata, ignorata: {BOOK_DIR}",
                file=sys.stderr,
            )
            BOOK_DIR = None

    ensure_sample_book()
    print(f"\nApri il browser su: http://{args.host}:{args.port}\n")
    app.run(host=args.host, port=args.port, debug=args.debug)


if __name__ == "__main__":
    main()
