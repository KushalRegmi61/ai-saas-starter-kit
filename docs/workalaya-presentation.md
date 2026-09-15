# Workalaya Agentic Assistant

Technical presentation context for the Workalaya Agentic Assistant. This
five-slide narrative is written for engineering audiences and separates the
assistant runtime, project-scoped MCP integration, CI/CD delivery, and demo
workflow.

## Slide 1 — Problem and System Overview

### Tracking Status Across Multiple Client Projects

Companies managing several client projects struggle to track progress across
distributed development teams, repositories, coding tools, and documentation.

Project information becomes fragmented, stale, and difficult to compare.
Workalaya connects developer workflows to structured, access-controlled
project intelligence:

```text
Developers using coding agents
        ↓
Project-scoped MCP server
        ↓
Normalized PostgreSQL project state
        ↓
LangGraph assistant + hybrid RAG
        ↓
Dashboard and conversational intelligence
```

### Presenter context

Workalaya is an internal project-intelligence system. It captures confirmed
project changes through the tools developers already use, stores structured
state separately from documentation, and gives authorized users a searchable
and conversational view of project health.

## Slide 2 — Agent Architecture and Delivered Extensions

### Role-Aware Agent Runtime and Hybrid RAG

```mermaid
flowchart LR
    USER[Authenticated User] --> WEB[Assistant Web UI]
    WEB --> WEBJWT[Assistant Web JWT<br/>web session / API access]
    WEBJWT --> WSTICKET[Short-Lived WebSocket Ticket<br/>first-frame chat authentication]
    WSTICKET --> AGENT[Agentic AI Orchestrator]

    subgraph ROUTING[Model Routing]
        AGENT --> ROUTER[Intent + Request Routing]
        ROUTER -->|chitchat / recovery| FAST[Fast Model<br/>gpt-4o-mini default]
        ROUTER -->|project or knowledge question| REASON[Reasoning Model<br/>gpt-5-nano default]
    end

    subgraph KNOWLEDGE[Authorized Tools and Knowledge]
        REASON --> TOOLS[Bounded Tool-Using Agent<br/>LangGraph + project tools]
        TOOLS --> STATE[Structured Project State<br/>Neon/PostgreSQL]
        TOOLS --> FILTER[Server-Derived AccessFilter<br/>project scope + role scope<br/>LLM cannot supply scope]
        FILTER --> RAG[Hybrid RAG]
        RAG --> VECTOR[Qdrant vectors]
        RAG --> BM25[Neon registry + BM25/cache]
        VECTOR --> FUSION[Retrieval Fusion / RRF]
        BM25 --> FUSION
        STATE --> CONTEXT[Project Facts + Documentation Evidence]
        FUSION --> CONTEXT
    end

    subgraph TRUST[Guardrails and Delivery]
        CONTEXT --> SYNTH[Grounded Answer Synthesis<br/>reasoning model]
        SYNTH --> GUARD[Guardrails<br/>authorization, grounding, recovery]
        FAST --> GUARD
        GUARD --> STREAM[Safe WebSocket Streaming]
        AGENT -.-> TRACE[Langfuse Tracing]
    end

    subgraph OUTPUTS[Business Outputs]
        STREAM --> ANSWER[Evidence-Backed Conversation]
        STATE --> DASH[Project Dashboards]
    end

    ANSWER --> WEB
    DASH --> WEB
    WEBJWT --> FILTER

    DEV[Developer Coding Agents] -.->|project-scoped MCP updates| STATE
    UPLOAD[Document Ingestion] -.->|chunk + embed| RAG

    classDef ai fill:#4c1d95,stroke:#a78bfa,color:#fff,stroke-width:2px;
    classDef model fill:#1d4ed8,stroke:#93c5fd,color:#fff,stroke-width:2px;
    classDef data fill:#14532d,stroke:#86efac,color:#fff,stroke-width:2px;
    classDef security fill:#92400e,stroke:#fbbf24,color:#fff,stroke-width:2px;
    classDef ops fill:#334155,stroke:#cbd5e1,color:#fff,stroke-width:1px;
    classDef output fill:#0f766e,stroke:#5eead4,color:#fff,stroke-width:2px;

    class AGENT,ROUTER,TOOLS,SYNTH,GUARD ai;
    class FAST,REASON model;
    class STATE,RAG,VECTOR,BM25,FUSION,CONTEXT data;
    class WEBJWT,WSTICKET,FILTER security;
    class TRACE,STREAM ops;
    class WEB,ANSWER,DASH output;
```

### Figure legend

| Visual treatment | Meaning |
| --- | --- |
| Purple | Agentic AI orchestration, tools, synthesis, and guardrails |
| Blue | Fast versus reasoning model routes |
| Green | Structured project state and hybrid RAG evidence |
| Amber | Authentication and server-derived authorization |
| Slate | Streaming and observability |
| Teal | User-facing outputs |

Solid arrows represent the normal execution path. Dashed arrows represent
conditional, fallback, or external-input paths.

### Delivered extensions shown by the architecture

