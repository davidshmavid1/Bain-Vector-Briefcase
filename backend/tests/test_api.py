import httpx
import pytest
import respx
from fastapi.testclient import TestClient

from app.config import Settings, get_settings
from app.main import app
from app.services.errors import AnalysisUnavailableError
from tests.conftest import make_varied_articles


@pytest.fixture
def client(settings):
    app.dependency_overrides[get_settings] = lambda: settings
    with TestClient(app, raise_server_exceptions=False) as test_client:
        yield test_client
    app.dependency_overrides.clear()


def gdelt_payload(count: int = 8) -> dict:
    return {"articles": make_varied_articles(count)}


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
        {"company": "Acme", "lookback_days": 15},
        {"company": "Acme", "lookback_days": 0},
        {"company": "Acme", "lookback_days": "thirty"},
        {"company": "Acme", "focus_areas": ["astrology"]},
    ],
)
def test_invalid_requests_return_422(client, payload):
    response = client.post("/api/v1/brief", json=payload)

    assert response.status_code == 422
    assert response.json()["detail"]


@pytest.mark.parametrize("lookback", [7, 30, 90])
@respx.mock
def test_supported_lookbacks_are_accepted(client, settings, monkeypatch, fake_gemini, analysis, lookback):
    respx.get(settings.gdelt_base_url).mock(return_value=httpx.Response(200, json=gdelt_payload()))
    fake_gemini(monkeypatch, parsed=analysis)

    response = client.post("/api/v1/brief", json={"company": "Acme Corp", "lookback_days": lookback})

    assert response.status_code == 200
    assert response.json()["lookback_days"] == lookback


def test_company_name_is_trimmed_and_focus_areas_normalized(
    client, settings, monkeypatch, fake_gemini, analysis
):
    with respx.mock:
        respx.get(settings.gdelt_base_url).mock(
            return_value=httpx.Response(200, json=gdelt_payload())
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
    respx.get(settings.gdelt_base_url).mock(return_value=httpx.Response(200, json=gdelt_payload()))
    fake_gemini(monkeypatch, parsed=analysis)

    response = client.post(
        "/api/v1/brief",
        json={"company": "Acme Corp", "lookback_days": 30, "focus_areas": ["strategy"]},
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
    respx.get(settings.gdelt_base_url).mock(return_value=httpx.Response(200, json=gdelt_payload()))
    fake_gemini(monkeypatch, parsed=hallucinated)

    body = client.post("/api/v1/brief", json={"company": "Acme Corp"}).json()

    assert body["risks"][0]["source_ids"] == ["source-2"]
    assert body["opportunities"] == []


# --- failure paths --------------------------------------------------------


@respx.mock
def test_no_articles_returns_friendly_404(client, settings):
    respx.get(settings.gdelt_base_url).mock(return_value=httpx.Response(200, json={"articles": []}))

    response = client.post("/api/v1/brief", json={"company": "Nonexistent Holdings"})

    assert response.status_code == 404
    assert "No recent news coverage" in response.json()["detail"]


@respx.mock
def test_too_few_articles_returns_friendly_404(client, settings):
    respx.get(settings.gdelt_base_url).mock(
        return_value=httpx.Response(200, json=gdelt_payload(count=2))
    )

    response = client.post("/api/v1/brief", json={"company": "Tiny Co"})

    assert response.status_code == 404


@respx.mock
def test_gdelt_failure_returns_503_without_stack_trace(client, settings):
    respx.get(settings.gdelt_base_url).mock(return_value=httpx.Response(500, text="boom"))

    response = client.post("/api/v1/brief", json={"company": "Acme Corp"})

    assert response.status_code == 503
    detail = response.json()["detail"]
    assert "Traceback" not in detail
    assert "boom" not in detail


@respx.mock
def test_gemini_failure_returns_503_without_leaking_secrets(client, settings, monkeypatch, fake_gemini):
    respx.get(settings.gdelt_base_url).mock(return_value=httpx.Response(200, json=gdelt_payload()))
    fake_gemini(monkeypatch, side_effect=RuntimeError("PERMISSION_DENIED api_key=AIzaSuperSecret"))

    response = client.post("/api/v1/brief", json={"company": "Acme Corp"})

    assert response.status_code == 503
    detail = response.json()["detail"]
    assert "AIzaSuperSecret" not in detail
    assert settings.gemini_api_key not in detail


@respx.mock
def test_failures_never_fall_back_to_demo_data(client, settings, monkeypatch, fake_gemini):
    respx.get(settings.gdelt_base_url).mock(return_value=httpx.Response(200, json=gdelt_payload()))
    fake_gemini(monkeypatch, side_effect=AnalysisUnavailableError())

    response = client.post("/api/v1/brief", json={"company": "Acme Corp"})

    assert response.status_code == 503
    assert "sources" not in response.json()


# --- demo mode ------------------------------------------------------------


def test_demo_mode_returns_labelled_sample_without_upstream_calls(settings):
    demo_settings = settings.model_copy(update={"demo_mode": True, "gemini_api_key": ""})
    app.dependency_overrides[get_settings] = lambda: demo_settings

    with respx.mock(assert_all_called=False) as mock:
        blocked = mock.get(settings.gdelt_base_url).mock(
            return_value=httpx.Response(200, json={"articles": []})
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
