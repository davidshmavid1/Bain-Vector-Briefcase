# Company Intelligence — persistent project memory

Read this at the start of every session in this repo. It exists so hard-won
context survives compaction and doesn't have to be re-derived. See `TODO.md`
for what's currently open.

## What this is

A consulting-prep tool: enter a company name, get a partner-ready brief built
from recent news. Monorepo, two Vercel projects deployed from one repo:

- `frontend/` — Next.js App Router, calls the backend with plain `fetch`. No
  Next.js Route Handlers; all business logic lives in Python.
- `backend/` — FastAPI. One real endpoint, `POST /api/v1/brief`. Retrieval
  (Tavily) → dedupe/rank (pure Python, provider-agnostic) → single Gemini call
  → citation-integrity sanitization → response.

Full API/architecture detail is in `README.md` — don't duplicate it here, this
file is for the *why*, not the *what*.

## Load-bearing decisions — don't relitigate these without new evidence

**Tavily, not GDELT, for retrieval.** GDELT's keyless endpoint throttles per
**IP** at 1 req/5s — fine for one local dev, unworkable for multiple testers
or a Vercel deployment sharing an IP with strangers. Tavily binds quota to the
key instead (1,000 free/month). Migration is `git log` around "replace GDELT
with Tavily" (PR #3) if the reasoning needs re-reading.

**Query augmentation for entity disambiguation does not work generically —
already tried, tested live, and reverted.** Appending a generic word like
`"company"` to a bare name (`"Gerber"` → `"Gerber company"`) does **not**
help Tavily disambiguate: live-tested, 0/20 results were the intended entity
(PR #5, closed unmerged). What **does** work, confirmed with two independent
live tests: a **specific, user-supplied descriptor** — `"Gerber Baby Food"`,
`"Schneider owner operators"`. A `"Company:"` label prefix was isolated and
tested separately — it changes nothing measurable; the descriptor is the
entire effect. Don't reach for an automatic backend query trick again without
new live evidence — the pattern says this needs to be user-supplied, not
inferred.

**Tavily's `score` field is relevance-to-query-text, not entity identity —
but it's a better ambiguity *signal* than first assessed.** Comparing a bad
query's score *within itself* shows no useful internal gap (true for
`"Gerber company"`: 0.05–0.33, all wrong, nothing to threshold on). But
comparing a bad query's ceiling against a good query's floor for the *same*
target company shows a large, clean gap: bare `"Gerber"` topped out at
`0.49` (still wrong — top result was even a different real company, Gerber
Gear); `"Gerber baby food"` bottomed out at `0.64` (10/10 correct). Same
pattern for Schneider: wrong-entity ceiling `0.56`, correct-entity floor
`0.68`. A threshold around `0.6` fits every data point gathered so far. Not
yet validated beyond two companies — see `TODO.md` before hardcoding a
default. Use this to *detect* an ambiguous query early (before spending a
Gemini call), not just to clean up results from an already-good one.

**`get_settings()` is `@lru_cache`d.** Editing `.env` on a running process
does nothing until the process is fully killed and restarted — no
file-watcher reloads it, and `--reload` only watches `.py` files.

**Vercel preview branch aliases are not constructable.** Once the full
hostname would exceed the 63-char DNS label limit, Vercel truncates the
branch name and appends an unpredictable hash. Don't try to guess or build
these URLs — read them from the dashboard, or better, use
`ALLOWED_ORIGIN_REGEX` (backend, Preview scope only) instead of chasing
literal preview origins for CORS.

**`NEXT_PUBLIC_*` vars are baked in at Next.js build time.** Changing one on
Vercel and not redeploying does nothing.

**Never let a real secret reach `.env.example`.** It's the tracked template,
not `.env`. This happened once — a Gemini key leaked into it, had to be
rotated and purged from git history, GitHub push-protection caught it on
push. `.env` values must also be unquoted with no `export` prefix — Vercel's
env UI stores values literally, it doesn't parse shell/dotenv syntax the way
`python-dotenv` does.

## Working with this user

- **Never commit, push, or open a PR without being explicitly asked** — not
  even after they pick an option via a design question. Choosing an approach
  is not authorization to touch git. This caused real friction once; don't
  repeat it. When in doubt, hand back the exact commands for them to run.
- **Never spend Tavily/Gemini credits on a live call without asking first.**
  The user runs most live Tavily sandbox tests themselves and pastes the raw
  JSON back for analysis — that's the established pattern, lean on it rather
  than testing unprompted.
- **Verify empirically before asserting something works**, especially for
  Tavily/Gemini query behavior. The query-augmentation fix (PR #5) was shipped
  on a plausible-sounding but untested theory, then live data flatly
  contradicted it. Test on real evidence before recommending, not after.
- **Format explanations as bullet points / tables**, not long prose
  paragraphs — explicit standing preference.

## Housekeeping — not urgent, don't act without being asked

Stale branches past their merged PRs, safe to delete whenever: `beta-2`,
`beta-2-preview` (local + remote), `feat/low-confidence-refinement-tip`
(local + remote, PR #6 merged but branch not cleaned up).
