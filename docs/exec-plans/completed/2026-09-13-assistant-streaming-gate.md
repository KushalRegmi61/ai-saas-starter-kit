# Assistant streaming repair + Phase 8 end-to-end gate (2026-09-13)

## Problem
WebSocket chat streaming was broken end to end: protocol drift across
backend/frontend, silent question drops, step-name mismatches, search-mode
422s, degenerate evidence cards, and — found live in this gate — three
server bugs that unit tests never caught.

## Phases
- 1 Backend `done` carries `answer` (`service/chat.py`); token `content`
  contract; 2 new `stream_chat` tests.
- 2 `connectAssistantSocket`/`assistantWsUrl` in `lib/api.ts`; hook
  delegates; stale-socket close; `.env.example` documents the API URL.
- 3 `busyRef` sync guard; loud offline/send-failure pills; clear on
  done/error/reset.
- 4 `NODE_STEP_MAP` (classify_intent/agent/tools/… → rewrite/retrieve/
  generate); `AgentStep` in `types`; step `name?`/`text?` passthrough.
- 5 `get_full_history` pairs `(turn_index, role, content, created_at)` rows
  into `{turn_index, question, answer, sources: [], created_at}`;
  `ConversationTurn` enriched to match. Per-turn sources are not persisted.
- 6 Search locked to hybrid: `SearchMode = "hybrid"`, selector removed,
  `sendAsk(q, topK)`. Standalone BM25 does not exist in retrieval
  (`search_rag` only branches on `hybrid`); `vector`/`bm25` 422d at the
  boundary. Real BM25-only would be new `libs/rag` feature work.
- 7 Evidence: tool stores `{**Source, "snippet": text[:300]}`
  (`SNIPPET_CHARS`); frontend `toEvidence()` adapter; `score?`/`snippet?`
  optional with panel fallbacks (no `NaN%`/empty quotes).
- 8 Gate fixes (all found live, all with regression tests):
  - agent-budget step crashed on non-dict `on_chain_end` output →
    `server_error` on every ReAct ask (`workflow.py` isinstance guard).
  - Parallel tool writes raised `InvalidUpdateError` on `sources` →
    `operator.add` for `sources`/`results`, last-wins for
    `workflow_steps` (`state.py`).
  - Unbounded LLM call hung a follow-up task forever →
    `AGENTIC_ASSISTANT_LLM_TIMEOUT_SECONDS` (default 120s) wired as
    `request_timeout` + `max_retries` (`config.py`, `llm.py`).

## Gate results (live, :8000 + :3001)
Cold ask → 128 tokens, full node trace, `done` + session id; follow-up →
77 tokens, session reused; history reload renders paired turns; `done`
sources carry `{source, page, chunk_index, score, snippet}`; bogus ticket
→ 4401 close; `pytest` 97 passed; `ruff`, `eslint`, `tsc` clean.

## Known limitations (not fixed)
- `grounded` is false when the answer paraphrases without naming the source
  file (`check_grounding` needs the literal filename or "do not know").
- Retrieval is slow (~25–30s per search: embed + Qdrant scroll + BM25 + RRF).
  Perf work is a separate effort.
- `messages` full-state returns re-append under the add reducer (latent,
  harmless today: turns end at `generate_final`, next turn reloads from DB).
- Rapid same-socket follow-ups (< teardown window) get a loud
  `request_in_progress`, never a silent drop. Real typing latency avoids it.
- E2E fixture doc (`e2e-timeoff-policy.txt`, tenant `api`) indexed for the
  gate, then purged (`{"purged": true}`).
