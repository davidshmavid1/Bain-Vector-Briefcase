import httpx
import pytest
import respx
from fastapi.testclient import TestClient

from app.config import Settings, get_settings
from app.main import app
from app.services.errors import AnalysisUnavailableError
from tests.conftest import tavily_payload


@pytest.fixture
def client(settings):
    app.dependency_overrides[get_settings] = lambda: settings
    with TestClient(app, raise_server_exceptions=False) as test_client:
        yield test_client
    app.dependency_overrides.clear()


TAVILY_URL = "https://api.tavily.com/search"


def news_payload(count: int = 8) -> dict:
    return tavily_payload(count)


def test_health_reports_status(client):
    response = client.get("/health")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["demo_mode"] is False
    assert "gemini_api_key" not in body


# --- request validation ---------------------------------------------------


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"company": ""},
        {"company": "A"},
        {"company": "x" * 200},
        {"company": "Acme", "time_range": "day"},  # deliberately excluded, too narrow
        {"company": "Acme", "time_range": "decade"},
        {"company": "Acme", "time_range": 30},
        {"company": "Acme", "focus_areas": ["astrology"]},
    ],
)
def test_invalid_requests_return_422(client, payload):
    response = client.post("/api/v1/brief", json=payload)

    assert response.status_code == 422
    assert response.json()["detail"]


@pytest.mark.parametrize("time_range", ["week", "month", "year"])
@respx.mock
def test_supported_time_ranges_are_accepted(client, settings, monkeypatch, fake_gemini, analysis, time_range):
    respx.post(TAVILY_URL).mock(return_value=httpx.Response(200, json=news_payload()))
    fake_gemini(monkeypatch, parsed=analysis)

    response = client.post("/api/v1/brief", json={"company": "Acme Corp", "time_range": time_range})

    assert response.status_code == 200
    assert response.json()["time_range"] == time_range


def test_company_name_is_trimmed_and_focus_areas_normalized(
    client, settings, monkeypatch, fake_gemini, analysis
):
    with respx.mock:
        respx.post(TAVILY_URL).mock(
            return_value=httpx.Response(200, json=news_payload())
        )
        fake_gemini(monkeypatch, parsed=analysis)

        response = client.post(
            "/api/v1/brief",
            json={"company": "  Acme   Corp  ", "focus_areas": ["Strategy", "strategy", "FINANCE"]},
        )

    assert response.status_code == 200
    assert response.json()["company"] == "Acme Corp"


# --- happy path -----------------------------------------------------------


