# Company Intelligence

Enter a company name, get a partner-ready client-preparation brief built from recent news
coverage — what happened, why it matters, the risks and opportunities it opens, the talking points
worth using, and the questions worth asking. Every finding cites the sources behind it.

- **Frontend** — Next.js (App Router), React, TypeScript, Tailwind CSS, shadcn/ui
- **Backend** — FastAPI, Pydantic v2, `httpx`, GDELT DOC 2.0, Gemini Flash via `google-genai`

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
- A Gemini API key from [Google AI Studio](https://aistudio.google.com/apikey) (free tier is enough)

No database, queue, cache or other paid infrastructure is required.

## Local setup

### 1. Backend

```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements-dev.txt
cp .env.example .env      # then add your GEMINI_API_KEY
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
| `GEMINI_API_KEY` | yes (unless `DEMO_MODE=true`) | — | Google AI Studio key. Server-side only; never sent to the browser. |
| `GEMINI_MODEL` | no | `gemini-3.6-flash` | Gemini model id. |
| `ALLOWED_ORIGINS` | no | `http://localhost:3000` | Comma-separated CORS origins. No wildcard is used. |
| `DEMO_MODE` | no | `false` | Return the bundled sample brief instead of calling GDELT/Gemini. |

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
  "lookback_days": 30,
  "focus_areas": ["technology", "strategy"]
}
```

- `company` — required, 2–120 characters.
- `lookback_days` — one of `7`, `30`, `90` (default `30`).
- `focus_areas` — optional; any of `technology`, `operations`, `strategy`, `finance`, `people`,
  `regulatory`, `sustainability`.

Responses:

| Status | Meaning |
| --- | --- |
| `200` | A validated `CompanyBrief`. |
| `422` | Request validation failed, with per-field detail. |
| `404` | No usable recent coverage for that company in the window. |
| `503` | GDELT or Gemini was unavailable, or `GEMINI_API_KEY` is unset. |

Upstream failures return a short, user-facing `detail` string. Stack traces, upstream payloads and
API keys are never included in a response.

## How a brief is produced

1. **Retrieve** — one GDELT DOC 2.0 `ArtList` query, scoped to the lookback window and English
   sources. Only metadata is used (headline, publisher domain, timestamp, URL); article bodies are
   never fetched or scraped.
2. **Filter** — malformed records are dropped, and because GDELT full-text-searches article
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

### Known upstream behaviour

GDELT asks for at most one request every five seconds and throttles in three different ways: an
`HTTP 429`, a plain-text notice under `HTTP 200`, or by refusing the connection outright. The news
service detects all three and retries twice with a backoff (6s, then 15s), and otherwise returns a
clear "rate-limiting" message rather than an empty result. Every other error status stays
fail-fast, since a bad query will not fix itself.

If a throttled response carries a `Retry-After` header — in either delta-seconds or HTTP-date form
— that value overrides the fixed schedule, because the server knows better than we do how long it
wants to be left alone. It is clamped to `gdelt_max_retry_delay` (30s) so an outsized value cannot
hold a brief request open. GDELT does not currently send the header on its 429s, but honouring it
is the correct default for any rate-limited upstream.

A busy window can outlast both retries. When that happens the request fails with the rate-limiting
message after roughly 50 seconds; waiting a minute and retrying is usually enough.

Gemini throttles and overloads too: an overloaded model returns `503 UNAVAILABLE` and a quota bite
returns `429`. Both clear on their own, so the analysis service retries once after 3s. A `400`,
`401`, `403` or `404` — bad key, bad model id, malformed request — fails immediately, because
waiting will not fix it.

One brief costs exactly **one** GDELT request and **one** Gemini request (plus at most one retry
each, only on transient failures). Rapid repeated searches — or several people behind one egress IP
— are what exhaust the per-IP allowance, not normal use.

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

Backend tests mock GDELT (via `respx`) and Gemini (via a fake client); no test makes a live call to
either service. Coverage includes request validation, deduplication, ranking determinism, the
headline relevance gate, empty and throttled GDELT results, Gemini failures and unparseable output,
a successful `/api/v1/brief` response, and invalid source references in model output.

## Deployment (two Vercel projects)

Deploy the monorepo as two separate projects from the same repository.

**Backend project**

1. New Project → import the repo → set **Root Directory** to `backend`.
2. `backend/vercel.json` already routes all traffic to the ASGI app in `app/main.py`.
3. Environment variables:
   - `GEMINI_API_KEY` — your key
   - `GEMINI_MODEL` — `gemini-3.6-flash`
   - `ALLOWED_ORIGINS` — the deployed frontend origin, e.g. `https://your-frontend.vercel.app`
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
