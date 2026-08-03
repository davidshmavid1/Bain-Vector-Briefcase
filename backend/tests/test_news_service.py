import json
from datetime import date, datetime, timedelta, timezone
from email.utils import format_datetime

import httpx
import pytest
import respx

from app.services import news_service
from app.services.errors import NewsConfigError, NewsQuotaExceededError, NewsUnavailableError
from tests.conftest import make_article, tavily_payload


def test_search_body_targets_news_and_the_requested_window(settings):
    body = news_service.build_search_body("Acme Corp", 30, settings)

    # "company" is appended to disambiguate names shared with people or other
    # entities (e.g. "Gerber" the baby-products company vs. Kaia Gerber) —
    # Tavily's search is semantic, so this shifts ranking with no new param.
    assert body["query"] == "Acme Corp company"
    # topic=news is what makes Tavily return published_date at all.
    assert body["topic"] == "news"
    assert body["search_depth"] == settings.tavily_search_depth
    start = date.fromisoformat(body["start_date"])
    end = date.fromisoformat(body["end_date"])
    assert (end - start).days == 30


def test_normalize_title_strips_publisher_tail_and_punctuation():
    assert news_service.normalize_title("Acme Corp Beats Estimates! - Reuters") == (
        "acme corp beats estimates"
    )


def test_deduplicate_removes_exact_and_near_duplicates():
    articles = [
        make_article("Acme Corp beats quarterly estimates on cloud growth", "reuters.com"),
        # Same story, different publisher tail -> near duplicate.
        make_article("Acme Corp beats quarterly estimates on cloud growth - CNBC", "cnbc.com"),
        # Same story, one extra word -> still a near duplicate by token overlap.
        make_article("Acme Corp beats quarterly estimates on strong cloud growth", "wsj.com"),
        make_article("Acme Corp opens new manufacturing plant in Ohio", "ft.com"),
    ]

    kept = news_service.deduplicate(articles)

    assert len(kept) == 2
    assert kept[0]["domain"] == "reuters.com"
    assert kept[1]["domain"] == "ft.com"


def test_deduplicate_removes_same_url_with_different_query_string():
    articles = [
        make_article("Acme Corp signs supply agreement", url="https://reuters.com/a?utm=1"),
        make_article("Totally different wording about Acme deal", url="https://reuters.com/a?utm=2"),
    ]

    assert len(news_service.deduplicate(articles)) == 1


def test_ranking_prefers_recent_and_relevant_headlines():
    articles = [
        make_article("Unrelated market wrap for European indices today", "reuters.com", days_ago=1),
        make_article("Acme Corp announces major acquisition of rival", "reuters.com", days_ago=25),
        make_article("Acme Corp raises full-year guidance after strong quarter", "wsj.com", days_ago=1),
    ]

    ranked = news_service.rank_articles(articles, "Acme Corp", 30)

    assert ranked[0]["title"].startswith("Acme Corp raises full-year guidance")
    assert ranked[1]["title"].startswith("Acme Corp announces major acquisition")
    assert ranked[2]["title"].startswith("Unrelated market wrap")


def test_ranking_is_deterministic():
    articles = [
        make_article("Acme Corp opens plant in Ohio", "reuters.com", days_ago=3),
        make_article("Acme Corp names new chief financial officer", "wsj.com", days_ago=3),
        make_article("Acme Corp faces antitrust probe in Europe", "ft.com", days_ago=3),
    ]

    first = [a["url"] for a in news_service.rank_articles(articles, "Acme Corp", 30)]
    second = [a["url"] for a in news_service.rank_articles(list(reversed(articles)), "Acme Corp", 30)]

    assert first == second


