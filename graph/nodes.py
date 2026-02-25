"""
graph/nodes.py — LangGraph 노드 구현

노드 구성:
  - planner_node : LLM에 Tool을 바인딩, 의도 파악 후 Tool 호출 선택 또는 직접 답변
  - executor_node : 승인된 Tool을 실제로 호출하고 결과를 messages에 추가
"""
from __future__ import annotations

import json
from typing import Any

from langchain_core.messages import AIMessage, ToolMessage

from graph.state import AgentState


# ── Planner Node ──────────────────────────────────────────────────────────────
async def planner_node(state: AgentState, llm_with_tools: Any) -> dict:
    """
    사용자 의도를 파악하고 Tool 호출 계획을 수립합니다.
    - tool_calls 있음 → pending_tool_calls에 저장, Executor로 이동
    - tool_calls 없음 → 직접 최종 답변
    """
    current_iter = state.get("iteration_count", 0) + 1
    response: AIMessage = await llm_with_tools.ainvoke(state["messages"])

    if response.tool_calls:
        pending = [
            {"id": tc["id"], "name": tc["name"], "args": tc["args"]}
            for tc in response.tool_calls
        ]
        plan = "\n".join(
            f"• {tc['name']}({json.dumps(tc['args'], ensure_ascii=False)})"
            for tc in pending
        )
        return {
            "messages": [response],
            "pending_tool_calls": pending,
            "plan": plan,
            "iteration_count": current_iter,
        }
    else:
        return {
            "messages": [response],
            "pending_tool_calls": [],
            "plan": "",
            "iteration_count": current_iter,
        }


# ── Executor Node ─────────────────────────────────────────────────────────────
async def executor_node(state: AgentState, tools_map: dict) -> dict:
    """
    pending_tool_calls의 Tool을 실제로 실행하고 ToolMessage를 messages에 추가합니다.
    execution_rejected=True인 경우 실제 실행 없이 "거절됨" ToolMessage를 생성하여
    messages를 항상 올바른 시퀀스(AIMessage→ToolMessage)로 유지합니다.
    """
    tool_messages = []
    results_summary = []

    # 거절된 경우: 모든 pending tool에 대해 "거절됨" ToolMessage 생성
    if state.get("execution_rejected", False):
        for tc in state.get("pending_tool_calls", []):
            tool_messages.append(
                ToolMessage(
                    content="사용자가 Tool 실행을 거절했습니다. 다른 방법을 안내해주세요.",
                    tool_call_id=tc["id"],
                )
            )
        return {
            "messages": tool_messages,
            "pending_tool_calls": [],
            "tool_results": [],
            "execution_rejected": False,
        }

    # 승인된 경우: 실제 Tool 실행
    for tc in state.get("pending_tool_calls", []):
        tool_name = tc["name"]
        tool_args = tc["args"]
        tool_call_id = tc["id"]

        if tool_name not in tools_map:
            content = f"[오류] 알 수 없는 Tool: {tool_name}"
        else:
            try:
                raw = await tools_map[tool_name].ainvoke(tool_args)
                if isinstance(raw, list):
                    content = "\n".join(
                        item.get("text", str(item)) if isinstance(item, dict) else str(item)
                        for item in raw
                    )
                elif isinstance(raw, dict):
                    content = json.dumps(raw, ensure_ascii=False)
                else:
                    content = str(raw)
                results_summary.append({"tool": tool_name, "result": content[:200]})
            except Exception as e:
                content = f"[오류] {tool_name}: {type(e).__name__}: {e}"

        tool_messages.append(
            ToolMessage(content=content, tool_call_id=tool_call_id)
        )

    return {
        "messages": tool_messages,
        "pending_tool_calls": [],
        "tool_results": results_summary,
        "execution_rejected": False,
    }
