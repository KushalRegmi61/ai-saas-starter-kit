# AI SaaS Starter Kit

[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
[![CI](https://github.com/backblaze-labs/ai-saas-starter-kit/actions/workflows/ci.yml/badge.svg)](https://github.com/backblaze-labs/ai-saas-starter-kit/actions/workflows/ci.yml)
[![Next.js 16](https://img.shields.io/badge/Next.js-16-black?logo=next.js)](https://nextjs.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-Python%203.11+-009688?logo=fastapi)](https://fastapi.tiangolo.com/)

An agent-ready, full-stack monorepo for building SaaS products with file storage, authentication, billing, retrieval-augmented generation, and a project-aware knowledge assistant.

The repository contains two related applications:

- `apps/web` is the general SaaS application: Supabase authentication, Stripe billing, Backblaze B2 uploads and file browsing, the dashboard, admin console, and the optional AI image-generation workflow.
- `apps/agentic-assistant-web` is the knowledge-assistant application: assistant login, streamed chat, conversation history, project dashboards, project evidence, and admin views.

The backend is split into a layered FastAPI service, an independent agentic-assistant service, a shared RAG engine, shared authentication primitives, and a small worker package. The project is designed so that coding agents can discover the architecture, constraints, commands, and feature contracts directly from the repository.

## What is included

### SaaS application

- Supabase email/password and email-code authentication
- Cookie-based sessions, protected routes, profiles, and Supabase `user`/`admin` roles
- Stripe Checkout, Billing Portal, Free/Pro/Team plans, webhook synchronization, and plan gates
- Direct browser-to-Backblaze B2 uploads using presigned URLs, upload progress, validation, and ownership scoping
- File browser with tree view, preview, download, metadata, and delete
- Dashboard with plan, storage, upload activity, and generation metrics
- Admin console for users, subscriptions, jobs, files, provider runs, and audited role changes
- Optional NVIDIA NIM image generation through Genblaze, persisted to B2 with provenance metadata

### Knowledge assistant

- Separate assistant identity store in Neon Postgres, independent from Supabase user roles
- Role-aware assistant JWTs and short-lived WebSocket tickets
- Persistent `WS /ask` chat with streamed workflow steps and generated tokens
- Conversation history with bounded recent-turn memory and rolling summaries
- LangGraph workflow for intent classification, retrieval, grading, query rewriting, answer generation, and grounding checks
- Project-scoped context: overview, features, blockers, updates, history, audit events, and project knowledge search
- Role-scoped project dashboard for admins, managers, and assigned leads
- Admin user provisioning, role changes, project administration, and indexed-document views

### Retrieval and ingestion

- Shared, auth-agnostic `libs/rag` package
- Hybrid retrieval over Qdrant and a Neon document registry/cache
- Query embeddings, semantic retrieval, corpus filtering, BM25/RRF fusion, optional reranking, and bounded caching
- RBAC through portable `AccessFilter` values resolved by each host service
- PDF, Markdown, and plain-text ingestion through the agentic-assistant service
- Tenant-aware indexing, idempotent content-hash deduplication, source deletion, and best-effort upload indexing

## Repository layout

```text
apps/
  web/                         General SaaS frontend (Next.js 16)
  agentic-assistant-web/       Knowledge assistant and project frontend (Next.js 16)
services/
  api/                         Layered FastAPI SaaS API
  agentic-assistant/           LangGraph assistant, auth, chat, projects, and ingestion API
  shared/                      Pure Python primitives shared by backend services
  worker/                      Small CLI worker consuming shared primitives
libs/
  rag/                         Retrieval and document-ingestion engine
  auth/                        Assistant identity, tokens, roles, and Neon store primitives
packages/
  shared/                      TypeScript contracts shared with the web frontend
supabase/                      Local/hosted Supabase migrations and templates
infra/railway/                 Railway deployment configuration
docs/                          Feature, security, reliability, workflow, and deployment docs
```

## Architecture

The SaaS API follows a strict dependency direction:

```text
types -> config -> repo -> service -> runtime
```

Routes validate boundary data and call services. Services contain business logic. Repositories contain external APIs such as Backblaze B2, Supabase, and Stripe. External SDKs do not leak into higher layers, `boto3` is restricted to the repository layer, and structural tests enforce import boundaries and the 300-line file limit.

The assistant uses the shared RAG and auth libraries but owns its host-specific policy, identity, persistence, and transport:

```text
assistant web
  -> assistant JWT / WebSocket ticket
  -> agentic-assistant API
  -> LangGraph workflow
  -> project tools + RAG search tool
  -> Qdrant / Neon
```

The main upload path keeps file bytes out of the API:

```text
browser -> API presign -> browser PUT to B2 -> API complete
                                      \\-> best-effort assistant ingestion
```

Read [ARCHITECTURE.md](ARCHITECTURE.md) for data flows, trust boundaries, persistence, and canonical files. Read [AGENTS.md](AGENTS.md) before making structural changes; it is the repository's coding-agent contract.

## Local development

### Requirements

- Node.js 20 or newer
- pnpm 9 or newer
- Python 3.11 or newer
- `uv`
- Docker and the Supabase CLI for the local Supabase stack
- Backblaze B2 for the general SaaS file features
- Neon Postgres, Qdrant, and an OpenAI-compatible embedding/LLM provider for the assistant features

### Install

```bash
pnpm install
uv sync --all-packages --all-groups
cp .env.example .env
```

`uv sync` creates one workspace virtual environment at `.venv` and installs the Python members (`services/api`, `services/agentic-assistant`, `services/shared`, `services/worker`, `libs/auth`, and `libs/rag`) as editable packages.

### Configure the SaaS application

Fill the root `.env` with the required Backblaze B2 and Supabase values. Stripe and NVIDIA are optional; their features remain disabled until configured.

For local Supabase:

```bash
supabase start
node scripts/sync-supabase-env.mjs
```

See [docs/deployment.md](docs/deployment.md) for B2 CORS, hosted Supabase, Stripe, production environment variables, and deployment topology.

### Configure the knowledge assistant

The assistant uses its own configuration namespace. Set the relevant values in the root environment, including:

```text
AGENTIC_ASSISTANT_DATABASE_URL
AGENTIC_ASSISTANT_JWT_SECRET
AGENTIC_ASSISTANT_SERVICE_TOKEN
AGENTIC_ASSISTANT_ADMIN_EMAIL
AGENTIC_ASSISTANT_ADMIN_PASSWORD
QDRANT_URL
QDRANT_API_KEY
QDRANT_COLLECTION
OPENAI_API_KEY
```

Set `NEXT_PUBLIC_ASSISTANT_API_URL` in `apps/agentic-assistant-web/.env.local` when the assistant API is not using its default local origin. The first admin is seeded only when the bootstrap credentials are supplied; existing users are not overwritten.

Assistant auth, role policy, project access, memory, WebSocket protocol, and ingestion behavior are documented in [docs/features/assistant-auth.md](docs/features/assistant-auth.md) and [docs/features/retrieval.md](docs/features/retrieval.md).

### Run the applications

```bash
pnpm dev
```

This starts the general web app at `http://localhost:3000` and the SaaS API at `http://localhost:8000`.

Run the assistant stack separately when needed:

```bash
pnpm dev:agent
pnpm dev:assistant-web
```

The assistant web app runs at `http://localhost:3001`; its API defaults to `http://localhost:8001`. `pnpm dev:all` runs the two frontends plus the SaaS API; start `pnpm dev:agent` separately for the assistant API:

```bash
pnpm dev:all
```

`pnpm doctor` runs the local preflight checks independently. `pnpm dev` runs it automatically first.

## Commands

| Command | Purpose |
| --- | --- |
| `pnpm dev` | General web app and SaaS API |
| `pnpm dev:all` | General web, assistant web, and SaaS API |
| `pnpm dev:agent` | Agentic-assistant API |
| `pnpm dev:assistant-web` | Agentic-assistant frontend |
| `pnpm build` / `pnpm build:assistant-web` | Build either frontend |
| `pnpm typecheck` / `pnpm typecheck:assistant-web` | Type-check either frontend |
| `pnpm lint` / `pnpm lint:assistant-web` | Lint either frontend |
| `pnpm lint:api` | Lint the SaaS API |
| `pnpm lint:agent` | Lint the assistant service |
| `pnpm lint:rag` / `pnpm lint:auth` | Lint shared Python libraries |
| `pnpm test:web` | General frontend unit tests |
| `pnpm test:api` | SaaS API tests |
| `pnpm test:agent` | Assistant tests |
| `pnpm test:rag` / `pnpm test:auth` | RAG and assistant-auth tests |
| `pnpm check:structure` | Verify API layering and structural rules |
| `pnpm test:e2e` | General frontend Playwright journeys |
| `pnpm stripe:seed` / `pnpm stripe:listen` | Seed Stripe test prices and forward webhooks |

The CI workflow runs the relevant lint, build, unit-test, API-test, and structural gates. Playwright requires the full local stack and is a local pre-release check rather than a CI gate.

## Feature documentation

- [Authentication](docs/features/authentication.md)
- [Assistant authentication and project access](docs/features/assistant-auth.md)
- [Retrieval, WebSocket chat, memory, and ingestion](docs/features/retrieval.md)
- [Billing](docs/features/billing.md)
- [File upload](docs/features/file-upload.md)
- [File browser](docs/features/file-browser.md)
- [Dashboard](docs/features/dashboard.md)
- [Admin console](docs/features/admin.md)
- [Image generation](docs/features/generation.md)
- [Design system](docs/design-system.md)

For operational context, see [docs/SECURITY.md](docs/SECURITY.md), [docs/RELIABILITY.md](docs/RELIABILITY.md), [docs/app-workflows.md](docs/app-workflows.md), [docs/dev-workflows.md](docs/dev-workflows.md), and [docs/exec-plans/](docs/exec-plans/).

## Deployment

The general SaaS application can be deployed as a split topology: the web app on Vercel and the FastAPI service on Railway, Render, or Fly.io, with hosted Supabase, Stripe, and Backblaze B2. Railway configuration is in [infra/railway/](infra/railway/).

The agentic-assistant API and frontend are separate deployable processes. They require Neon, Qdrant, an LLM/embedding provider, and the assistant-specific `AGENTIC_ASSISTANT_*` configuration. Do not reuse Supabase service-role credentials as assistant identity credentials; the two auth systems are intentionally separate.

See [docs/deployment.md](docs/deployment.md) for the current deployment procedure and environment contract.

## Contributing

1. Read [AGENTS.md](AGENTS.md) and [ARCHITECTURE.md](ARCHITECTURE.md).
2. Keep changes inside the appropriate layer or package.
3. Update the matching feature or operational documentation with behavior changes.
4. Run the focused tests first, then the relevant lint, build, and structural checks.

Security issues should be reported privately through the repository's GitHub security advisory flow. This project is released under the [MIT License](LICENSE).
