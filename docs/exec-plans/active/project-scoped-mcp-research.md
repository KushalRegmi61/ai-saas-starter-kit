# Project-Scoped MCP Integration Research

## Executive recommendation

Implement a remote Streamable HTTP MCP server backed by the existing
`services/agentic-assistant` Neon/Postgres pool. Keep platform authentication
and MCP authorization separate:

```text
Platform JWT
  -> admin/lead dashboard APIs
  -> create projects, assign leads, issue/revoke MCP credentials

Project MCP credential
  -> Streamable HTTP /mcp
  -> resolve one project server-side
  -> expose only that project's tools and rows
```

The lead should generate a project credential from the platform only after an
admin assigns that lead to the project. The credential must be opaque, random,
hashed at rest, revocable, expiring, and bound in the database to exactly one
project. The MCP tool payload must not be the authority for selecting a
project.

This is safer and simpler than giving Claude Code a normal lead JWT. The
existing JWT can authenticate the lead to the dashboard, but it is too broad
for a coding-agent connection unless every downstream operation independently
enforces project ownership.

## Evidence from the current repository

The current assistant service already provides useful identity foundations:

- `assistant_users` stores `id`, email, password hash, role, and timestamps.
- Roles currently include `employee`, `lead`, `manager`, and `admin`.
- `/auth/login` mints an assistant JWT containing `sub`, `role`, issuer, issue
  time, and expiry.
- `/auth/ws-ticket` converts a normal user JWT into a short-lived WebSocket
  ticket.
- Admin-only user-management routes already use a JWT dependency.
- The ingestion surface currently accepts either the configured internal
  service token or an admin JWT. That credential must not be reused for the
  project MCP surface.
- The assistant service already uses the configured
  `AGENTIC_ASSISTANT_DATABASE_URL` Neon/Postgres connection and has an audit
  event table.
- The current frontend admin area manages assistant users and ingestion. It is
  an appropriate shell for adding project and token-management views, but it
  is not yet a project dashboard.

The current worktree contains unrelated ingestion, retrieval, and frontend
changes. Before implementation, isolate this feature from those edits and
recheck the current diff.

## Protocol and client findings

### MCP transport

The MCP specification defines JSON-RPC over either stdio or Streamable HTTP.
For HTTP implementations, subsequent requests carry the negotiated
`MCP-Protocol-Version` header, and authorization is sent in the HTTP
`Authorization: Bearer` header. Invalid or expired credentials should fail at
the HTTP boundary with `401`, not as an ordinary tool-level error.

The MCP authorization specification describes an OAuth 2.1 resource-server
model, protected-resource metadata, authorization-server discovery, PKCE, and
resource/audience binding. It also explicitly warns against accepting tokens
issued for another resource or passing an inbound token through to downstream
services.

For the first POC, the platform-issued opaque project credential can be
implemented as a private bearer credential at the resource server boundary.
The server should still use standard bearer semantics and HTTPS. If broad
third-party OAuth interoperability becomes a requirement, replace the issuance
endpoint with an OAuth authorization server or an identity provider that emits
audience-bound tokens. Do not silently call the opaque token an OAuth access
token.

The official Python SDK supports Streamable HTTP, bearer-token verification,
protected-resource metadata, and per-request auth context. It can also return
an ASGI application that is mounted into an existing FastAPI/Starlette
deployment. This makes a Python MCP adapter compatible with the current
assistant service without requiring a second deployment for the POC.

### Claude Code

Claude Code recommends remote HTTP MCP servers for hosted services. A lead can
configure the generated credential with a command equivalent to:

```bash
claude mcp add --transport http project-status \
  https://assistant.example.com/mcp \
  --header "Authorization: Bearer $PROJECT_MCP_TOKEN"
```

The safer operational approach is to keep the token in the shell environment
or a local secret manager, not in a committed `.mcp.json`. Claude Code supports
local, project, and user MCP configuration scopes. The project configuration
should contain the endpoint only; the secret should remain local.

For development, a stdio wrapper can read `PROJECT_MCP_TOKEN` and connect to
the same service logic in-process or launch a local server. Production should
prefer the hosted HTTP endpoint so revocation and audit checks happen centrally.

### Codex

Codex CLI supports MCP servers through the `mcp_servers` section in
`~/.codex/config.toml`. The current configuration model supports command-based
servers and remote URL/auth fields, including HTTP headers and bearer-token
environment-variable configuration in current Codex sources/configuration
references.

