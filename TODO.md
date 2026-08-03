# Open items

Read alongside `CLAUDE.md`. Nothing here is started — these are decisions
pending the user's input, not work in progress.

## Awaiting decision: entity-disambiguation follow-up

Four live tests so far (see `CLAUDE.md`). Confirmed: a user-supplied
descriptor (e.g. "owner operators", "Baby Food") fixes ambiguous company
names where an automatic query trick failed. Also confirmed, correcting an
earlier, more pessimistic read of the same data: comparing a bad query's
score *ceiling* against a good query's score *floor* for the same target
shows a large, clean gap —

| Query | Score range | Entity match |
| --- | --- | --- |
| `"Gerber"` (bare) | `0.18–0.49` | 0/10 |
| `"Gerber baby food"` | `0.64–0.85` | 10/10 |
| `"schneider owner operators"` | correct `0.68–0.76`, wrong `0.56` | 2/3 |

— i.e. score is a better ambiguity *signal* than first thought, just not yet
validated beyond two companies.

**Not yet decided — user is gathering more score data before committing to a
number:** the actual `tavily_min_score` threshold value. 0.6 fits all data
collected so far with margin on both sides, but that's two companies' worth
of evidence. **Do not hardcode or ship a default threshold without asking —
this is explicitly still pending, not settled.**

**Decided, once a threshold exists:** what happens when too few sources clear
it — a new `AmbiguousResultsError` (mirrors `NewsConfigError` /
`NewsQuotaExceededError` in `errors.py`), distinct from `NoArticlesFoundError`
because coverage does exist here, it's just about the wrong entity. Skips the
Gemini call entirely (real cost savings — a low-score result set was always
going to produce a low-confidence brief nobody trusts). Copy should point
straight at the same refinement-descriptor guidance already shipped in
`confidence-badge.tsx`'s `refinementSuggestion()`, e.g.:

> "The results for 'Gerber' look like they're about a different company,
> person, or product with the same name. Try adding an industry or product
> descriptor — e.g. 'Gerber Baby Food' instead of just 'Gerber'."

Still open, independent of the threshold question: whether to *also* build
the optional disambiguation-hint input (small field next to the search bar;
if filled, appended to the query verbatim — the `"Company:"` label prefix was
tested and shown to make no measurable difference, so don't reintroduce it).
That would touch `BriefRequest`, `build_search_body` / the cache key in
`news_service.py` (the hint changes the actual query, so it must be part of
the cache key), and the frontend form + types.

Do not implement any of this without asking — deliberately left open, not
forgotten.

## Housekeeping

Delete once convenient, no urgency: `beta-2`, `beta-2-preview` (local +
remote), `feat/low-confidence-refinement-tip` (local + remote — PR #6 already
merged).
