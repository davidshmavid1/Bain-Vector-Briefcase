import pytest

from app.schemas import AnalysisDevelopment, AnalysisInsight, BriefAnalysis
from app.services import analysis_service
from app.services.errors import AnalysisConfigError, AnalysisUnavailableError


def test_prompt_contains_every_source_id_and_isolates_untrusted_text(sources):
    prompt = analysis_service.build_prompt("Acme Corp", 30, sources, ["strategy"])

    for source in sources:
        assert source.id in prompt
        assert source.url in prompt
    assert "untrusted data" in prompt
    assert "strategy" in prompt


def test_sanitize_drops_invalid_source_references(sources, analysis):
    polluted = analysis.model_copy(
        update={
            "developments": [
                analysis.developments[0].model_copy(
                    update={"source_ids": ["source-1", "source-99", ""]}
                )
            ],
            "risks": [
                # Every reference is invented -> the whole insight must be dropped.
                AnalysisInsight(
                    insight="Fabricated risk",
                    rationale="Not grounded in any real source.",
                    source_ids=["source-42", "made-up"],
                )
            ],
        }
    )

    cleaned = analysis_service.sanitize_analysis(polluted, sources)

    assert cleaned.developments[0].source_ids == ["source-1"]
    assert cleaned.risks == []


def test_sanitize_deduplicates_repeated_source_ids(sources, analysis):
    polluted = analysis.model_copy(
        update={
            "developments": [
                analysis.developments[0].model_copy(
                    update={"source_ids": ["source-1", "source-1", "source-2"]}
                )
            ]
        }
    )

    cleaned = analysis_service.sanitize_analysis(polluted, sources)

    assert cleaned.developments[0].source_ids == ["source-1", "source-2"]


def test_sanitize_downgrades_confidence_when_evidence_is_thin(sources, analysis):
    # Fewer than four surviving sources can never justify "high".
    thin = analysis_service.sanitize_analysis(analysis, sources[:2])
    assert thin.confidence == "medium"


def test_sanitize_drops_to_low_when_no_development_survives(sources, analysis):
    groundless = analysis.model_copy(
        update={
            "developments": [
                analysis.developments[0].model_copy(update={"source_ids": ["source-900"]})
            ]
        }
    )

    cleaned = analysis_service.sanitize_analysis(groundless, sources)

    assert cleaned.developments == []
    assert cleaned.confidence == "low"


def test_sanitize_keeps_confidence_when_evidence_is_broad(sources, analysis):
    assert analysis_service.sanitize_analysis(analysis, sources).confidence == "high"


def test_converters_preserve_source_ids(analysis):
    developments = analysis_service.to_developments(analysis.developments)
    risks = analysis_service.to_insights(analysis.risks)

    assert developments[0].source_ids == ["source-1", "source-2"]
    assert risks[0].source_ids == ["source-3"]


@pytest.mark.asyncio
async def test_missing_api_key_raises_config_error(settings, sources):
    unconfigured = settings.model_copy(update={"gemini_api_key": ""})

    with pytest.raises(AnalysisConfigError):
        await analysis_service.analyze("Acme Corp", 30, sources, settings=unconfigured)


@pytest.mark.asyncio
async def test_gemini_failure_is_wrapped_without_leaking_details(
    settings, sources, monkeypatch, fake_gemini
):
    fake_gemini(monkeypatch, side_effect=RuntimeError("500 INTERNAL: key=AIzaSecretValue"))

    with pytest.raises(AnalysisUnavailableError) as exc:
        await analysis_service.analyze("Acme Corp", 30, sources, settings=settings)

    assert "AIzaSecretValue" not in str(exc.value)
    assert "temporarily unavailable" in str(exc.value)


@pytest.mark.asyncio
async def test_unparseable_output_raises_analysis_unavailable(
    settings, sources, monkeypatch, fake_gemini
):
    fake_gemini(monkeypatch, parsed=None, text="not json at all")

    with pytest.raises(AnalysisUnavailableError):
        await analysis_service.analyze("Acme Corp", 30, sources, settings=settings)


