import json
from datetime import datetime, timedelta, timezone
from email.utils import format_datetime
from typing import List

import httpx
import pytest
import respx

from app.services import news_service
from app.services.errors import NewsUnavailableError
from tests.conftest import make_article, make_varied_articles


def test_build_query_quotes_company_and_restricts_language():
    assert news_service.build_query("Acme Corp") == '"Acme Corp" sourcelang:english'


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


@pytest.mark.asyncio
@respx.mock
async def test_collect_sources_happy_path(settings):
    payload = {"articles": make_varied_articles(8)}
    respx.get(settings.gdelt_base_url).mock(return_value=httpx.Response(200, json=payload))

    sources = await news_service.collect_sources("Acme Corp", 30, settings=settings)

    assert len(sources) == 8
    assert [s.id for s in sources] == [f"source-{i}" for i in range(1, 9)]
    assert all(s.url.startswith("https://") for s in sources)


@pytest.mark.asyncio
@respx.mock
async def test_collect_sources_caps_at_max_sources(settings):
    payload = {"articles": make_varied_articles(29)}
    respx.get(settings.gdelt_base_url).mock(return_value=httpx.Response(200, json=payload))

    sources = await news_service.collect_sources("Acme Corp", 30, settings=settings)

    assert len(sources) == settings.max_sources


@pytest.mark.asyncio
@respx.mock
async def test_empty_gdelt_results_return_no_sources(settings):
    respx.get(settings.gdelt_base_url).mock(return_value=httpx.Response(200, json={"articles": []}))

    assert await news_service.collect_sources("Nonexistent Co", 7, settings=settings) == []


@pytest.mark.asyncio
@respx.mock
async def test_blank_gdelt_body_returns_no_sources(settings):
    respx.get(settings.gdelt_base_url).mock(return_value=httpx.Response(200, text="   "))

    assert await news_service.collect_sources("Nonexistent Co", 7, settings=settings) == []


@pytest.mark.asyncio
@respx.mock
async def test_non_json_gdelt_response_raises_news_unavailable(settings):
    respx.get(settings.gdelt_base_url).mock(
        return_value=httpx.Response(200, text="Your query was malformed.")
    )

    with pytest.raises(NewsUnavailableError):
        await news_service.collect_sources("Acme Corp", 30, settings=settings)


RATE_LIMIT_BODY = "Please limit requests to one every 5 seconds or contact the maintainer."


@pytest.mark.asyncio
@respx.mock
async def test_rate_limited_response_is_retried_then_succeeds(settings):
    fast_retry = settings.model_copy(update={"gdelt_retry_delays": (0.0,)})
    respx.get(settings.gdelt_base_url).mock(
        side_effect=[
            httpx.Response(200, text=RATE_LIMIT_BODY),
            httpx.Response(200, json={"articles": make_varied_articles(5)}),
        ]
    )

    sources = await news_service.collect_sources("Acme Corp", 30, settings=fast_retry)

    assert len(sources) == 5


@pytest.mark.asyncio
@respx.mock
async def test_persistent_rate_limiting_raises_a_clear_error(settings):
    fast_retry = settings.model_copy(update={"gdelt_retry_delays": (0.0,)})
    respx.get(settings.gdelt_base_url).mock(return_value=httpx.Response(200, text=RATE_LIMIT_BODY))

    with pytest.raises(NewsUnavailableError) as exc:
        await news_service.collect_sources("Acme Corp", 30, settings=fast_retry)

    assert "rate-limiting" in str(exc.value)


@pytest.mark.asyncio
@respx.mock
async def test_http_429_is_retried_then_succeeds(settings):
    # GDELT throttles with a real 429 as well as with a plain-text notice
    # under HTTP 200; both have to survive a retry.
    fast_retry = settings.model_copy(update={"gdelt_retry_delays": (0.0,)})
    respx.get(settings.gdelt_base_url).mock(
        side_effect=[
            httpx.Response(429, text=RATE_LIMIT_BODY),
            httpx.Response(200, json={"articles": make_varied_articles(5)}),
        ]
    )

    sources = await news_service.collect_sources("Acme Corp", 30, settings=fast_retry)

    assert len(sources) == 5