The install instructions should therefore be generated rather than committed
as a repository secret:

```toml
[mcp_servers.project_status]
url = "https://assistant.example.com/mcp"
bearer_token_env_var = "PROJECT_MCP_TOKEN"
```

Codex configuration is not as consistently project-local as Claude Code's
`.mcp.json` workflow. The token must still scope the server-side access; local
configuration scope is not a security boundary.

### OpenCode

OpenCode supports remote MCP servers using Streamable HTTP. Its configuration
can disable built-in OAuth and send a header-backed credential from an
environment variable:

```jsonc
{
  "$schema": "https://opencode.ai/config.json",
  "mcp": {
    "servers": {
      "project-status": {
        "type": "remote",
        "url": "https://assistant.example.com/mcp",
        "oauth": false,
        "headers": {
          "Authorization": "Bearer {env:PROJECT_MCP_TOKEN}"
        }
      }
    }
  }
}
```

If the product later adopts a standards-compliant OAuth flow, OpenCode can use
its browser/PKCE authorization flow instead. The POC should keep the endpoint
compatible with both approaches by using standard HTTP bearer behavior and
returning correct `401`/`WWW-Authenticate` responses.

## Security model

### Two identities, two scopes

```text
assistant_users.id / role
    identifies a human in the platform

project_mcp_tokens.token_hash -> project_id + created_by
    authorizes one coding-agent connection for one project
```

The MCP server should create an immutable request context:

```python
@dataclass(frozen=True)
class ProjectMcpContext:
    token_id: str
    project_id: str
    project_name: str
    lead_id: str
    token_label: str
```

All repository functions receive `context.project_id`. A model-provided
`project_id` is either omitted from tool schemas or compared with the bound
value and rejected when different.

### Token lifecycle

1. The admin creates a project.
2. The admin assigns a lead.
3. The lead signs into the platform with the existing assistant JWT.
4. The platform checks that the JWT subject equals the project's current
   `lead_id`.
5. The platform generates at least 256 bits of random token material.
6. It stores only a SHA-256 or keyed hash of the token.
7. It returns the raw token once and marks it as shown.
8. Every MCP HTTP request hashes the bearer value and looks up the active row.
9. The server verifies not revoked, not expired, project exists, and creator is
   still the assigned lead.
10. Reassignment or revocation immediately blocks the old token.

Suggested generation:

```python
raw = "prj_" + secrets.token_urlsafe(32)
stored_hash = hashlib.sha256(raw.encode("utf-8")).hexdigest()
```

The API response must never return `token_hash`. Logs must record token ID,
project ID, actor ID, and outcome, never the raw bearer value.

### Database schema

Use project-specific tables in the assistant database. The six domain tables
from the product proposal remain valid; these are the minimum security and
ownership tables needed for the workflow:

```sql
CREATE TABLE assistant_projects (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    lead_id TEXT REFERENCES assistant_users(id),
    status TEXT NOT NULL CHECK (status IN ('ON_TRACK','AT_RISK','BLOCKED','COMPLETED')),
    completion_percentage INTEGER NOT NULL CHECK (completion_percentage BETWEEN 0 AND 100),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE assistant_project_mcp_tokens (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL REFERENCES assistant_projects(id) ON DELETE CASCADE,
    token_hash TEXT NOT NULL UNIQUE,
    created_by TEXT NOT NULL REFERENCES assistant_users(id),
    label TEXT NOT NULL,
    expires_at TIMESTAMPTZ,
    last_used_at TIMESTAMPTZ,
    revoked_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX assistant_project_mcp_tokens_active_idx
ON assistant_project_mcp_tokens (project_id)
WHERE revoked_at IS NULL;
```

The project lead relation can remain a single `lead_id` for the POC. If
co-leads are likely soon, use a `assistant_project_leads(project_id, user_id)`
join table now, but do not introduce it merely to support the MCP token.

The product tables should be normalized:

- `assistant_project_features`
- `assistant_project_blockers`
- `assistant_daily_project_updates`
- `assistant_feature_status_history`

Do not store current feature status as JSON. Counts and status distribution
must be SQL-queryable. Daily narrative is separate from feature truth.

### Token authorization pseudocode