def test_ranking_excludes_malformed_articles():
    articles = [
        make_article("Acme Corp reports record annual revenue growth", "reuters.com"),
        {"title": "No url here at all in this record", "domain": "x.com", "seendate": "20260101T000000Z"},
        {"url": "https://a.com/1", "title": "Short", "domain": "a.com", "seendate": "20260101T000000Z"},
        {"url": "https://b.com/1", "title": "Acme Corp bad date field here", "domain": "b.com", "seendate": "nope"},
    ]

    ranked = news_service.rank_articles(articles, "Acme Corp", 30)

    assert len(ranked) == 1
    assert ranked[0]["domain"] == "reuters.com"


def test_focus_area_boosts_matching_headline():
    regulatory = make_article("Acme Corp faces antitrust probe from regulator", days_ago=5)
    neutral = make_article("Acme Corp opens visitor centre at headquarters", days_ago=5)

    with_focus = news_service.score_article(regulatory, "Acme Corp", 30, ["regulatory"])
    without_focus = news_service.score_article(regulatory, "Acme Corp", 30, None)

    assert with_focus > without_focus
    assert with_focus > news_service.score_article(neutral, "Acme Corp", 30, ["regulatory"])


def test_to_sources_assigns_stable_sequential_ids():
    articles = [
        make_article("Acme Corp headline one about the quarter", "reuters.com"),
        make_article("Acme Corp headline two about the plant", "wsj.com"),
    ]

    sources = news_service.to_sources(articles)

    assert [s.id for s in sources] == ["source-1", "source-2"]
    assert sources[0].publisher == "Reuters"
    assert sources[0].url == articles[0]["url"]
    assert sources[0].snippet is None


@pytest.mark.parametrize(
    ("domain", "expected"),
    [
        ("reuters.com", "Reuters"),
        ("www.reuters.com", "Reuters"),
        ("finance.yahoo.com", "Yahoo Finance"),
        ("world.kbs.co.kr", "Kbs"),
        ("bbc.co.uk", "BBC"),
        ("windowscentral.com", "Windowscentral"),
    ],
)
def test_publisher_name_from_domain(domain, expected):
    assert news_service._publisher_name(domain) == expected


def test_at_most_three_headlines_per_publisher_lead_the_ranking(settings):
    dominant = [
        make_article(headline, "loudpublisher.com", days_ago=1)
        for headline in [
            "Acme Corp raises full-year guidance after a strong quarter",
            "Acme Corp opens a robotics plant in Ohio",
            "Acme Corp names a new chief financial officer",
            "Acme Corp signs a cloud partnership with a carrier",
        ]
    ]
    other = make_article("Regulators open an antitrust probe into Acme pricing", "ft.com", days_ago=1)

    limited = news_service._limit_per_publisher(
        news_service.rank_articles(dominant + [other], "Acme Corp", 30)
    )

    assert sum(1 for a in limited[:4] if a["domain"] == "loudpublisher.com") == 3
    assert limited[3]["domain"] == "ft.com"


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (
            "Siemens , Nvidia advance self - verifying agentic AI workflows",
            "Siemens, Nvidia advance self-verifying agentic AI workflows",
        ),
        ("Siemens Updates Desigo CC - ISSSource", "Siemens Updates Desigo CC - ISSSource"),
        ("Why is Microsoft stock soaring ?", "Why is Microsoft stock soaring?"),
        ("Acme beats estimates ( MSFT : NASDAQ )", "Acme beats estimates (MSFT: NASDAQ)"),
        ("Acme  Corp\n reports   record revenue", "Acme Corp reports record revenue"),
        ("Acme Corp 's chief executive steps down", "Acme Corp's chief executive steps down"),
        ("Acme Corp - Reuters", "Acme Corp - Reuters"),
    ],
)
def test_tidy_title_repairs_spaced_punctuation(raw, expected):
    assert news_service.tidy_title(raw) == expected


def test_spaced_hyphen_is_not_mistaken_for_a_publisher_tail():
    # A raw GDELT "self - verifying" looks like " - Publisher" to the tail regex.
    # Left unrepaired it swallowed the rest of the headline, starving dedup and
    # the relevance gate of the very tokens they match on.
    raw = "Acme Corp and Nvidia advance self - verifying agentic workflows"

    normalized = news_service.normalize_title(raw)

    assert normalized == "acme corp and nvidia advance self verifying agentic workflows"


