# Bain Vector Briefcase

Enter a company name, get a partner-ready client-preparation brief built from recent news
coverage — what happened, why it matters, the risks and opportunities it opens, the talking points
worth using, and the questions worth asking. Every finding cites the sources behind it.

- **Frontend** — Next.js (App Router), React, TypeScript, Tailwind CSS, shadcn/ui
- **Backend** — FastAPI, Pydantic v2, `httpx`, Tavily news search, Gemini Flash via `google-genai`

All retrieval, filtering, ranking, analysis, API-key handling and business logic live in the Python
backend. The frontend is a presentation layer that calls one endpoint with `fetch`; there are no
Next.js Route Handlers.

```text
.
├── frontend/          # Next.js app
│   ├── app/           # layout, page, global styles
│   ├── components/    # feature components + shadcn/ui primitives
│   └── lib/           # API client, types, formatting, recent-search store
├── backend/
│   ├── app/
│   │   ├── main.py            # FastAPI app, CORS, /health
│   │   ├── config.py          # environment-driven settings
│   │   ├── schemas.py         # API + Gemini structured-output models
│   │   ├── routes/briefs.py   # POST /api/v1/brief
│   │   └── services/          # news_service, analysis_service, demo_data, errors
│   └── tests/                 # pytest, all external services mocked
└── README.md
```

## Requirements

