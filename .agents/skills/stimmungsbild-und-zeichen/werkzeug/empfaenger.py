"""Nimmt Bilder per POST /<id> entgegen und legt sie in .scratch/gemini/<id>.jpg ab.

Läuft auf 127.0.0.1:8455. Gemini darf nicht nach 127.0.0.1 verbinden, ein neuer
Tab schon: der Agent öffnet ``http://127.0.0.1:8455/x#name=dataurl``, die Seite
schickt das Bild an sich selbst (Ablauf in ``../SKILL.md``).
"""

import re
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

#: Das Repo liegt vier Ebenen über diesem Werkzeug (.agents/skills/<skill>/werkzeug).
ZIEL = Path(__file__).resolve().parents[4] / ".scratch" / "gemini"
ZIEL.mkdir(parents=True, exist_ok=True)


class Handler(BaseHTTPRequestHandler):
    def _cors(self):
        self.send_header("Access-Control-Allow-Origin", "https://gemini.google.com")
        self.send_header("Access-Control-Allow-Methods", "POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Access-Control-Allow-Private-Network", "true")

    def do_GET(self):
        if self.path.startswith("/bild/"):
            # Ein Bild aus .scratch/gemini (auch verworfen/) für die Vorlage-Seite.
            rel = self.path[len("/bild/"):]
            f = (ZIEL / rel).resolve()
            if ZIEL.resolve() not in f.parents or not f.is_file():
                self.send_response(404)
                self.end_headers()
                return
            self.send_response(200)
            self.send_header("Content-Type", "image/jpeg")
            self.end_headers()
            self.wfile.write(f.read_bytes())
            return
        if self.path.startswith("/schicke/"):
            # Eingebettet in Gemini: schickt das Bild per postMessage an die Seite darüber.
            rel = self.path[len("/schicke/"):]
            page = ("<!doctype html><meta charset=utf-8><script>(async()=>{"
                    "const b=await (await fetch('/bild/" + rel + "')).blob();"
                    "(window.opener||parent).postMessage({vorlage:b},'*');"
                    "document.body.textContent='geschickt '+!!window.opener;})()</script>"
                    ).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(page)
            return
        if self.path.startswith("/vorlage/"):
            # Ein Knopf legt das Bild als PNG in die Zwischenablage (braucht einen Klick).
            rel = self.path[len("/vorlage/"):]
            page = ("<!doctype html><meta charset=utf-8><img src='/bild/" + rel + "' width=200>"
                    "<button id=k style='font-size:24px'>Kopieren</button><p id=s></p><script>"
                    "k.onclick=async()=>{const i=document.querySelector('img');"
                    "const c=document.createElement('canvas');"
                    "c.width=i.naturalWidth;c.height=i.naturalHeight;"
                    "c.getContext('2d').drawImage(i,0,0);"
                    "const b=await new Promise(r=>c.toBlob(r,'image/png'));"
                    "try{await navigator.clipboard.write("
                    "[new ClipboardItem({'image/png':b})]);s.textContent='kopiert';}"
                    "catch(e){s.textContent='Fehler: '+e;}};</script>").encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(page)
            return
        # Die Seite liest das Bild aus dem Anker (#data:...) und schickt es an sich
        # selbst: Gemini darf nicht nach 127.0.0.1 verbinden, ein neuer Tab schon.
        page = (b"<!doctype html><meta charset=utf-8><body>speichere...<script>"
                b"(async()=>{const out=[];"
                b"for(const part of location.hash.slice(1).split('|')){"
                b"const i=part.indexOf('=');const name=part.slice(0,i),d=part.slice(i+1);"
                b"const blob=await (await fetch(d)).blob();"
                b"const r=await fetch('/'+name,{method:'POST',body:blob});"
                b"out.push(name+' '+r.status);}"
                b"document.body.textContent='gespeichert: '+out.join(', ');})()</script>")
        self.send_response(200)
        self.send_header("Content-Type", "text/html")
        self.end_headers()
        self.wfile.write(page)

    def do_OPTIONS(self):
        self.send_response(204)
        self._cors()
        self.end_headers()

    def do_POST(self):
        name = self.path.strip("/")
        if not re.fullmatch(r"[a-z_]+", name):
            self.send_response(400)
            self._cors()
            self.end_headers()
            return
        data = self.rfile.read(int(self.headers["Content-Length"]))
        (ZIEL / f"{name}.jpg").write_bytes(data)
        print(name, len(data), flush=True)
        self.send_response(200)
        self._cors()
        self.end_headers()
        self.wfile.write(b"ok")


ThreadingHTTPServer(("127.0.0.1", 8455), Handler).serve_forever()
