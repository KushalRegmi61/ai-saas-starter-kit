"""HTTP shell of the assistant service: ingest/purge routes + health probe.

Thin handlers only — the engine lives in `agent/` (graph, tools) and
`libs/rag`. Retrieval is intentionally NOT exposed here; it is an
agent-internal tool only.
"""
