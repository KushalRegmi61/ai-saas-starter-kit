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
tool data or authorization details. Failed audits replace the answer with the
same warm rejection template. That final answer is persisted.

The existing WebSocket protocol is unchanged. Generated tokens can arrive
before the audit completes; the terminal `done.answer` is authoritative and
replaces the streamed draft in the web client. A failed draft may therefore be
briefly visible before the final safe response arrives.