def test_publisher_tail_is_still_stripped():
    assert news_service.normalize_title("Acme Corp beats estimates - Reuters") == "acme corp beats estimates"


def test_spaced_hyphen_headlines_still_deduplicate():
    articles = [
        make_article("Acme Corp and Nvidia advance self - verifying agentic workflows", "reuters.com"),
        make_article("Acme Corp and Nvidia advance self-verifying agentic workflows", "cnbc.com"),
    ]

    assert len(news_service.deduplicate(articles)) == 1


def _response_with(header_value):
    headers = {"Retry-After": header_value} if header_value is not None else {}
    return httpx.Response(429, headers=headers, text="slow down")


@pytest.mark.parametrize(
    ("header", "expected"),
    [
        ("2", 2.0),
        ("0", 0.0),
        ("  7  ", 7.0),
        (None, None),
        ("", None),
        ("soon", None),
        ("-5", 0.0),          # never negative
        ("9999", 30.0),       # clamped to the ceiling
    ],
)
def test_retry_after_parsing(header, expected):
    assert news_service._retry_after_seconds(_response_with(header), 30.0) == expected


def test_retry_after_accepts_http_date():
    when = datetime.now(timezone.utc) + timedelta(seconds=12)
    header = format_datetime(when, usegmt=True)

    seconds = news_service._retry_after_seconds(_response_with(header), 30.0)

    assert seconds is not None and 8 <= seconds <= 14


def test_retry_after_in_the_past_is_zero():
    header = format_datetime(datetime.now(timezone.utc) - timedelta(minutes=5), usegmt=True)

    assert news_service._retry_after_seconds(_response_with(header), 30.0) == 0.0


# --- Tavily retrieval -----------------------------------------------------


TAVILY_URL = "https://api.tavily.com/search"


@pytest.mark.asyncio
@respx.mock
async def test_collect_sources_happy_path(settings):
    route = respx.post(TAVILY_URL).mock(return_value=httpx.Response(200, json=tavily_payload(8)))

    sources = await news_service.collect_sources("Acme Corp", 30, settings=settings)

    assert len(sources) == 8
    assert [s.id for s in sources] == [f"source-{i}" for i in range(1, 9)]
    assert all(s.url.startswith("https://") for s in sources)
    # The excerpt is the whole point of the move off GDELT.
    assert all(s.snippet for s in sources)
    assert all(s.published_at is not None for s in sources)

    request = route.calls.last.request
    assert request.headers["Authorization"] == f"Bearer {settings.tavily_api_key}"
    assert json.loads(request.content)["topic"] == "news"


@pytest.mark.asyncio
@respx.mock
async def test_configured_search_depth_reaches_the_request(settings):
    deep = settings.model_copy(update={"tavily_search_depth": "advanced"})
    route = respx.post(TAVILY_URL).mock(return_value=httpx.Response(200, json=tavily_payload(5)))

    await news_service.collect_sources("Acme Corp", 30, settings=deep)

    assert json.loads(route.calls.last.request.content)["search_depth"] == "advanced"


@pytest.mark.parametrize("lookback", [7, 30, 90])
@pytest.mark.asyncio
@respx.mock
async def test_lookback_window_is_sent_as_dates(settings, lookback):
    route = respx.post(TAVILY_URL).mock(return_value=httpx.Response(200, json=tavily_payload(5)))

    await news_service.collect_sources("Acme Corp", lookback, settings=settings)

    body = json.loads(route.calls.last.request.content)
    start = date.fromisoformat(body["start_date"])
    end = date.fromisoformat(body["end_date"])
    assert (end - start).days == lookback


