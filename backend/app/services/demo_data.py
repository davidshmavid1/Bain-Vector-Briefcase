"""Bundled sample brief for DEMO_MODE=true.

Used only when DEMO_MODE is explicitly enabled, so the UI can be developed
without repeatedly calling GDELT and Gemini. It is never a fallback for a
failed live request.
"""

from datetime import datetime, timedelta, timezone

from ..schemas import CompanyBrief, Development, Insight, Source

DEMO_NOTICE = "SAMPLE BRIEF (demo mode) — illustrative content, not live news coverage."


def build_demo_brief(company: str, time_range: str) -> CompanyBrief:
    now = datetime.now(timezone.utc)
    sources = [
        Source(
            id="source-1",
            title=f"{company} expands data-centre capacity to meet AI demand",
            url="https://example.com/demo/capacity",
            publisher="Example Business Daily",
            published_at=now - timedelta(days=2),
            snippet=None,
        ),
        Source(
            id="source-2",
            title=f"{company} names new chief operating officer",
            url="https://example.com/demo/coo",
            publisher="Example Wire",
            published_at=now - timedelta(days=6),
            snippet=None,
        ),
        Source(
            id="source-3",
            title=f"Regulators open review of {company}'s latest acquisition",
            url="https://example.com/demo/review",
            publisher="Example Regulatory Review",
            published_at=now - timedelta(days=11),
            snippet=None,
        ),
    ]

    return CompanyBrief(
        company=company,
        generated_at=now,
        executive_summary=(
            f"{DEMO_NOTICE} Over the sample window, {company} is shown scaling infrastructure "
            "ahead of demand while absorbing a leadership change and a regulatory review of a "
            "recent acquisition. Enable a live GEMINI_API_KEY to generate a real brief."
        ),
        developments=[
            Development(
                title="Capacity expansion announced",
                date=(now - timedelta(days=2)).date().isoformat(),
                summary=f"{company} announced additional data-centre capacity.",
                why_it_matters="Signals confidence in sustained demand and a step-up in capital intensity.",
                source_ids=["source-1"],
            ),
            Development(
                title="New chief operating officer appointed",
                date=(now - timedelta(days=6)).date().isoformat(),
                summary=f"{company} appointed a new COO.",
                why_it_matters="An operating-leadership change often precedes a cost or delivery agenda.",
                source_ids=["source-2"],
            ),
        ],
        risks=[
            Insight(
                insight="Regulatory review could delay integration of the acquisition.",
                rationale="Coverage reports an open regulator review of the transaction.",
                source_ids=["source-3"],
            )
        ],
        opportunities=[
            Insight(
                insight="Capacity build-out creates an opening for cost-to-serve work.",
                rationale="Hypothesis: rapid infrastructure expansion typically outpaces unit-economics discipline.",
                source_ids=["source-1"],
            )
        ],
        talking_points=[
            "Capacity is being added ahead of demand — the question is payback, not ambition.",
            "A new COO in seat is the natural owner of an operating-model agenda.",
        ],
        recommended_questions=[
            "How are you underwriting returns on the new capacity, and over what horizon?",
            "What does the new COO want to have changed twelve months from now?",
            "What is your contingency if the regulatory review runs past this fiscal year?",
        ],
        sources=sources,
        confidence="low",
        time_range=time_range,
        is_demo=True,
    )
