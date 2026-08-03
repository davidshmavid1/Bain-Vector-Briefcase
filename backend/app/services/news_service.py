"""Tavily news retrieval, deduplication and deterministic ranking.

Only article *metadata* is used (headline, snippet, publisher domain, timestamp,
URL). Full article bodies are never fetched or scraped.

Retrieval is provider-specific; everything below `deduplicate()` operates on a
normalised article dict and is deliberately provider-agnostic.
"""

import asyncio
import logging
import re
import time
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Dict, List, Optional, Sequence, Tuple
from urllib.parse import urlparse

import httpx

from ..config import Settings, get_settings
from ..schemas import Source
from .errors import NewsConfigError, NewsQuotaExceededError, NewsUnavailableError

logger = logging.getLogger(__name__)

_TITLE_NOISE = re.compile(r"[^a-z0-9 ]+")
_PUBLISHER_TAIL = re.compile(r"\s+[-|–—»:]\s+[^-|–—»:]{2,40}$")

_STOPWORDS = frozenset(
    """a an and are as at be by for from has have in into is it its of on or that the to
    with will was were after over new says said amid up down its it's""".split()
)

# Used only to nudge ranking toward the partner's stated focus. Deterministic —
# no model call is involved in ranking.
_FOCUS_KEYWORDS: Dict[str, Sequence[str]] = {
    "technology": ("ai", "cloud", "software", "chip", "platform", "data", "digital", "product"),
    "operations": ("supply", "factory", "plant", "logistics", "manufacturing", "outage", "capacity"),
    "strategy": ("acquisition", "merger", "partnership", "expansion", "restructuring", "stake", "deal"),
    "finance": ("earnings", "revenue", "profit", "guidance", "debt", "dividend", "quarter", "loss"),
    "people": ("ceo", "chief", "hiring", "layoffs", "workforce", "union", "appoints", "resigns"),
    "regulatory": ("regulator", "antitrust", "lawsuit", "probe", "fine", "compliance", "court", "ruling"),
    "sustainability": ("emissions", "climate", "renewable", "sustainability", "esg", "carbon"),
}

_LOW_VALUE_DOMAINS = frozenset(
    {
        "prnewswire.com",
        "globenewswire.com",
        "businesswire.com",
        "einnews.com",
        "openpr.com",
        "finanzen.net",
        "marketscreener.com",
    }
)


# Some feeds pad punctuation with spaces ("Siemens , Nvidia advance self -
# verifying workflows"). Repairing that is not only cosmetic: an unrepaired
# "self - verifying" looks exactly like a " - Publisher" tail, so the tail regex
# would swallow the rest of the headline and starve dedup and the relevance gate.
_SPACE_BEFORE_PUNCT = re.compile(r"\s+([,.;:!?%)\]])")
_SPACE_AFTER_OPEN = re.compile(r"([(\[])\s+")
_SPACED_APOSTROPHE = re.compile(r"\s+(['’])\s*(?=[a-z])")
# Only rejoin a spaced hyphen between two lowercase words: "self - verifying" is
# one word, while "Desigo CC - ISSSource" really is a publisher tail.
_INTRAWORD_HYPHEN = re.compile(r"(?<=[a-z])\s+-\s+(?=[a-z])")


def tidy_title(title: str) -> str:
    """Repair spaced-out punctuation, preserving the original wording."""
    cleaned = " ".join((title or "").split())
    cleaned = _INTRAWORD_HYPHEN.sub("-", cleaned)
    cleaned = _SPACED_APOSTROPHE.sub(r"\1", cleaned)
    cleaned = _SPACE_BEFORE_PUNCT.sub(r"\1", cleaned)
    return _SPACE_AFTER_OPEN.sub(r"\1", cleaned)


def normalize_title(title: str) -> str:
    """Lowercase, drop a trailing ' - Publisher' tail, and strip punctuation."""
    cleaned = tidy_title(title)
    cleaned = _PUBLISHER_TAIL.sub("", cleaned)
    cleaned = _TITLE_NOISE.sub(" ", cleaned.lower())
    return " ".join(cleaned.split())


def _significant_tokens(normalized_title: str) -> frozenset:
    return frozenset(t for t in normalized_title.split() if t not in _STOPWORDS and len(t) > 2)