@respx.mock
def test_successful_brief_response(client, settings, monkeypatch, fake_gemini, analysis):
    respx.post(TAVILY_URL).mock(return_value=httpx.Response(200, json=news_payload()))
    fake_gemini(monkeypatch, parsed=analysis)

    response = client.post(
        "/api/v1/brief",
        json={"company": "Acme Corp", "time_range": "month", "focus_areas": ["strategy"]},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["company"] == "Acme Corp"
    assert body["generated_at"]
    assert body["executive_summary"]
    assert body["confidence"] in {"low", "medium", "high"}
    assert body["is_demo"] is False

    source_ids = {source["id"] for source in body["sources"]}
    assert len(source_ids) == 8
    for section in ("developments", "risks", "opportunities"):
        for item in body[section]:
            assert item["source_ids"]
            assert set(item["source_ids"]) <= source_ids

    # Source URLs survive the whole pipeline.
    assert all(source["url"].startswith("https://") for source in body["sources"])


@respx.mock
def test_invalid_source_references_are_stripped_from_the_response(
    client, settings, monkeypatch, fake_gemini, analysis
):
    hallucinated = analysis.model_copy(
        update={
            "risks": [
                analysis.risks[0].model_copy(update={"source_ids": ["source-77", "source-2"]})
            ],
            "opportunities": [
                analysis.opportunities[0].model_copy(update={"source_ids": ["source-404"]})
            ],
        }
    )
    respx.post(TAVILY_URL).mock(return_value=httpx.Response(200, json=news_payload()))
    fake_gemini(monkeypatch, parsed=hallucinated)

    body = client.post("/api/v1/brief", json={"company": "Acme Corp"}).json()

    assert body["risks"][0]["source_ids"] == ["source-2"]
    assert body["opportunities"] == []


# --- failure paths --------------------------------------------------------


@respx.mock
def test_no_articles_returns_friendly_404(client, settings):
    respx.post(TAVILY_URL).mock(return_value=httpx.Response(200, json={"results": []}))

    response = client.post("/api/v1/brief", json={"company": "Nonexistent Holdings"})

    assert response.status_code == 404
    assert "No recent news coverage" in response.json()["detail"]


@respx.mock
def test_too_few_articles_returns_friendly_404(client, settings):
    respx.post(TAVILY_URL).mock(
        return_value=httpx.Response(200, json=news_payload(count=2))
    )

    response = client.post("/api/v1/brief", json={"company": "Tiny Co"})

    assert response.status_code == 404


@respx.mock
def test_news_failure_returns_503_without_stack_trace(client, settings):
    respx.post(TAVILY_URL).mock(return_value=httpx.Response(500, json={"error": "boom"}))

    response = client.post("/api/v1/brief", json={"company": "Acme Corp"})

    assert response.status_code == 503
    detail = response.json()["detail"]
    assert "Traceback" not in detail
    assert "boom" not in detail


@respx.mock
def test_gemini_failure_returns_503_without_leaking_secrets(client, settings, monkeypatch, fake_gemini):
    respx.post(TAVILY_URL).mock(return_value=httpx.Response(200, json=news_payload()))
    fake_gemini(monkeypatch, side_effect=RuntimeError("PERMISSION_DENIED api_key=AIzaSuperSecret"))

    response = client.post("/api/v1/brief", json={"company": "Acme Corp"})

    assert response.status_code == 503
    detail = response.json()["detail"]
    assert "AIzaSuperSecret" not in detail
    assert settings.gemini_api_key not in detail


@respx.mock
def test_failures_never_fall_back_to_demo_data(client, settings, monkeypatch, fake_gemini):
    respx.post(TAVILY_URL).mock(return_value=httpx.Response(200, json=news_payload()))
    fake_gemini(monkeypatch, side_effect=AnalysisUnavailableError())

    response = client.post("/api/v1/brief", json={"company": "Acme Corp"})

    assert response.status_code == 503
    assert "sources" not in response.json()


# --- demo mode ------------------------------------------------------------


def test_demo_mode_returns_labelled_sample_without_upstream_calls(settings):
    demo_settings = settings.model_copy(update={"demo_mode": True, "gemini_api_key": ""})
    app.dependency_overrides[get_settings] = lambda: demo_settings

    with respx.mock(assert_all_called=False) as mock:
        blocked = mock.post(TAVILY_URL).mock(
            return_value=httpx.Response(200, json={"results": []})
        )
        with TestClient(app) as demo_client:
            response = demo_client.post("/api/v1/brief", json={"company": "Acme Corp"})

    app.dependency_overrides.clear()

    assert response.status_code == 200
    body = response.json()
    assert body["is_demo"] is True
    assert "SAMPLE BRIEF" in body["executive_summary"]
    assert not blocked.called


def test_settings_parse_multiple_allowed_origins():
    parsed = Settings(allowed_origins="http://localhost:3000, https://app.example.com ")

    assert parsed.allowed_origin_list == ["http://localhost:3000", "https://app.example.com"]


def test_cors_is_not_wildcarded():
    assert "*" not in get_settings().allowed_origin_list


# --- CORS ------------------------------------------------------------------

PREVIEW_REGEX = r"^https://[a-z0-9-]+-davidshmavid1s-projects\.vercel\.app$"
LISTED_ORIGIN = "http://localhost:3000"
# Truncated-and-hashed Vercel branch alias: impossible to allowlist literally.
PREVIEW_ORIGIN = "https://bain-vector-briefcase-inqq-git-b-7c4d7c-davidshmavid1s-projects.vercel.app"


def preflight(test_client, origin: str):
    return test_client.options(
        "/api/v1/brief",
        headers={
            "Origin": origin,
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "content-type",
        },
    )


def allowed_origin_header(settings, origin: str, **overrides):
    """Drive the real middleware and return the granted origin, if any.

    The middleware is constructed from module-level settings at import time, so
    a fresh app is built per case rather than overriding the dependency.
    """
    from fastapi import FastAPI
    from fastapi.middleware.cors import CORSMiddleware

    configured = settings.model_copy(update=overrides)
    probe = FastAPI()
    probe.add_middleware(
        CORSMiddleware,
        allow_origins=configured.allowed_origin_list,
        allow_origin_regex=configured.allowed_origin_pattern,
        allow_credentials=False,
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["Content-Type"],
    )

    @probe.post("/api/v1/brief")
    async def _stub() -> dict:  # pragma: no cover - never invoked by a preflight
        return {}

    with TestClient(probe) as client:
        response = preflight(client, origin)
    return response.headers.get("access-control-allow-origin")


def test_origin_in_the_explicit_list_is_allowed(settings):
    granted = allowed_origin_header(settings, LISTED_ORIGIN, allowed_origins=LISTED_ORIGIN)

    assert granted == LISTED_ORIGIN


def test_preview_origin_is_allowed_by_regex(settings):
    granted = allowed_origin_header(
        settings, PREVIEW_ORIGIN, allowed_origins=LISTED_ORIGIN, allowed_origin_regex=PREVIEW_REGEX
    )

    assert granted == PREVIEW_ORIGIN


def test_explicit_list_still_works_when_a_regex_is_set(settings):
    granted = allowed_origin_header(
        settings, LISTED_ORIGIN, allowed_origins=LISTED_ORIGIN, allowed_origin_regex=PREVIEW_REGEX
    )

    assert granted == LISTED_ORIGIN


def test_unrelated_origin_is_rejected(settings):
    granted = allowed_origin_header(
        settings, "https://evil.com", allowed_origins=LISTED_ORIGIN, allowed_origin_regex=PREVIEW_REGEX
    )

    assert granted is None


def test_another_vercel_account_is_rejected(settings):
    # Same platform, different team: must not match.
    granted = allowed_origin_header(
        settings,
        "https://something-someoneelses-projects.vercel.app",
        allowed_origins=LISTED_ORIGIN,
        allowed_origin_regex=PREVIEW_REGEX,
    )

    assert granted is None


def test_suffix_lookalike_is_rejected(settings):
    # Passes a naive "endswith"/search check; fullmatch anchoring must reject it.
    granted = allowed_origin_header(
        settings,
        "https://x-davidshmavid1s-projects.vercel.app.evil.com",
        allowed_origins=LISTED_ORIGIN,
        allowed_origin_regex=PREVIEW_REGEX,
    )

    assert granted is None


def test_subdomain_cannot_widen_the_pattern(settings):
    # [a-z0-9-]+ excludes dots, so an extra label must not match.
    granted = allowed_origin_header(
        settings,
        "https://evil.attacker-davidshmavid1s-projects.vercel.app",
        allowed_origins=LISTED_ORIGIN,
        allowed_origin_regex=PREVIEW_REGEX,
    )

    assert granted is None


def test_empty_regex_does_not_widen_the_allowlist(settings):
    """An unset regex must leave the explicit list as the only gate."""
    granted = allowed_origin_header(
        settings, "https://evil.com", allowed_origins=LISTED_ORIGIN, allowed_origin_regex=""
    )

    assert granted is None


@pytest.mark.parametrize("raw", ["", "   ", "\n"])
def test_blank_regex_yields_no_pattern(settings, raw):
    assert settings.model_copy(update={"allowed_origin_regex": raw}).allowed_origin_pattern is None


def test_configured_regex_is_passed_through(settings):
    configured = settings.model_copy(update={"allowed_origin_regex": PREVIEW_REGEX})

    assert configured.allowed_origin_pattern == PREVIEW_REGEX


def test_the_app_wires_the_regex_into_cors_middleware():
    """Guards the wiring in main.py, not just the property.

    allowed_origin_pattern could be correct while main.py still passed the raw
    string; this reads back what the running app actually configured.
    """
    from fastapi.middleware.cors import CORSMiddleware

    cors = [m for m in app.user_middleware if m.cls is CORSMiddleware]
    assert len(cors) == 1

    configured = cors[0].kwargs
    assert "allow_origin_regex" in configured, "main.py must pass allow_origin_regex"
    # Unset here, and None rather than "" — see Settings.allowed_origin_pattern
    # for why the distinction is kept even though fullmatch makes "" harmless.
    assert configured["allow_origin_regex"] is None
    assert "*" not in configured["allow_origins"]