@pytest.mark.asyncio
@respx.mock
async def test_persistent_http_429_names_rate_limiting(settings):
    fast_retry = settings.model_copy(update={"gdelt_retry_delays": (0.0,)})
    respx.get(settings.gdelt_base_url).mock(return_value=httpx.Response(429, text=RATE_LIMIT_BODY))

    with pytest.raises(NewsUnavailableError) as exc:
        await news_service.collect_sources("Acme Corp", 30, settings=fast_retry)

    assert "rate-limiting" in str(exc.value)


@pytest.mark.asyncio
@respx.mock
async def test_429_then_refused_connection_still_names_rate_limiting(settings):
    # Observed live: GDELT answers 429 for a while, then stops accepting the
    # connection entirely. The transport failure comes last, but throttling is
    # still the real cause and the message has to say so.
    fast_retry = settings.model_copy(update={"gdelt_retry_delays": (0.0, 0.0)})
    respx.get(settings.gdelt_base_url).mock(
        side_effect=[
            httpx.Response(429, text=RATE_LIMIT_BODY),
            httpx.Response(429, text=RATE_LIMIT_BODY),
            httpx.ConnectTimeout("timed out"),
        ]
    )

    with pytest.raises(NewsUnavailableError) as exc:
        await news_service.collect_sources("Acme Corp", 30, settings=fast_retry)

    assert "rate-limiting" in str(exc.value)


@pytest.mark.asyncio
@respx.mock
async def test_transport_failure_alone_stays_generic(settings):
    fast_retry = settings.model_copy(update={"gdelt_retry_delays": (0.0,)})
    respx.get(settings.gdelt_base_url).mock(side_effect=httpx.ConnectTimeout("timed out"))

    with pytest.raises(NewsUnavailableError) as exc:
        await news_service.collect_sources("Acme Corp", 30, settings=fast_retry)

    assert "rate-limiting" not in str(exc.value)


@pytest.mark.asyncio
@respx.mock
async def test_client_error_status_fails_without_retrying(settings):
    # A 400 means the query itself is wrong, so retrying only wastes the budget.
    route = respx.get(settings.gdelt_base_url).mock(
        return_value=httpx.Response(400, text="bad query")
    )

    with pytest.raises(NewsUnavailableError):
        await news_service.collect_sources("Acme Corp", 30, settings=settings)

    assert route.call_count == 1


@pytest.mark.asyncio
@respx.mock
async def test_headlines_that_never_name_the_company_are_dropped(settings):
    # GDELT full-text-searches article bodies, so off-topic headlines come back.
    articles = make_varied_articles(6) + [
        make_article("European indices close higher on energy and banking stocks", "reuters.com"),
        make_article("Funky Taurus Media - Music Photo Agency and Products", "funkytaurus.com"),
    ]
    respx.get(settings.gdelt_base_url).mock(
        return_value=httpx.Response(200, json={"articles": articles})
    )

    sources = await news_service.collect_sources("Acme Corp", 30, settings=settings)

    assert len(sources) == 6
    assert all("acme" in source.title.lower() for source in sources)


@pytest.mark.asyncio
@respx.mock
async def test_headline_gate_relaxes_when_it_would_starve_the_brief(settings):
    articles = make_varied_articles(1) + [
        make_article("European indices close higher on energy and banking stocks", "reuters.com"),
        make_article("Industrial output rises across the eurozone in June", "ft.com"),
    ]
    respx.get(settings.gdelt_base_url).mock(
        return_value=httpx.Response(200, json={"articles": articles})
    )

    sources = await news_service.collect_sources("Acme Corp", 30, settings=settings)

    assert len(sources) == 3
    assert sources[0].title.startswith("Acme Corp")


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


@pytest.mark.asyncio
@respx.mock
async def test_gdelt_http_error_raises_news_unavailable(settings):
    respx.get(settings.gdelt_base_url).mock(return_value=httpx.Response(503, text="unavailable"))

    with pytest.raises(NewsUnavailableError) as exc:
        await news_service.collect_sources("Acme Corp", 30, settings=settings)

    assert "unavailable" in str(exc.value).lower()


