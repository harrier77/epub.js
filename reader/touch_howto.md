# Piano modifiche: costringere il touch ad operare come il mouse BT

File target: `static/index.html`

## Perché oggi si comportano diversamente

Non è colpa del codice: è il browser Android che tratta il dito diversamente dal mouse.

1. **Tap ≠ click immediato** — il browser sintetizza `mousedown/mouseup/click`
   solo dopo aver escluso double-tap-zoom o scroll; col mouse la sequenza
   arriva subito. Nei documenti iframe di epub.js il `click` del popover
   (`bindInlineEdit`) può arrivare in ritardo o non arrivare.
2. **Selezione collassata prima del click** — su touch `getSelection()` è già
   vuota quando scatta `click`. È il motivo per cui esistono `snapshotSel()`,
   `caretRangeFromPoint`, `captureSentenceAtPoint`.
3. **Gesti nativi concorrenti** — long-press → menu Copia/Cerca/Traduci,
   double-tap → zoom, pinch → zoom pagina. `touch-action: none` su `#viewer`
   copre solo scroll/pinch dentro il viewer, non long-press e double-tap fuori.
4. **Swipe su pipeline separata** — gli swipe usano `touchstart`/`touchend`
   (eventi che il mouse non genera mai): mouse e touch percorrono due
   pipeline diverse.

Strategia: usare **solo Pointer Events** e sopprimere i gesti nativi, così il
dito produce la stessa sequenza logica del mouse (pointerdown → move → up →
click). Il drag del popover e il grip resize già usano Pointer Events con
`setPointerCapture`: funzioneranno identici senza ritocchi.

## Modifiche previste

### 1. Meta viewport — niente zoom utente (elimina il double-tap delay)

```html
<meta name="viewport" content="width=device-width, initial-scale=1, maximum-scale=1, user-scalable=no">
```

### 2. CSS globale anti-gesto

```css
html { touch-action: manipulation; }   /* niente double-tap-zoom ovunque */
#viewer, .epub-container {
  -webkit-user-select: none;
  user-select: none;
  -webkit-touch-callout: none;         /* niente menu long-press */
}
```

⚠ Decisione aperta: togliendo `user-select` si perde la selezione testuale
col dito. Se la vogliamo mantenere, lasciare `user-select` e accettare che la
selezione resta l'unica vera divergenza (già mitigata da snapshotSel ecc.).

### 3. Sopprimere i gesti nativi rimasti

```js
document.addEventListener("contextmenu", function (e) { e.preventDefault(); });
```

### 4. Swipe convertito a Pointer Events

Eliminare i due handler `rendition.on("touchstart")` / `rendition.on("touchend")`
in `openBook()` e spostare la stessa logica dentro `bindInlineEdit()`, sui
documenti degli iframe:

```js
(function () {
  var sx = null, sy = null, st = 0;
  doc.addEventListener("pointerdown", function (e) {
    if (e.pointerType === "mouse") { sx = null; return; } // mouse: niente swipe
    sx = e.clientX; sy = e.clientY; st = performance.now();
  }, true);
  doc.addEventListener("pointerup", function (e) {
    if (sx == null) return;
    var dx = e.clientX - sx, dy = e.clientY - sy,
        dt = performance.now() - st;
    sx = null;
    if (dt > 800 || dt < 30) return;
    if (Math.abs(dx) < 60) return;
    if (Math.abs(dx) < Math.abs(dy) * 1.5) return;
    if (dx < 0 && !document.getElementById("next").disabled) navigate(1);
    else if (dx > 0 && !document.getElementById("prev").disabled) navigate(-1);
  }, true);
})();
```

Soglie invariate rispetto agli attuali handler touch (30–800 ms, 60 px,
orizzontalità 1.5×). Il guard su `pointerType === "mouse"` mantiene il
comportamento attuale del mouse; se un giorno volessimo lo swipe col mouse BT
basta rimuoverlo.

### 5. (Opzionale) emulare l'hover

I `:hover` non esistono sul touch. Se servono sui bottoni toolbar:
classi `.hover` aggiunte via `pointerenter`/`pointerleave`, oppure
`<script>` vuoto su `touchstart` (abilita hover sticky in alcuni WebView).

## Verifica dopo le modifiche

- Tap su paragrafo → popover preparato immediatamente (nessun ritardo).
- Selezione testo + tap → modalità Frammento con lo span giusto.
- Swipe orizzontale rapido → cambia pagina; gesto lento/verticale → selezione.
- Long-press sul testo → nessun menu nativo.
- Double-tap → nessuno zoom della pagina.
- Mouse BT: comportamento invariato (click, drag popover, grip, niente swipe).