@pytest.mark.asyncio
async def test_analyze_makes_exactly_one_model_call(settings, sources, monkeypatch, fake_gemini, analysis):
    recorder = fake_gemini(monkeypatch, parsed=analysis)

    result = await analysis_service.analyze("Acme Corp", 30, sources, settings=settings)

    assert len(recorder.calls) == 1
    assert isinstance(result, BriefAnalysis)
    assert result.executive_summary == analysis.executive_summary


@pytest.mark.asyncio
async def test_analyze_falls_back_to_json_text(settings, sources, monkeypatch, fake_gemini, analysis):
    fake_gemini(monkeypatch, parsed=None, text=analysis.model_dump_json())

    result = await analysis_service.analyze("Acme Corp", 30, sources, settings=settings)

    assert result.developments[0].title == "Stronger quarterly results"


@pytest.mark.asyncio
async def test_analyze_sanitizes_model_output(settings, sources, monkeypatch, fake_gemini, analysis):
    hallucinated = analysis.model_copy(
        update={
            "opportunities": [
                AnalysisInsight(
                    insight="Invented opportunity",
                    rationale="Cites a source that was never retrieved.",
                    source_ids=["source-999"],
                )
            ],
            "developments": [
                AnalysisDevelopment(
                    title="Real development",
                    date="2026-07-01",
                    summary="Grounded in retrieved coverage.",
                    why_it_matters="Relevant to the client agenda.",
                    source_ids=["source-2", "source-500"],
                )
            ],
        }
    )
    fake_gemini(monkeypatch, parsed=hallucinated)

    result = await analysis_service.analyze("Acme Corp", 30, sources, settings=settings)

    assert result.opportunities == []
    assert result.developments[0].source_ids == ["source-2"]


# --- transient-failure retry ----------------------------------------------


class _ApiError(Exception):
    """Stands in for google.genai.errors.APIError, which carries `.code`."""

    def __init__(self, code: int, message: str = "upstream error"):
        super().__init__(message)
        self.code = code


@pytest.mark.parametrize("code", [429, 500, 502, 503, 504])
def test_transient_statuses_are_retryable(code):
    assert analysis_service._is_transient(_ApiError(code))


@pytest.mark.parametrize("code", [400, 401, 403, 404])
def test_client_errors_are_not_retryable(code):
    assert not analysis_service._is_transient(_ApiError(code))


def test_timeouts_are_retryable():
    import httpx

    assert analysis_service._is_transient(httpx.ConnectTimeout("slow"))
    assert not analysis_service._is_transient(ValueError("nope"))


@pytest.mark.asyncio
async def test_overloaded_model_is_retried_then_succeeds(
    settings, sources, monkeypatch, fake_gemini, analysis
):
    monkeypatch.setattr(analysis_service.asyncio, "sleep", _no_sleep)
    recorder = fake_gemini(monkeypatch, parsed=analysis, side_effects=[_ApiError(503, "overloaded")])

    result = await analysis_service.analyze("Acme Corp", 30, sources, settings=settings)

    assert len(recorder.calls) == 2
    assert result.executive_summary == analysis.executive_summary


@pytest.mark.asyncio
async def test_persistent_overload_fails_cleanly(settings, sources, monkeypatch, fake_gemini):
    monkeypatch.setattr(analysis_service.asyncio, "sleep", _no_sleep)
    recorder = fake_gemini(monkeypatch, side_effect=_ApiError(503, "overloaded"))

    with pytest.raises(AnalysisUnavailableError) as exc:
        await analysis_service.analyze("Acme Corp", 30, sources, settings=settings)

    assert len(recorder.calls) == 2  # one attempt + one retry
    assert "overloaded" not in str(exc.value)


@pytest.mark.asyncio
async def test_bad_request_is_not_retried(settings, sources, monkeypatch, fake_gemini):
    monkeypatch.setattr(analysis_service.asyncio, "sleep", _no_sleep)
    recorder = fake_gemini(monkeypatch, side_effect=_ApiError(400, "bad model id"))

    with pytest.raises(AnalysisUnavailableError):
        await analysis_service.analyze("Acme Corp", 30, sources, settings=settings)

    assert len(recorder.calls) == 1


async def _no_sleep(_seconds):
    return None