def _parse_seendate(value: str) -> Optional[datetime]:
    """Parse Tavily's `published_date`. It is not a fixed format in practice —
    ISO-8601 with or without a timezone, and sometimes an RFC 2822 date — so try
    the plausible shapes rather than assuming one."""
    raw = (value or "").strip()
    if not raw:
        return None

    iso = raw.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(iso)
    except ValueError:
        try:
            parsed = parsedate_to_datetime(raw)
        except (TypeError, ValueError):
            return None
    if parsed is None:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _is_well_formed(article: dict) -> bool:
    title = (article.get("title") or "").strip()
    url = (article.get("url") or "").strip()
    domain = (article.get("domain") or "").strip()
    if len(title) < 15 or len(_significant_tokens(normalize_title(title))) < 3:
        return False
    if not url.startswith(("http://", "https://")) or not domain:
        return False
    return _parse_seendate(article.get("seendate", "")) is not None


# Trailing host labels that are suffixes rather than the outlet's name, so
# "finance.yahoo.com" -> Yahoo and "world.kbs.co.kr" -> Kbs.
_HOST_SUFFIXES = frozenset(
    """com org net co uk jp kr au in de fr io us ca br za gov edu info biz tv me cn ru es it nl
    se no ch ie nz sg hk ae sa mx ar cl pl pt tr il dk fi be at gr th id my ph vn tw ng ke""".split()
)

_PUBLISHER_NAMES = {
    "reuters.com": "Reuters",
    "apnews.com": "AP News",
    "bloomberg.com": "Bloomberg",
    "ft.com": "Financial Times",
    "wsj.com": "The Wall Street Journal",
    "nytimes.com": "The New York Times",
    "cnbc.com": "CNBC",
    "bbc.com": "BBC",
    "bbc.co.uk": "BBC",
    "theguardian.com": "The Guardian",
    "forbes.com": "Forbes",
    "techcrunch.com": "TechCrunch",
    "theverge.com": "The Verge",
    "arstechnica.com": "Ars Technica",
    "axios.com": "Axios",
    "politico.com": "Politico",
    "economist.com": "The Economist",
    "finance.yahoo.com": "Yahoo Finance",
    "seekingalpha.com": "Seeking Alpha",
    "zdnet.com": "ZDNET",
    "wired.com": "WIRED",
}


def _publisher_name(domain: str) -> str:
    host = domain.lower().removeprefix("www.")
    if host in _PUBLISHER_NAMES:
        return _PUBLISHER_NAMES[host]
    labels = [label for label in host.split(".") if label]
    while len(labels) > 1 and labels[-1] in _HOST_SUFFIXES:
        labels.pop()
    return labels[-1].replace("-", " ").title() if labels else host


def _company_tokens(company: str) -> frozenset:
    """Significant tokens of the company name, with a short-name fallback."""
    tokens = _significant_tokens(normalize_title(company))
    return tokens or frozenset(normalize_title(company).split()) or frozenset({company.lower()})


def _mentions_company(article: dict, company: str) -> bool:
    """Full-text search matches article bodies, so plenty of hits never name the
    company in the headline. Require the headline itself to carry it."""
    normalized = normalize_title(article.get("title") or "")
    phrase = normalize_title(company)
    if phrase and phrase in normalized:
        return True
    tokens = _company_tokens(company)
    matched = sum(1 for token in tokens if token in normalized.split())
    return matched * 2 >= len(tokens)


def _retry_after_seconds(response: httpx.Response, ceiling: float) -> Optional[float]:
    """Read RFC 9110 `Retry-After`, in either delta-seconds or HTTP-date form.

    The server knows better than our fixed schedule how long it wants to be left
    alone, so an explicit header always wins. It is still clamped: an absurd or
    hostile value must not hold a request open indefinitely.

    Tavily sends this header on its 429s, so it is the primary signal rather
    than a defensive nicety.
    """
    raw = (response.headers.get("Retry-After") or "").strip()
    if not raw:
        return None

    try:
        seconds = float(raw)
    except ValueError:
        try:
            when = parsedate_to_datetime(raw)
        except (TypeError, ValueError):
            logger.debug("Ignoring unparseable Retry-After header")
            return None
        if when is None:
            return None
        if when.tzinfo is None:
            when = when.replace(tzinfo=timezone.utc)
        seconds = (when - datetime.now(timezone.utc)).total_seconds()

    if seconds != seconds or seconds in (float("inf"), float("-inf")):  # NaN / inf
        return None
    return max(0.0, min(seconds, ceiling))


# Tavily rate-limits and overloads with statuses that clear on their own. A
# 401/403 is a bad key and will never clear, so it fails fast.
_RETRYABLE_STATUS = frozenset({429, 500, 502, 503, 504})
_AUTH_STATUS = frozenset({401, 403})


