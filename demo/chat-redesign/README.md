# Retakt Mobile-Redesign (Vorschau)

Alle vier mobilen Bildschirme im Retakt-Stil (dunkles Glas-Theme der Lovable-App), 1:1-Ersatz für die Seiten in `backend/`. Die Originale bleiben unverändert (gehören A).

| Adresse | Seite | Quelle im Backend |
| --- | --- | --- |
| `/` und `/chat` | Schaden melden | `backend/intake.html` |
| `/garage` | Werkstatt-Upload (Link mit Token) | `backend/garage.html` |
| `/reviewer` | Reviewer-Chat | `backend/chat.html` |
| `/reviewer/evidence` | Quote Evidence | `backend/quote_review.html` |
| `/mobile.html` | Handy-Rahmen mit Umschalter über alle vier Seiten | nur Vorschau |

## Starten (aus dem Repo-Root)

```sh
python3 -m backend --store sqlite --db /tmp/retakt-demo.sqlite3     # Backend auf :8765 (offline, Wegwerf-DB)
python3 demo/chat-redesign/serve.py --port 8090                     # Vorschau auf :8090
open http://127.0.0.1:8090/mobile.html
```

`serve.py` liefert die neuen Seiten unter denselben Adressen aus und leitet alles andere (`/api/*`, `/assets/*`, `/examples/*`) unverändert ans Backend. Gemeinsame Bausteine: `retakt.css`. Skripte der Seiten sind byte-identisch mit den Originalen; nur Markup und CSS sind neu.

## Übernahme ins Backend
Datei für Datei nach `backend/` kopieren (`index.html` → `chat.html`, `evidence.html` → `quote_review.html`) und `retakt.css` unter `/retakt.css` ausliefern lassen. Das ist eine Absprache mit A.
