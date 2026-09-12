"""Agentic-assistant service entrypoint: ingest/purge HTTP + health.

Retrieval stays inside the agent graph (tool-only, no route) and user auth
arrives with the auth session — this app serves machine callers on the
service token plus the open health probe.
"""

import logging
import sys

from fastapi import FastAPI

from agent.config import get_agent_settings
from agent.runtime import health, ingest

logging.basicConfig(level=logging.INFO, stream=sys.stderr)
logger = logging.getLogger("agentic-assistant")

settings = get_agent_settings()
if not settings.agent_service_token:
    logger.warning(
        "AGENT_SERVICE_TOKEN is empty: /ingest and /sources answer "
        "503 until it is set. Never expose this service publicly without it."
    )

app = FastAPI(
    title="Agentic Assistant",
    description="Knowledge-assistant backend: RAG ingestion service + agent engine",
    version="0.1.0",
)

app.include_router(health.router, tags=["health"])
app.include_router(ingest.router, tags=["ingest"])
