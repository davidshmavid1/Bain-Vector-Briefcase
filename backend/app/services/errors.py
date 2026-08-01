"""Domain errors that the API layer maps to clean HTTP responses.

Messages here are user-facing: they must never carry upstream payloads,
stack traces, URLs with credentials, or API keys.
"""


class BriefError(Exception):
    """Base class for expected, user-presentable failures."""

    status_code = 502
    message = "Something went wrong while preparing the brief."

    def __init__(self, message: str = ""):
        super().__init__(message or self.message)
        self.message = message or self.message


class NewsUnavailableError(BriefError):
    status_code = 503
    message = "The news service is temporarily unavailable. Please try again in a moment."


class NoArticlesFoundError(BriefError):
    status_code = 404
    message = (
        "No recent news coverage was found for that company. "
        "Try a longer timeframe or check the spelling of the company name."
    )


class AnalysisUnavailableError(BriefError):
    status_code = 503
    message = "The analysis service is temporarily unavailable. Please try again in a moment."


class AnalysisConfigError(BriefError):
    status_code = 503
    message = "The analysis service is not configured. Set GEMINI_API_KEY on the server."