@pytest.mark.asyncio
@respx.mock
async def test_results_are_normalised_onto_the_internal_shape(settings):
    payload = {
        "results": [
            {
                "title": "Acme Corp opens a plant in Ohio",
                "url": "https://www.reuters.com/business/acme-plant",
                "content": "  Acme Corp said   it opened a plant.  ",
                "score": 0.94,
                "published_date": "2026-07-30T12:00:00Z",
            }
        ]
    }
    respx.post(TAVILY_URL).mock(return_value=httpx.Response(200, json=payload))

    sources = await news_service.collect_sources("Acme Corp", 30, settings=settings)

    source = sources[0]
    assert source.url == "https://www.reuters.com/business/acme-plant"
    # Tavily sends no domain field, so the publisher is derived from the URL.
    assert source.publisher == "Reuters"
    assert source.snippet == "Acme Corp said it opened a plant."
    assert source.published_at.year == 2026


@pytest.mark.asyncio
@respx.mock
async def test_malformed_results_are_dropped_not_fatal(settings):
    payload = {
        "results": [
            {"title": "", "url": "https://reuters.com/a", "content": "x"},
            {"title": "Acme Corp raises full-year guidance today", "url": ""},
            {"title": "Acme Corp names a new chief financial officer", "url": "not-a-url"},
            *tavily_payload(4)["results"],
        ]
    }
    respx.post(TAVILY_URL).mock(return_value=httpx.Response(200, json=payload))

    sources = await news_service.collect_sources("Acme Corp", 30, settings=settings)

    assert len(sources) == 4


@pytest.mark.asyncio
async def test_missing_key_fails_before_any_http_call(settings):
    unconfigured = settings.model_copy(update={"tavily_api_key": ""})

    with pytest.raises(NewsConfigError) as exc:
        await news_service.collect_sources("Acme Corp", 30, settings=unconfigured)

    assert "TAVILY_API_KEY" in str(exc.value)


@pytest.mark.asyncio
@respx.mock
async def test_empty_results_return_no_sources(settings):
    respx.post(TAVILY_URL).mock(return_value=httpx.Response(200, json={"results": []}))

    assert await news_service.collect_sources("Nonexistent Co", 7, settings=settings) == []


@pytest.mark.asyncio
@respx.mock
async def test_response_without_results_list_is_an_error(settings):
    respx.post(TAVILY_URL).mock(return_value=httpx.Response(200, json={"unexpected": True}))

    with pytest.raises(NewsUnavailableError):
        await news_service.collect_sources("Acme Corp", 30, settings=settings)


# --- error mapping --------------------------------------------------------


@pytest.mark.parametrize("status", [401, 403])
@pytest.mark.asyncio
@respx.mock
async def test_rejected_key_fails_fast_without_retrying(settings, status):
    route = respx.post(TAVILY_URL).mock(return_value=httpx.Response(status, json={"error": "bad key"}))

    with pytest.raises(NewsConfigError):
        await news_service.collect_sources("Acme Corp", 30, settings=settings)

    assert route.call_count == 1  # waiting will not fix a bad key


@pytest.mark.asyncio
@respx.mock
async def test_quota_exhaustion_is_reported_distinctly(settings):
    route = respx.post(TAVILY_URL).mock(
        return_value=httpx.Response(429, json={"code": "QUOTA_EXCEEDED", "error": "monthly credits used"})
    )

    with pytest.raises(NewsQuotaExceededError) as exc:
        await news_service.collect_sources("Acme Corp", 30, settings=settings)

    assert "quota" in str(exc.value).lower()
    assert route.call_count == 1  # a retry cannot conjure credits


@pytest.mark.asyncio
@respx.mock
async def test_rate_limit_is_retried_then_succeeds(settings, monkeypatch):
    slept = []

    async def record_sleep(seconds):
        slept.append(seconds)

    monkeypatch.setattr(news_service.asyncio, "sleep", record_sleep)
    respx.post(TAVILY_URL).mock(
        side_effect=[
            httpx.Response(429, headers={"retry-after": "4"}, json={"error": "too many requests"}),
            httpx.Response(200, json=tavily_payload(5)),
        ]
    )

    sources = await news_service.collect_sources("Acme Corp", 30, settings=settings)

    assert len(sources) == 5
    assert slept == [4.0]  # the header wins over the configured delay


