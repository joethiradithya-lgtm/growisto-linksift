# Growisto LinkSift — Agentic Web App

Score and filter a backlink list for outreach prioritization, with **automatic site-activity detection** so dead sites get penalized before they waste anyone's time.

A browser tool: upload a CSV/Excel export from Ahrefs/Semrush/Moz, get back a ranked, filterable shortlist with Strong / Good / Weak / Reject tiers — plus a live activity indicator for every domain.

> **Note:** This replaces the earlier Claude Code plugin version of LinkSift. The plugin was a CLI that produced an Excel file; this version is a web app with a live agent loop. Read [`MIGRATION.md`](MIGRATION.md) if you were using the old plugin.

---

## What it does

For each backlink in your upload:

1. **Site activity check** — inspects `sitemap.xml` → RSS/Atom feed → blog page (fallback scrape). If the site hasn't published anything in the last N months (default 6), it's flagged as `INACTIVE`.
2. **Agentic relevance scoring** — a Claude agent reasons over each batch and decides relevance to your industry + geography. Can deep-dive into ambiguous domains by fetching their homepage.
3. **Composite ranking** — combines DR + Traffic + Spam Score + AI relevance + activity into a single sortable score.
4. **Live results** — see verdicts stream into the UI as the agent works.

---

## Quickstart

### Prereqs
- **Python 3.10+** — <https://www.python.org/downloads/>
- **Node.js LTS** — <https://nodejs.org/> (the Claude Agent SDK bundles a CLI that needs Node)
- **Anthropic API key** — <https://console.anthropic.com/settings/keys>

### Run

**Windows:** double-click `start.bat`

**Mac/Linux:** `bash start.sh`

The script installs everything, asks for your API key on first run, and opens your browser to <http://localhost:8000>.

Full step-by-step guide for non-developers: see [`SETUP.md`](SETUP.md).

---

## Architecture

```
┌─────────────────┐      SSE       ┌────────────────────┐
│  frontend/      │ ────────────▶  │  backend/server.py │  FastAPI
│  index.html     │  ◀──────────   │                    │
└─────────────────┘                └──────────┬─────────┘
                                              │
                                   ┌──────────▼─────────┐
                                   │  agent.py          │  orchestrator
                                   │  • parallel        │
                                   │    site_activity   │  ← sitemap/RSS/scrape
                                   │  • Claude Agent    │
                                   │    SDK loop        │
                                   └──────────┬─────────┘
                                              │  MCP tools
                                   ┌──────────▼─────────┐
                                   │  agent_tools.py    │
                                   │  • check_activity  │
                                   │  • fetch_homepage  │
                                   │  • finalize_verdict│
                                   └────────────────────┘
```

The agent only has access to three sandboxed tools (`allowed_tools` is locked). No filesystem, no Bash, no arbitrary web fetching.

---

## File layout

```
growisto-linksift/
├── start.sh / start.bat       # one-click startup scripts
├── README.md                  # this file
├── SETUP.md                   # beginner setup guide
├── MIGRATION.md               # for users of the old plugin
├── .gitignore
├── backend/
│   ├── requirements.txt
│   ├── server.py              # FastAPI + SSE
│   ├── agent.py               # Claude Agent SDK orchestrator
│   ├── agent_tools.py         # custom MCP tools
│   └── site_activity.py       # sitemap/RSS/scrape (no LLM)
└── frontend/
    └── index.html             # web UI
```

---

## How site activity is determined

For each domain, in this order:

1. **`sitemap.xml`** — walks the sitemap (one level into nested indexes, prioritizing blog/news/post sitemaps), reads `<lastmod>` dates from URLs containing blog/news/articles/etc.
2. **RSS / Atom feed** — tries common paths (`/feed`, `/rss`, `/atom.xml`, `/blog/feed`, …) and parses `pubDate` / `updated`.
3. **Fallback scrape** — fetches `/blog`, `/news`, `/articles`, etc. and extracts dates from `<time datetime="…">`, `<meta property="article:published_time">`, and date-class elements.

A domain is `ACTIVE` if at least one post falls inside the configured window (default 6 months, adjustable in the UI). All checks run in parallel before the LLM agent runs, so activity data is free.

---

## How the agent scores relevance

Each batch (~15 domains) is sent to Claude Sonnet 4.5 with:
- The target site's industry + geography
- The CSV-derived metadata for each domain
- The pre-computed activity result for each domain

The agent has three tools:

| Tool                          | When the agent uses it                                          |
| ----------------------------- | --------------------------------------------------------------- |
| `check_site_activity`         | Re-verify activity if something looks off (rarely needed)       |
| `fetch_homepage_summary`      | Pull homepage title/description if CSV metadata is too sparse   |
| `finalize_backlink_decision`  | **Required exactly once per domain** — records the verdict      |

Scoring bands:

| Band   | Score   | Meaning                              |
| ------ | ------- | ------------------------------------ |
| Strong | 80–100  | Outreach immediately                 |
| Good   | 60–79   | Worth outreach with personalization  |
| Weak   | 40–59   | Only if other tiers exhausted        |
| Reject | 0–39    | Don't outreach                       |

Inactive sites get an automatic ≥20 point penalty and are capped at "Weak".

---

## Tuning

Edit these in code:

| Setting                | File                  | Default        |
| ---------------------- | --------------------- | -------------- |
| Activity window        | UI control            | 6 months       |
| Batch size             | `frontend/index.html` (`batch_size` in payload) | 15 |
| Model                  | `agent.py` (`MODEL` constant) | `claude-sonnet-4-5` |
| Activity concurrency   | `agent.py` (`_gather_activity(... concurrency=8)`) | 8 |
| Activity window cap    | `server.py` (`window_months: Field(6, ge=1, le=24)`) | 1–24 |

---

## CSV / Excel input

Upload an export from Ahrefs, Semrush, Moz, or any tool with these columns (headers required, names are auto-detected via aliases):

**Required:** `domain` (or `url`, `referring domain`, `source`, …) + `dr` (or `domain rating`, `domain authority`, …) + `traffic` (or `organic traffic`, `monthly visits`, …)

**Optional:** `spam_score`, `category` / `niche`, `description`, `country`, `language`

The parser handles CSV, TSV, and `.xlsx` / `.xls`.

---

## Cost notes

Activity checks are **free** (no LLM tokens). The agent step uses Sonnet 4.5; expect roughly $0.01–$0.05 per 100 backlinks depending on how many domains trigger deep-dive `fetch_homepage_summary` calls. The "agent done" event in the UI shows the exact cost per batch.

---

## License

Internal Growisto tooling.
