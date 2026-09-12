"""Agentic-assistant service entrypoint: ingest/purge HTTP + health.

Retrieval stays inside the agent graph (tool-only, no route). The mutation
surface serves machine callers on the service token plus browser callers on
an admin assistant JWT (see agent.authz), alongside the open health probe.
"""

import logging
import sys

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

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

# Browser-direct admin flow (login, then Bearer JWT on /ingest + /sources)
# needs CORS; Bearer auth means no cookies, so no allow_credentials. Tighten
# allow_origins to the frontend domain once it is known.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health.router, tags=["health"])
app.include_router(ingest.router, tags=["ingest"])
