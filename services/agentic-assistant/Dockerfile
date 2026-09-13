# Build from the repository root:
#   docker build -f services/agentic-assistant/Dockerfile -t ai-saas-agent .
#
# The root context is intentional. This service depends on the workspace
# packages in libs/rag, libs/auth, and services/shared.
FROM ghcr.io/astral-sh/uv:0.10.7 AS uv
FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_NO_DEV=1 \
    PATH="/app/.venv/bin:$PATH"

WORKDIR /app

COPY --from=uv /uv /uvx /bin/

# Copy only dependency metadata first so Docker can cache dependency
# resolution while application source changes.
COPY pyproject.toml uv.lock ./
COPY libs/auth/pyproject.toml libs/auth/pyproject.toml
COPY libs/rag/pyproject.toml libs/rag/pyproject.toml
COPY services/shared/pyproject.toml services/shared/pyproject.toml
COPY services/agentic-assistant/pyproject.toml services/agentic-assistant/pyproject.toml

# Install third-party dependencies without trying to build the editable
# workspace packages before their source trees have been copied.
RUN uv sync --frozen --no-dev --package ai-saas-agentic-assistant \
    --no-install-workspace --no-install-project

# Workspace packages are installed as editable packages by uv, so their source
# trees must remain at these paths in the final image.
COPY libs/auth/src libs/auth/src
COPY libs/rag/src libs/rag/src
COPY services/shared/src services/shared/src
COPY services/agentic-assistant/src services/agentic-assistant/src
COPY services/agentic-assistant/main.py services/agentic-assistant/main.py

RUN uv sync --frozen --no-dev --package ai-saas-agentic-assistant

# Keep the runtime user unprivileged. The service does not need a writable
# application directory; temporary files should use /tmp.
RUN useradd --create-home --uid 10001 appuser \
    && chown -R appuser:appuser /app
USER appuser

ENV PYTHONPATH=/app/services/agentic-assistant

EXPOSE 8001

CMD ["sh", "-c", "exec uvicorn main:app --host 0.0.0.0 --port ${PORT:-8001}"]
