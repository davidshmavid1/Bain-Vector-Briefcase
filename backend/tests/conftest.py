from datetime import datetime, timedelta, timezone
from typing import List, Optional

import pytest

from app.config import Settings
from app.schemas import (
    AnalysisDevelopment,
    AnalysisInsight,
    BriefAnalysis,
    Source,
    SourceEntityMatch,
    TargetEntity,
)


@pytest.fixture(autouse=True)
def isolate_news_service_state():
    """The result cache and rate gate are module-level, so reset them around
    every test — otherwise one case's cached result satisfies the next case's
    request and its call-count assertions silently pass."""
    from app.services import news_service

    news_service.clear_cache()
    news_service.reset_rate_gate()
    yield
    news_service.clear_cache()
    news_service.reset_rate_gate()


@pytest.fixture
def settings() -> Settings:
    return Settings(
        gemini_api_key="test-key",
        gemini_model="gemini-2.5-flash",
        allowed_origins="http://localhost:3000",
        demo_mode=False,
        tavily_api_key="tvly-test-key",
        # Real spacing would slow every test that touches retrieval. The gate's
        # behaviour is covered explicitly in test_news_service.py instead.
        tavily_min_interval_seconds=0.0,
    )


def make_article(
    title: str,
    domain: str = "reuters.com",
    days_ago: int = 1,
    url: Optional[str] = None,
    snippet: Optional[str] = None,
) -> dict:
    """An article in the internal normalised shape, i.e. post-`_normalize_result`.

    Pipeline tests (dedup, ranking, publisher capping) consume this directly and
    are deliberately independent of whichever provider produced it.
    """
    seen = datetime.now(timezone.utc) - timedelta(days=days_ago)
    return {
        "url": url or f"https://{domain}/{abs(hash(title)) % 10**8}",
        "title": title,
        "seendate": seen.isoformat(),
        "domain": domain,
        "snippet": snippet,
    }


def make_tavily_result(
    title: str,
    domain: str = "reuters.com",
    days_ago: int = 1,
    url: Optional[str] = None,
    content: str = "A short excerpt from the article body.",
) -> dict:
    """A raw Tavily result, i.e. what the API actually returns pre-normalisation."""
    seen = datetime.now(timezone.utc) - timedelta(days=days_ago)
    return {
        "title": title,
        "url": url or f"https://{domain}/{abs(hash(title)) % 10**8}",
        "content": content,
        "score": 0.9,
        "published_date": seen.isoformat().replace("+00:00", "Z"),
    }


def tavily_payload(count: int) -> dict:
    """A full Tavily search response carrying `count` distinct results."""
    return {
        "query": "Acme Corp",
        "results": [
            make_tavily_result(headline, domain=f"publisher{i}.com", days_ago=i)
            for i, headline in enumerate(DISTINCT_HEADLINES[:count], start=1)
        ],
        "response_time": 1.2,
    }


# Genuinely distinct headlines, so deduplication does not collapse fixtures
# that are only meant to exercise ranking, capping or the API surface.
DISTINCT_HEADLINES = [
    "Acme Corp raises full-year guidance after a strong fourth quarter",
    "Acme Corp opens a robotics manufacturing plant in Ohio",
    "European regulators open an antitrust probe into Acme pricing",
    "Acme Corp names a veteran operator as chief financial officer",
    "Acme Corp signs a multi-year cloud partnership with a major carrier",
    "Union representing Acme warehouse staff votes to authorise a strike",
    "Acme Corp writes down the value of its consumer hardware division",
    "Analysts upgrade Acme Corp on improving industrial margins",
    "Acme Corp recalls a batch of batteries over overheating reports",
    "Acme Corp commits to renewable power across its European sites",
    "Acme Corp acquires a small logistics software startup in Berlin",
    "Data breach exposes contact details of some Acme business customers",
    "Acme Corp delays the launch of its next-generation sensor line",
    "Acme Corp expands its India engineering centre with 900 new roles",
    "Shareholder group pushes Acme Corp to split its chairman role",
    "Acme Corp reports a second consecutive quarter of volume declines",
    "Acme Corp wins a defence contract for maintenance services",
    "Court dismisses a patent claim brought against Acme Corp",
    "Acme Corp lowers prices across its subscription software tiers",
    "Acme Corp begins construction of a battery recycling facility",
    "Rating agency revises the outlook on Acme Corp debt to stable",
    "Acme Corp pilots an automated inspection system at two factories",
    "Former Acme Corp executive joins a rival as head of strategy",
    "Acme Corp settles a long-running environmental dispute in Texas",
    "Acme Corp reorganises its Asia-Pacific sales leadership structure",
    "Insurers question the coverage terms of an Acme Corp supplier claim",
    "Acme Corp trims its capital expenditure plan for the coming year",
    "Acme Corp launches a repair programme for older industrial units",
    "Local officials approve a tax package for an Acme Corp expansion",
]