- Node.js 20.9+
- Python 3.14+
- A Tavily API key from [tavily.com](https://www.tavily.com) — free "Researcher" tier, 1,000 searches/month, no card
- A Gemini API key from [Google AI Studio](https://aistudio.google.com/apikey) (free tier is enough)

No database, queue, cache or other paid infrastructure is required.

## Local setup

### 1. Backend

```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements-dev.txt
cp .env.example .env      # then add TAVILY_API_KEY and GEMINI_API_KEY
uvicorn app.main:app --reload --port 8000
```

The API is now on `http://localhost:8000` — check `http://localhost:8000/health`, and browse the
generated OpenAPI docs at `http://localhost:8000/docs`.

### 2. Frontend

```bash
cd frontend
npm install
cp .env.example .env.local
npm run dev
```

Open `http://localhost:3000`.

### Demo mode

To build UI without spending Gemini calls, set `DEMO_MODE=true` in `backend/.env` and restart the
API. `POST /api/v1/brief` then returns a bundled sample brief flagged with `is_demo: true`, which
the UI labels clearly. Demo data is **never** used as a fallback when a real request fails — a
failed request always surfaces as an error.

## Environment variables

### `backend/.env`

| Variable | Required | Default | Purpose |
| --- | --- | --- | --- |
| `TAVILY_API_KEY` | yes (unless `DEMO_MODE=true`) | — | Tavily search key. Server-side only; never sent to the browser. |
| `TAVILY_SEARCH_DEPTH` | no | `basic` | `basic` (1 credit/search) or `advanced` (2). |
| `GEMINI_API_KEY` | yes (unless `DEMO_MODE=true`) | — | Google AI Studio key. Server-side only; never sent to the browser. |
| `GEMINI_MODEL` | no | `gemini-3.6-flash` | Gemini model id. |
| `ALLOWED_ORIGINS` | no | `http://localhost:3000` | Comma-separated CORS origins. No wildcard is used. |
| `ALLOWED_ORIGIN_REGEX` | no | — | Optional anchored regex for origins that cannot be listed literally, e.g. Vercel previews. Empty means unused. |
| `DEMO_MODE` | no | `false` | Return the bundled sample brief instead of calling Tavily/Gemini. |

### `frontend/.env.local`

| Variable | Required | Default | Purpose |
| --- | --- | --- | --- |
| `NEXT_PUBLIC_API_URL` | no | `http://localhost:8000` | Base URL of the FastAPI backend, no trailing slash. |

## API

### `GET /health`

```json
{ "status": "ok", "demo_mode": false, "analysis_configured": true, "model": "gemini-3.6-flash" }
```

### `POST /api/v1/brief`

```json
{
  "company": "Microsoft",
  "time_range": "month",
  "focus_areas": ["technology", "strategy"]
}
```

- `company` — required, 2–120 characters.
- `time_range` — one of `week`, `month`, `year` (default `month`). Sent straight through to
  Tavily's own `time_range` parameter — no client-side date math involved.
- `focus_areas` — optional; any of `technology`, `operations`, `strategy`, `finance`, `people`,
  `regulatory`, `sustainability`.

Responses:

| Status | Meaning |
| --- | --- |
| `200` | A validated `CompanyBrief`. |
| `422` | Request validation failed, with per-field detail. |
| `404` | No usable recent coverage for that company in the window. |
| `503` | Tavily or Gemini was unavailable, a key is unset or rejected, or the monthly search quota is exhausted. |

Upstream failures return a short, user-facing `detail` string. Stack traces, upstream payloads and
API keys are never included in a response.

## How a brief is produced

1. **Retrieve** — one Tavily `topic="news"` search scoped to the lookback window via
   `start_date`/`end_date`. Only metadata is used: headline, excerpt, publisher domain, timestamp
   and URL. Full article bodies are never fetched or scraped.
2. **Filter** — malformed records are dropped, and because full-text search matches article
   *bodies*, headlines that never name the company are dropped too. That gate relaxes automatically
   if it would leave too little to work with.
3. **Deduplicate** — by URL, by normalised headline (publisher tails like `— Reuters` removed), and
   by token overlap for near-identical rewrites of the same story.
4. **Rank** — a deterministic score over recency, headline relevance to the company, source quality
   and focus-area match, with at most three headlines per publisher leading the list. No model call
   is involved in ranking. Up to 12 sources get stable `source-1…source-N` ids.
5. **Analyse** — a *single* Gemini request covering all selected sources, using structured output
   bound to a Pydantic schema. The prompt fences the article text as untrusted data, forbids
   invented events or figures, requires source citations, and requires hypotheses to be labelled.
6. **Verify** — any `source_ids` the model invents are stripped; an item left with no valid citation
   is dropped entirely, and confidence is downgraded when the surviving evidence is thin.

### Why Tavily

Retrieval originally used GDELT's keyless DOC 2.0 API. It works and has no monthly cap, but it
throttles per **IP** at one request every five seconds — so every tester on a network shares a
12-requests-per-minute budget, and a backend deployed to Vercel would share its IP with strangers.
No amount of client-side care creates capacity that does not exist.

Tavily's free tier binds the quota to the key instead:

| | GDELT keyless | Tavily free |
| --- | --- | --- |
| Monthly cap | none | 1,000 searches |
| Throughput | 12/min, per IP | 100/min, per key |
| Rate-limit signal | `HTTP 200` + English prose | `429` + `Retry-After` |
| Article excerpts | none | yes |

The excerpts matter most. Under GDELT, `Source.snippet` was always empty and the model reasoned
from bare headlines. Tavily returns a `content` excerpt per result, which flows through to the
prompt as evidence the model may cite.

### Known upstream behaviour

Transient failures — `429` rate limiting, `5xx`, timeouts — are retried once. A `Retry-After`
header, in either delta-seconds or HTTP-date form, overrides the configured delay and is clamped to
`tavily_max_retry_delay` (30s).

Three cases deliberately fail fast, because waiting cannot fix them: `401`/`403` (bad key), a `429`
whose body names a quota or credit problem (monthly allowance exhausted), and any other `4xx`.

Outbound calls are serialised behind a lock and spaced by `tavily_min_interval_seconds`, so
concurrent searches queue rather than bursting past the per-minute ceiling. Raw results are cached
for `tavily_cache_seconds` (10 min) keyed on company and window, so a repeat or shared search costs
no credit at all.

Gemini throttles and overloads too: an overloaded model returns `503 UNAVAILABLE` and a quota bite
returns `429`. Both clear on their own, so the analysis service retries once after 3s. A `400`,
`401`, `403` or `404` — bad key, bad model id, malformed request — fails immediately.

One brief costs exactly **one** Tavily credit and **one** Gemini request, plus at most one retry
each on transient failures. Every cache hit costs nothing.

## Testing and verification

```bash
cd backend && ./.venv/bin/python -m pytest -q && ./.venv/bin/ruff check app tests
```

Lint rules live in `backend/ruff.toml`, which is the project's linter of record — without it each
editor applies its own defaults and reports findings this project has not opted into. `ruff format`
is deliberately *not* part of the workflow; the existing layout is hand-tuned.

```bash
cd frontend && npx tsc --noEmit && npm run lint && npm run build
```

Backend tests mock Tavily (via `respx`) and Gemini (via a fake client); **no test makes a live call
to either service, so running the suite spends no credits.** Coverage includes request validation,
the Tavily request shape and result normalisation, deduplication, ranking determinism, the headline
relevance gate, every mapped upstream error (rejected key, quota exhausted, rate limited, timeout),
the rate gate and cache, Gemini failures and unparseable output, a successful `/api/v1/brief`
response, and invalid source references in model output. One test asserts the API key never appears
in an error response.

### CORS and Vercel preview deployments

Production has stable domains, so `ALLOWED_ORIGINS` handles it. Preview deployments do not:

| URL type | Example | Problem |
| --- | --- | --- |
| Per-deployment | `…-inqq-ch88ftyv6-…` | a new hash on every push |
| Branch alias | `…-inqq-git-b-7c4d7c-…` | truncated and hashed |

The branch alias looks like the stable answer but is not reliably constructable. A hostname such as
`bain-vector-briefcase-inqq-git-beta-2-preview-davidshmavid1s-projects` is 69 characters, and DNS
labels cap at 63 — so Vercel truncates the branch name and appends a hash. The two projects truncate
differently because their names differ in length.

`ALLOWED_ORIGIN_REGEX` covers that case. Set it on the **Preview** scope only:

```env
ALLOWED_ORIGIN_REGEX=^https://[a-z0-9-]+-yourteam-projects\.vercel\.app$
```

Anchor it and pin it to your own account suffix. `[a-z0-9-]+` excludes dots, so an extra subdomain
label cannot widen it, and Starlette matches with `fullmatch`, so a lookalike such as
`https://x-yourteam-projects.vercel.app.evil.com` is rejected. Leave it unset in production.

## Deployment (two Vercel projects)

Deploy the monorepo as two separate projects from the same repository.

**Backend project**

1. New Project → import the repo → set **Root Directory** to `backend`.
2. `backend/vercel.json` already routes all traffic to the ASGI app in `app/main.py`.
3. Environment variables:
   - `TAVILY_API_KEY` — your Tavily key
   - `GEMINI_API_KEY` — your Gemini key
   - `GEMINI_MODEL` — `gemini-3.6-flash`
   - `ALLOWED_ORIGINS` — the deployed frontend origin, e.g. `https://your-frontend.vercel.app`
   - `ALLOWED_ORIGIN_REGEX` — optional, Preview scope only (see above)
   - `DEMO_MODE` — `false`
4. Deploy, then confirm `https://<backend>.vercel.app/health`.

**Frontend project**

1. New Project → import the same repo → set **Root Directory** to `frontend`.
2. Environment variable:
   - `NEXT_PUBLIC_API_URL` — `https://<backend>.vercel.app`
3. Deploy.

After both are live, make sure `ALLOWED_ORIGINS` on the backend exactly matches the frontend origin
(scheme included, no trailing slash), then redeploy the backend. Add preview origins to the same
comma-separated list if you want preview deployments to work.

## Scope

Deliberately excluded: databases, authentication, user accounts, vector stores, Redis, background
workers, agent frameworks, saved reports, analytics, and full-article scraping. Only recent company
names are stored in `localStorage`; generated briefs are never persisted.

Briefs summarise public news metadata as a preparation aid. They are not diligence and not
investment advice.
