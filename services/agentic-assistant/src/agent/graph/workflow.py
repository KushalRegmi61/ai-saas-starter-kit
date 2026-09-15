"""Parent ReAct agent graph + stream_graph() event translator.

Graph topology:

    START
      └─► classify_intent
            ├─[chitchat]──► chitchat_respond ──► END
            ├─[out_of_scope]──► out_of_scope ──► END
            └─[needs_tools]► agent ◄────────────────┐
                              │                      │
                         [tools & under budget]      │
                              └──► tools ────────────┘
                         [no tool_calls | budget hit]
                              └──► generate_final ──► END

stream_graph() replaces streaming.py — pure event translator:
  on_chat_model_stream (not from classify) → token event
  node transitions                         → step event
  LangGraph chain end                      → done event (grounding already in state)

No generation logic lives here. All generation is in nodes via agent/llm.py.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from functools import lru_cache

from auth.types import AssistantClaims
from langchain_core.messages import AIMessage
from langgraph.graph import END, StateGraph
from langgraph.prebuilt import ToolNode
from rag.types import AccessFilter, SearchMode

from agent.config import get_agent_settings
from agent.graph.nodes.agent import agent_node
from agent.graph.nodes.chitchat import chitchat_respond
from agent.graph.nodes.classify import classify_intent
from agent.graph.nodes.generate_final import generate_final
from agent.graph.nodes.out_of_scope import out_of_scope
from agent.graph.nodes.routing import route_after_agent, route_after_classify
from agent.graph.state import AgentState, make_initial_state
from agent.graph.tool_runner import force_global_search, force_project_search, make_tool_runner
from agent.llm import _content_text
from agent.tracing import get_langchain_callbacks, trace_span
from agent.types import AskResponse

logger = logging.getLogger(__name__)

# Nodes whose start events emit a step to the client
_STEP_NODES = frozenset(
    {"classify_intent", "chitchat_respond", "out_of_scope", "agent", "tools", "generate_final"}
)
_GENERATION_NODES = frozenset({"chitchat_respond", "generate_final"})


# --------------------------------------------------------------------------- #
# Graph factory                                                                #
# --------------------------------------------------------------------------- #


@lru_cache(maxsize=1)
def get_agent_graph():
    """Compile and cache the parent ReAct agent graph."""
    import agent.tools as tools_mod  # triggers tool self-registration

    all_tools = tools_mod.get_all_tools()
    tool_node = ToolNode(all_tools)  # ABAC injection via InjectedState at call time

    graph = StateGraph(AgentState)
    graph.add_node("classify_intent", classify_intent)
    graph.add_node("chitchat_respond", chitchat_respond)
    graph.add_node("out_of_scope", out_of_scope)
    graph.add_node("agent", agent_node)
    graph.add_node("tools", make_tool_runner(tool_node))
    graph.add_node("force_project_search", force_project_search)
    graph.add_node("force_global_search", force_global_search)
    graph.add_node("generate_final", generate_final)

    graph.set_entry_point("classify_intent")
    graph.add_conditional_edges(
        "classify_intent",
        route_after_classify,
        {
            "chitchat": "chitchat_respond",
            "out_of_scope": "out_of_scope",
            "needs_tools": "agent",
        },
    )
    graph.add_edge("chitchat_respond", END)
    graph.add_edge("out_of_scope", END)
    graph.add_conditional_edges(
        "agent",
        route_after_agent,
        {
            "tools": "tools",
            "force_project_search": "force_project_search",
            "force_global_search": "force_global_search",
            "generate": "generate_final",
        },
    )
    graph.add_edge("force_project_search", "tools")
    graph.add_edge("force_global_search", "tools")
    graph.add_edge("tools", "agent")
    graph.add_edge("generate_final", END)

    compiled = graph.compile()
    logger.info("workflow: graph compiled nodes=%s", list(graph.nodes))
    return compiled


# --------------------------------------------------------------------------- #
# stream_graph — pure event translator (replaces streaming.py)               #
# --------------------------------------------------------------------------- #


async def stream_graph(
    question: str,
    *,
    top_k: int = 4,
    search_mode: SearchMode = "auto",
    access_filter: AccessFilter | None = None,
    conversation_history: list[dict] | None = None,
    memory_summary: str = "",
    claims: AssistantClaims | None = None,
    pool=None,
) -> AsyncIterator[dict]:
    """Translate LangGraph events into WebSocket protocol events.

    Yields:
      {"type": "step",  "name": <node>, "text": <description>}
      {"type": "token", "content": <token_text>}
      {"type": "done",  "answer": ..., "sources": ..., "grounded": ...,
                        "workflow_steps": [...]}

    No generation logic here. All streaming happens inside nodes via
    agent/llm.py stream_response(). This function only translates events.

    access_filter is set once from JWT claims and never mutated.
    ToolNode injects it into tools via InjectedState — LLM never sees it.
    """
    settings = get_agent_settings()
    if not settings.openai_api_key:
        logger.warning("workflow: stream_graph rejected, OPENAI_API_KEY missing")
        raise ValueError("OPENAI_API_KEY is missing. Set it before asking questions.")

    logger.info(
        "workflow: stream start question_len=%d top_k=%d mode=%s history=%d",
        len(question),
        top_k,
        search_mode,
        len(conversation_history or []),
    )
    initial_state = make_initial_state(
        question,
        access_filter=access_filter,
        conversation_history=conversation_history,
        memory_summary=memory_summary,
        claims=claims,
        pool=pool,
        search_mode=search_mode,
    )
    initial_state["workflow_steps"] = ["started agent workflow"]

    graph = get_agent_graph()

    with trace_span(
        name="agent_ask_stream",
        input_data={"question": question, "top_k": top_k},
        metadata={"operation": "agent_ask_stream", "top_k": top_k},
    ) as span:
        final_output: dict = {}
        async for event in graph.astream_events(
            initial_state,
            version="v2",
            config={"callbacks": get_langchain_callbacks()},
        ):
            kind: str = event["event"]
            name: str = event.get("name", "")
            metadata: dict = event.get("metadata", {})
            node_name: str = metadata.get("langgraph_node", "") or name

            # Node start → step event
            if kind == "on_chain_start" and node_name in _STEP_NODES:
                logger.info("workflow: node start name=%s", node_name)
                yield {
                    "type": "step",
                    "name": node_name,
                    "text": _step_label(node_name),
                }

            # Track active node for token suppression
            # Token stream → token event (generation nodes only)
            elif kind == "on_chat_model_stream":
                # Read the node from this event rather than mutable global state;
                # LangGraph may interleave nested runnable events.
                if node_name in _GENERATION_NODES:
                    chunk = event["data"].get("chunk")
                    if chunk is not None:
                        token = _content_text(chunk.content)
                        if token:
                            yield {"type": "token", "content": token}

            # Agent budget step event. The end payload is not always the
            # state-update dict (inner runnables report plain outputs), so
            # only render counts when the shape allows — the start step
            # already covers the thinking indicator otherwise.
            elif kind == "on_chain_end" and node_name == "agent":
                output = event["data"].get("output", {})
                if isinstance(output, dict):
                    from agent.graph.nodes.agent import MAX_ITERATIONS, MAX_LOOP_TOKENS

                    yield {
                        "type": "step",
                        "name": "agent_budget",
                        "text": (
                            f"reasoning: {output.get('tool_call_count', 0)}/{MAX_ITERATIONS} steps, "
                            f"{output.get('loop_tokens_used', 0)}/{MAX_LOOP_TOKENS} tokens"
                        ),
                    }
                else:
                    logger.debug(
                        "workflow: agent end output is %s, skipping budget step",
                        type(output).__name__,
                    )

            # Top-level graph end → capture final state
            elif kind == "on_chain_end" and name == "LangGraph":
                final_output = event["data"].get("output", {})

        # Done — grounding already run by nodes, answer already in state
        if not final_output:
            logger.warning("stream_graph: graph ended without final output")
            yield {
                "type": "done",
                "answer": "I was unable to complete the request.",
                "sources": [],
                "project_evidence": [],
                "grounded": False,
                "rewritten_question": None,
                "workflow_steps": initial_state["workflow_steps"],
            }
            return

        # Extract final answer — nodes set state["answer"] directly
        answer = final_output.get("answer", "")
        if not answer:
            # Fallback: last AIMessage content (should not happen with generate_final)
            for msg in reversed(final_output.get("messages", [])):
                if isinstance(msg, AIMessage) and msg.content:
                    answer = str(msg.content)
                    break

        result = {
            "type": "done",
            "answer": answer,
            "sources": final_output.get("sources", []),
            "project_evidence": [
                evidence.model_dump(mode="json") if hasattr(evidence, "model_dump") else evidence
                for evidence in final_output.get("project_evidence", [])
            ],
            "grounded": final_output.get("grounded", False),
            "rewritten_question": None,
            "workflow_steps": final_output.get("workflow_steps", []),
        }
        span["output"] = {
            "answer_length": len(answer),
            "sources_count": len(result["sources"]),
            "grounded": result["grounded"],
            "workflow_steps": len(result["workflow_steps"]),
        }
        logger.info(
            "workflow: stream done answer_len=%d sources=%d grounded=%s steps=%d",
            len(answer),
            len(result["sources"]),
            result["grounded"],
            len(result["workflow_steps"]),
        )
        yield result


# --------------------------------------------------------------------------- #
# Sync ask() — for tests and non-streaming callers                            #
# --------------------------------------------------------------------------- #


def ask(
    question: str,
    *,
    top_k: int = 4,
    search_mode: SearchMode = "auto",
    access_filter: AccessFilter | None = None,
    conversation_history: list[dict] | None = None,
    memory_summary: str | None = None,
    claims: AssistantClaims | None = None,
    pool=None,
) -> AskResponse:
    """Run the agent graph synchronously (tests + non-streaming callers)."""
    settings = get_agent_settings()
    if not settings.openai_api_key:
        logger.warning("workflow: ask rejected, OPENAI_API_KEY missing")
        raise ValueError("OPENAI_API_KEY is missing.")

    logger.info("workflow: ask start question_len=%d mode=%s", len(question), search_mode)
    with trace_span("agent_ask", input_data={"question": question}) as span:
        initial_state = make_initial_state(
            question,
            access_filter=access_filter,
            conversation_history=conversation_history,
            memory_summary=memory_summary or "",
            claims=claims,
            pool=pool,
            search_mode=search_mode,
        )
        initial_state["workflow_steps"] = ["started agent workflow"]
        final_state = get_agent_graph().invoke(
            initial_state,
            config={"callbacks": get_langchain_callbacks()},
        )

        answer = final_state.get("answer", "")
        if not answer:
            for msg in reversed(final_state.get("messages", [])):
                if isinstance(msg, AIMessage) and msg.content:
                    answer = str(msg.content)
                    break

        response = AskResponse(
            answer=answer,
            sources=[],
            grounded=final_state.get("grounded", False),
            workflow_steps=final_state.get("workflow_steps", []),
        )
        span["output"] = {"answer_length": len(answer), "grounded": response.grounded}
        logger.info("workflow: ask done answer_len=%d grounded=%s", len(answer), response.grounded)
        return response


def _step_label(node_name: str) -> str:
    return {
        "classify_intent": "classifying intent",
        "chitchat_respond": "generating response",
        "out_of_scope": "scope rejection",
        "agent": "agent reasoning",
        "tools": "executing tools",
        "generate_final": "generating final answer",
    }.get(node_name, node_name)
