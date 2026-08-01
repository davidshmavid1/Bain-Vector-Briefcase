"""FastAPI application entry point."""

import logging

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from .config import get_settings
from .routes import briefs

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

settings = get_settings()

app = FastAPI(
    title="Company Intelligence API",
    description="Turns recent news coverage into a client-preparation brief.",
    version="1.0.0",
)

# Explicit origin list only — no wildcard, so credentials and production
# deployments stay safe.
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origin_list,
    allow_credentials=False,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["Content-Type"],
)

app.include_router(briefs.router)


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """Log the detail server-side; never leak internals to the client."""
    logger.exception("Unhandled error on %s %s", request.method, request.url.path)
    return JSONResponse(
        status_code=500,
        content={"detail": "An unexpected server error occurred. Please try again."},
    )


@app.get("/health", tags=["system"])
async def health() -> dict:
    return {
        "status": "ok",
        "demo_mode": settings.demo_mode,
        "analysis_configured": bool(settings.gemini_api_key),
        "model": settings.gemini_model,
    }
