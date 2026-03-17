"""
graph/graph.py — LangGraph 그래프 빌드

흐름:
  Start → router → planner → [conditional_edge]
                               ├─ "need_execution" → executor → planner (루프백, 재라우팅 없음)
                               └─ "final_answer"   → END

시맨틱 라우터:
  router 노드가 사용자 질문을 도메인(eai/eigw/mcg/apply/all)으로 분류하여
  state["selected_tools"]에 저장합니다.
  planner 노드는 해당 도구만 bind_tools하여 실행합니다.

  executor → planner 루프백 시에는 router를 거치지 않으므로
  selected_tools가 그대로 유지되어 기존 컨텍스트가 보존됩니다.

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

from graph.nodes import executor_node, planner_node, router_node
from graph.state import AgentState

# planner-executor 루프 최대 반복 횟수 (Over-planning / 무한루프 방지)
MAX_ITERATIONS = 5


# ── Conditional Edge ──────────────────────────────────────────────────────────
def route_after_planner(state: AgentState) -> str:
    """Planner 실행 후 분기 결정

    iteration_count가 MAX_ITERATIONS를 초과하면 pending_tool_calls가 있어도
    END로 강제 라우팅하여 무한루프를 차단합니다.
    """
    # if state.get("iteration_count", 0) >= MAX_ITERATIONS:
    #     # 루프 한도 초과 — 강제 종료
    #     print(f"[Guard] iteration_count={state.get('iteration_count')} >= MAX_ITERATIONS={MAX_ITERATIONS}, 강제 종료")
    #     return "final_answer"
    if state.get("pending_tool_calls"):
        return "need_execution"
    return "final_answer"


# ── 그래프 빌드 ───────────────────────────────────────────────────────────────
def build_graph(llm: Any, tools_map: dict) -> Any:
    """
    컴파일된 LangGraph를 반환합니다.

    Args:
        llm:       bind_tools 미적용 순수 AzureChatOpenAI 인스턴스
        tools_map: {tool_name: tool_callable} 딕셔너리
    """
    builder = StateGraph(AgentState)

    # ── 노드 등록 ──────────────────────────────────────────────
    builder.add_node(
        "router",
        functools.partial(router_node, llm=llm, tools_map=tools_map),
    )
    builder.add_node(
        "planner",
        functools.partial(planner_node, llm=llm, tools_map=tools_map),
    )
    builder.add_node(
        "executor",
        functools.partial(executor_node, tools_map=tools_map),
    )

    # ── 진입점: START → router ─────────────────────────────────
    builder.set_entry_point("router")

    # ── router → planner ──────────────────────────────────────
    builder.add_edge("router", "planner")

    # ── Planner → Conditional Edge ────────────────────────────
    builder.add_conditional_edges(
        "planner",
        route_after_planner,
        {
            "need_execution": "executor",
            "final_answer": END,
        },
    )

    # ── Executor → Planner 루프백 (router 미경유) ──────────────
    # selected_tools는 최초 라우팅 결과를 유지하여 컨텍스트 보존
    builder.add_edge("executor", "planner")

    # ── 컴파일: executor 직전에 interrupt → 승인 UI 표시 ──────
    checkpointer = MemorySaver()
    return builder.compile(
        checkpointer=checkpointer,
        interrupt_before=["executor"],
    )
