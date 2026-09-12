"""Health probe: no dependencies, no auth (deploy healthcheck target)."""

from fastapi import APIRouter

router = APIRouter()


@router.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "service": "agentic-assistant"}
