# Agentic-assistant WebSocket chat and conversation memory

**Status: implemented 2026-09-12.**

The agentic-assistant now exposes a persistent authenticated `WS /ask` surface.
Clients exchange a normal assistant JWT for a short-lived WebSocket ticket at
`POST /auth/ws-ticket`, authenticate that ticket in the first WebSocket frame,
and then send multiple sequential `ask` messages. The server emits workflow
steps and answer tokens and persists the exchange before the final `done` event.

Conversation data is stored in Neon alongside assistant identity and RAG
metadata. Every user and assistant turn is retained for the owning subject.
The prompt memory window defaults to six turns and is supplemented by an LLM-
generated rolling summary. `tiktoken` keeps the summary plus recent turns under
the configured memory budget; summary failures fall back to the newest raw
turns without losing stored history.

The implementation uses only `AGENTIC_ASSISTANT_*` names for agent-owned
settings, including history, memory, and WebSocket ticket TTL controls. Shared
provider settings such as `OPENAI_*` remain global.

Verification includes WebSocket ticket isolation, persistent socket behavior,
concurrent-request rejection, async token streaming, ownership checks,
six-turn memory, summary compaction, fallback behavior, pool cleanup, and the
existing assistant auth/ingestion/workflow suites.
