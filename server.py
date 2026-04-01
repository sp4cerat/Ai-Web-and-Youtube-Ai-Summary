#!/usr/bin/env python3
"""
YouTube Search + Transcript Summary Server
-------------------------------------------
Endpoints:
  GET  /                     → serves the frontend
  GET  /api/search?q=...&page=1  → search YouTube videos
  GET  /api/transcript/<id>  → fetch transcript for a video
  POST /api/summary          → fetch transcript + summarize via LLM

Config: config.json (LLM provider, model, API key, server settings)
"""

import json
import hashlib
import os
import re
import secrets
import requests
from flask import Flask, jsonify, request, send_from_directory, make_response
from youtube_transcript_api import YouTubeTranscriptApi

# ── Load config ──────────────────────────────────────────────────────────────

CONFIG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.json")

with open(CONFIG_PATH, "r") as f:
    CONFIG = json.load(f)

LLM = CONFIG["llm"]
SERVER = CONFIG["server"]
YT = CONFIG["youtube"]

# Generate a stable auth token from the password (so cookies survive restarts)
PASSWORD = SERVER.get("password", "").strip()
AUTH_TOKEN = hashlib.sha256(f"ytsearch:{PASSWORD}".encode()).hexdigest() if PASSWORD else ""

app = Flask(__name__, static_folder="static")
app.secret_key = secrets.token_hex(32)


# ── Auth ─────────────────────────────────────────────────────────────────────

LOGIN_PAGE = """<!DOCTYPE html>
<html lang="de">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>YT Search · Login</title>
<link href="https://fonts.googleapis.com/css2?family=DM+Sans:wght@400;500;700&family=Space+Mono:wght@700&display=swap" rel="stylesheet">
<style>
  :root { --bg:#0a0a0c; --surface:#131318; --border:#2a2a35; --text:#e8e6f0;
          --text-dim:#8b8998; --accent:#ff3b5c; --accent2:#7c5cff; }
  * { margin:0; padding:0; box-sizing:border-box; }
  body { font-family:'DM Sans',sans-serif; background:var(--bg); color:var(--text);
         min-height:100vh; display:flex; align-items:center; justify-content:center; }
  .login-box { background:var(--surface); border:1px solid var(--border); border-radius:16px;
               padding:40px; max-width:380px; width:100%; text-align:center; }
  .login-box h1 { font-family:'Space Mono',monospace; font-size:1.5rem; margin-bottom:8px;
                   background:linear-gradient(135deg,var(--accent),var(--accent2));
                   -webkit-background-clip:text; -webkit-text-fill-color:transparent; }
  .login-box p { color:var(--text-dim); font-size:0.9rem; margin-bottom:24px; }
  .login-input { width:100%; padding:14px 18px; border-radius:10px; border:1px solid var(--border);
                 background:var(--bg); color:var(--text); font-family:inherit; font-size:1rem;
                 outline:none; margin-bottom:16px; transition:border-color 0.3s; }
  .login-input:focus { border-color:var(--accent2); }
  .login-btn { width:100%; padding:14px; border:none; border-radius:10px; cursor:pointer;
               background:linear-gradient(135deg,var(--accent),var(--accent2)); color:#fff;
               font-family:inherit; font-size:1rem; font-weight:600; transition:opacity 0.2s; }
  .login-btn:hover { opacity:0.85; }
  .login-error { color:var(--accent); font-size:0.85rem; margin-top:12px; display:none; }
</style>
</head>
<body>
<div class="login-box">
  <h1>▶ YT Search</h1>
  <p>Passwort eingeben</p>
  <input type="password" class="login-input" id="pw" placeholder="Passwort" autofocus
         onkeydown="if(event.key==='Enter')login()">
  <button class="login-btn" onclick="login()">Anmelden</button>
  <div class="login-error" id="err">Falsches Passwort</div>
</div>
<script>
async function login() {
  const pw = document.getElementById('pw').value;
  const resp = await fetch('/api/login', {
    method: 'POST',
    headers: {'Content-Type':'application/json'},
    body: JSON.stringify({password: pw})
  });
  if (resp.ok) {
    window.location.reload();
  } else {
    document.getElementById('err').style.display = 'block';
    document.getElementById('pw').value = '';
    document.getElementById('pw').focus();
  }
}
</script>
</body>
</html>"""


