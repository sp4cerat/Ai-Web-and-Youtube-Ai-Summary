# AI Web · YT Search

KI-gestützte Plattform mit drei Modulen: AI-Fragen mit rekursiven Inline-Erklärungen, Web-Zusammenfassungen mit Link-Navigation, und YouTube-Suche mit Transcript-Summaries.

## Features

### AI Tab
- **Frage stellen** → LLM antwortet kurz und prägnant
- **Klickbare Fachbegriffe** — schwer verständliche Begriffe werden automatisch markiert
- **Inline-Erklärungen** — Klick auf einen Begriff fügt eine Erklärung in Klammern nahtlos in den Text ein
- **Rekursiv** — Erklärungen enthalten selbst wieder klickbare Begriffe, beliebig tief
- **Farbtiefe** — jede Erklärungsebene in eigener Farbe (lila → rosa → grün → gelb → orange)
- **Cache** — einmal geladene Erklärungen werden gecacht, Auf-/Zuklappen ohne API-Call
- **Toggle** — Klick auf Erklärung klappt sie zu, Klick auf Begriff öffnet sie wieder

### AI Web Tab
- **Zwei Modi:**
  - **Iframe-Modus** (Standard) — Webseite wird eingebettet, Links öffnen ein Popup (Öffnen / Summary / Hier laden)
  - **Zusammenfassungs-Modus** (Toggle) — LLM-Summary mit klickbaren Inline-Links, Navigation durch Zusammenfassungen
- **Seite zusammenfassen** — Button in der Adressleiste fasst die aktuelle Seite zusammen
- **Kategorisierte Links** — Links werden nach Relevanz sortiert in aufklappbare Sektionen:
  - Inhaltliche Links (offen)
  - Kategorien & Themen (zugeklappt)
  - Navigation & Sonstiges (zugeklappt)
  - Social Media (zugeklappt)
- **Zurück-Navigation** — Breadcrumb-Historie beim Browsen durch Summaries

### YT Search Tab
- **YouTube-Suche** via Innertube API (schnell, kein API-Key nötig)
- **10 Ergebnisse** pro Seite mit "Mehr laden" (Continuation-Token)
- **Video-Karten** mit Thumbnail, Titel, Kanal, Views, Datum
- **Sortierung** — Relevanz, Views ↓/↑, Neueste, Älteste
- **Öffnen** — Direktlink zu YouTube
- **Summary** — Transcript automatisch laden und per LLM zusammenfassen

### Allgemein
- **Passwortschutz** (optional) — in `config.json` konfigurierbar, Cookie-basiert (90 Tage)
- **Sub-Pfade** — `index.html` in Unterordnern von `static/` erreichbar (z.B. `/test`)
- **CLI-Optionen** — `--port`, `--host`, `--debug` überschreiben `config.json`

## Setup

```bash
# 1. Dependencies
pip install -r requirements.txt

# 2. Config anpassen — API Key eintragen
nano config.json

# 3. Server starten
python server.py --port 8080
```

Browser öffnen: **http://localhost:8080**

## Projektstruktur

```
├── server.py           # Flask Backend (alle API-Endpoints)
├── config.json         # LLM, Server, YouTube Konfiguration
├── requirements.txt    # Python Dependencies
├── README.md
└── static/
    └── index.html      # Frontend (Tabs, UI, JS)
```

## Config (`config.json`)

```json
{
  "llm": {
    "provider": "openrouter",
    "api_url": "https://openrouter.ai/api/v1/chat/completions",
    "api_key": "YOUR_OPENROUTER_API_KEY",
    "model": "google/gemini-2.0-flash-001",
    "max_tokens": 1024,
    "temperature": 0.3
  },
  "server": {
    "host": "0.0.0.0",
    "port": 5000,
    "debug": true,
    "password": ""
  },
  "youtube": {
    "results_per_page": 10,
    "transcript_languages": ["de", "en", "auto"]
  }
}
```

| Feld | Beschreibung |
|------|-------------|
| `llm.api_key` | OpenRouter API Key |
| `llm.model` | z.B. `google/gemini-2.0-flash-001`, `anthropic/claude-3.5-sonnet`, `openai/gpt-4o-mini` |
| `server.password` | Leer = kein Passwort. Gesetzt = Login-Seite mit Cookie (90 Tage) |
| `youtube.results_per_page` | Videos pro Seite (Standard: 10) |
| `youtube.transcript_languages` | Bevorzugte Sprachen, z.B. `["de", "en"]` |

## API Endpoints

| Endpoint | Methode | Beschreibung |
|----------|---------|-------------|
| `/api/ask` | POST | AI-Frage beantworten mit markierten Begriffen |
| `/api/explain` | POST | Begriff als Inline-Klammer erklären (rekursiv) |
| `/api/search?q=...` | GET | YouTube-Suche (Innertube API) |
| `/api/transcript/<id>` | GET | Video-Transcript abrufen |
| `/api/summary` | POST | Transcript + LLM-Zusammenfassung |
| `/api/web-fetch?url=...` | GET | Webseite via Proxy laden |
| `/api/web-summary` | POST | Webseite zusammenfassen mit kategorisierten Links |
| `/api/login` | POST | Passwort-Authentifizierung |

## Tech Stack

- **Backend:** Python / Flask
- **Transcript:** `youtube-transcript-api` (kostenlos)
- **Suche:** YouTube Innertube API (kostenlos, kein Key nötig)
- **Web-Extraktion:** BeautifulSoup4
- **LLM:** OpenRouter (oder jeder OpenAI-kompatible Endpoint)
- **Frontend:** Vanilla HTML/CSS/JS, kein Build-Step