# Our own recency scoring (score_article/rank_articles below) needs a plain
# day-count, but Tavily's time_range is a string — this mapping exists only to
# feed that formula and is never sent to Tavily itself.
TIME_RANGE_DAYS = {"week": 7, "month": 30, "year": 365}


def build_search_body(company: str, time_range: str, settings: Settings) -> dict:
    """Tavily request body. `topic="news"` is what makes `published_date` appear.

    `time_range` is Tavily's own parameter — sent through as-is rather than
    translated into computed start/end dates.
    """
    return {
        "query": company,
        "topic": "news",
        "search_depth": settings.tavily_search_depth,
        "max_results": settings.tavily_max_results,
        "time_range": time_range,
    }


async def _post_search(
    client: httpx.AsyncClient,
    settings: Settings,
    body: dict,
    timeout: httpx.Timeout,
) -> dict:
    response = await client.post(
        settings.tavily_base_url,
        json=body,
        headers={"Authorization": f"Bearer {settings.tavily_api_key}"},
        timeout=timeout,
    )
    response.raise_for_status()
    return response.json()


# Tavily allows 100 requests/minute on the free tier. Retrying a 429 only reacts
# to a violation already committed; this gate prevents it. Every outbound call —
# first attempts and retries alike — passes through here, so concurrent searches
# queue instead of racing each other past the ceiling.
_rate_gate: Optional[asyncio.Lock] = None
_rate_gate_loop = None
# None means "no call yet". Not 0.0: time.monotonic()'s zero point is arbitrary
# and on some platforms sits near process start, which would make the very first
# request on a fresh server wait out a full interval for nothing.
_last_call_at: Optional[float] = None


def _gate() -> asyncio.Lock:
    """Return a lock bound to the *running* loop.

    A module-level `asyncio.Lock()` binds to whichever loop exists at import
    time, which is not the loop uvicorn later runs on — using it raises "got
    Future attached to a different loop". Creating it lazily, and recreating it
    if the loop changes, keeps it correct in both the server and the tests.
    """
    global _rate_gate, _rate_gate_loop
    loop = asyncio.get_event_loop()
    if _rate_gate is None or _rate_gate_loop is not loop:
        _rate_gate = asyncio.Lock()
        _rate_gate_loop = loop
    return _rate_gate


def reset_rate_gate() -> None:
    """Forget the last call and drop the lock. For tests, so cases neither wait
    on each other's timestamps nor inherit a lock from a closed loop."""
    global _last_call_at, _rate_gate, _rate_gate_loop
    _last_call_at = None
    _rate_gate = None
    _rate_gate_loop = None


async def _spaced_post(
    client: httpx.AsyncClient,
    settings: Settings,
    body: dict,
    timeout: httpx.Timeout,
) -> dict:
    global _last_call_at
    async with _gate():
        if _last_call_at is not None:
            wait = settings.tavily_min_interval_seconds - (time.monotonic() - _last_call_at)
            if wait > 0:
                logger.debug("Holding Tavily request %.2fs to respect the rate limit", wait)
                await asyncio.sleep(wait)
        try:
            return await _post_search(client, settings, body, timeout)
        finally:
            # Record even on failure: a rejected request still spent the slot.
            _last_call_at = time.monotonic()


def _is_quota_exhausted(response: httpx.Response) -> bool:
    """A 429 means either "too fast" (retry) or "out of credits" (do not)."""
    try:
        payload = response.json()
    except ValueError:
        payload = {}
    haystack = " ".join(
        str(payload.get(field, "")) for field in ("code", "error", "detail", "message")
    ).lower()
    return "quota" in haystack or "credit" in haystack