@app.before_request
def check_auth():
    """If password is configured, require auth cookie for all routes except login."""
    if not PASSWORD:
        return  # No password set → open access

    if request.path == "/api/login":
        return  # Allow login endpoint

    token = request.cookies.get("yt_auth", "")
    if token != AUTH_TOKEN:
        # Return login page for browser requests, 401 for API
        if request.path.startswith("/api/"):
            return jsonify({"error": "Nicht autorisiert"}), 401
        return LOGIN_PAGE, 200


@app.route("/api/login", methods=["POST"])
def login():
    """Validate password and set auth cookie."""
    data = request.get_json() or {}
    pw = data.get("password", "")

    if pw == PASSWORD:
        resp = make_response(jsonify({"ok": True}))
        resp.set_cookie(
            "yt_auth",
            AUTH_TOKEN,
            max_age=60 * 60 * 24 * 90,  # 90 Tage
            httponly=True,
            samesite="Lax",
        )
        return resp
    return jsonify({"error": "Falsches Passwort"}), 403


# ── Routes ───────────────────────────────────────────────────────────────────

@app.route("/")
def index():
    return send_from_directory("static", "index.html")


@app.route("/<path:subpath>")
def serve_subpath(subpath):
    """Serve index.html from static/<subpath>/ subdirectories."""
    # Try subpath/index.html first, then subpath as file
    import os
    sub_index = os.path.join(subpath, "index.html")
    static_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")
    if os.path.isfile(os.path.join(static_dir, sub_index)):
        return send_from_directory("static", sub_index)
    if os.path.isfile(os.path.join(static_dir, subpath)):
        return send_from_directory("static", subpath)
    return "Not found", 404


