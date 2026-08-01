"""GDELT news retrieval, deduplication and deterministic ranking.

Only GDELT article *metadata* is used (headline, publisher domain, timestamp,
URL). Article bodies are never fetched or scraped.
"""

import asyncio
import json
import logging
import re
import time
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from typing import Dict, List, Optional, Sequence, Tuple

import httpx

from ..config import Settings, get_settings
from ..schemas import Source
from .errors import NewsUnavailableError

logger = logging.getLogger(__name__)

# GDELT's DOC 2.0 "ArtList" mode returns these fields per article:
# url, url_mobile, title, seendate, socialimage, domain, language, sourcecountry.
# There is no abstract/snippet field, so Source.snippet stays empty here.
_GDELT_TIMESTAMP = "%Y%m%dT%H%M%SZ"
_GDELT_WINDOW = "%Y%m%d%H%M%S"

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


def build_query(company: str) -> str:
    """GDELT query string: exact company phrase, English sources only."""
    phrase = company.replace('"', " ").strip()
    return f'"{phrase}" sourcelang:english'


# GDELT pads punctuation with spaces ("Siemens , Nvidia advance self - verifying
# workflows"). Repairing that is not only cosmetic: an unrepaired "self - verifying"
# looks exactly like a " - Publisher" tail, so the tail regex used to swallow the
# rest of the headline and starve deduplication and the relevance gate.
_SPACE_BEFORE_PUNCT = re.compile(r"\s+([,.;:!?%)\]])")
_SPACE_AFTER_OPEN = re.compile(r"([(\[])\s+")
_SPACED_APOSTROPHE = re.compile(r"\s+(['’])\s*(?=[a-z])")
# Only rejoin a spaced hyphen between two lowercase words: "self - verifying" is
# one word, while "Desigo CC - ISSSource" really is a publisher tail.
_INTRAWORD_HYPHEN = re.compile(r"(?<=[a-z])\s+-\s+(?=[a-z])")


def tidy_title(title: str) -> str:
    """Repair GDELT's spaced-out punctuation, preserving the original wording."""
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
    try:
        return datetime.strptime(value, _GDELT_TIMESTAMP).replace(tzinfo=timezone.utc)
    except (TypeError, ValueError):
        return None


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
    """GDELT searches article bodies, so plenty of hits never name the company
    in the headline. Require the headline itself to carry the company."""
    normalized = normalize_title(article.get("title") or "")
    phrase = normalize_title(company)
    if phrase and phrase in normalized:
        return True
    tokens = _company_tokens(company)
    matched = sum(1 for token in tokens if token in normalized.split())
    return matched * 2 >= len(tokens)


def _is_rate_limited(body: str) -> bool:
    """GDELT throttles with a plain-text notice under HTTP 200."""
    return "limit requests" in body[:400].lower()


# GDELT also throttles with a real HTTP 429, which clears on its own and so is
# worth a retry. Every other error status stays fail-fast: a 4xx means the
# request itself is wrong, and a 5xx is not ours to wait out.
_RETRYABLE_STATUS = frozenset({429})

_RATE_LIMIT_MESSAGE = (
    "The news service is rate-limiting requests right now. "
    "Please wait a few seconds and try again."
)


def _retry_after_seconds(response: httpx.Response, ceiling: float) -> Optional[float]:
    """Read RFC 9110 `Retry-After`, in either delta-seconds or HTTP-date form.

    The server knows better than our fixed schedule how long it wants to be left
    alone, so an explicit header always wins. It is still clamped: an absurd or
    hostile value must not hold a request open indefinitely.

    GDELT does not currently send this header on its 429s, but honouring it is
    the correct default for any rate-limited upstream.
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


async def _get_body(
    client: httpx.AsyncClient,
    settings: Settings,
    params: dict,
    timeout: httpx.Timeout,
) -> str:
    response = await client.get(settings.gdelt_base_url, params=params, timeout=timeout)
    response.raise_for_status()
    return response.text.strip()


# GDELT allows one request every five seconds per IP. Retrying a 429 only
# reacts to a violation we already committed; this gate prevents it. Every
# outbound GDELT call — first attempts and retries alike — passes through here,
# so concurrent searches queue instead of racing each other into a 429.
_rate_gate: Optional[asyncio.Lock] = None
_rate_gate_loop = None
# None means "no call yet". Not 0.0: time.monotonic()'s zero point is arbitrary
# and on some platforms sits near process start, which would make the very first
# request on a fresh server wait out a full interval for nothing.
_last_call_at: Optional[float] = None


def _gate() -> asyncio.Lock:
    """Return a lock bound to the *running* loop.

    A module-level `asyncio.Lock()` binds to whichever loop exists at import
    time, which on Python 3.9 is not the loop uvicorn later runs on — using it
    raises "got Future attached to a different loop". Creating it lazily, and
    recreating it if the loop changes, keeps it correct in both the server and
    the test suite.
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


async def _spaced_get(
    client: httpx.AsyncClient,
    settings: Settings,
    params: dict,
    timeout: httpx.Timeout,
) -> str:
    global _last_call_at
    async with _gate():
        if _last_call_at is not None:
            wait = settings.gdelt_min_interval_seconds - (time.monotonic() - _last_call_at)
            if wait > 0:
                logger.debug("Holding GDELT request %.1fs to respect the rate limit", wait)
                await asyncio.sleep(wait)
        try:
            return await _get_body(client, settings, params, timeout)
        finally:
            # Record even on failure: a rejected request still spent the slot.
            _last_call_at = time.monotonic()


