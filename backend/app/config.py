"""Application configuration, loaded from the environment."""

from functools import lru_cache
from typing import List, Literal, Optional, Tuple

from pydantic_settings import BaseSettings, SettingsConfigDict

SearchDepth = Literal["basic", "advanced", "fast", "ultra-fast"]


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

    # Optional regex for origins that cannot be listed literally. Vercel preview
    # URLs change on every deploy, and their branch aliases are truncated and
    # hashed once the hostname would exceed the 63-character DNS label limit, so
    # there is no stable string to allowlist.
    #
    # Empty means "no regex" — see allowed_origin_pattern. Never set this to a
    # bare ".*"; scope it to hosts you control, e.g.
    #   ^https://[a-z0-9-]+-yourteam-projects\.vercel\.app$
    allowed_origin_regex: str = ""

    # When true the API returns a bundled, clearly labelled sample brief instead
    # of calling Tavily/Gemini. Never used as a fallback for real failures.
    demo_mode: bool = False

    gemini_timeout_seconds: float = 90.0
    # An overloaded Gemini model returns 503 and clears on its own, so a
    # single short retry turns a visible failure into a slower success.
    gemini_retry_delays: Tuple[float, ...] = (3.0,)

    # --- Tavily news retrieval -------------------------------------------
    # Quota is bound to the key rather than to the caller's IP, which is what
    # makes multi-user testing and a shared-IP deployment viable at all.
    tavily_api_key: str = ""
    tavily_base_url: str = "https://api.tavily.com/search"
    # `basic` costs 1 credit per search, `advanced` costs 2. The free tier is
    # 1,000 credits a month, so the default keeps the full search budget.
    tavily_search_depth: SearchDepth = "basic"
    # 20 is the API maximum. Over-fetching is free — the cost is per search,
    # not per result — and gives deduplication and ranking more to work with.
    tavily_max_results: int = 20
    tavily_connect_timeout: float = 10.0
    tavily_read_timeout: float = 30.0

    # Tavily allows 100 requests/minute on the free tier. Spacing outbound
    # calls slightly keeps a burst of concurrent searches inside that ceiling
    # rather than relying on the retry to clean up a 429 we caused ourselves.
    tavily_min_interval_seconds: float = 0.6
    # A 429 is transient and clears quickly; one retry is enough.
    tavily_retry_delays: Tuple[float, ...] = (2.0,)
    # Ceiling applied to a server-supplied `Retry-After`, so a large or
    # hostile value cannot hold a brief request open indefinitely.
    tavily_max_retry_delay: float = 30.0
    # How long raw results stay reusable. Every cache hit is a credit saved,
    # which matters more than the rate-limit slot it also saves.
    tavily_cache_seconds: float = 600.0

    # How many ranked sources are handed to the model.
    max_sources: int = 12
    min_sources: int = 3

    @property
    def allowed_origin_list(self) -> List[str]:
        return [origin.strip() for origin in self.allowed_origins.split(",") if origin.strip()]

    @property
    def allowed_origin_pattern(self) -> Optional[str]:
        """The regex to hand to CORSMiddleware, or None when unset.

        Current Starlette matches with `fullmatch`, so an empty pattern would
        match only an empty origin — not every origin. The conversion to None is
        kept regardless: it states the intent ("no regex configured") rather
        than relying on that matching semantic, which older Starlette versions
        did not share — they used `match`, where an empty pattern is a prefix
        that matches anything.
        """
        return self.allowed_origin_regex.strip() or None


@lru_cache
def get_settings() -> Settings:
    return Settings()
