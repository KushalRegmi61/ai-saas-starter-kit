"""Agentic-assistant service entrypoint: ingestion, auth, and chat.

Retrieval stays inside the agent graph (tool-only, no route). The mutation
surface serves machine callers on the service token plus browser callers on
an admin assistant JWT (see agent.authz), alongside the open health probe.
"""

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from agent.config import get_agent_settings
from agent.logging_config import configure_logging
from api import auth, chat, health, ingest
from models.conversations import ensure_conversation_tables
from models.users import ensure_and_seed, get_pool

logger = configure_logging()

settings = get_agent_settings()
if not settings.agent_service_token:
    logger.warning(
        "AGENTIC_ASSISTANT_SERVICE_TOKEN is empty: /ingest and /sources answer "
        "503 until it is set. Never expose this service publicly without it."
    )


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("agentic-assistant starting: lifespan enter")
    settings = get_agent_settings()
    pool = None
    if settings.agentic_assistant_database_url:
        logger.info("lifespan: database configured, opening pool")
        pool = get_pool(settings.agentic_assistant_database_url)
        try:
            with pool.connection() as connection:
                logger.info("lifespan: ensuring tables + admin seed")
                ensure_and_seed(
                    connection,
                    settings.agentic_assistant_admin_email,
                    settings.agentic_assistant_admin_password,
                )
                ensure_conversation_tables(connection)
                logger.info("lifespan: tables ready")
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
            logger.info("lifespan: pool ready, serving")
            yield
        finally:
            logger.info("lifespan: closing pool")
            pool.close()
            app.state.assistant_user_pool = None
            logger.info("lifespan: pool closed")
    else:
        logger.warning("lifespan: no database URL, running without auth store")
        app.state.assistant_user_pool = None
        yield
    logger.info("agentic-assistant stopping: lifespan exit")


app = FastAPI(
    title="Agentic Assistant",
    description="Knowledge-assistant backend: RAG ingestion service + agent engine",
    version="0.1.0",
    lifespan=lifespan,
)

# Browser-direct admin flow (login, then Bearer JWT on /ingest + /sources)
# needs CORS; Bearer auth means no cookies, so no allow_credentials.
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_allowed_origins,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health.router, tags=["health"])
app.include_router(ingest.router, tags=["ingest"])
app.include_router(auth.router, tags=["auth"])
app.include_router(chat.router, tags=["chat"])