async def _fetch_body_with_backoff(
    client: httpx.AsyncClient,
    settings: Settings,
    params: dict,
    timeout: httpx.Timeout,
) -> str:
    """GDELT throttles at the connection, status and response level, so retry
    transport failures, 429/5xx statuses and plain-text throttle notices a
    bounded number of times."""
    delays = [*settings.gdelt_retry_delays, None]
    throttled = False
    for delay in delays:
        try:
            body = await _spaced_get(client, settings, params, timeout)
            if not _is_rate_limited(body):
                return body
            throttled = True
            reason = "throttle notice"
        except httpx.HTTPStatusError as exc:
            status = exc.response.status_code
            logger.warning("GDELT returned HTTP %s", status)
            if status not in _RETRYABLE_STATUS:
                raise NewsUnavailableError() from exc
            throttled = True
            if delay is None:
                raise NewsUnavailableError(_RATE_LIMIT_MESSAGE) from exc
            # An explicit Retry-After overrides our own schedule.
            requested = _retry_after_seconds(exc.response, settings.gdelt_max_retry_delay)
            if requested is not None:
                delay = requested
            reason = f"HTTP {status}"
        except httpx.HTTPError as exc:
            logger.warning("GDELT request failed: %s", type(exc).__name__)
            if delay is None:
                # Once GDELT is throttling in earnest it stops answering the
                # connection at all, so an earlier 429 explains this failure
                # far better than a generic outage would.
                raise NewsUnavailableError(
                    _RATE_LIMIT_MESSAGE if throttled else ""
                ) from exc
            reason = type(exc).__name__

        if delay is None:
            return body
        logger.info("GDELT returned %s; retrying in %ss", reason, delay)
        await asyncio.sleep(delay)

    raise NewsUnavailableError()  # unreachable: the loop always returns or raises


# Raw GDELT results, keyed by the two inputs that shape the query. Focus areas
# only affect ranking, so they are deliberately not part of the key. News moves
# slowly enough that a short reuse window costs nothing in freshness and saves
# the rate-limit slot entirely on a repeated or shared search.
_articles_cache: Dict[Tuple[str, int], Tuple[float, List[dict]]] = {}


def clear_cache() -> None:
    """Drop cached GDELT results. For tests, and for a manual cache bust."""
    _articles_cache.clear()


def _cache_key(company: str, lookback_days: int) -> Tuple[str, int]:
    return (" ".join(company.lower().split()), lookback_days)


async def fetch_articles(
    company: str,
    lookback_days: int,
    settings: Optional[Settings] = None,
    client: Optional[httpx.AsyncClient] = None,
) -> List[dict]:
    """Fetch raw article metadata from the GDELT DOC 2.0 API."""
    settings = settings or get_settings()

    key = _cache_key(company, lookback_days)
    cached = _articles_cache.get(key)
    if cached is not None and time.monotonic() < cached[0]:
        logger.info("Serving %s (%sd) from cache; no GDELT call", company, lookback_days)
        return list(cached[1])

    now = datetime.now(timezone.utc)
    params = {
        "query": build_query(company),
        "mode": "ArtList",
        "format": "json",
        "maxrecords": str(settings.gdelt_max_records),
        "sort": "DateDesc",
        "startdatetime": (now - timedelta(days=lookback_days)).strftime(_GDELT_WINDOW),
        "enddatetime": now.strftime(_GDELT_WINDOW),
    }
    timeout = httpx.Timeout(settings.gdelt_read_timeout, connect=settings.gdelt_connect_timeout)

    owns_client = client is None
    client = client or httpx.AsyncClient(timeout=timeout, follow_redirects=True)
    try:
        body = await _fetch_body_with_backoff(client, settings, params, timeout)
    finally:
        if owns_client:
            await client.aclose()

    if not body:
        return []
    if _is_rate_limited(body):
        raise NewsUnavailableError(_RATE_LIMIT_MESSAGE)
    try:
        payload = json.loads(body)
    except ValueError as exc:
        # GDELT also answers malformed queries with plain text under HTTP 200.
        logger.warning("GDELT returned a non-JSON response")
        raise NewsUnavailableError() from exc

    articles = payload.get("articles") if isinstance(payload, dict) else None
    result = [a for a in articles if isinstance(a, dict)] if isinstance(articles, list) else []

    _articles_cache[key] = (time.monotonic() + settings.gdelt_cache_seconds, list(result))
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
                snippet=None,
            )
        )
    return sources


async def collect_sources(
    company: str,
    lookback_days: int,
    focus_areas: Optional[Sequence[str]] = None,
    settings: Optional[Settings] = None,
    client: Optional[httpx.AsyncClient] = None,
) -> List[Source]:
    """Full retrieval pipeline: fetch -> filter -> dedupe -> rank -> ids."""
    settings = settings or get_settings()
    raw = await fetch_articles(company, lookback_days, settings=settings, client=client)

    well_formed = [a for a in raw if _is_well_formed(a)]
    on_topic = [a for a in well_formed if _mentions_company(a, company)]
    # Relax the headline gate only if it would leave too little to work with.
    candidates = on_topic if len(on_topic) >= settings.min_sources else well_formed

    unique = deduplicate(candidates)
    ranked = rank_articles(unique, company, lookback_days, focus_areas)
    varied = _limit_per_publisher(ranked)
    return to_sources(varied[: settings.max_sources])