- Assistant authentication and role-based access.
- Project dashboards and normalized project state.
- Features, blockers, updates, and audit events in PostgreSQL.
- Hybrid RAG using Qdrant and Neon.
- Two-tier model routing: a fast model for classification, chitchat, and
  recovery; a reasoning model for tool selection and final grounded answers.
- Bounded LangGraph ReAct execution with mandatory project knowledge search,
  grounding checks, and safe recovery responses.
- Separation between authoritative project tools and documentation evidence.
- Persistent conversation memory and history.
- Async WebSocket streaming of workflow steps and generated tokens.
- Langfuse tracing for agent and retrieval execution.

### Key engineering decisions

- PostgreSQL is authoritative for structured project state.
- RAG supplies documentation context and evidence.
- RBAC filters are derived server-side from verified roles.
- The model cannot choose its own project or access scope.
- Project references are resolved against the caller's authorized projects.
- Agent loops, tool calls, and LLM requests are bounded.
- Fast and reasoning models are environment-swappable through
  `AGENTIC_ASSISTANT_FAST_MODEL` and `AGENTIC_ASSISTANT_REASONING_MODEL`.

### Presenter context

The important separation is between facts, context, and control flow. The fast
model classifies the request and handles conversational recovery. The bounded
ReAct loop uses the reasoning model to select authorized tools. Project tools
read authoritative structured state, while the RAG tool finds supporting
internal documentation through the server-derived access filter. The final
reasoning model synthesizes both sources, then a grounding audit either emits
the evidence-backed answer or invokes a fast recovery response. The LLM never
creates the caller's project scope or authorization filter.

## Slide 3 — Project-Scoped MCP Integration

### Secure Project Updates From Developer Coding Agents

Example Claude Code connection:

```bash
claude mcp add --transport http project-status \
  https://assistant.example.com/mcp \
  --header "Authorization: Bearer $PROJECT_MCP_TOKEN"
```

Authorization flow:

```text
Bearer token
    ↓
Hash lookup
    ↓
ProjectMcpContext
    ↓
Project-bound SQL predicates
    ↓
MCP tools
```

### Security boundary

- Human dashboard access uses assistant JWTs.
- Coding-agent access uses separate opaque project credentials.
- Credentials are stored as hashes and support expiration and revocation.
- Each credential is bound to one project.
- Project scope is resolved by the server.
- A model-supplied `project_id` is never treated as authority.
- Authentication failures and project mutations are audited.

### MCP tool groups

- Read project context and historical updates.
- Create or update features.
- Create or resolve blockers.
- Submit confirmed daily updates.

The MCP surface exposes controlled project operations rather than generic SQL
or cross-project access.

### Presenter context

The credential is deliberately narrower than a normal platform identity. A
developer's coding agent can update the project it is authorized for, but the
agent cannot use its prompt or tool arguments to switch projects.

## Slide 4 — CI/CD Pipeline

### Dependency-Aware Delivery for the Monorepo

```mermaid
flowchart LR
    PUSH[Push / Pull Request] --> DETECT[Affected Project Detection]
    DETECT --> DEP[Dependency + Consumer Closure]
    DEP --> MATRIX[Targeted CI Matrix]

    MATRIX --> FRONTEND[Frontend Lint, Build, Tests]
    MATRIX --> BACKEND[Python Ruff, Pytest, Structure Checks]
    MATRIX --> AGENT[Assistant + RAG Validation]

    FRONTEND --> GATE{Checks Pass}
    BACKEND --> GATE
    AGENT --> GATE

    GATE -->|No| BLOCK[Block Delivery]
    GATE -->|Yes| BUILD[Build Agent Docker Image]
    BUILD --> CACHE[Buildx Cache]
    CACHE --> PUBLISH[Docker Hub Publish]
    PUBLISH --> SHA[sha-*]
    PUBLISH --> LATEST[latest]
```

### Pipeline behavior

- Changed projects and transitive consumers are detected automatically.
- Documentation-only changes avoid unnecessary project fan-out.
- CI metadata changes still trigger validation.
- Node projects use pnpm; Python projects use uv.
- The agent image is built from the repository root because it consumes
  shared workspace libraries.
- Buildx enables cache-capable Docker builds.
- Successful agent-impacting changes publish `sha-*` and `latest` Docker Hub
  tags.
- The frontend deployment target is Vercel; the containerized backend is
  designed for Render deployment.

### Presenter context

The CI design follows dependency impact. A change in a shared package should
validate its consumers, while documentation-only changes should not trigger
every application check.

## Slide 5 — Technical Demo

### From Developer Activity to Project Intelligence

1. Open the project dashboard.
2. Connect a developer's coding agent to the MCP endpoint.
3. Read the authenticated project context.
4. Submit a confirmed feature or blocker update.
5. Verify the normalized state in PostgreSQL-backed project views.
6. Ask the assistant what changed, what is blocked, and what needs attention.
7. Show LangGraph combining project tools with RBAC-filtered documentation.
8. Show tokens streaming into the UI immediately.
9. Reopen a previous conversation from the history panel.
10. Show the final evidence-backed response.

### Closing message

Workalaya turns distributed developer activity and internal documentation into
scoped, traceable, and queryable project intelligence.
