"""HTTP runtime: ingest/purge routes (service-token gated) + health probe.

Retrieval is intentionally NOT exposed here — it is an agent-internal tool
only. User-facing auth lands with the auth session; until then this surface
is machine-to-machine plus an open health check.
"""
