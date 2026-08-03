# Open items

Read alongside `CLAUDE.md`. Nothing here is started — these are decisions
pending the user's input, not work in progress.

## Awaiting decision: entity-disambiguation follow-up

Two live tests confirmed a user-supplied descriptor (e.g. "owner operators",
"Baby Food") fixes ambiguous company names where an automatic query trick
failed (see `CLAUDE.md`). A third test confirmed Tavily's relevance `score`
only usefully separates correct from incorrect results once the query is
already disambiguated — it's a cleanup step, not a fix on its own.

Presented as a three-way choice, not yet answered:

1. **Optional disambiguation-hint field** — a small input next to the search
   bar; if filled, appended to the query verbatim (`company + " " + hint`,
   no label prefix — the "Company:" label was tested and shown to make no
   difference). Touches `BriefRequest` (backend schema), `build_search_body`
   / cache key (`news_service.py` — the hint changes the actual query, so it
   must be part of the cache key), and the frontend form + types.
2. **Tavily score threshold** — capture `score` in `_normalize_result()`
   (currently dropped), add a `tavily_min_score` setting, drop results below
   it before dedupe/ranking ever sees them.
3. **Both together** — the combination the evidence actually supports: hint
   fixes the ambiguous case, threshold cleans up stragglers on an
   already-good query (e.g. Schneider Electric still appeared at position 3
   even with the "owner operators" descriptor).

Do not implement any of these without asking which one(s) — this was
deliberately left open, not forgotten.

## Housekeeping

Delete once convenient, no urgency: `beta-2`, `beta-2-preview` (local +
remote), `feat/low-confidence-refinement-tip` (local + remote — PR #6 already
merged).