```python
async def authenticate_project_token(request) -> ProjectMcpContext:
    bearer = parse_bearer_header(request.headers.get("authorization"))
    if not bearer:
        raise http_401("Bearer token required")

    row = await project_tokens.find_active_by_hash(sha256(bearer))
    if row is None:
        raise http_401("Invalid project credential")
    if row.revoked_at is not None or expired(row.expires_at):
        raise http_401("Project credential expired or revoked")

    project = await projects.get(row.project_id)
    if project is None:
        raise http_401("Project credential invalid")
    if project.lead_id != row.created_by:
        raise http_403("Credential owner is no longer assigned to project")

    await project_tokens.touch_last_used(row.id)
    return ProjectMcpContext(...)
```

Do not put authorization in the LLM prompt. Prompts can explain the tool
contract, but only the HTTP dependency and repository query predicates enforce
security.

## Minimal MCP tool surface

The POC should expose five tools, with project scope implicit in the auth
context:

| Tool | Read/write | Purpose |
|---|---|---|
| `get_project_context` | Read | Project summary, status, completion, feature counts, open blockers, latest update |
| `get_project_features` | Read | Features and current statuses |
| `get_previous_update` | Read | Latest confirmed daily update |
| `update_feature_status` | Write | Move one feature to a validated status and append history |
| `submit_daily_update` | Write | Persist a confirmed narrative/completion update and blocker references |

`get_project_context` should be the canonical first call. It should execute a
small bounded set of SQL queries in one service operation and return structured
JSON:

```json
{
  "project": {
    "id": "p-123",
    "name": "Payments",
    "status": "AT_RISK",
    "completion_percentage": 72
  },
  "feature_counts": {"DEV": 3, "QA": 5, "UAT": 4, "PROD": 18},
  "open_blockers": [],
  "latest_update": {},
  "scope": {"project_id": "p-123"}
}
```

The tool must obtain `project_id` from the authenticated context. This is the
answer to “how can every MCP call get project information from Postgres?”:

```text
HTTP Bearer token
  -> token hash lookup
  -> project_id lookup
  -> ProjectMcpContext
  -> project service
  -> repository queries with WHERE project_id = context.project_id
```

There should be no generic SQL tool, arbitrary filter tool, cross-project
search tool, or “set project status” tool in the first version. Project status
should be derived or updated through validated domain mutations.

### Confirmation and writes

The preferred interface is:

```text
Claude Code: get_project_context()
Claude Code: get_project_features()
Claude Code: proposes changes in chat
Lead: reviews and confirms
Claude Code: update_feature_status(...)
Claude Code: submit_daily_update(...)
```

The server validates:

- feature belongs to the bound project;
- status is in the allowed enum;
- blocker IDs belong to the bound project;
- completion is an integer from 0 to 100;
- summary length is bounded;
- updates are idempotent where practical;
- every mutation records actor/token/project audit metadata.

If stronger confirmation is needed, add a `prepare_project_update` resource or
tool that creates a short-lived proposal record, followed by
`confirm_project_update(proposal_id)`. Do not make the POC autonomous by
default.

## Platform API and dashboard

### Admin experience

Add a Projects section alongside the existing Users and Ingestion areas.

Admin project list:

```text
Projects
----------------------------------------------------------------
Name          Lead          Status       Completion   Last update
Payments      Maya          AT_RISK      72%          2h ago
Identity      Arun          ON_TRACK     48%          1d ago
```

Admin project detail:

- project name and status;
- completion percentage;
- assigned lead and reassignment action;
- feature count by status;
- open blockers;
- latest daily updates;
- feature history;
- active token count and last-used time;
- revoke-token action;
- audit timeline.

Admin actions:

```text
POST   /projects
GET    /projects
GET    /projects/{project_id}
PATCH  /projects/{project_id}/lead
GET    /projects/{project_id}/tokens
POST   /projects/{project_id}/tokens/{token_id}/revoke
```

Only the admin role can create projects, assign leads, and revoke any token.
The admin may view all project state.

### Lead experience

The lead dashboard should show only assigned projects:

- “My projects” list;
- current status and completion;
- feature distribution;
- blockers;
- latest update;
- “Generate Claude/Coding Agent Access” action;
- token label, expiry, created time, last used time;
- revoke/regenerate controls.

The token creation dialog must say:

```text
This credential can read and update only this project.
It will be shown once. Store it in your local secret manager or environment.
Never commit it to a repository or paste it into a shared chat.
```

