"""Application configuration, loaded from the environment."""

from functools import lru_cache
from typing import List, Tuple

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    gemini_api_key: str = ""
    # gemini-2.5-flash now 404s for keys that were not already using it, so the
    # default tracks a current Flash model. Pinned rather than
    # `gemini-flash-latest` so a Google-side rollout cannot change behaviour
    # underneath a running deployment.
    gemini_model: str = "gemini-3.6-flash"

    # Comma-separated list of allowed browser origins.
    allowed_origins: str = "http://localhost:3000"

    # When true the API returns a bundled, clearly labelled sample brief instead
    # of calling GDELT/Gemini. Never used as a fallback for real failures.
    demo_mode: bool = False

    gdelt_base_url: str = "https://api.gdeltproject.org/api/v2/doc/doc"
    gdelt_connect_timeout: float = 10.0
    gdelt_read_timeout: float = 30.0
    gemini_timeout_seconds: float = 90.0
    # An overloaded Gemini model returns 503 and clears on its own, so a
    # single short retry turns a visible failure into a slower success.
    gemini_retry_delays: Tuple[float, ...] = (3.0,)

    # GDELT asks for at most one request every five seconds and answers
    # throttled clients with plain text or HTTP 429, so back off before giving
    # up. A busy window can take longer than one interval to clear, hence two
    # attempts; the total added latency is bounded at ~21s.
    gdelt_retry_delays: Tuple[float, ...] = (6.0, 15.0)
    # Ceiling applied to a server-supplied `Retry-After`, so a large or
    # hostile value cannot hold a brief request open indefinitely.
    gdelt_max_retry_delay: float = 30.0
    # GDELT allows one request every five seconds per IP. The news service
    # spaces its own outbound calls to honour this rather than relying on the
    # retry to clean up a 429 we caused ourselves.
    gdelt_min_interval_seconds: float = 5.0
    # How long raw GDELT results stay reusable. Repeat or shared searches for
    # the same company and window then cost no rate-limit slot at all.
    gdelt_cache_seconds: float = 600.0

    # How many raw GDELT records to pull before ranking/deduplication
    # (250 is the API maximum).
    gdelt_max_records: int = 250
    # How many ranked sources are handed to the model.
    max_sources: int = 12
    min_sources: int = 3

    @property
    def allowed_origin_list(self) -> List[str]:
        return [origin.strip() for origin in self.allowed_origins.split(",") if origin.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