async def _search_with_backoff(
    client: httpx.AsyncClient,
    settings: Settings,
    body: dict,
    timeout: httpx.Timeout,
) -> dict:
    """One retry for transient failures, honouring `Retry-After` when sent."""
    delays = [*settings.tavily_retry_delays, None]
    for delay in delays:
        try:
            return await _spaced_post(client, settings, body, timeout)
        except httpx.HTTPStatusError as exc:
            status = exc.response.status_code
            logger.warning("Tavily returned HTTP %s", status)
            if status in _AUTH_STATUS:
                raise NewsConfigError(
                    "The news service rejected the API key. Check TAVILY_API_KEY on the server."
                ) from exc
            if status == 429 and _is_quota_exhausted(exc.response):
                raise NewsQuotaExceededError() from exc
            if status not in _RETRYABLE_STATUS or delay is None:
                raise NewsUnavailableError() from exc
            # An explicit Retry-After overrides our own schedule.
            requested = _retry_after_seconds(exc.response, settings.tavily_max_retry_delay)
            if requested is not None:
                delay = requested
            reason = f"HTTP {status}"
        except httpx.HTTPError as exc:
            logger.warning("Tavily request failed: %s", type(exc).__name__)
            if delay is None:
                raise NewsUnavailableError() from exc
            reason = type(exc).__name__

        logger.info("Tavily returned %s; retrying in %ss", reason, delay)
        await asyncio.sleep(delay)

    raise NewsUnavailableError()  # unreachable: the loop always returns or raises


def _normalize_result(result: dict) -> Optional[dict]:
    """Map a Tavily result onto the internal article shape the pipeline uses.

    Tavily sends no domain, so it is derived from the URL. `content` becomes the
    snippet — the field GDELT never had, and the reason briefs can now cite more
    than a headline.
    """
    url = (result.get("url") or "").strip()
    title = (result.get("title") or "").strip()
    if not url or not title:
        return None

    host = urlparse(url).netloc.lower()
    if not host:
        return None

    snippet = " ".join((result.get("content") or "").split()) or None
    return {
        "url": url,
        "title": title,
        "seendate": (result.get("published_date") or "").strip(),
        "domain": host,
        "snippet": snippet,
    }


# Raw results, keyed by the two inputs that shape the query. Focus areas only
# affect ranking, so they are deliberately not part of the key. News moves
# slowly enough that a short reuse window costs nothing in freshness and saves
# a whole credit on a repeated or shared search.
_articles_cache: Dict[Tuple[str, str], Tuple[float, List[dict]]] = {}


def clear_cache() -> None:
    """Drop cached results. For tests, and for a manual cache bust."""
    _articles_cache.clear()


def _cache_key(company: str, time_range: str) -> Tuple[str, str]:
    return (" ".join(company.lower().split()), time_range)


async def fetch_articles(
    company: str,
    time_range: str,
    settings: Optional[Settings] = None,
    client: Optional[httpx.AsyncClient] = None,
) -> List[dict]:
    """Fetch recent news metadata from Tavily, normalised for the pipeline."""
    settings = settings or get_settings()
    if not settings.tavily_api_key:
        raise NewsConfigError()

    key = _cache_key(company, time_range)
    cached = _articles_cache.get(key)
    if cached is not None and time.monotonic() < cached[0]:
        logger.info("Serving %s (%s) from cache; no credit spent", company, time_range)
        return list(cached[1])

    body = build_search_body(company, time_range, settings)
    timeout = httpx.Timeout(settings.tavily_read_timeout, connect=settings.tavily_connect_timeout)

    owns_client = client is None
    client = client or httpx.AsyncClient(timeout=timeout)
    try:
        payload = await _search_with_backoff(client, settings, body, timeout)
    finally:
        if owns_client:
            await client.aclose()

    raw = payload.get("results") if isinstance(payload, dict) else None
    if not isinstance(raw, list):
        logger.warning("Tavily response had no results list")
        raise NewsUnavailableError()

    result = [
        article
        for article in (_normalize_result(r) for r in raw if isinstance(r, dict))
        if article is not None
    ]

    _articles_cache[key] = (time.monotonic() + settings.tavily_cache_seconds, list(result))
    return result


def deduplicate(articles: Sequence[dict]) -> List[dict]:
    """Drop exact URL repeats, identical headlines and near-duplicate coverage."""
    kept: List[dict] = []
    seen_urls: set = set()
    seen_titles: set = set()
    kept_tokens: List[frozenset] = []

    for article in articles:
        url = (article.get("url") or "").strip()
        url_key = url.split("?", 1)[0].rstrip("/").lower()
        if url_key in seen_urls:
            continue
        normalized = normalize_title(article.get("title") or "")
        if normalized in seen_titles:
            continue
        tokens = _significant_tokens(normalized)
        if any(_jaccard(tokens, other) >= 0.8 for other in kept_tokens):
            continue

        seen_urls.add(url_key)
        seen_titles.add(normalized)
        kept_tokens.append(tokens)
        kept.append(article)

    return kept


def _jaccard(left: frozenset, right: frozenset) -> float:
    if not left or not right:
        return 0.0
    union = len(left | right)
    return len(left & right) / union if union else 0.0