After creation, display copyable setup snippets for Claude Code, Codex, and
OpenCode. Never display the token again from the dashboard.

Lead endpoints:

```text
GET  /projects/mine
GET  /projects/{project_id}
POST /projects/{project_id}/tokens
GET  /projects/{project_id}/tokens       # metadata only
POST /projects/{project_id}/tokens/{id}/revoke
```

The API checks `claims.subject == project.lead_id` for every lead operation.
The frontend is not the security boundary.

### Manager experience

Managers do not need MCP credentials. They need a read-only project dashboard
and assistant tools backed by structured project queries:

- project portfolio table;
- risk/status filters;
- completion trend;
- blocker summary;
- feature distribution;
- “changed since yesterday” view;
- chat questions such as “what changed?” and “why is this at risk?”

The LangGraph manager agent should call structured project services first. RAG
should be used only for project documentation or technical rationale, not for
current feature counts or authoritative status.

## Repository-specific implementation sequence

### Phase 0: boundary and schema preparation

Phase 0 is backend foundation only. It adds the project domain contract,
`assistant_projects` startup schema, async persistence primitives, and reusable
role-capability constants. It does not expose project HTTP routes, generate MCP
credentials, mount MCP, or add dashboard screens.

Files to inspect or add:

```text
services/agentic-assistant/src/models/projects.py
services/agentic-assistant/tests/test_projects.py
services/agentic-assistant/tests/test_lifespan.py
```

Prefer explicit models and service functions. Keep SQL in repository/model
modules, not route handlers. Extend the existing async table initialization or
move to a migration runner before production; `CREATE TABLE IF NOT EXISTS` is
acceptable for the local POC but is not a sufficient long-term migration
strategy.

Phase 0 completion criteria:

- project status and public project shapes are typed;
- project creation, lookup, listing, lead assignment, and lead-scoped listing
  are transaction-neutral async persistence functions;
- assignment accepts only users with role `lead`, is idempotent for the same
  lead, and raises an assignment conflict instead of silently replacing a
  different lead;
- the project table uses `ON DELETE RESTRICT` for lead references and a status
  check constraint;
- startup fails if project schema initialization fails;
- tests cover schema shape, persistence behavior, authorization capabilities,
  and startup failure;
- no project endpoint, MCP credential, or MCP tool exists yet.

### Phase 1: projects and assignments

Implement:

1. project model and enums;
2. project CRUD for admin;
3. lead assignment;
4. list-my-projects for lead;
5. manager read-only project list/detail;
6. authorization tests for every role and unassigned lead.

Acceptance criteria:

- admin can assign Lead A to Project A;
- Lead A sees Project A but not unrelated Project B;
- Manager can read allowed projects but cannot assign leads;
- reassignment is atomic and audited.

The Phase 1 implementation adds the authenticated project API and shared
role-aware `/projects` web surface. It intentionally does not add MCP
credentials, MCP routes/tools, feature tracking, blockers, daily updates, or
manager-agent project tools.

### Phase 2: project credentials

Implement:

1. random credential generation;
2. hash-at-rest persistence;
3. one-time raw-token response;
4. expiry and revocation;
5. token metadata list;
6. current-assignment check;
7. audit events and structured security logs.

Do not add token values to Pydantic response models used for list endpoints.
Use a separate `ProjectTokenCreatedResponse` model that contains the raw token
only on creation.

### Phase 3: MCP server

Add the official Python MCP SDK as a dependency if the repository does not
already include it. Mount a Streamable HTTP app into the assistant ASGI
application or run a separately deployed MCP process sharing the same service
and model modules. A separate process is cleaner operationally; a mounted app
is the smallest POC. Either way, the MCP handler must call the same project
service layer as dashboard APIs.

Conceptual structure:

```text
src/mcp_server/
  server.py          MCP lifecycle and tool registration
  auth.py            bearer parsing and token verification
  context.py         ProjectMcpContext
  tools.py           five thin tool handlers
```

Tool handlers should be thin adapters:

```python
@mcp.tool()
async def get_project_context(ctx: Context) -> ProjectContextResponse:
    auth = await require_project_mcp_context()
    return await project_service.get_context(auth.project_id)
```

The real implementation must use the SDK's request auth context or a custom
ASGI middleware, not a module-global current project. Module globals would be
unsafe when multiple leads connect concurrently.

