# AI Web · YT Search

AI-powered platform with three modules: an AI Q&A with recursive inline explanations, web page summarization with link navigation, and YouTube search with transcript summaries.

## Features

### AI Tab
- **Ask questions** → LLM responds concisely
- **Clickable terms** — complex concepts are automatically highlighted
- **Inline explanations** — click a term to insert a parenthetical explanation seamlessly into the text
- **Recursive** — explanations contain their own clickable terms, nestable to any depth
- **Color-coded depth** — each explanation level uses a distinct color (purple → pink → green → yellow → orange)
- **Cached** — explanations are cached client-side; toggling open/closed requires no API calls
- **Toggle** — click an explanation to collapse it, click the term to expand it again

### AI Web Tab
- **Two modes:**
  - **Iframe mode** (default) — pages are embedded via proxy, link clicks open a popup (Open / Summary / Load here)
  - **Summary mode** (toggle) — LLM summary with clickable inline links, browse through summaries
- **Summarize page** — button in the address bar summarizes the current page
- **Categorized links** — links are relevance-scored and grouped into collapsible sections:
  - Content links (open by default)
  - Categories & Topics (collapsed)
  - Navigation & Misc (collapsed)
  - Social Media (collapsed)
- **Back navigation** — breadcrumb history when browsing through summaries

### YT Search Tab
- **YouTube search** via Innertube API (fast, no API key needed)
- **10 results** per page with "Load more" (continuation tokens)
- **Video cards** with thumbnail, title, channel, views, date
- **Sorting** — Relevance, Views ↓/↑, Newest, Oldest
- **Open** — direct link to YouTube
- **Summary** — automatically fetch transcript and summarize via LLM

### General
- **Password protection** (optional) — configurable in `config.json`, cookie-based (90 days)
- **Sub-paths** — place `index.html` in subdirectories of `static/` (e.g. accessible at `/test`)
- **CLI options** — `--port`, `--host`, `--debug` override `config.json`

## Setup

```bash
# 1. Install dependencies
pip install -r requirements.txt

# 2. Configure — add your API key
nano config.json

# 3. Start the server
python server.py --port 8080
```

Open in browser: **http://localhost:8080**

## Project Structure

```
├── server.py           # Flask backend (all API endpoints)
├── config.json         # LLM, server, YouTube configuration
├── requirements.txt    # Python dependencies
├── README.md
└── static/
    └── index.html      # Frontend (tabs, UI, JS — single file)
```

## Configuration (`config.json`)

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

| Field | Description |
|-------|-------------|
| `llm.api_key` | Your OpenRouter API key |
| `llm.model` | e.g. `google/gemini-2.0-flash-001`, `anthropic/claude-3.5-sonnet`, `openai/gpt-4o-mini` |
| `server.password` | Empty = no auth. Set a value = login page with 90-day cookie |
| `youtube.results_per_page` | Videos per page (default: 10) |
| `youtube.transcript_languages` | Preferred transcript languages, e.g. `["de", "en"]` |

## API Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/ask` | POST | Answer a question with highlighted terms |
| `/api/explain` | POST | Explain a term as an inline parenthetical (recursive) |
| `/api/search?q=...` | GET | YouTube search (Innertube API) |
| `/api/transcript/<id>` | GET | Fetch video transcript |
| `/api/summary` | POST | Transcript + LLM summary |
| `/api/web-fetch?url=...` | GET | Proxy-fetch a web page |
| `/api/web-summary` | POST | Summarize a web page with categorized links |
| `/api/login` | POST | Password authentication |

## Tech Stack

- **Backend:** Python / Flask
- **Transcripts:** `youtube-transcript-api` (free, no API key)
- **Search:** YouTube Innertube API (free, no API key)
- **Web extraction:** BeautifulSoup4
- **LLM:** OpenRouter (or any OpenAI-compatible endpoint)
- **Frontend:** Vanilla HTML/CSS/JS, no build step