@app.route("/api/search")
def search_videos():
    """Search YouTube via Innertube API (single request, full metadata)."""
    query = request.args.get("q", "").strip()
    continuation = request.args.get("continuation", "")
    per_page = YT.get("results_per_page", 10)

    if not query and not continuation:
        return jsonify({"error": "Missing query parameter 'q'"}), 400

    try:
        headers = {
            "Content-Type": "application/json",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        }

        if continuation:
            # Load more results via continuation token
            payload = {
                "context": {
                    "client": {
                        "clientName": "WEB",
                        "clientVersion": "2.20240101.00.00",
                        "hl": "de",
                        "gl": "DE",
                    }
                },
                "continuation": continuation,
            }
            resp = requests.post(
                "https://www.youtube.com/youtubei/v1/search?prettyPrint=false",
                headers=headers,
                json=payload,
                timeout=15,
            )
        else:
            # Initial search
            payload = {
                "context": {
                    "client": {
                        "clientName": "WEB",
                        "clientVersion": "2.20240101.00.00",
                        "hl": "de",
                        "gl": "DE",
                    }
                },
                "query": query,
            }
            resp = requests.post(
                "https://www.youtube.com/youtubei/v1/search?prettyPrint=false",
                headers=headers,
                json=payload,
                timeout=15,
            )

        resp.raise_for_status()
        data = resp.json()

        # Parse results from Innertube response
        videos = []
        next_continuation = ""

        # Extract video items from the nested response structure
        contents = []
        if continuation:
            # Continuation response structure
            actions = data.get("onResponseReceivedCommands", [])
            for action in actions:
                items = (
                    action.get("appendContinuationItemsAction", {})
                    .get("continuationItems", [])
                )
                contents.extend(items)
        else:
            # Initial search response structure
            sections = (
                data.get("contents", {})
                .get("twoColumnSearchResultsRenderer", {})
                .get("primaryContents", {})
                .get("sectionListRenderer", {})
                .get("contents", [])
            )
            for section in sections:
                items = (
                    section.get("itemSectionRenderer", {})
                    .get("contents", [])
                )
                contents.extend(items)
                # Check for continuation token in section list
                ct = section.get("continuationItemRenderer", {})
                if ct:
                    next_continuation = (
                        ct.get("continuationEndpoint", {})
                        .get("continuationCommand", {})
                        .get("token", "")
                    )

        for item in contents:
            # Check for continuation token
            ct = item.get("continuationItemRenderer", {})
            if ct:
                next_continuation = (
                    ct.get("continuationEndpoint", {})
                    .get("continuationCommand", {})
                    .get("token", "")
                )
                continue

            renderer = item.get("videoRenderer")
            if not renderer:
                continue

            vid_id = renderer.get("videoId", "")

            # Title
            title_runs = renderer.get("title", {}).get("runs", [])
            title = "".join(r.get("text", "") for r in title_runs)

            # Channel
            channel_runs = (
                renderer.get("ownerText", {}).get("runs", [])
                or renderer.get("longBylineText", {}).get("runs", [])
            )
            channel = "".join(r.get("text", "") for r in channel_runs)

            # Duration
            duration_text = (
                renderer.get("lengthText", {}).get("simpleText", "")
            )

            # Views - extract raw number
            view_text = renderer.get("viewCountText", {}).get("simpleText", "")
            view_count = 0
            if view_text:
                digits = re.sub(r"[^\d]", "", view_text)
                view_count = int(digits) if digits else 0

            # Format views for display
            if view_count >= 1_000_000:
                views = f"{view_count / 1_000_000:.1f}M views"
            elif view_count >= 1_000:
                views = f"{view_count / 1_000:.1f}K views"
            elif view_count > 0:
                views = f"{view_count} views"
            else:
                views = view_text  # fallback to raw text (e.g. live streams)

            # Published date
            published_text = renderer.get("publishedTimeText", {}).get("simpleText", "")

            # Thumbnail
            thumbs = renderer.get("thumbnail", {}).get("thumbnails", [])
            thumb_url = thumbs[-1]["url"] if thumbs else f"https://i.ytimg.com/vi/{vid_id}/hqdefault.jpg"

            videos.append(
                {
                    "id": vid_id,
                    "title": title,
                    "channel": channel,
                    "duration": duration_text,
                    "views": views,
                    "view_count": view_count,
                    "published": published_text,
                    "thumbnail": thumb_url,
                    "url": f"https://www.youtube.com/watch?v={vid_id}",
                }
            )

        has_more = bool(next_continuation)

        return jsonify({
            "videos": videos,
            "has_more": has_more,
            "continuation": next_continuation,
        })

    except requests.exceptions.Timeout:
        return jsonify({"error": "Suche hat zu lange gedauert"}), 504
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/transcript/<video_id>")
def get_transcript(video_id):
    """Fetch the transcript/captions for a YouTube video."""
    langs = YT.get("transcript_languages", ["de", "en"])

    try:
        ytt = YouTubeTranscriptApi()
        entries = ytt.fetch(video_id, languages=langs)

        # Build full text
        full_text = " ".join(
            snippet.text for snippet in entries
        )
        # Also return structured entries
        structured = [
            {
                "start": round(snippet.start, 1),
                "duration": round(snippet.duration, 1),
                "text": snippet.text,
            }
            for snippet in entries
        ]

        lang_code = getattr(entries, "language_code", langs[0] if langs else "en")

        return jsonify(
            {
                "video_id": video_id,
                "language": lang_code,
                "text": full_text,
                "segments": structured,
            }
        )

    except Exception as e:
        return jsonify({"error": f"Transcript-Fehler: {str(e)}"}), 500


