# Assistant Guardrails

The agentic assistant has three input outcomes:

- `chitchat` handles greetings, thanks, and short conversational messages.
- `needs_tools` handles project intelligence and authorized enterprise knowledge
  retrieved through the assistant's role-scoped tools.
- `out_of_scope` handles unrelated requests with a deterministic warm response.

Out-of-scope requests do not invoke retrieval, tools, or another generation
call. The response explains that the assistant is built for project progress,
status, features, blockers, updates, decisions, and authorized enterprise
knowledge.

Answers generated for `needs_tools` are audited after generation. The answer
must have authorized RAG or structured project evidence, cite retrieved RAG
sources when applicable, remain tied to the resolved project, and avoid raw
tool data or authorization details. Before generation, tool JSON is redacted
of identifiers and identity material (project/call IDs, filters, claims,
tokens), so the model cannot echo them into the draft and trip the audit.
The internal-data audit only flags vocabulary the model introduced: a keyword
hit (`project_id`, `access_filter`, `authorization`, ...) is a violation only
when that term does not appear in the retrieved RAG chunks, so faithful
summaries of documentation about the assistant itself stay grounded. Actual
runtime values (claim subjects, tool call IDs, project IDs, UUID/token
shapes) are always violations. The audit reason names the matched signal
(`internal_data:<pattern>`) for log triage.
The project-scope check tolerates natural
paraphrase of the resolved project name (full name or a quorum of its
significant tokens); only answers about an unrelated project fail it. Failed
audits replace the answer with the same warm rejection template. That final
answer is persisted.

When every selected project tool returns `forbidden`, the agent falls back to
a single deterministic `search_knowledge_base` call with the full user
question before generating the final answer. The global knowledge base is
ABAC-filtered by the same access filter, so it only returns content the user
may see. The final answer is then grounded in those knowledge results (with
source citations) when they contain the information, and abstains honestly
when they do not. The grounding audit treats those fallback RAG chunks as
valid evidence, so the resolved-project-name requirement does not force a
refusal on the fallback path. If the fallback also finds nothing, the answer
stays a refusal stating the information is not accessible.

Roles with no project visibility at all (for example `employee`, which fails
the project-viewer check for every project) skip the project SQL tools
upfront: the classifier routes them straight to `search_knowledge_base`
instead of collecting guaranteed `forbidden` evidence cards. Leads keep the
project tools because their access is per-project — whether a referenced
project is theirs is only knowable by resolving it server-side — and the
fallback above covers the case where it is not.

The existing WebSocket protocol is unchanged. Generated tokens can arrive
before the audit completes; the terminal `done.answer` is authoritative and
replaces the streamed draft in the web client. A failed draft may therefore be
briefly visible before the final safe response arrives.