def score_article(
    article: dict,
    company: str,
    lookback_days: int,
    focus_areas: Optional[Sequence[str]] = None,
    now: Optional[datetime] = None,
) -> float:
    """Deterministic 0-1 relevance score: recency + headline relevance + quality."""
    now = now or datetime.now(timezone.utc)
    normalized = normalize_title(article.get("title") or "")
    tokens = _significant_tokens(normalized)

    seen = _parse_seendate(article.get("seendate", ""))
    age_days = max((now - seen).total_seconds() / 86400, 0.0) if seen else float(lookback_days)
    recency = max(0.0, 1.0 - (age_days / max(lookback_days, 1)))

    company_tokens = _company_tokens(company)
    matched = sum(1 for token in company_tokens if token in normalized)
    relevance = matched / len(company_tokens)
    if normalize_title(company) and normalize_title(company) in normalized:
        relevance = min(1.0, relevance + 0.15)

    focus_hit = 0.0
    for area in focus_areas or []:
        keywords = _FOCUS_KEYWORDS.get(area, ())
        if any(keyword in tokens or keyword in normalized for keyword in keywords):
            focus_hit = 1.0
            break

    domain = (article.get("domain") or "").lower().removeprefix("www.")
    quality = 1.0
    if domain in _LOW_VALUE_DOMAINS:
        quality -= 0.6
    if len(normalized) < 25:
        quality -= 0.3
    quality = max(0.0, quality)

    return round(0.40 * recency + 0.35 * relevance + 0.15 * quality + 0.10 * focus_hit, 6)


def rank_articles(
    articles: Sequence[dict],
    company: str,
    lookback_days: int,
    focus_areas: Optional[Sequence[str]] = None,
    now: Optional[datetime] = None,
) -> List[dict]:
    """Sort by score, then recency, then URL so results are fully reproducible."""
    now = now or datetime.now(timezone.utc)
    scored = [
        (score_article(a, company, lookback_days, focus_areas, now), a)
        for a in articles
        if _is_well_formed(a)
    ]
    epoch = datetime(1970, 1, 1, tzinfo=timezone.utc)
    scored.sort(
        key=lambda pair: (
            -pair[0],
            -(_parse_seendate(pair[1].get("seendate", "")) or epoch).timestamp(),
            (pair[1].get("url") or ""),
        )
    )
    return [article for _, article in scored]


def _limit_per_publisher(articles: Sequence[dict], limit: int = 3) -> List[dict]:
    """Keep the ranking varied: at most `limit` headlines from one domain."""
    counts: Dict[str, int] = {}
    kept: List[dict] = []
    overflow: List[dict] = []
    for article in articles:
        domain = (article.get("domain") or "").lower()
        counts[domain] = counts.get(domain, 0) + 1
        (kept if counts[domain] <= limit else overflow).append(article)
    return kept + overflow


def to_sources(articles: Sequence[dict]) -> List[Source]:
    """Assign stable `source-N` ids in final ranked order."""
    sources: List[Source] = []
    for index, article in enumerate(articles, start=1):
        sources.append(
            Source(
                id=f"source-{index}",
                title=tidy_title(article.get("title") or ""),
                url=article["url"],
                publisher=_publisher_name(article.get("domain") or ""),
                published_at=_parse_seendate(article.get("seendate", "")),
                snippet=article.get("snippet"),
            )
        )
    return sources


async def collect_sources(
    company: str,
    time_range: str,
    focus_areas: Optional[Sequence[str]] = None,
    settings: Optional[Settings] = None,
    client: Optional[httpx.AsyncClient] = None,
) -> List[Source]:
    """Full retrieval pipeline: fetch -> filter -> dedupe -> rank -> ids."""
    settings = settings or get_settings()
    raw = await fetch_articles(company, time_range, settings=settings, client=client)

    well_formed = [a for a in raw if _is_well_formed(a)]
    on_topic = [a for a in well_formed if _mentions_company(a, company)]
    # Relax the headline gate only if it would leave too little to work with.
    candidates = on_topic if len(on_topic) >= settings.min_sources else well_formed

    unique = deduplicate(candidates)
    # score_article/rank_articles score recency against a day-count, not a
    # time_range string — TIME_RANGE_DAYS is the (internal-only) bridge.
    ranked = rank_articles(unique, company, TIME_RANGE_DAYS[time_range], focus_areas)
    varied = _limit_per_publisher(ranked)
    return to_sources(varied[: settings.max_sources])