### Phase 4: dashboard integration

Add typed frontend API functions, query hooks, and components. The existing
assistant dashboard uses direct fetch helpers; preserve its local convention
for this surface unless the frontend is migrated as a separate task. Do not
put authorization decisions in React state.

Minimum frontend components:

```text
projects/project-table.tsx
projects/project-detail.tsx
projects/lead-assignment-dialog.tsx
projects/project-token-dialog.tsx
projects/token-setup-snippets.tsx
projects/project-audit-timeline.tsx
```

### Phase 5: project-agent tool registration

Register the read-only project-agent tool contracts through the existing agent
tool registry:

```text
resolve_project(project_reference, project_id=None)
get_project_status(project_reference, project_id=None)
get_project_history(project_reference, project_id=None, since=None, limit=50)
get_project_metrics(project_reference, project_id=None)
search_project_knowledge(project_reference, query, project_id=None, top_k=4)
```

`project_reference` is the user-facing natural-language input. `project_id` is
optional and can be supplied when an upstream caller already has a project ID,
but it is only a hint until the authenticated project service validates it.
The registration phase defines typed result envelopes, validation, registry
metadata, and the service boundary. It does not add natural-language project
discovery, DB/RAG fan-out, classifier routing, ReAct behavior, conversation
state, or project-specific Qdrant filters.

The project service must validate an optional ID against the caller's existing
project visibility rules and reject a reference/ID mismatch. It must never use
a model-provided ID as authorization. Phase 6 will supply authenticated claims
and the assistant pool to these contracts and design resolution, ambiguity,
parallel DB/RAG search, and RAG query construction in detail.

### Phase 6: manager-agent project discovery and retrieval

Implement agent-driven project discovery and retrieval on the existing ReAct
graph. The classifier and agent select the registered tools; the server injects
verified claims and the assistant pool through request-scoped state. Resolution
searches only the caller's visible projects with bounded SQL matching, and
ambiguous results return safe candidates for clarification. The existing
LangGraph tool runner fans out independent status, metrics, history, and RAG
calls, while final synthesis fans them back in. Structured project state is
authoritative for current status, completion, blockers, counts, and history;
RAG is supporting knowledge and runs only after a project is resolved.

The optional `project_id` remains a validated hint, never authorization. A new
explicit project reference takes precedence over recent conversation context.
No project IDs, claims, database handles, token material, or internal
authorization details are exposed to the model or final response.

## Testing and verification

### Unit and service tests

- token entropy and hash-only persistence;
- expired and revoked token rejection;
- raw token omitted from logs and list responses;
- lead can create only for an assigned project;
- manager/admin cannot create lead credentials unless explicitly allowed;
- reassignment invalidates old credential;
- feature IDs and blocker IDs cannot cross project boundaries;
- status enum and completion validation;
- audit rows contain actor, project, operation, token ID, and outcome.

### MCP protocol tests

Use the MCP Inspector and the official Python SDK client to verify:

1. unauthenticated `/mcp` returns HTTP 401;
2. malformed credential returns HTTP 401;
3. valid credential initializes and lists exactly five tools;
4. `get_project_context` returns only its project;
5. every write is persisted;
6. second project cannot be selected through tool arguments;
7. revocation blocks the same HTTP connection's next request;
8. protocol-version headers are accepted after initialization;
9. concurrent project sessions do not leak context.

### Client compatibility tests

Run the generated setup snippet against:

- Claude Code remote HTTP configuration and `/mcp` status;
- Codex CLI MCP listing and one read/write call;
- OpenCode remote server listing and one read/write call.

Use a non-production test project and a short-lived token. Never use a real
lead credential in a checked-in fixture.

### Security acceptance test

```text
Admin creates A and B.
Admin assigns Lead 1 to A.
Lead 1 generates token T_A.
T_A reads A successfully.
T_A reads B: denied.
T_A updates a B feature: denied.
Admin reassigns A to Lead 2.
T_A mutation: denied.
Lead 2 generates T_A2.
T_A2 updates A.
Manager sees the update immediately in dashboard and chat.
```

Run the repository-required lint, focused assistant tests, frontend tests, and
structural checks. For this repo, the relevant existing commands include
`pnpm test:agent`, `pnpm lint:agent`, `pnpm lint`, `pnpm test:web`, and
`pnpm check:structure`, plus `git diff --check`.