def make_varied_articles(count: int) -> List[dict]:
    """Build `count` distinct, well-formed GDELT-shaped articles."""
    if count > len(DISTINCT_HEADLINES):
        raise ValueError("Not enough distinct headlines for this fixture.")
    return [
        make_article(headline, domain=f"publisher{index}.com", days_ago=index)
        for index, headline in enumerate(DISTINCT_HEADLINES[:count], start=1)
    ]


@pytest.fixture
def sources() -> List[Source]:
    now = datetime.now(timezone.utc)
    return [
        Source(
            id=f"source-{i}",
            title=f"Acme Corp headline number {i} about quarterly results",
            url=f"https://reuters.com/story-{i}",
            publisher="Reuters",
            published_at=now - timedelta(days=i),
        )
        for i in range(1, 6)
    ]


@pytest.fixture
def analysis() -> BriefAnalysis:
    return BriefAnalysis(
        target_entity=TargetEntity(
            name="Acme Corp",
            entity_type="company",
            parent_company="",
            industry="",
            entity_confidence="high",
            ambiguity_detected=False,
        ),
        source_entity_matches=[
            SourceEntityMatch(source_id=f"source-{i}", classification="target_company")
            for i in range(1, 6)
        ],
        executive_summary="Acme Corp reported stronger quarterly results and opened a new plant.",
        developments=[
            AnalysisDevelopment(
                title="Stronger quarterly results",
                date="2026-07-20",
                summary="Acme reported improved quarterly performance.",
                why_it_matters="Sets the baseline for the cost agenda discussion.",
                source_ids=["source-1", "source-2"],
            )
        ],
        risks=[
            AnalysisInsight(
                insight="Plant ramp-up may strain supply chain.",
                rationale="Coverage notes a new plant opening within the window.",
                source_ids=["source-3"],
            )
        ],
        opportunities=[
            AnalysisInsight(
                insight="Margin momentum supports a pricing review.",
                rationale="Hypothesis: improved results usually free up pricing headroom.",
                source_ids=["source-4"],
            )
        ],
        talking_points=["Results beat the prior quarter."],
        recommended_questions=["What is driving the margin improvement?"],
        confidence="high",
    )


class _FakeResponse:
    def __init__(self, parsed, text):
        self.parsed = parsed
        self.text = text


class _Recorder:
    """Captures the arguments of every generate_content call."""

    def __init__(self):
        self.calls: List[dict] = []


@pytest.fixture
def fake_gemini():
    """Replace `genai.Client` so no live Gemini request is ever made."""

    def install(monkeypatch, parsed=None, text=None, side_effect=None, side_effects=None) -> _Recorder:
        """`side_effect` raises on every call; `side_effects` raises once per
        entry and then falls through to the normal response, which is how a
        transient-then-successful upstream is simulated."""
        from google import genai

        recorder = _Recorder()
        pending = list(side_effects or [])

        async def generate_content(*, model, contents, config):
            recorder.calls.append({"model": model, "contents": contents, "config": config})
            if side_effect is not None:
                raise side_effect
            if pending:
                raise pending.pop(0)
            return _FakeResponse(parsed, text)

        class _FakeClient:
            def __init__(self, **kwargs):
                self.aio = type("Aio", (), {"models": type("Models", (), {"generate_content": staticmethod(generate_content)})()})()

        monkeypatch.setattr(genai, "Client", _FakeClient)
        return recorder

    return install