@pytest.mark.asyncio
@respx.mock
async def test_persistent_rate_limiting_raises_news_unavailable(settings, monkeypatch):
    monkeypatch.setattr(news_service.asyncio, "sleep", _no_sleep)
    route = respx.post(TAVILY_URL).mock(
        return_value=httpx.Response(429, json={"error": "too many requests"})
    )

    with pytest.raises(NewsUnavailableError):
        await news_service.collect_sources("Acme Corp", 30, settings=settings)

    assert route.call_count == 2


@pytest.mark.asyncio
@respx.mock
async def test_server_error_is_retried(settings, monkeypatch):
    monkeypatch.setattr(news_service.asyncio, "sleep", _no_sleep)
    respx.post(TAVILY_URL).mock(
        side_effect=[
            httpx.Response(503, json={"error": "unavailable"}),
            httpx.Response(200, json=tavily_payload(5)),
        ]
    )

    assert len(await news_service.collect_sources("Acme Corp", 30, settings=settings)) == 5


@pytest.mark.asyncio
@respx.mock
async def test_client_error_is_not_retried(settings, monkeypatch):
    monkeypatch.setattr(news_service.asyncio, "sleep", _no_sleep)
    route = respx.post(TAVILY_URL).mock(return_value=httpx.Response(400, json={"error": "bad request"}))

    with pytest.raises(NewsUnavailableError):
        await news_service.collect_sources("Acme Corp", 30, settings=settings)

    assert route.call_count == 1


@pytest.mark.asyncio
@respx.mock
async def test_transient_timeout_is_retried(settings, monkeypatch):
    monkeypatch.setattr(news_service.asyncio, "sleep", _no_sleep)
    respx.post(TAVILY_URL).mock(
        side_effect=[httpx.ConnectTimeout("slow"), httpx.Response(200, json=tavily_payload(5))]
    )

    assert len(await news_service.collect_sources("Acme Corp", 30, settings=settings)) == 5


@pytest.mark.asyncio
@respx.mock
async def test_persistent_timeout_raises_news_unavailable(settings, monkeypatch):
    monkeypatch.setattr(news_service.asyncio, "sleep", _no_sleep)
    route = respx.post(TAVILY_URL).mock(side_effect=httpx.ConnectTimeout("slow"))

    with pytest.raises(NewsUnavailableError):
        await news_service.collect_sources("Acme Corp", 30, settings=settings)

    assert route.call_count == 2


@pytest.mark.parametrize("status", [401, 429, 400, 503])
@pytest.mark.asyncio
@respx.mock
async def test_the_api_key_never_appears_in_an_error(settings, monkeypatch, status):
    monkeypatch.setattr(news_service.asyncio, "sleep", _no_sleep)
    # An upstream that echoes the key back must not leak it onward.
    respx.post(TAVILY_URL).mock(
        return_value=httpx.Response(status, json={"error": f"rejected key {settings.tavily_api_key}"})
    )

    with pytest.raises(Exception) as exc:
        await news_service.collect_sources("Acme Corp", 30, settings=settings)

    assert settings.tavily_api_key not in str(exc.value)


# --- rate gate and cache --------------------------------------------------


@pytest.mark.asyncio
@respx.mock
async def test_repeat_search_spends_no_credit(settings):
    route = respx.post(TAVILY_URL).mock(return_value=httpx.Response(200, json=tavily_payload(6)))

    first = await news_service.collect_sources("Acme Corp", 30, settings=settings)
    second = await news_service.collect_sources("Acme Corp", 30, settings=settings)

    assert route.call_count == 1
    assert [s.url for s in first] == [s.url for s in second]


@pytest.mark.asyncio
@respx.mock
async def test_cache_key_ignores_case_and_padding(settings):
    route = respx.post(TAVILY_URL).mock(return_value=httpx.Response(200, json=tavily_payload(6)))

    await news_service.collect_sources("Acme Corp", 30, settings=settings)
    await news_service.collect_sources("  acme   corp ", 30, settings=settings)

    assert route.call_count == 1


