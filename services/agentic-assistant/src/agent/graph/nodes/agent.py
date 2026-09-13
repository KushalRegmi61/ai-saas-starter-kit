"""ReAct agent node.

One Thought→(Action) iteration. On each call:
  1. Binds classifier-selected tools to the LLM
  2. Invokes async with full message history (Thought)
  3. LLM returns AIMessage with tool_calls (→ Action) or plain content (→ Final Answer)
  4. Tracks iteration count + cumulative token usage for budget enforcement

Uses invoke_with_tools() from agent.llm — async, no streaming on this call
(the agent's reasoning/tool-selection step is not streamed to the client).

ReAct system prompt injected once on the first iteration (tool_call_count=0).
Subsequent iterations use message history as-is.

ABAC: access_filter stays in AgentState. ToolNode injects it into each tool
call via InjectedState. This node never reads or passes the filter.
"""

from __future__ import annotations

import logging

from langchain_core.messages import BaseMessage, SystemMessage
from langchain_core.runnables import RunnableConfig

from agent.graph.state import AgentState
from agent.llm import invoke_with_tools

logger = logging.getLogger(__name__)

MAX_ITERATIONS: int = 5
MAX_LOOP_TOKENS: int = 4000

_REACT_SYSTEM_TEMPLATE = """\
You are a helpful enterprise knowledge assistant that reasons step by step.

{memory_block}\
Follow the ReAct pattern:
  Thought: reason about what you know and what you need to find out
  Action: call the appropriate tool if more information is needed
  Observation: read the tool result and update your reasoning
  ... repeat as needed ...
  Final Answer: when you have sufficient information, answer the user directly

Guidelines:
- Be precise in tool queries — use specific, self-contained questions
- Cite sources from the context in your final answer
- If the knowledge base does not contain an answer, say so honestly
- Do not fabricate information not present in tool results

Budget status: {iterations}/{max_iterations} steps, {tokens_used}/{max_tokens} tokens.
{budget_warning}"""

_BUDGET_WARNING = (
    "\n⚠ Near reasoning budget — synthesise the best answer from information "
    "already retrieved rather than making additional tool calls.\n"
)


async def agent_node(state: AgentState, config: RunnableConfig | None = None) -> dict:
    """ReAct reasoning node — one Thought→(Action) iteration."""
    import agent.tools as tools_mod

    iterations = state.get("tool_call_count", 0)
    logger.info(
        "node agent: start iteration=%d tokens_used=%d", iterations, state.get("loop_tokens_used", 0)
    )
    selected = state.get("selected_tools") or []
    tool_fns = (
        tools_mod.get_tools_by_name(selected) if selected else tools_mod.get_all_tools()
    )

    tokens_used = state.get("loop_tokens_used", 0)
    near_budget = iterations >= MAX_ITERATIONS - 1 or tokens_used >= MAX_LOOP_TOKENS - 500

    messages: list[BaseMessage] = list(state.get("messages", []))
    if iterations == 0:
        system = _REACT_SYSTEM_TEMPLATE.format(
            memory_block=_build_memory_block(state),
            iterations=iterations,
            max_iterations=MAX_ITERATIONS,
            tokens_used=tokens_used,
            max_tokens=MAX_LOOP_TOKENS,
            budget_warning=_BUDGET_WARNING if near_budget else "",
        )
        messages = [SystemMessage(content=system), *messages]

    response = await invoke_with_tools(
        messages, tool_fns, config=config
    )

    usage = getattr(response, "usage_metadata", None)
    if isinstance(usage, dict):
        tokens_this_call = usage.get("total_tokens", 0)
    else:
        tokens_this_call = getattr(usage, "total_tokens", 0) if usage else 0

    new_iterations = iterations + 1
    new_tokens = tokens_used + tokens_this_call
    has_calls = bool(getattr(response, "tool_calls", []))

    logger.info(
        "node agent: done iteration=%d/%d tokens_total=%d has_tool_calls=%s",
        new_iterations,
        MAX_ITERATIONS,
        new_tokens,
        has_calls,
    )

    return {
        **state,
        "messages": [response],
        "tool_call_count": new_iterations,
        "loop_tokens_used": new_tokens,
        "workflow_steps": [
            *state.get("workflow_steps", []),
            f"agent: iteration={new_iterations}/{MAX_ITERATIONS} "
            f"tokens={new_tokens}/{MAX_LOOP_TOKENS} tool_calls={has_calls}",
        ],
    }


def _build_memory_block(state: AgentState) -> str:
    parts: list[str] = []
    if state.get("memory_summary"):
        parts.append(f"Conversation summary:\n{state['memory_summary']}\n\n")
    history = state.get("conversation_history", [])
    if history:
        lines = [
            f"{'User' if t.get('role') == 'user' else 'Assistant'}: {t.get('content', '')}"
            for t in history[-6:]
        ]
        parts.append("Recent conversation:\n" + "\n".join(lines) + "\n\n")
    return "".join(parts)
