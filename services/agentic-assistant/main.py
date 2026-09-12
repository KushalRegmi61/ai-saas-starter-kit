"""Agentic-assistant service entrypoint: ingest/purge HTTP + health.

Retrieval stays inside the agent graph (tool-only, no route). The mutation
surface serves machine callers on the service token plus browser callers on
an admin assistant JWT (see agent.authz), alongside the open health probe.
"""

import logging
import sys
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from agent.config import get_agent_settings
from api import auth, health, ingest
from models.users import ensure_and_seed, get_pool

logging.basicConfig(level=logging.INFO, stream=sys.stderr)
logger = logging.getLogger("agentic-assistant")

settings = get_agent_settings()
if not settings.agent_service_token:
    logger.warning(
        "AGENTIC_ASSISTANT_SERVICE_TOKEN is empty: /ingest and /sources answer "
        "503 until it is set. Never expose this service publicly without it."
    )


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_agent_settings()
    pool = None
    if settings.agentic_assistant_database_url:
        pool = get_pool(settings.agentic_assistant_database_url)
        try:
            with pool.connection() as connection:
                ensure_and_seed(
                    connection,
                    settings.agentic_assistant_admin_email,
                    settings.agentic_assistant_admin_password,
                )
            if settings.agentic_assistant_admin_email:
                logger.info(
                    "Assistant admin bootstrap checked for email=%s",
                    settings.agentic_assistant_admin_email.strip().lower(),
                )
            else:
                logger.warning(
                    "AGENTIC_ASSISTANT_ADMIN_EMAIL and "
                    "AGENTIC_ASSISTANT_ADMIN_PASSWORD are empty: "
                    "an admin must already exist in assistant_users"
                )
            app.state.assistant_user_pool = pool
            yield
        finally:
            pool.close()
            app.state.assistant_user_pool = None
    else:
        app.state.assistant_user_pool = None
        yield


app = FastAPI(
    title="Agentic Assistant",
    description="Knowledge-assistant backend: RAG ingestion service + agent engine",
    version="0.1.0",
    lifespan=lifespan,
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
app.include_router(auth.router, tags=["auth"])
