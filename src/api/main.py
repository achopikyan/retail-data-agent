"""FastAPI app for the Retail Data Analysis agent.

Run locally:
    uvicorn src.api.main:app --reload --port 8000

OpenAPI docs: http://localhost:8000/docs
"""
from __future__ import annotations

import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from src.api.routes import audit, chat, feedback, personas, prefs, reports, sessions, threads
from src.obs.log import setup_logging

setup_logging(logging.INFO)


app = FastAPI(
    title="Retail Data Analysis Agent",
    description=(
        "REST + SSE API in front of the LangGraph chat agent that answers "
        "natural-language questions about the BigQuery thelook_ecommerce "
        "dataset. Mirrors every CLI capability."
    ),
    version="0.1.0",
)

# CORS — open in dev. In production this should be restricted to your domain.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["*"],
)


@app.get("/healthz")
def healthz() -> dict:
    return {"status": "ok"}


# Routes
app.include_router(chat.router)
app.include_router(reports.router)
app.include_router(audit.router)
app.include_router(feedback.router)
app.include_router(prefs.router)
app.include_router(personas.router)
app.include_router(sessions.router)
app.include_router(threads.router)
