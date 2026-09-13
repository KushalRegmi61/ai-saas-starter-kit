"""Health probe: no dependencies, no auth (deploy healthcheck target)."""

import logging

from fastapi import APIRouter

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/health")
def health() -> dict[str, str]:
    logger.debug("health: probe ok")
    return {"status": "ok", "service": "agentic-assistant"}