@pytest.mark.asyncio
@respx.mock
async def test_persistent_gdelt_timeout_raises_news_unavailable(settings):
    fast_retry = settings.model_copy(update={"gdelt_retry_delays": (0.0,)})
    route = respx.get(settings.gdelt_base_url).mock(side_effect=httpx.ConnectTimeout("timed out"))

    with pytest.raises(NewsUnavailableError):
        await news_service.collect_sources("Acme Corp", 30, settings=fast_retry)

    assert route.call_count == 2


@pytest.mark.asyncio
@respx.mock
async def test_transient_gdelt_timeout_is_retried(settings):
    fast_retry = settings.model_copy(update={"gdelt_retry_delays": (0.0,)})
    respx.get(settings.gdelt_base_url).mock(
        side_effect=[
            httpx.ConnectTimeout("timed out"),
            httpx.Response(200, json={"articles": make_varied_articles(5)}),
        ]
    )

    sources = await news_service.collect_sources("Acme Corp", 30, settings=fast_retry)

    assert len(sources) == 5


@pytest.mark.asyncio
@respx.mock
async def test_http_error_status_is_not_retried(settings):
    fast_retry = settings.model_copy(update={"gdelt_retry_delays": (0.0,)})
    route = respx.get(settings.gdelt_base_url).mock(return_value=httpx.Response(500, text="boom"))

    with pytest.raises(NewsUnavailableError):
        await news_service.collect_sources("Acme Corp", 30, settings=fast_retry)

    assert route.call_count == 1


@pytest.mark.asyncio
@respx.mock
async def test_lookback_window_is_sent_to_gdelt(settings):
    route = respx.get(settings.gdelt_base_url).mock(
        return_value=httpx.Response(200, json={"articles": []})
    )

    await news_service.collect_sources("Acme Corp", 7, settings=settings)

    params = route.calls.last.request.url.params
    start = datetime.strptime(params["startdatetime"], "%Y%m%d%H%M%S").replace(tzinfo=timezone.utc)
    delta = datetime.now(timezone.utc) - start
    assert timedelta(days=7) - timedelta(minutes=2) < delta < timedelta(days=7, minutes=2)
    assert json.loads(params["maxrecords"]) == settings.gdelt_max_records


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
def test_tidy_title_repairs_gdelt_spacing(raw, expected):
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


# --- Retry-After handling -------------------------------------------------


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


@pytest.mark.asyncio
@respx.mock
async def test_retry_after_header_overrides_configured_delay(settings, monkeypatch):
    slept: List[float] = []

    async def record_sleep(seconds):
        slept.append(seconds)

    monkeypatch.setattr(news_service.asyncio, "sleep", record_sleep)
    respx.get(settings.gdelt_base_url).mock(
        side_effect=[
            httpx.Response(429, headers={"Retry-After": "3"}, text="slow down"),
            httpx.Response(200, json={"articles": make_varied_articles(5)}),
        ]
    )

    sources = await news_service.collect_sources("Acme Corp", 30, settings=settings)

    assert len(sources) == 5
    assert slept == [3.0]  # the header, not the configured 6.0


@pytest.mark.asyncio
@respx.mock
async def test_without_retry_after_the_configured_delay_is_used(settings, monkeypatch):
    slept: List[float] = []

    async def record_sleep(seconds):
        slept.append(seconds)

    monkeypatch.setattr(news_service.asyncio, "sleep", record_sleep)
    respx.get(settings.gdelt_base_url).mock(
        side_effect=[
            httpx.Response(429, text="slow down"),
            httpx.Response(200, json={"articles": make_varied_articles(5)}),
        ]
    )

    await news_service.collect_sources("Acme Corp", 30, settings=settings)

    assert slept == [settings.gdelt_retry_delays[0]]


@pytest.mark.asyncio
@respx.mock
async def test_absurd_retry_after_is_clamped(settings, monkeypatch):
    slept: List[float] = []

    async def record_sleep(seconds):
        slept.append(seconds)

    monkeypatch.setattr(news_service.asyncio, "sleep", record_sleep)
    respx.get(settings.gdelt_base_url).mock(
        side_effect=[
            httpx.Response(429, headers={"Retry-After": "86400"}, text="slow down"),
            httpx.Response(200, json={"articles": make_varied_articles(5)}),
        ]
    )

    await news_service.collect_sources("Acme Corp", 30, settings=settings)

    assert slept == [settings.gdelt_max_retry_delay]
