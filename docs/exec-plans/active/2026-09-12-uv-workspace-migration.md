# uv Workspace Migration (`knowledge-os`) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace per-service `requirements.txt` + isolated `.venv`s with a single uv workspace rooted at `pyproject.toml` (`knowledge-os`), one `uv.lock`, one root `.venv`.

**Architecture:** Root declares `[tool.uv.workspace]` members (`libs/*`, `services/*`); each member keeps its own PEP 621 `pyproject.toml` with `>=` floors (exact pins move into `uv.lock`); dev tools move to `[dependency-groups] dev`; scripts/CI/doctor point at the root venv.

**Tech Stack:** uv workspaces, PEP 621, setuptools, ruff, pytest.

**Spec:** User directives 2026-09-12 — root `pyproject.toml` named `knowledge-os` (not `ai-saas-starter-kit`), delete `requirements.txt`, follow monorepo conventions.

## Global Constraints

- `requires-python = ">=3.11"` in every member (verbatim, already true everywhere).
- Floors equal current `==` pins (e.g. `fastapi>=0.139.2`, `ruff>=0.15.22`); never float above what CI last tested.
- `genblaze-core/nvidia/s3` stay on the same `0.3.x` line (`==0.3.6/==0.3.1/==0.3.5` → `>=` floors at those versions).
- Files stay under 300 lines; no `print()`; ruff `I001` ordering; docs updated in the same change.
- Do not touch `services/agentic-assistant/src/**`, `AGENTS.md`/`ARCHITECTURE.md` agent lines, or pnpm/JS wiring beyond path updates.

---

### Task 1: Root `pyproject.toml` (`knowledge-os`)

**Files:**
- Create: `pyproject.toml`

**Interfaces:**
- Consumes: member names `ai-saas-shared/rag/auth/api/worker/agentic-assistant` (must match sibling `pyproject.toml` `name` fields).
- Produces: workspace root every `uv sync` / CodeNib edge resolves against.

- [ ] **Step 1: Create `pyproject.toml`**

```toml
[project]
name = "knowledge-os"
version = "0.1.0"
description = "Knowledge OS monorepo workspace root (umbrella over libs/* and services/*)"
requires-python = ">=3.11"
dependencies = []

[tool.uv.workspace]
members = ["libs/*", "services/*"]

[build-system]
requires = ["setuptools>=61"]
build-backend = "setuptools.build_meta"
```

- [ ] **Step 2: Validate it parses**

Run: `python3 -c "import tomllib; print(tomllib.load(open('pyproject.toml','rb'))['project']['name'])"`
Expected: `knowledge-os`

### Task 2: Member `dependencies` — move pins from `requirements.txt` to `pyproject.toml`

**Files:**
- Modify: `services/api/pyproject.toml`, `services/agentic-assistant/pyproject.toml`, `services/worker/pyproject.toml`

**Interfaces:**
- Consumes: exact pins in each service's `requirements.txt` (source of truth for floors).
- Produces: member `dependencies` (runtime, `>=` floors) + `[dependency-groups] dev` (ruff/pytest).

- [ ] **Step 1: `services/api/pyproject.toml`** — extend `dependencies` to runtime set, add dev group:

```toml
dependencies = [
    "ai-saas-shared",
    "ai-saas-rag",
    "ai-saas-auth",
    "bcrypt>=5.0.0",
    "fastapi>=0.139.2",
    "uvicorn[standard]>=0.51.0",
    "python-multipart>=0.0.32",
    "python-dotenv>=1.2.2",
    "pydantic>=2.13.4",
    "pydantic-settings>=2.14.2",
    "boto3>=1.43.52",
    "Pillow>=12.3.0",
    "pypdf>=6.16.1",
    "httpx>=0.28.1",
    "stripe>=12.5.1",
    "genblaze-core>=0.3.6",
    "genblaze-nvidia>=0.3.1",
    "genblaze-s3>=0.3.5",
]

[dependency-groups]
dev = ["ruff>=0.15.22", "pytest>=9.1.1", "pytest-asyncio>=1.4.0"]
```

- [ ] **Step 2: `services/agentic-assistant/pyproject.toml`** — add missing `ai-saas-shared` (its `requirements.txt` pins it but `pyproject` omits it) and `ai-saas-auth` (approved upcoming consumer for role-aware tool binding), runtime floors from its `requirements.txt`, dev group with `ruff>=0.16.7`:

```toml
dependencies = [
    "ai-saas-rag",
    "ai-saas-shared",
    "ai-saas-auth",
    "fastapi>=0.139.2",
    "uvicorn[standard]>=0.51.0",
    "python-dotenv>=1.2.3",
    "pydantic>=2.13.4",
    "pydantic-settings>=2.14.2",
    "httpx>=0.28.1",
    "openai>=3.13.0",
    "langchain>=1.4.0",
    "langchain-openai>=1.6.2",
    "langgraph>=1.2.11",
    "langfuse>=4.15.2",
]

[dependency-groups]
dev = ["ruff>=0.16.7", "pytest>=9.1.1", "pytest-asyncio>=1.4.0"]
```

- [ ] **Step 3: `services/worker/pyproject.toml`** — append dev group only (`dependencies` already correct):

```toml
[dependency-groups]
dev = ["pytest>=9.1.1"]
```

