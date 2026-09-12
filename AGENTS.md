<!-- last_verified: 2026-07-15 -->
# AGENTS.md

This is the authoritative control surface for all coding agents. Read this first.

## 1. Repository Map

```
apps/web/          Next.js 16 frontend (App Router, Tailwind v4, shadcn/ui)
services/api/      FastAPI backend (layered: types/config/repo/service/runtime)
libs/rag/          Shared RAG library (importable engine: retrieval + ingestion, auth-agnostic)
packages/shared/   Shared TypeScript types
docs/              System of record (features, workflows, security, reliability)
docs/exec-plans/   Execution plans and tech debt tracker
infra/railway/     Deployment config
```

## 2. Building on This Starter Kit

When this repo is used as the foundation for a new app, the following pieces are part of the starter contract — keep them. Adapt only what the new use case actually requires.

**Keep as-is (do not strip, rename, or replace)**
- **UI kit / design system.** `apps/web/src/components/ui/` (shadcn primitives), the design tokens in `apps/web/src/app/globals.css`, and the `/design` reference page. Build new screens with these primitives; never edit the generated `components/ui/` files directly. Restyling happens through tokens in `globals.css`.
- **File Explorer.** `/files` route, `apps/web/src/app/files/`, and `apps/web/src/components/files/`. The Files sidebar entry in `apps/web/src/components/layout/app-sidebar.tsx` stays.
- **Upload.** `/upload` route, `apps/web/src/app/upload/`, and `apps/web/src/components/upload/`. The Upload sidebar entry stays.
- The sidebar nav itself (Dashboard, Upload, Files, Settings, plus the Design System utility link).

**Adapt to the new use case**
- **Dashboard.** `/` route and `apps/web/src/components/dashboard/` (stats cards, upload chart, recent uploads table) are illustrative defaults. Replace them with metrics, charts, and tables that reflect what the new app actually does (e.g. transcripts processed, embeddings indexed, classifications run). New aggregations must flow through the same `runtime -> service -> repo` layering and be exposed via TanStack Query hooks in `apps/web/src/lib/queries.ts` — no bare `useEffect + fetch`.
- Update `docs/features/dashboard.md` in the same PR as any dashboard change (see §9).

**Why this contract exists**
- The UI kit, Files, and Upload pages are the reusable B2-backed scaffolding that makes this a starter kit — stripping them defeats the purpose. The dashboard is the only screen explicitly designed to be rewritten per app.

## 3. Architectural Invariants

**Backend layering**: `types` -> `config` -> `repo` -> `service` -> `runtime`

- No backward imports across layers
- No `boto3` outside `repo/`
- No business logic in route handlers (`runtime/`)
- All external APIs wrapped in `repo/` adapters
- All request/response data validated at boundary (Pydantic models)
- No shared mutable state across layers

**Frontend**: shadcn/ui components in `src/components/ui/` are generated — never modify them.

**Data fetching**: every API call flows through TanStack Query hooks in `apps/web/src/lib/queries.ts`. No bare `useEffect + fetch` patterns. New endpoints touch three files: `runtime/<router>.py`, `lib/api-client.ts`, `lib/queries.ts`.

## 4. Quality Expectations

- **DRY** — do not duplicate logic, types, or constants. Extract shared code only when used in 2+ places.
- Structured JSON logging only — no `print()` statements
- No raw SDK calls outside `repo/` layer
- Files stay under 300 lines
- Tests added or updated for every behavior change
- Docs updated in same PR as code changes
- Lint clean before merge
- Prefer boring, composable libraries over clever abstractions
- No implicit type assumptions — use typed models

## 5. Mechanical Enforcement

| Rule | Enforced by |
|------|-------------|
| No backward imports | `tests/test_structure.py::test_no_backward_imports` |
| No boto3 outside repo/ | `tests/test_structure.py::test_boto3_only_in_repo` |
| No genblaze_* outside repo/ | `tests/test_structure.py::test_genblaze_only_in_repo` |
| File size < 300 lines | `tests/test_structure.py::test_file_size_limits` |
| All layers exist | `tests/test_structure.py::test_all_layers_exist` |
| No bare print() | `ruff` rule T20 |
| Import ordering | `ruff` rule I001 |
| Frontend strict equality | `eslint` rule eqeqeq |
| No unused vars | `eslint` + `ruff` rules |

## 6. Commands