@app.route("/api/summary", methods=["POST"])
def summarize():
    """Fetch transcript and summarize it via the configured LLM."""
    data = request.get_json() or {}
    video_id = data.get("video_id", "")
    video_title = data.get("title", "Video")

    if not video_id:
        return jsonify({"error": "video_id fehlt"}), 400

    # Step 1: Get transcript
    langs = YT.get("transcript_languages", ["de", "en"])
    try:
        ytt = YouTubeTranscriptApi()
        entries = ytt.fetch(video_id, languages=langs)
        full_text = " ".join(snippet.text for snippet in entries)
        lang_code = getattr(entries, "language_code", langs[0] if langs else "en")

    except Exception as e:
        return jsonify({"error": f"Transcript-Fehler: {str(e)}"}), 500

    # Truncate very long transcripts (most LLMs handle ~100k tokens)
    max_chars = 80_000
    if len(full_text) > max_chars:
        full_text = full_text[:max_chars] + "\n\n[... Transcript gekürzt ...]"

    # Step 2: Summarize via LLM
    summary_lang = "Deutsch" if lang_code.startswith("de") else "der Sprache des Transcripts"

    prompt = f"""Fasse das folgende YouTube-Video-Transcript zusammen.

Video-Titel: {video_title}

Erstelle eine strukturierte Zusammenfassung auf {summary_lang} mit:
1. **Kernaussage** (1-2 Sätze)
2. **Wichtigste Punkte** (3-7 Stichpunkte)
3. **Fazit / Takeaway** (1-2 Sätze)

Transcript:
{full_text}"""

    try:
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {LLM['api_key']}",
        }
        # Support site URL / app name for OpenRouter
        if LLM.get("provider") == "openrouter":
            headers["HTTP-Referer"] = "http://localhost:5000"
            headers["X-Title"] = "YT-Search-Summary"

        payload = {
            "model": LLM["model"],
            "max_tokens": LLM.get("max_tokens", 1024),
            "temperature": LLM.get("temperature", 0.3),
            "messages": [{"role": "user", "content": prompt}],
        }

        resp = requests.post(LLM["api_url"], headers=headers, json=payload, timeout=60)
        resp.raise_for_status()
        result = resp.json()

        # Extract text from response (OpenRouter / OpenAI compatible format)
        summary_text = (
            result.get("choices", [{}])[0]
            .get("message", {})
            .get("content", "Keine Zusammenfassung erhalten.")
        )

        return jsonify(
            {
                "video_id": video_id,
                "title": video_title,
                "summary": summary_text,
                "model": LLM["model"],
                "transcript_length": len(full_text),
            }
        )

    except requests.exceptions.RequestException as e:
        return jsonify({"error": f"LLM-Fehler: {str(e)}"}), 500


# ── Web Proxy & Summary ──────────────────────────────────────────────────────