(`libs/*` and `services/shared` need no changes — leaf deps already `>=`-style, no requirements files.)

### Task 3: Delete `requirements.txt`, sync, retire per-service venvs

**Files:**
- Delete: `services/api/requirements.txt`, `services/agentic-assistant/requirements.txt`, `services/worker/requirements.txt`
- Create: `uv.lock` (via `uv sync`)
- Delete dirs: `services/api/.venv`, `services/agentic-assistant/.venv`, `services/worker/.venv`

- [ ] **Step 1: Delete the three `requirements.txt` files** (`git rm`).
- [ ] **Step 2: Sync the workspace** — Run: `uv sync --all-packages --all-groups`. Expected: exit 0, `uv.lock` + root `.venv` created. If uv reports an ambiguous workspace dep, add `[tool.uv.sources]` `workspace = true` entries to the consuming member and re-run (do not restructure).
- [ ] **Step 3: Remove stale per-service `.venv` dirs** (untracked; avoids shadow imports from dead venvs).

### Task 4: Repoint scripts, doctor, CI

**Files:**
- Modify: `package.json` (scripts), `scripts/doctor.mjs`, `scripts/configure_b2_cors.py` (comment only), `.github/workflows/ci.yml`

- [ ] **Step 1: `package.json`** — every `lint:*`/`test:*` uses the root venv; `dev:api` uses root uvicorn:

```json
"dev:api": ".venv/bin/uvicorn main:app --reload --port ${API_PORT:-8000}",
"lint:api": ".venv/bin/ruff check services/api",
"lint:shared": ".venv/bin/ruff check services/shared",
"lint:worker": ".venv/bin/ruff check services/worker",
"lint:rag": ".venv/bin/ruff check libs/rag",
"lint:agent": ".venv/bin/ruff check services/agentic-assistant",
"lint:auth": ".venv/bin/ruff check libs/auth",
"test:api": "cd services/api && ../../.venv/bin/python -m pytest",
"test:shared": "cd services/shared && ../../.venv/bin/python -m pytest",
"test:worker": "cd services/worker && ../../.venv/bin/python -m pytest",
"test:rag": "cd libs/rag && ../../.venv/bin/python -m pytest",
"test:agent": "cd services/agentic-assistant && ../../.venv/bin/python -m pytest",
"test:auth": "cd libs/auth && ../../.venv/bin/python -m pytest",
"check:structure": "cd services/api && ../../.venv/bin/python -m pytest tests/test_structure.py -v"
```

(`dev:api` runs with cwd = repo root, so `main:app` no longer resolves — `services/api/main.py` is the entrypoint. Fix the command to `cd services/api && ../../.venv/bin/uvicorn main:app ...`.)

- [ ] **Step 2: `scripts/doctor.mjs`** — `VENV_UVICORN` → `resolve(REPO_ROOT, ".venv/bin/uvicorn")`; remediation message → ``Run: `uv sync --all-packages --all-groups` ``.
- [ ] **Step 3: `scripts/configure_b2_cors.py`** — usage comment `.venv` path → root `.venv`.
- [ ] **Step 4: `ci.yml` `api` job** — replace venv+pip block with uv:

```yaml
      - name: Install uv
        uses: astral-sh/setup-uv@v5

      - name: Sync workspace
        run: uv sync --frozen --all-packages --all-groups

      - name: Lint (ruff)
        run: .venv/bin/ruff check services/api libs/rag libs/auth services/shared services/worker

      - name: Tests (pytest)
        run: cd services/api && ../../.venv/bin/python -m pytest
```

(Keep the job's existing name/steps otherwise; widening CI to all services' suites is a follow-up.)

### Task 5: Docs + gates + commit

**Files:**
- Modify: `AGENTS.md` (§6 setup/commands), `docs/dev-workflows.md` (Python env section), `ARCHITECTURE.md` (workspace paragraph)
- Grep `docs/`, `README.md`, `infra/` for `requirements.txt` / `services/api/.venv` and update hits.

- [ ] **Step 1: Update docs** — replace `pip install -r requirements.txt` flows with `uv sync --all-packages --all-groups`; document single root `.venv` + `uv.lock`.
- [ ] **Step 2: Run full gates** — `uv run --frozen ruff check` per member (via package.json scripts), all `test:*`, `check:structure`. Expected: green.
- [ ] **Step 3: Commit** — stage only migration files (`git status` must show no agent-source or unrelated edits):

```bash
git add pyproject.toml uv.lock package.json services/api/pyproject.toml services/agentic-assistant/pyproject.toml services/worker/pyproject.toml .github/workflows/ci.yml scripts/doctor.mjs scripts/configure_b2_cors.py AGENTS.md ARCHITECTURE.md docs/dev-workflows.md
git rm -q services/api/requirements.txt services/agentic-assistant/requirements.txt services/worker/requirements.txt
git commit -m "chore(python): uv workspace (knowledge-os), drop requirements.txt"
```

## Self-Review

- Spec coverage: root name `knowledge-os` (Task 1); requirements.txt deleted (Task 3); pyproject-only deps (Task 2); monorepo conventions — single venv/lock, scripts, CI, docs (Tasks 4–5). Covered.
- Placeholder scan: every step names exact files, exact commands, exact expected output. Clean.
- Type consistency: dep names match sibling `name` fields (`ai-saas-*`); floors equal deleted pins. Consistent.
