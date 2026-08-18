"""Lancia il lettore EPUB aprendo il browser e chiudendosi automaticamente
alla chiusura della finestra del browser.

Usa il monkey-patching di Flask per:
  - aggiungere /api/heartbeat senza modificare app.py
  - iniettare il JS di heartbeat nell'HTML senza modificare index.html
"""
import os
import subprocess
import threading
import time
import webbrowser

import app

# --- Configurazione heartbeat ---
HEARTBEAT_INTERVAL = 3   # secondi tra un ping e l'altro
HEARTBEAT_TIMEOUT  = 10  # secondi senza ping → arresto automatico

_heartbeat_ts = time.monotonic()
_injected_tag = None  # cache del tag <script> da iniettare


def _build_heartbeat_tag():
    """Ritorna il tag <script> da iniettare nelle pagine HTML."""
    global _injected_tag
    if _injected_tag is None:
        _injected_tag = (
            "<script>"
            "(function(){"
            "var i=setInterval(function(){"
            "fetch('/api/heartbeat',{method:'GET'}).catch(function(){});"
            "}," + str(HEARTBEAT_INTERVAL * 1000) + ");"
            "window.addEventListener('beforeunload',function(){"
            "navigator.sendBeacon('/api/heartbeat');"
            "});"
            "})();"
            "</script>"
        )
    return _injected_tag


def _watchdog():
    """Thread daemon: se il browser smette di pingare, termina il processo."""
    while True:
        time.sleep(5)
        if time.monotonic() - _heartbeat_ts > HEARTBEAT_TIMEOUT:
            print("Browser chiuso, arresto automatico.", flush=True)
            # taskkill e' il modo piu' affidabile per chiudere un .pyw
            # senza console su Windows (os._exit da solo a volte lascia
            # il processo fantasma).
            try:
                subprocess.Popen(
                    ["taskkill", "/F", "/PID", str(os.getpid())],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
            except Exception:
                os._exit(0)
            break


def _setup_heartbeat():
    """Registra endpoint, injection hook e watchdog.
    Chiamare UNA VOLTA prima di app.main()."""
    global _heartbeat_ts
    _heartbeat_ts = time.monotonic()  # evita shutdown immediato all'avvio

    # --- Endpoint /api/heartbeat ---
    @app.app.route("/api/heartbeat", methods=["GET", "POST"])
    def heartbeat():
        global _heartbeat_ts
        _heartbeat_ts = time.monotonic()
        return app.jsonify(ok=True)

    # --- Iniezione JS nell'HTML (after_request) ---
    tag = _build_heartbeat_tag()

    @app.app.after_request
    def _inject_heartbeat_script(response):
        ct = response.content_type or ""
        if "text/html" not in ct:
            return response
        data = response.get_data(as_text=True)
        if not data or tag in data:
            return response
        # inietta prima di </body> (o in coda)
        idx = data.rfind("</body>")
        if idx == -1:
            idx = data.rfind("</html>")
        if idx == -1:
            data += tag
        else:
            data = data[:idx] + tag + data[idx:]
        response.set_data(data)
        return response

    # --- Watchdog ---
    threading.Thread(target=_watchdog, daemon=True).start()


def open_browser():
    time.sleep(1)
    webbrowser.open("http://localhost:5000")


if __name__ == "__main__":
    _setup_heartbeat()
    threading.Thread(target=open_browser, daemon=True).start()
    app.main()