@pytest.mark.asyncio
@respx.mock
async def test_a_different_window_is_fetched_separately(settings):
    route = respx.post(TAVILY_URL).mock(return_value=httpx.Response(200, json=tavily_payload(6)))

    await news_service.collect_sources("Acme Corp", 30, settings=settings)
    await news_service.collect_sources("Acme Corp", 7, settings=settings)

    assert route.call_count == 2


@pytest.mark.asyncio
@respx.mock
async def test_expired_cache_entry_is_refetched(settings):
    brief_cache = settings.model_copy(update={"tavily_cache_seconds": 0.0})
    route = respx.post(TAVILY_URL).mock(return_value=httpx.Response(200, json=tavily_payload(6)))

    await news_service.collect_sources("Acme Corp", 30, settings=brief_cache)
    await news_service.collect_sources("Acme Corp", 30, settings=brief_cache)

    assert route.call_count == 2


@pytest.mark.asyncio
@respx.mock
async def test_failed_search_is_not_cached(settings, monkeypatch):
    monkeypatch.setattr(news_service.asyncio, "sleep", _no_sleep)
    respx.post(TAVILY_URL).mock(
        side_effect=[
            httpx.Response(503, json={"error": "x"}),
            httpx.Response(503, json={"error": "x"}),
            httpx.Response(200, json=tavily_payload(6)),
        ]
    )

    with pytest.raises(NewsUnavailableError):
        await news_service.collect_sources("Acme Corp", 30, settings=settings)

    assert len(await news_service.collect_sources("Acme Corp", 30, settings=settings)) == 6


@pytest.mark.asyncio
@respx.mock
async def test_first_call_is_not_delayed(settings, monkeypatch):
    slept = []

    async def record_sleep(seconds):
        slept.append(seconds)

    monkeypatch.setattr(news_service.asyncio, "sleep", record_sleep)
    spaced = settings.model_copy(update={"tavily_min_interval_seconds": 5.0})
    respx.post(TAVILY_URL).mock(return_value=httpx.Response(200, json=tavily_payload(5)))

    await news_service.collect_sources("Acme Corp", 30, settings=spaced)

    assert slept == []


@pytest.mark.asyncio
@respx.mock
async def test_outbound_calls_are_spaced_by_the_minimum_interval(settings, monkeypatch):
    slept = []
    real_sleep = news_service.asyncio.sleep

    async def record_sleep(seconds):
        slept.append(seconds)
        await real_sleep(0)

    monkeypatch.setattr(news_service.asyncio, "sleep", record_sleep)
    spaced = settings.model_copy(update={"tavily_min_interval_seconds": 5.0})
    respx.post(TAVILY_URL).mock(return_value=httpx.Response(200, json=tavily_payload(5)))

    await news_service.collect_sources("Acme Corp", 30, settings=spaced)
    news_service.clear_cache()
    await news_service.collect_sources("Acme Corp", 30, settings=spaced)

    assert len(slept) == 1
    assert 0 < slept[0] <= 5.0


@pytest.mark.asyncio
@respx.mock
async def test_concurrent_searches_do_not_race_into_a_burst(settings, monkeypatch):
    in_flight = 0
    max_in_flight = 0

    async def tracking_post(client, s, body, timeout):
        nonlocal in_flight, max_in_flight
        in_flight += 1
        max_in_flight = max(max_in_flight, in_flight)
        await news_service.asyncio.sleep(0)
        in_flight -= 1
        return tavily_payload(5)

    monkeypatch.setattr(news_service, "_post_search", tracking_post)

    await news_service.asyncio.gather(
        *(news_service.collect_sources(f"Company {i}", 30, settings=settings) for i in range(5))
    )

    assert max_in_flight == 1


async def _no_sleep(_seconds):
    return None