## Decisions to lock before coding

1. One lead per project or multiple leads?
2. Token default lifetime: recommended 30 days with explicit regeneration, or
   short-lived OAuth-style access tokens?
3. One active token per project or multiple device-labelled tokens?
4. Should the MCP be mounted in the assistant service or deployed separately?
5. Which projects may a manager view: all projects or an assigned portfolio?
6. Is token generation itself sufficient lead confirmation, or is a separate
   proposal/confirmation record required for writes?

## Locked POC decisions

The POC will use the following decisions:

- One lead per project.
- Project MCP credentials expire after 30 days.
- A project may have multiple active, labelled credentials for different
  machines or coding-agent environments.
- The MCP server is mounted inside the existing assistant service for the POC.
  A separate MCP deployment remains a later operational extraction, not a
  prerequisite for validation.
- Managers can view all projects through the dashboard and manager agent.
- Write tools require explicit confirmation in the coding-agent conversation
  before they are called.

These choices keep the POC small while preserving the security boundary that
matters: every credential remains scoped to one project, and every mutation is
validated and audited server-side.

## Sources

1. [Model Context Protocol specification](https://modelcontextprotocol.io/specification/2025-06-18), including architecture, lifecycle, authorization, and transports.
2. [MCP authorization specification](https://modelcontextprotocol.io/specification/2025-06-18/basic/authorization), for bearer handling, protected-resource metadata, PKCE, audience binding, and token passthrough restrictions.
3. [MCP transports specification](https://modelcontextprotocol.io/specification/2025-06-18/basic/transports), for stdio and Streamable HTTP behavior and protocol-version headers.
4. [Official MCP Python SDK](https://github.com/modelcontextprotocol/python-sdk), for Streamable HTTP server/client support.
5. [Python SDK authorization guide](https://github.com/modelcontextprotocol/python-sdk/blob/main/docs/run/authorization.md), for resource-server token verification and request auth context.
6. [Python SDK ASGI guide](https://github.com/modelcontextprotocol/python-sdk/blob/main/docs/run/asgi.md), for mounting MCP into an existing ASGI application.
7. [Claude Code MCP documentation](https://code.claude.com/docs/en/mcp), for remote HTTP, stdio, bearer headers, scopes, and configuration.
8. [OpenCode MCP server documentation](https://opencode.ai/v2/docs/mcp-servers), for remote Streamable HTTP, OAuth, headers, and environment-backed credentials.
9. [OpenAI Codex MCP configuration source](https://github.com/openai/codex/blob/main/codex-rs/core/config.schema.json), for the current `mcp_servers` configuration surface and HTTP/auth fields.

## Status

Phase 0 and Phase 1 implementation are present in the current worktree.
Phase 2 adds project-scoped coding-agent credentials inside the existing
`services/agentic-assistant` deployment: hash-at-rest 30-day tokens, labelled
metadata, lead/admin platform APIs, one-time secret responses, ownership
invalidation, and project-dashboard controls.

Phase 3 adds the in-process Streamable HTTP MCP server at `/mcp`. The server
revalidates the Phase 2 bearer token on every HTTP request, binds a
request-scoped `ProjectMcpContext`, and exposes exactly five tools:
`get_project_context`, `get_project_features`, `get_previous_update`,
`update_feature_status`, and `submit_daily_update`. Project features,
blockers, daily updates, and feature history are persisted in normalized
Postgres tables. Write tools require explicit lead confirmation in the coding
agent conversation and remain validated and audited server-side.

Phase 5 registers five read-only project-agent tool contracts with typed
project references, optional validated IDs, bounded parameters, and no write
capabilities. Phase 6 now wires those tools into the existing authenticated
ReAct workflow: role-scoped SQL resolution, ambiguity-safe candidates,
parallel structured/RAG reads after resolution, and final synthesis with
structured state authoritative over RAG. A separately deployed MCP service
remains deferred. Phase 4 adds the assistant-web project dashboard and typed,
role-authorized project-state reads for context, features, updates, history,
and audit events. The POC does not expose generic SQL or share project context
through module-global state.

The new token unit tests, project persistence/service tests, Ruff checks, and
assistant-web lint/typecheck pass. The repository's HTTP/TestClient lifespan
path remains a known validation limitation because the focused API/lifespan
process stalls before emitting a pytest summary.