```bash
# Run
pnpm dev               # start both frontend and backend
pnpm dev:web           # frontend only
pnpm dev:api           # backend only
pnpm stripe:seed       # create Stripe products/prices + write price ids into .env
pnpm stripe:listen     # forward Stripe webhooks to the local API

# Test & Lint
pnpm lint              # frontend lint (eslint)
pnpm build             # frontend type check + build
pnpm test:web          # frontend unit tests (vitest)
pnpm lint:api          # backend lint (ruff)
pnpm lint:shared        # shared package lint (ruff)
pnpm lint:worker        # worker lint (ruff)
pnpm lint:rag           # rag library lint (ruff)
pnpm test:api          # backend tests (pytest)
pnpm test:shared       # shared package tests (pytest)
pnpm test:worker       # worker tests (pytest)
pnpm test:rag          # rag library tests (pytest)
pnpm check:structure   # structural boundary tests
pnpm test:e2e          # Playwright e2e tests (local / pre-release only — see below)
```

CI (`.github/workflows/ci.yml`) runs the lint, type-check/build, unit, and
structural gates on every PR and push to `main`: `lint`, `build`, `test:web`,
`lint:api`, `test:api`, `check:structure`. **`test:e2e` is NOT in CI** — the
Playwright journeys need the full stack (Supabase + API + Stripe CLI + mailpit),
which isn't wired into CI yet; run it locally as a pre-release gate (see
`docs/exec-plans/tech-debt-tracker.md`).

## 7. Agent Workflow

1. Read this file first.
2. Review [ARCHITECTURE.md](ARCHITECTURE.md) before structural changes.
3. For non-trivial changes, create a plan in `docs/exec-plans/active/`.
4. Implement the smallest coherent change.
5. Run: `pnpm lint && pnpm test:web && pnpm lint:api && pnpm test:api && pnpm check:structure`
6. Update docs in the same PR (see §9).
7. Move completed plans to `docs/exec-plans/completed/`.
8. Only change files relevant to the task. No drive-by improvements.

## 8. Frontend Conventions

See [docs/dev-workflows.md](docs/dev-workflows.md) for full details.

## 9. Doc Update Mapping

| Change Type | Update Location |
|-------------|-----------------|
| Feature logic, inputs, outputs, tests | `docs/features/<feature>.md` |
| User journeys | `docs/app-workflows.md` |
| System layout, deployments | `ARCHITECTURE.md` |
| Dev or testing process | `docs/dev-workflows.md` |
| Setup or scope changes | `README.md` |
| Security changes | `docs/SECURITY.md` |
| Reliability changes | `docs/RELIABILITY.md` |
| Active work plans | `docs/exec-plans/active/` |
| Known tech debt | `docs/exec-plans/tech-debt-tracker.md` |

If documentation and implementation conflict, update docs in the same PR. Documentation rot destroys agent reliability.

## 10. Doc Map

| Topic | Location |
|-------|----------|
| System layout, data flows, boundaries | [ARCHITECTURE.md](ARCHITECTURE.md) |
| Feature docs | [docs/features/](docs/features/) |
| User journeys | [docs/app-workflows.md](docs/app-workflows.md) |
| Engineering workflows and testing | [docs/dev-workflows.md](docs/dev-workflows.md) |
| Security principles | [docs/SECURITY.md](docs/SECURITY.md) |
| Reliability expectations | [docs/RELIABILITY.md](docs/RELIABILITY.md) |
| Execution plans | [docs/exec-plans/](docs/exec-plans/) |
| Tech debt | [docs/exec-plans/tech-debt-tracker.md](docs/exec-plans/tech-debt-tracker.md) |

## 11. When Unsure

- Prefer boring, stable libraries
- Prefer small PRs over large changes
- Add tests with every change
- Never bypass lint rules without explicit instruction
- Ask before making destructive or irreversible changes

## 12. CodeNib Context (MCP)

- The `codenib` MCP server (configured in `opencode.json`) serves the prebuilt BM25 + symbol-graph + dense-vector index for this repo (typescript + python).
- Use `explore_context` before editing unfamiliar code and `dependency_subgraph` for impact analysis instead of manual grep-hopping.
- If `codenib codegraph status` reports a stale index, rebuild it before relying on its results.
- The index only verifies against a fully committed tree: commit any change (code, docs, or config) and rebuild afterwards, or `explore_context` degrades to location-only results.
- Rebuild with `codenib index <repo> --preset full --rebuild` plus the MiniLM flags below. `search_zoekt` is unavailable (`zoekt-git-index` binary not installed on this machine); `search_regex` covers that ground.
- Dense embeddings run on CPU with MiniLM-L6-v2: prefix `CUDA_VISIBLE_DEVICES=""` and append `--embedding-model sentence-transformers/all-MiniLM-L6-v2 --embedding-dimension 384`. The default CodeRankEmbed model OOMs this machine's GPU.
- Keep the stub `tsconfig.json` and `packages/shared/tsconfig.json` files in place; the indexer creates them and deleting them marks the index stale.
