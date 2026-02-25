"""
graph/graph.py — LangGraph 그래프 빌드

흐름:
  Start → planner → [conditional_edge]
                      ├─ "need_execution" → executor → planner (루프)
                      └─ "final_answer"   → END

Human-in-the-loop:
  interrupt_before=["executor"] 설정으로 executor 진입 직전에 그래프를 멈춥니다.
  app.py가 승인 UI를 보여준 뒤:
    - 승인: Command(resume=None) → executor 정상 실행
    - 거절: Command(resume="rejected") → planner로 재라우팅 (향후 확장 가능)
"""
from __future__ import annotations

import functools
from typing import Any

from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, StateGraph

from graph.nodes import executor_node, planner_node
from graph.state import AgentState

# planner-executor 루프 최대 반복 횟수 (Over-planning / 무한루프 방지)
MAX_ITERATIONS = 5


# ── Conditional Edge ──────────────────────────────────────────────────────────
def route_after_planner(state: AgentState) -> str:
    """Planner 실행 후 분기 결정

    iteration_count가 MAX_ITERATIONS를 초과하면 pending_tool_calls가 있어도
    END로 강제 라우팅하여 무한루프를 차단합니다.
    """
    if state.get("iteration_count", 0) >= MAX_ITERATIONS:
        # 루프 한도 초과 — 강제 종료
        print(f"[Guard] iteration_count={state.get('iteration_count')} >= MAX_ITERATIONS={MAX_ITERATIONS}, 강제 종료")
        return "final_answer"
    if state.get("pending_tool_calls"):
        return "need_execution"
    return "final_answer"


# ── 그래프 빌드 ───────────────────────────────────────────────────────────────
def build_graph(llm_with_tools: Any, tools_map: dict) -> Any:
    """
    컴파일된 LangGraph를 반환합니다.

    Args:
        llm_with_tools: bind_tools()가 완료된 AzureChatOpenAI 인스턴스
        tools_map:      {tool_name: tool_callable} 딕셔너리
    """
    builder = StateGraph(AgentState)

    # ── 노드 등록 ──────────────────────────────────────────────
    builder.add_node(
        "planner",
        functools.partial(planner_node, llm_with_tools=llm_with_tools),
    )
    builder.add_node(
        "executor",
        functools.partial(executor_node, tools_map=tools_map),
    )

    # ── 진입점 ────────────────────────────────────────────────
    builder.set_entry_point("planner")

    # ── Planner → Conditional Edge ────────────────────────────
    builder.add_conditional_edges(
        "planner",
        route_after_planner,
        {
            "need_execution": "executor",
            "final_answer": END,
        },
    )

    # ── Executor → Planner 루프백 ─────────────────────────────
    builder.add_edge("executor", "planner")

    # ── 컴파일: executor 직전에 interrupt → 승인 UI 표시 ──────
    checkpointer = MemorySaver()
    return builder.compile(
        checkpointer=checkpointer,
        interrupt_before=["executor"],
    )
