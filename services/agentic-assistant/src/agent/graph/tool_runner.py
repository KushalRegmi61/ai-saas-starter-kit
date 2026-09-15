"""ToolNode adapter for structured project results and diagnostics."""

from __future__ import annotations

import json
from typing import Any

from langchain_core.messages import AIMessage, ToolMessage
from langgraph.prebuilt import ToolNode
from rag.types import SearchResult

from agent.graph.state import AgentState
from agent.types import ProjectCandidate, ProjectToolEvidence


def make_tool_runner(tool_node: ToolNode):
    """Wrap ToolNode output with project state and outcome metadata."""

    async def run_tools(state: AgentState, config=None) -> dict:
        output = await tool_node.ainvoke(state, config=config)
        messages = output.get("messages", []) if isinstance(output, dict) else []
        updates: dict[str, Any] = {"messages": messages}
        outcomes: list[dict[str, Any]] = []
        evidence: list[ProjectToolEvidence] = []
        for message in messages:
            if not isinstance(message, ToolMessage) or not message.content:
                continue
            if not message.name or not (
                message.name.startswith("get_project_")
                or message.name == "search_project_knowledge"
            ):
                continue
            try:
                payload = json.loads(str(message.content))
            except (TypeError, ValueError):
                outcomes.append(
                    {"tool": message.name, "status": "tool_error", "message": "invalid result"}
                )
                evidence.append(
                    ProjectToolEvidence(
                        tool=message.name,
                        status="validation_error",
                        message="Project tool returned an invalid result.",
                    )
                )
                continue
            resolution = payload.get("resolution", {})
            outcome = {
                "tool": message.name,
                "status": resolution.get("status", "unknown"),
                "result_count": _project_result_count(message.name, payload),
            }
            tool_evidence = _build_project_evidence(message.name, payload)
            if tool_evidence is not None:
                evidence.append(tool_evidence)
            if resolution.get("project"):
                updates["resolved_project"] = ProjectCandidate.model_validate(
                    resolution["project"]
                )
            if resolution.get("candidates"):
                updates["project_candidates"] = [
                    ProjectCandidate.model_validate(candidate)
                    for candidate in resolution["candidates"]
                ]
            if message.name == "search_project_knowledge":
                result_items = payload.get("results", [])
                updates["results"] = [
                    SearchResult.model_validate(item)
                    for item in result_items
                    if isinstance(item, dict)
                ]
                updates["sources"] = [
                    {**item.get("source", {}), "snippet": item.get("text", "")[:300]}
                    for item in result_items
                    if isinstance(item, dict) and isinstance(item.get("source"), dict)
                ]
                outcome["knowledge_result_count"] = len(result_items)
            outcomes.append(outcome)

        if outcomes:
            updates["project_tool_outcomes"] = outcomes
            updates["project_evidence"] = evidence
            updates["workflow_steps"] = [
                *state.get("workflow_steps", []),
                *[
                    f"{item['tool']}: status={item['status']} "
                    f"results={item.get('result_count', 0)}"
                    for item in outcomes
                ],
            ]
        return updates

    return run_tools


def _project_result_count(tool_name: str, payload: dict) -> int:
    if tool_name == "get_project_features":
        return len(payload.get("features", []))
    if tool_name == "get_project_blockers":
        return len(payload.get("blockers", []))
    if tool_name == "get_project_activity":
        return len(payload.get("updates", [])) + len(payload.get("history", []))
    if tool_name == "search_project_knowledge":
        return len(payload.get("results", []))
    if tool_name == "get_project_overview":
        resolved = payload.get("resolution", {}).get("project")
        return 1 if payload.get("project") or resolved else 0
    return 1 if payload.get("project") else 0


def _build_project_evidence(tool_name: str, payload: dict) -> ProjectToolEvidence | None:
    """Convert a tool envelope into bounded, safe UI evidence."""
    resolution = payload.get("resolution", {})
    status = resolution.get("status", "validation_error")
    project = resolution.get("project") or {}
    project_name = project.get("name") if isinstance(project, dict) else None
    result_count = _project_result_count(tool_name, payload)
    summary: dict[str, Any] = {}
    records: list[dict[str, Any]] = []

    if tool_name == "get_project_overview":
        summary = {
            "status": payload.get("status"),
            "completion_percentage": payload.get("completion_percentage"),
            "feature_counts": payload.get("feature_counts", {}),
            "open_blocker_count": payload.get("open_blocker_count", 0),
        }
        latest = payload.get("latest_update")
        if isinstance(latest, dict):
            summary["latest_update"] = {
                "summary": latest.get("summary"),
                "completion_percentage": latest.get("completion_percentage"),
                "created_at": latest.get("created_at"),
            }
    elif tool_name == "get_project_features":
        records = [
            {
                "name": item.get("name"),
                "description": item.get("description"),
                "status": item.get("status"),
                "updated_at": item.get("updated_at"),
            }
            for item in payload.get("features", [])[:10]
            if isinstance(item, dict)
        ]
        summary = {"feature_counts": payload.get("feature_counts", {})}
    elif tool_name == "get_project_blockers":
        records = [
            {
                "title": item.get("title"),
                "description": item.get("description"),
                "severity": item.get("severity"),
                "status": item.get("status"),
                "created_at": item.get("created_at"),
                "resolved_at": item.get("resolved_at"),
            }
            for item in payload.get("blockers", [])[:10]
            if isinstance(item, dict)
        ]
    elif tool_name == "get_project_activity":
        records = [
            {
                "kind": "update",
                "summary": item.get("summary"),
                "completion_percentage": item.get("completion_percentage"),
                "created_at": item.get("created_at"),
            }
            for item in payload.get("updates", [])[:5]
            if isinstance(item, dict)
        ]
        records.extend(
            {
                "kind": "history",
                "feature_name": item.get("feature_name"),
                "old_status": item.get("old_status"),
                "new_status": item.get("new_status"),
                "changed_at": item.get("changed_at"),
            }
            for item in payload.get("history", [])[:5]
            if isinstance(item, dict)
        )
        summary = {"update_count": len(payload.get("updates", [])), "history_count": len(payload.get("history", []))}
    elif tool_name == "search_project_knowledge":
        summary = {"query": payload.get("query"), "knowledge_result_count": result_count}
        records = [
            {
                "source": item.get("source", {}).get("source"),
                "page": item.get("source", {}).get("page"),
                "snippet": item.get("text", "")[:300],
            }
            for item in payload.get("results", [])[:10]
            if isinstance(item, dict) and isinstance(item.get("source"), dict)
        ]

    return ProjectToolEvidence(
        tool=tool_name,
        status=status,
        project_name=project_name,
        result_count=result_count,
        summary=summary,
        records=records,
        message=resolution.get("message"),
    )


def force_project_search(state: AgentState) -> dict:
    """Create a bounded fallback call when structured data was empty."""
    project = state.get("resolved_project") or {}
    reference = project.get("name", "") if isinstance(project, dict) else project.name
    # The project tool resolves natural-language references server-side. This
    # preserves a deterministic RAG call even when the model tried to answer
    # without first calling a structured project tool.
    reference = reference or state["question"]
    return {
        "messages": [
            AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": "search_project_knowledge",
                        "args": {"project_reference": reference, "query": state["question"]},
                        "id": "project-search-fallback",
                        "type": "tool_call",
                    }
                ],
            )
        ],
        "workflow_steps": [
            *state.get("workflow_steps", []),
            "project_search_fallback_called",
        ],
    }
