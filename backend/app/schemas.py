"""Pydantic models for the public API and for Gemini structured output."""

from datetime import datetime
from typing import List, Literal, Optional

from pydantic import BaseModel, Field, field_validator

# Matches Tavily's own `time_range` parameter values exactly (minus "day",
# which is too narrow a window for this product) — sent straight through to
# the search request rather than translated via computed start/end dates.
TimeRange = Literal["week", "month", "year"]
Confidence = Literal["low", "medium", "high"]

ALLOWED_FOCUS_AREAS = [
    "technology",
    "operations",
    "strategy",
    "finance",
    "people",
    "regulatory",
    "sustainability",
]


class BriefRequest(BaseModel):
    company: str = Field(..., min_length=2, max_length=120)
    time_range: TimeRange = "month"
    focus_areas: Optional[List[str]] = Field(default=None, max_length=len(ALLOWED_FOCUS_AREAS))

    @field_validator("company")
    @classmethod
    def clean_company(cls, value: str) -> str:
        cleaned = " ".join(value.split())
        if len(cleaned) < 2:
            raise ValueError("Company name must contain at least 2 characters.")
        return cleaned

    @field_validator("focus_areas")
    @classmethod
    def clean_focus_areas(cls, value: Optional[List[str]]) -> Optional[List[str]]:
        if value is None:
            return None
        seen: List[str] = []
        for raw in value:
            area = raw.strip().lower()
            if area not in ALLOWED_FOCUS_AREAS:
                raise ValueError(
                    f"Unsupported focus area '{raw}'. Allowed: {', '.join(ALLOWED_FOCUS_AREAS)}."
                )
            if area not in seen:
                seen.append(area)
        return seen or None


class Source(BaseModel):
    id: str
    title: str
    url: str
    publisher: str
    published_at: Optional[datetime] = None
    # GDELT's article list does not return an abstract, so this stays optional
    # rather than being fabricated downstream.
    snippet: Optional[str] = None


class Development(BaseModel):
    title: str
    date: Optional[str] = None
    summary: str
    why_it_matters: str
    source_ids: List[str] = Field(default_factory=list)


class Insight(BaseModel):
    insight: str
    rationale: str
    source_ids: List[str] = Field(default_factory=list)


class CompanyBrief(BaseModel):
    company: str
    generated_at: datetime
    executive_summary: str
    developments: List[Development] = Field(default_factory=list)
    risks: List[Insight] = Field(default_factory=list)
    opportunities: List[Insight] = Field(default_factory=list)
    talking_points: List[str] = Field(default_factory=list)
    recommended_questions: List[str] = Field(default_factory=list)
    sources: List[Source] = Field(default_factory=list)
    confidence: Confidence = "low"
    time_range: TimeRange = "month"
    is_demo: bool = False


# --- Gemini structured-output models -------------------------------------
# Kept flat and fully required: the structured-output schema converter is
# happier without optional/defaulted fields, and the API layer re-validates.


class AnalysisDevelopment(BaseModel):
    title: str
    date: str
    summary: str
    why_it_matters: str
    source_ids: List[str]


class AnalysisInsight(BaseModel):
    insight: str
    rationale: str
    source_ids: List[str]


class BriefAnalysis(BaseModel):
    executive_summary: str
    developments: List[AnalysisDevelopment]
    risks: List[AnalysisInsight]
    opportunities: List[AnalysisInsight]
    talking_points: List[str]
    recommended_questions: List[str]
    confidence: Confidence


class ErrorResponse(BaseModel):
    detail: str