@app.route("/api/web-fetch")
def web_fetch():
    """Proxy-fetch a web page and return HTML with rewritten links."""
    url = request.args.get("url", "").strip()
    if not url:
        return jsonify({"error": "URL fehlt"}), 400

    if not url.startswith(("http://", "https://")):
        url = "https://" + url

    try:
        from urllib.parse import urljoin, urlparse

        resp = requests.get(
            url,
            headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
            },
            timeout=15,
            allow_redirects=True,
        )
        resp.raise_for_status()

        # Detect encoding
        resp.encoding = resp.apparent_encoding or "utf-8"
        html = resp.text
        base_url = resp.url  # final URL after redirects

        # Get page title
        title = ""
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(html, "html.parser")
        if soup.title and soup.title.string:
            title = soup.title.string.strip()

        # Inject <base> tag so relative resources load correctly
        parsed = urlparse(base_url)
        base_origin = f"{parsed.scheme}://{parsed.netloc}"
        base_tag = f'<base href="{base_url}" target="_blank">'

        # Inject our link-interceptor script + base tag
        inject_script = """
<script>
document.addEventListener('click', function(e) {
    var link = e.target.closest('a');
    if (!link || !link.href) return;
    var href = link.getAttribute('href') || '';
    if (href.startsWith('#') || href.startsWith('javascript:')) return;
    if (link.getAttribute('role') === 'button') return;
    if (link.closest('form') || link.closest('button')) return;
    if (link.type === 'submit' || link.classList.contains('btn') || link.classList.contains('button')) return;
    e.preventDefault();
    e.stopPropagation();
    window.parent.postMessage({
        type: 'link-click',
        url: link.href,
        text: (link.textContent || '').trim().substring(0, 200)
    }, '*');
}, true);
</script>
"""
        # Insert base tag and script into head
        if "<head" in html.lower():
            html = re.sub(
                r"(<head[^>]*>)",
                rf"\1{base_tag}",
                html,
                count=1,
                flags=re.IGNORECASE,
            )
        else:
            html = base_tag + html

        # Append interceptor script before </body> or at end
        if "</body>" in html.lower():
            html = html.replace("</body>", inject_script + "</body>")
            html = html.replace("</BODY>", inject_script + "</BODY>")
        else:
            html += inject_script

        return jsonify({
            "html": html,
            "url": base_url,
            "title": title,
        })

    except requests.exceptions.RequestException as e:
        return jsonify({"error": f"Fetch-Fehler: {str(e)}"}), 500
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/web-summary", methods=["POST"])
def web_summary():
    """Fetch a web page, extract text, and summarize via LLM."""
    data = request.get_json() or {}
    url = data.get("url", "").strip()
    link_text = data.get("text", "")

    if not url:
        return jsonify({"error": "URL fehlt"}), 400

    if not url.startswith(("http://", "https://")):
        url = "https://" + url

    # Step 1: Fetch page and extract text
    try:
        from urllib.parse import urljoin, urlparse

        resp = requests.get(
            url,
            headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
            },
            timeout=15,
            allow_redirects=True,
        )
        resp.raise_for_status()
        resp.encoding = resp.apparent_encoding or "utf-8"

        from bs4 import BeautifulSoup
        soup = BeautifulSoup(resp.text, "html.parser")

        page_title = ""
        if soup.title and soup.title.string:
            page_title = soup.title.string.strip()

        # Extract links with relevance scoring
        base_url = resp.url
        parsed_base = urlparse(base_url)
        base_domain = parsed_base.netloc.replace("www.", "")

        nav_tags = {"nav", "footer", "header", "aside"}
        nav_classes = {"nav", "navbar", "sidebar", "footer", "menu", "breadcrumb",
                       "widget", "social", "share", "cookie", "banner", "ad",
                       "advertisement", "related", "trending", "ticker", "breaking"}

        raw_links = []
        seen_urls = set()
        for a in soup.find_all("a", href=True):
            href = a["href"].strip()
            if not href or href.startswith("#") or href.startswith("javascript:"):
                continue
            if a.get("role") == "button" or a.find_parent("button"):
                continue
            abs_url = urljoin(base_url, href)
            if not abs_url.startswith(("http://", "https://")):
                continue
            link_text = a.get_text(strip=True)
            if not link_text or len(link_text) < 5:
                continue
            if abs_url in seen_urls:
                continue
            seen_urls.add(abs_url)

            # ── Score and classify the link ──
            score = 50  # base score
            link_type = "content"  # default

            # Detect social links
            social_domains = {"facebook.com", "twitter.com", "x.com", "instagram.com",
                              "linkedin.com", "youtube.com", "tiktok.com", "pinterest.com",
                              "reddit.com", "t.me", "telegram.org", "whatsapp.com",
                              "mastodon.social", "threads.net", "bsky.app"}
            link_domain = urlparse(abs_url).netloc.replace("www.", "")
            if any(sd in link_domain for sd in social_domains):
                link_type = "social"
                score -= 40

            # Detect category/tag/meta links
            lower_url = abs_url.lower()
            cat_patterns = ["/tag/", "/category/", "/kategorie/", "/thema/",
                            "/rubrik/", "/ressort/", "/topics/", "/author/", "/autor/"]
            if any(p in lower_url for p in cat_patterns):
                link_type = "category"
                score -= 30

            # Detect utility/legal links
            util_patterns = ["/login", "/register", "/search", "/newsletter",
                             "/datenschutz", "/impressum", "/privacy", "/terms",
                             "/contact", "/kontakt", "/about", "/feed", ".xml", ".rss",
                             "/agb", "/nutzungsbedingungen", "/hilfe", "/help", "/faq"]
            if any(p in lower_url for p in util_patterns):
                link_type = "nav"
                score -= 30

            # Check if in nav/footer/sidebar
            in_nav = False
            for parent in a.parents:
                tag_name = parent.name or ""
                if tag_name in nav_tags:
                    in_nav = True
                    break
                parent_classes = " ".join(parent.get("class", []) or []).lower()
                parent_id = (parent.get("id") or "").lower()
                if any(nc in parent_classes or nc in parent_id for nc in nav_classes):
                    in_nav = True
                    break

            if in_nav and link_type == "content":
                link_type = "nav"
                score -= 40

            # Boost: longer link text (more descriptive = more likely article)
            if len(link_text) > 30:
                score += 20
            elif len(link_text) > 15:
                score += 10

            # Boost: link inside <article>, <main>, <section>, <p>
            for parent in a.parents:
                if parent.name == "article" or parent.name == "main":
                    score += 30
                    if link_type != "content":
                        link_type = "content"  # override if clearly in content
                    break
                parent_classes = " ".join(parent.get("class", []) or []).lower()
                if any(c in parent_classes for c in ["content", "article", "story", "post", "entry", "body"]):
                    score += 25
                    if link_type != "content":
                        link_type = "content"
                    break

            # Boost: same domain (internal content links)
            if link_domain == base_domain:
                score += 10

            # Penalize: very short paths (likely homepage/category)
            link_path = urlparse(abs_url).path.strip("/")
            if len(link_path) < 5 or link_path.count("/") == 0:
                score -= 15

            raw_links.append({"url": abs_url, "text": link_text[:150], "score": score, "type": link_type})

        # Separate by type, sort each by score
        raw_links.sort(key=lambda x: x["score"], reverse=True)
        links = [{"url": l["url"], "text": l["text"]} for l in raw_links if l["type"] == "content" and l["score"] > 10][:30]
        nav_links = [{"url": l["url"], "text": l["text"]} for l in raw_links if l["type"] == "nav"][:15]
        cat_links = [{"url": l["url"], "text": l["text"]} for l in raw_links if l["type"] == "category"][:15]
        social_links = [{"url": l["url"], "text": l["text"]} for l in raw_links if l["type"] == "social"][:10]

        # Remove non-content elements for text extraction
        for tag in soup(["script", "style", "nav", "footer", "header", "aside", "iframe", "noscript"]):
            tag.decompose()

        # Extract text
        full_text = soup.get_text(separator="\n", strip=True)
        full_text = re.sub(r"\n{3,}", "\n\n", full_text)

    except requests.exceptions.RequestException as e:
        return jsonify({"error": f"Fetch-Fehler: {str(e)}"}), 500
    except Exception as e:
        return jsonify({"error": str(e)}), 500

    if len(full_text.strip()) < 50:
        return jsonify({"error": "Zu wenig Text auf der Seite gefunden"}), 404

    # Truncate
    max_chars = 80_000
    if len(full_text) > max_chars:
        full_text = full_text[:max_chars] + "\n\n[... Text gekürzt ...]"

    # Step 2: Summarize via LLM
    title_for_prompt = page_title or link_text or url

    # Build link reference for the LLM
    link_ref = ""
    if links:
        link_lines = []
        for i, lnk in enumerate(links):
            link_lines.append(f"[{i+1}] {lnk['text']} → {lnk['url']}")
        link_ref = "\n".join(link_lines)

    prompt = f"""Fasse den folgenden Webseiten-Inhalt zusammen.

Seiten-Titel: {title_for_prompt}
URL: {url}

Erstelle eine strukturierte Zusammenfassung auf Deutsch mit:
1. **Kernaussage** (1-2 Sätze)
2. **Wichtigste Punkte** (3-7 Stichpunkte)
3. **Fazit / Takeaway** (1-2 Sätze)

VERLINKUNG:
- Verlinke NUR Begriffe, die direkt im Inhalt inhaltlich relevant sind — z.B. erwähnte Personen,
  Ereignisse, Studien, Produkte oder vertiefende Artikel.
- Nutze Markdown-Links: [Stichwort](URL)
- Verwende NUR URLs aus der Link-Liste unten, die zum jeweiligen Thema passen.
- KEINE Links für Navigationselemente, Kategorien, Menüpunkte, Social Media oder Werbung.
- Maximal 3-6 Links im gesamten Text — nur die inhaltlich wertvollsten.
- Im Zweifel lieber keinen Link setzen als einen irrelevanten.

Verfügbare inhaltliche Links:
{link_ref}

Inhalt:
{full_text}"""

    try:
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {LLM['api_key']}",
        }
        if LLM.get("provider") == "openrouter":
            headers["HTTP-Referer"] = "http://localhost:5000"
            headers["X-Title"] = "AI-Web-Summary"

        payload = {
            "model": LLM["model"],
            "max_tokens": LLM.get("max_tokens", 1024),
            "temperature": LLM.get("temperature", 0.3),
            "messages": [{"role": "user", "content": prompt}],
        }

        llm_resp = requests.post(LLM["api_url"], headers=headers, json=payload, timeout=60)
        llm_resp.raise_for_status()
        result = llm_resp.json()

        summary_text = (
            result.get("choices", [{}])[0]
            .get("message", {})
            .get("content", "Keine Zusammenfassung erhalten.")
        )

        return jsonify(
            {
                "url": url,
                "title": page_title,
                "summary": summary_text,
                "model": LLM["model"],
                "text_length": len(full_text),
                "links": links,
                "nav_links": nav_links,
                "cat_links": cat_links,
                "social_links": social_links,
            }
        )

    except requests.exceptions.RequestException as e:
        return jsonify({"error": f"LLM-Fehler: {str(e)}"}), 500


