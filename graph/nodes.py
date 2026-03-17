"""
graph/nodes.py — LangGraph 노드 구현

노드 구성:
  - router_node : 사용자 질문을 도메인(eai/eigw/mcg/apply/all)으로 분류하여
                  사용할 도구 목록을 state에 기록 (경량 LLM 호출)
  - planner_node : router가 선택한 도구만 bind_tools한 뒤 의도 파악 및 도구 호출 결정
  - executor_node : 승인된 Tool을 실제로 호출하고 결과를 messages에 추가
"""
from __future__ import annotations

import json
from typing import Any

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from pydantic import BaseModel, Field

from graph.state import AgentState


# ── 도메인별 도구 접두사 매핑 ─────────────────────────────────────────────────
# 도구 이름의 접두사(prefix)를 기준으로 카테고리를 분류합니다.
# 새 도구를 추가할 때 이 맵만 갱신하면 됩니다.
CATEGORY_PREFIXES: dict[str, list[str]] = {
    "eai":  ["get_queue_depth", "get_eai_", "get_statistic_hourly_eai",
             "get_statistic_daily_eai", "get_statistic_monthly_eai"],
    "eigw": ["get_eigw_", "get_statistic_hourly_eigw",
             "get_statistic_daily_eigw", "get_statistic_monthly_eigw"],
    "mcg":  ["get_mcg_", "get_statistic_hourly_mcg",
             "get_statistic_daily_mcg", "get_statistic_monthly_mcg"],
    "apply": ["get_interface_request", "create_interface_request",
               "save_eai_interface", "save_eigw_interface",
               "save_interface_request", "search_chargr",
               "search_eigw_out_chargr", "search_interface_request",
               "get_eai_interface_request", "get_eigw_interface_request",
               "get_interface_request_detail"],
}

# 카테고리 무관하게 항상 포함할 공통 도구
COMMON_TOOLS: list[str] = [
    "get_date_range",
    "search_institution_code",
]


def _tools_for_categories(categories: list[str], tools_map: dict) -> list[str]:
    """
    선택된 카테고리 목록에 해당하는 도구 이름을 tools_map에서 찾아 반환합니다.
    'all' 카테고리이면 전체 도구를 반환합니다.
    공통 도구(COMMON_TOOLS)는 항상 포함됩니다.
    """
    if "all" in categories:
        return list(tools_map.keys())

    selected: set[str] = set(COMMON_TOOLS) & set(tools_map.keys())
    for cat in categories:
        prefixes = CATEGORY_PREFIXES.get(cat, [])
        for tool_name in tools_map:
            if any(tool_name.startswith(p) for p in prefixes):
                selected.add(tool_name)

    return list(selected)


# ── Pydantic 스키마 — Router 출력 ─────────────────────────────────────────────
class RouterOutput(BaseModel):
    """시맨틱 라우터의 구조화된 출력 스키마."""

    categories: list[str] = Field(
        description=(
            "사용자 질문과 관련된 도메인 카테고리 목록.\n"
            "가능한 값: 'eai', 'eigw', 'mcg', 'apply', 'all'\n"
            "- eai   : EAI 모니터링/통계 관련 질의\n"
            "- eigw  : EIGW 모니터링/통계/오류 관련 질의\n"
            "- mcg   : MCG 모니터링/통계 관련 질의\n"
            "- apply : 인터페이스 신청, EAI/EIGW 신청, 기존 신청 조회 관련 질의\n"
            "- all   : 여러 도메인에 걸치거나 분류 불가한 경우 (Fallback)\n"
            "복수 도메인 선택 가능: 예) ['eai', 'eigw']"
        )
    )


# ── Router Node ───────────────────────────────────────────────────────────────
async def router_node(state: AgentState, llm: Any, tools_map: dict) -> dict:
    """
    사용자 질문을 분석하여 관련 도메인 카테고리를 분류합니다.

    - 최근 HumanMessage를 기반으로 경량 LLM 호출(with_structured_output)을 수행합니다.
    - 분류된 카테고리에 해당하는 도구 이름 목록을 state["selected_tools"]에 저장합니다.
    - 매 새 질의마다 덮어써서 이전 턴 상태를 자동 초기화합니다.
    - executor → planner 루프백 시에는 이 노드를 거치지 않으므로 선택된 도구가 보존됩니다.
    """
    # 가장 최근 HumanMessage 추출
    last_human = ""
    for msg in reversed(state.get("messages", [])):
        if isinstance(msg, HumanMessage) and msg.content:
            last_human = msg.content
            break

    router_system = (
        "당신은 사용자 질문을 분석하여 관련 도메인을 분류하는 라우터입니다.\n"
        "아래 카테고리 중에서 해당하는 것을 모두 선택하세요.\n"
        "- eai   : EAI 연동량, 큐 적체, EAI 통계/모니터링\n"
        "- eigw  : EIGW 오류, 응답속도, 연동량, EIGW 통계/모니터링\n"
        "- mcg   : MCG 채널 상태, TPS, MCG 통계/모니터링\n"
        "- apply : 인터페이스 신청, EAI/EIGW 신청, 기존 신청서 조회\n"
        "- all   : 여러 도메인에 걸치거나 도메인을 특정할 수 없는 경우\n"
        "복수 선택이 가능합니다. 불명확하면 all을 선택하세요.\n\n"
        "[용어 해석 주의]\n"
        "- 사용자가 'MQ' 또는 '큐' 또는 '적체'라고 언급하면 이는 EAI의 MQ 큐를 의미합니다. MCG가 아닌 eai 카테고리를 선택하세요."
    )

    router_llm = llm.with_structured_output(RouterOutput)
    result: RouterOutput = await router_llm.ainvoke([
        {"role": "system", "content": router_system},
        {"role": "user",   "content": last_human},
    ])

    categories = result.categories or ["all"]

    # 카테고리 유효성 보정
    valid_cats = {"eai", "eigw", "mcg", "apply", "all"}
    categories = [c for c in categories if c in valid_cats] or ["all"]

    selected_tools = _tools_for_categories(categories, tools_map)
    print(f"[Router] categories={categories}, tools({len(selected_tools)})={selected_tools}")

    return {"selected_tools": selected_tools}


# ── Planner Node ──────────────────────────────────────────────────────────────
async def planner_node(state: AgentState, llm: Any, tools_map: dict) -> dict:
    """
    사용자 의도를 파악하고 Tool 호출 계획을 수립합니다.
    router_node가 state["selected_tools"]에 저장한 도구만 동적으로 바인딩합니다.

    - tool_calls 있음 → pending_tool_calls에 저장, Executor로 이동
    - tool_calls 없음 → 직접 최종 답변
    """
    current_iter = state.get("iteration_count", 0) + 1

    selected = state.get("selected_tools") or list(tools_map.keys())
    bound_tools = [tools_map[name] for name in selected if name in tools_map]
    bound_llm = llm.bind_tools(bound_tools)

    response: AIMessage = await bound_llm.ainvoke(state["messages"])

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
