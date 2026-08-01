"""Brief generation endpoint. Kept thin: validate, retrieve, analyse, return."""

import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException

from ..config import Settings, get_settings
from ..schemas import BriefRequest, CompanyBrief, ErrorResponse
from ..services import analysis_service, news_service
from ..services.demo_data import build_demo_brief
from ..services.errors import BriefError, NoArticlesFoundError

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1", tags=["briefs"])


@router.post(
    "/brief",
    response_model=CompanyBrief,
    responses={
        404: {"model": ErrorResponse},
        503: {"model": ErrorResponse},
    },
)
async def create_brief(
    request: BriefRequest,
    settings: Settings = Depends(get_settings),
) -> CompanyBrief:
    if settings.demo_mode:
        return build_demo_brief(request.company, request.lookback_days)

    try:
        sources = await news_service.collect_sources(
            company=request.company,
            lookback_days=request.lookback_days,
            focus_areas=request.focus_areas,
            settings=settings,
        )
        if len(sources) < settings.min_sources:
            raise NoArticlesFoundError()

        analysis = await analysis_service.analyze(
            company=request.company,
            lookback_days=request.lookback_days,
            sources=sources,
            focus_areas=request.focus_areas,
            settings=settings,
        )
    except BriefError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc

    return CompanyBrief(
        company=request.company,
        generated_at=datetime.now(timezone.utc),
        executive_summary=analysis.executive_summary,
        developments=analysis_service.to_developments(analysis.developments),
        risks=analysis_service.to_insights(analysis.risks),
        opportunities=analysis_service.to_insights(analysis.opportunities),
        talking_points=analysis.talking_points,
        recommended_questions=analysis.recommended_questions,
        sources=sources,
        confidence=analysis.confidence,
        lookback_days=request.lookback_days,
        is_demo=False,
    )