# ── AI Ask & Explain ─────────────────────────────────────────────────────────

def _llm_call(prompt, max_tokens=None):
    """Helper: call configured LLM and return response text."""
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {LLM['api_key']}",
    }
    if LLM.get("provider") == "openrouter":
        headers["HTTP-Referer"] = "http://localhost:5000"
        headers["X-Title"] = "AI-Ask"

    payload = {
        "model": LLM["model"],
        "max_tokens": max_tokens or LLM.get("max_tokens", 1024),
        "temperature": LLM.get("temperature", 0.3),
        "messages": [{"role": "user", "content": prompt}],
    }
    resp = requests.post(LLM["api_url"], headers=headers, json=payload, timeout=60)
    resp.raise_for_status()
    result = resp.json()
    return (
        result.get("choices", [{}])[0]
        .get("message", {})
        .get("content", "")
    )


@app.route("/api/ask", methods=["POST"])
def ask():
    """Answer a question, marking complex terms with {{term}} syntax."""
    data = request.get_json() or {}
    question = data.get("question", "").strip()

    if not question:
        return jsonify({"error": "Frage fehlt"}), 400

    prompt = f"""Beantworte die folgende Frage kurz und prägnant auf Deutsch.

WICHTIG: Markiere schwer verständliche Fachbegriffe, Konzepte oder Passagen mit
doppelten spitzen Klammern: <<Begriff>> oder <<komplexe Passage>>.
Markiere 3-8 Begriffe pro Antwort — nur solche, die wirklich erklärungsbedürftig sind.
Beispiel: "Die <<Mitochondrien>> sind für die <<ATP-Synthese>> verantwortlich."
Verwende NIEMALS geschweifte Klammern {{}} für Markierungen.

Frage: {question}"""

    try:
        answer = _llm_call(prompt)
        return jsonify({
            "answer": answer,
            "model": LLM["model"],
        })
    except requests.exceptions.RequestException as e:
        return jsonify({"error": f"LLM-Fehler: {str(e)}"}), 500


