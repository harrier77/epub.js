# Lettore EPUB (Flask + epub.js)

Lettore di ebook EPUB servito da Flask e renderizzato nel browser con
[epub.js](https://github.com/futurepress/epub.js). L'obiettivo è avvicinarsi
all'esperienza degli editor EPUB come [Sigil](https://sigil-ebook.com),
replicandone alcune funzioni utili per la lettura e l'ispezione dei file:
libreria lato server, controllo della visualizzazione e browser del pacchetto
EPUB.

## Avvio

```bash
python3 app.py            # http://127.0.0.1:5000
python3 app.py --port 8080
python3 app.py --debug
```

Al primo avvio viene scaricato un libro di esempio (*Alice nel Paese delle
Meraviglie*) e salvato in `static/book.epub`.

## Funzioni

### Libreria lato server (niente file picker client)
I libri non si aprono dal disco del client: il server espone `GET /api/books`,
che elenca i file `.epub` presenti in `static/`. Il menu **Libreria** nella
toolbar mostra i titoli (estratti dai metadati OPF di ogni EPUB); basta
aggiungere un `.epub` nella cartella `static/` e riavviare o ricaricare la
pagina per vederlo comparire.

### Pagina singola / doppia pagina affiancata
Il pulsante **Una pagina / Due pagine** commuta a runtime tra
`rendition.spread("none")` e `rendition.spread("auto")`, senza ricaricare il
libro.

### Larghezza massima del container
Il selettore **Larghezza massima pagina** imposta (in percentuale dello
schermo, da 40% a 100%) la larghezza massima dell'area di lettura, per non
avere righe troppo lunghe su monitor o tablet molto larghi. Il layout viene
ricalcolato subito via `rendition.resize()`.

### Browser del pacchetto EPUB (stile Sigil)
Il pulsante **File** apre una sidebar con l'elenco di tutti i file inclusi nel
manifest dell'EPUB, raggruppati per tipo (Documenti, Stili, Immagini, Font,
Script, Audio/Video, Altri):

- i documenti che fanno parte dello **spine** (flusso di lettura) sono
  cliccabili: un clic naviga a quel documento nel lettore;
- il file corrente viene evidenziato automaticamente a ogni cambio pagina;
- la sidebar si chiude con il pulsante ✕ o con `Esc`.

### Navigazione
- Pulsanti **‹ Precedente / Successivo ›**
- Frecce **← / →** della tastiera

## Struttura

```
app.py           server Flask: libreria, endpoint /api/books, estrazione titoli
static/          libri .epub e asset web
  index.html     interfaccia (toolbar, viewer, sidebar)
  epub.js        libreria epub.js
  jszip.min.js   dipendenza di epub.js (caricata PRIMA di epub.js)
```

Nota: `jszip.min.js` va caricato prima di `epub.js` perché il build di epub.js
lo tratta come dipendenza esterna.