@app.route("/api/explain", methods=["POST"])
def explain():
    """Explain a term as a short parenthetical insert."""
    data = request.get_json() or {}
    term = data.get("term", "").strip()
    context = data.get("context", "").strip()
    sentence = data.get("sentence", "").strip()

    if not term:
        return jsonify({"error": "Begriff fehlt"}), 400

    prompt = f"""Erkläre "{term}" als Klammereinschub in 20-40 Wörtern.

Antwortformat EXAKT so — NUR der Klammerinhalt:
(inhaltliche Erklärung hier)

REGELN:
- Erkläre die BEDEUTUNG und RELEVANZ, nicht bloß Symbole oder Buchstaben.
- Bei Formeln: erkläre was die Formel AUSSAGT, nicht was die Variablen heißen.
- Allgemeinverständlich, aber nicht trivial. Ein informierter Laie soll es verstehen.
- Markiere 0-2 schwer verständliche Unterbegriffe mit <<Begriff>>.

Beispiele:
- "S = A/4G" → (besagt, dass die Entropie eines Schwarzen Lochs proportional zu seiner <<Ereignishorizont>>-Fläche ist — ein zentraler Hinweis auf die Verbindung zwischen <<Quanteninformation>> und Raumzeitgeometrie)
- "Mitochondrien" → (Zellorganellen, die Nährstoffe in den universellen Energieträger <<ATP>> umwandeln und so praktisch alle Lebensprozesse antreiben)
- "CRISPR" → (ein molekulares Werkzeug, mit dem Forscher gezielt einzelne <<Gene>> verändern können, basierend auf einem natürlichen Abwehrmechanismus von Bakterien)
- "Hubble-Konstante" → (gibt an, wie schnell sich das Universum aktuell ausdehnt — verschiedene Messmethoden liefern widersprüchliche Werte, bekannt als die <<Hubble-Spannung>>)

Gib NUR die Klammer zurück. Keinen Satz drumherum, keine Wiederholung des Begriffs.

{"Kontext: " + context if context else ""}
Begriff: "{term}"
Antwort:"""

    try:
        explanation = _llm_call(prompt, max_tokens=250)

        # Aggressive cleanup
        explanation = explanation.strip().strip('"').strip("'")
        explanation = re.sub(r"\n+", " ", explanation)
        explanation = re.sub(r"\s{2,}", " ", explanation).strip()

        # If LLM returned more than the parenthetical, extract the outer (...)
        # Match opening ( to last ) — handles nested parens
        paren_match = re.match(r"^\s*(\(.*\))\s*$", explanation, re.DOTALL)
        if paren_match:
            explanation = paren_match.group(1)
        elif "(" in explanation and ")" in explanation:
            start = explanation.index("(")
            end = explanation.rindex(")") + 1
            explanation = explanation[start:end]
        else:
            # No parens found — wrap it, and truncate if too long
            # Remove any repeated sentence context
            if sentence:
                # Strip anything that looks like the original sentence
                for fragment in sentence.split("."):
                    fragment = fragment.strip()
                    if len(fragment) > 20 and fragment in explanation:
                        explanation = explanation.replace(fragment, "").strip(" ,.")
            # Remove the term itself from the start
            if explanation.lower().startswith(term.lower()):
                explanation = explanation[len(term):].lstrip(" ,;:-")
            # Remove leading/trailing junk
            explanation = explanation.strip(" ,;:.")
            if explanation:
                explanation = f"({explanation})"

        # Final safety: cap length
        if len(explanation) > 500:
            cut = explanation[:500].rfind(" ")
            explanation = explanation[:cut].rstrip(" ,;:") + ")"

        return jsonify({
            "term": term,
            "explanation": explanation,
        })
    except requests.exceptions.RequestException as e:
        return jsonify({"error": f"LLM-Fehler: {str(e)}"}), 500


# ── Main ─────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="YT Search + Transcript Summary Server")
    parser.add_argument("-p", "--port", type=int, default=None, help="Server-Port (überschreibt config.json)")
    parser.add_argument("--host", type=str, default=None, help="Server-Host (überschreibt config.json)")
    parser.add_argument("--debug", action="store_true", default=None, help="Debug-Modus aktivieren")
    args = parser.parse_args()

    host = args.host or SERVER.get("host", "0.0.0.0")
    port = args.port or SERVER.get("port", 5000)
    debug = args.debug if args.debug is not None else SERVER.get("debug", False)

    print(f"🎬 YT Search Server starting on {host}:{port}")
    print(f"🤖 LLM: {LLM['model']} via {LLM['provider']}")
    app.run(host=host, port=port, debug=debug)
