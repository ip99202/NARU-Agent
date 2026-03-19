"""
graph/nodes.py — LangGraph 노드 구현

노드 구성:
  - router_node : 사용자 질문을 도메인(eai/eigw/mcg/apply/all)으로 분류하여
                  사용할 도구 목록을 state에 기록 (최소한의 LLM 호출)
                  매 새 메시지마다 iteration_count / last_plan_signature 리셋
  - planner_node : router가 선택한 도구만 bind_tools한 뒤 의도 파악 및 도구 호출 결정
                   Self-Correction: last_tool_error 기반 수정 힌트 주입
                   Stagnation 감지: 동일 tool+args 반복 시 graceful 종료
                   error_retries >= MAX_RETRIES 시 graceful 종료
  - executor_node : 승인된 Tool을 실제로 호출하고 결과를 messages에 추가
                    오류 발생 시 error_retries / last_tool_error 상태 업데이트
"""
from __future__ import annotations

import json
import logging
from typing import Annotated, Any, TypedDict

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage

from graph.state import AgentState

# ── 로깅 설정 ──────────────────────────────────────────────────────────────────
logger = logging.getLogger("naru.agent")

# ── 상수 ───────────────────────────────────────────────────────────────────────
MAX_RETRIES = 3  # Self-Correction 최대 재시도 횟수


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


def _plan_signature(tool_calls: list) -> str:
    """
    tool_calls 리스트를 정렬된 문자열 시그니처로 변환합니다.
    동일한 tool + 동일한 args 조합이면 동일한 시그니처를 반환합니다.
    Stagnation(무한루프) 감지에 사용합니다.
    """
    return "|".join(
        f"{tc['name']}:{json.dumps(tc['args'], sort_keys=True, ensure_ascii=False)}"
        for tc in sorted(tool_calls, key=lambda x: x["name"])
    )


# ── TypedDict 스키마 — Router 출력 ───────────────────────────────────────────
# Pydantic BaseModel 대신 TypedDict를 사용합니다.
# with_structured_output이 내부적으로 parsed 필드에 인스턴스를 붙일 때
# Pydantic V2가 직렬화 경고를 내는 업스트림 이슈를 회피합니다.
class RouterOutput(TypedDict):
    categories: Annotated[
        list[str],
        (
            "사용자 질문과 관련된 도메인 카테고리 목록.\n"
            "가능한 값: 'eai', 'eigw', 'mcg', 'apply', 'all'\n"
            "- eai   : EAI 모니터링/통계 관련 질의\n"
            "- eigw  : EIGW 모니터링/통계/오류 관련 질의\n"
            "- mcg   : MCG 모니터링/통계 관련 질의\n"
            "- apply : 인터페이스 신청, EAI/EIGW 신청, 기존 신청 조회 관련 질의\n"
            "- all   : 여러 도메인에 걸치거나 분류 불가한 경우 (Fallback)\n"
            "복수 도메인 선택 가능: 예) ['eai', 'eigw']"
        ),
    ]


# ── Router Node ───────────────────────────────────────────────────────────────
async def router_node(state: AgentState, llm: Any, tools_map: dict) -> dict:
    """
    사용자 질문을 분석하여 관련 도메인 카테고리를 분류합니다.

    - 최근 HumanMessage를 기반으로 최소한의 LLM 호출(with_structured_output)을 수행합니다.
    - 분류된 카테고리에 해당하는 도구 이름 목록을 state["selected_tools"]에 저장합니다.
    - 매 새 질의마다 iteration_count / last_plan_signature / error 상태를 리셋합니다.
    - executor → planner 루프백 시에는 이 노드를 거치지 않으므로 선택된 도구가 보존됩니다.
    """
    logger.info("[Router] ▶ 진입 | messages=%d", len(state.get("messages", [])))

    # 가장 최근 HumanMessage 추출
    last_human = ""
    for msg in reversed(state.get("messages", [])):
        if isinstance(msg, HumanMessage) and msg.content:
            last_human = msg.content
            break

    logger.info("[Router] 질문: %s", last_human[:100])

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

    # TypedDict이므로 dict 접근 방식 사용
    categories = result.get("categories") or ["all"]

    # 카테고리 유효성 보정
    valid_cats = {"eai", "eigw", "mcg", "apply", "all"}
    categories = [c for c in categories if c in valid_cats] or ["all"]

    selected_tools = _tools_for_categories(categories, tools_map)

    logger.info(
        "[Router] ◀ 완료 | categories=%s | tools(%d)=%s",
        categories, len(selected_tools), selected_tools,
    )
    print(f"[Router] categories={categories}, tools({len(selected_tools)})={selected_tools}")

    return {
        "selected_tools": selected_tools,
        # 새 메시지마다 루프 관련 상태 리셋
        "iteration_count": 0,
        "last_plan_signature": "",
        "error_retries": 0,
        "last_tool_error": "",
    }


# ── Planner Node ──────────────────────────────────────────────────────────────
async def planner_node(state: AgentState, llm: Any, tools_map: dict) -> dict:
    """
    사용자 의도를 파악하고 Tool 호출 계획을 수립합니다.
    router_node가 state["selected_tools"]에 저장한 도구만 동적으로 바인딩합니다.

    Self-Correction:
      - last_tool_error가 있으면 LLM 컨텍스트에 수정 힌트를 주입합니다.
      - error_retries >= MAX_RETRIES이면 graceful 메시지를 반환합니다.

    Stagnation 감지:
      - 동일한 tool+args 시그니처가 연속으로 나타나면 무한루프로 판단합니다.

    - tool_calls 있음 → pending_tool_calls에 저장, Executor로 이동
    - tool_calls 없음 → 직접 최종 답변
    """
    current_iter = state.get("iteration_count", 0) + 1
    error_retries = state.get("error_retries", 0)
    last_tool_error = state.get("last_tool_error", "")

    logger.info(
        "[Planner] ▶ 진입 | iteration=%d | messages=%d | error_retries=%d",
        current_iter, len(state.get("messages", [])), error_retries,
    )

    # ── Self-Correction: 에러 재시도 한도 초과 ─────────────────────────────
    if error_retries >= MAX_RETRIES:
        logger.warning(
            "[Planner] error_retries=%d >= MAX_RETRIES=%d → graceful 종료",
            error_retries, MAX_RETRIES,
        )
        graceful_msg = AIMessage(
            content=(
                f"도구 호출 중 오류가 {error_retries}회 반복되어 자동으로 처리를 중단합니다.\n"
                f"마지막 오류: {last_tool_error}\n"
                "파라미터를 확인하시거나 질문을 구체화해 주세요."
            )
        )
        return {
            "messages": [graceful_msg],
            "pending_tool_calls": [],
            "current_plan": [],
            "plan": "",
            "iteration_count": current_iter,
        }

    selected = state.get("selected_tools") or list(tools_map.keys())
    bound_tools = [tools_map[name] for name in selected if name in tools_map]
    bound_llm = llm.bind_tools(bound_tools)

    # ── Self-Correction: 오류 컨텍스트 주입 ──────────────────────────────
    if last_tool_error:
        logger.info("[Planner] Self-Correction 힌트 주입 | error=%s", last_tool_error[:120])
        correction_hint = SystemMessage(
            content=(
                "[Self-Correction 지시] 이전 도구 호출에서 오류가 발생했습니다.\n"
                f"오류 내용: {last_tool_error}\n"
                "파라미터를 수정하거나 다른 도구를 사용하여 재시도하세요. "
                "절대 동일한 파라미터를 그대로 반복하지 마세요."
            )
        )
        messages_to_send = [correction_hint] + list(state["messages"])
    else:
        messages_to_send = state["messages"]

    response: AIMessage = await bound_llm.ainvoke(messages_to_send)

    if response.tool_calls:
        reasoning = (getattr(response, "content", "") or "").strip()
        if reasoning:
            logger.info("[Planner] 판단 근거: %s", reasoning[:300])

        pending = [
            {"id": tc["id"], "name": tc["name"], "args": tc["args"]}
            for tc in response.tool_calls
        ]

        # ── Stagnation 감지 ───────────────────────────────────────────────
        current_sig = _plan_signature(pending)
        prev_sig = state.get("last_plan_signature", "")
        if current_sig and current_sig == prev_sig:
            logger.warning(
                "[Planner] Stagnation 감지 | 동일 시그니처 반복: %s → graceful 종료",
                current_sig[:120],
            )
            graceful_msg = AIMessage(
                content=(
                    "동일한 도구를 같은 파라미터로 반복 시도하고 있습니다.\n"
                    "현재 분석으로는 자동 처리가 어렵습니다. "
                    "질문을 구체화하거나 다른 방법을 안내드릴게요."
                )
            )
            return {
                "messages": [graceful_msg],
                "pending_tool_calls": [],
                "current_plan": [],
                "plan": "",
                "iteration_count": current_iter,
                "last_plan_signature": "",
            }

        # ── 구조화된 계획 생성 ────────────────────────────────────────────
        current_plan = [
            {"step": i + 1, "tool": tc["name"], "args": tc["args"]}
            for i, tc in enumerate(pending)
        ]
        plan = "\n".join(
            f"• {tc['name']}({json.dumps(tc['args'], ensure_ascii=False)})"
            for tc in pending
        )

        logger.info(
            "[Planner] ◀ 완료 | pending_tools=%s | iteration=%d",
            [tc["name"] for tc in pending], current_iter,
        )

        return {
            "messages": [response],
            "pending_tool_calls": pending,
            "current_plan": current_plan,
            "plan": plan,
            "iteration_count": current_iter,
            "last_plan_signature": current_sig,
            "last_tool_error": "",  # 성공적으로 새 계획 수립 시 에러 초기화
        }
    else:
        logger.info(
            "[Planner] ◀ 완료 | 직접 답변 | iteration=%d | content_len=%d",
            current_iter, len(getattr(response, "content", "") or ""),
        )
        return {
            "messages": [response],
            "pending_tool_calls": [],
            "current_plan": [],
            "plan": "",
            "iteration_count": current_iter,
        }


# ── Executor Node ─────────────────────────────────────────────────────────────
async def executor_node(state: AgentState, tools_map: dict) -> dict:
    """
    pending_tool_calls의 Tool을 실제로 실행하고 ToolMessage를 messages에 추가합니다.
    execution_rejected=True인 경우 실제 실행 없이 "거절됨" ToolMessage를 생성하여
    messages를 항상 올바른 시퀀스(AIMessage→ToolMessage)로 유지합니다.

    Self-Correction:
      - 오류 발생 시 error_retries를 증가시키고 last_tool_error에 기록합니다.
      - planner_node가 이 정보를 읽어 파라미터 수정 후 재시도합니다.
    """
    pending_tools = state.get("pending_tool_calls", [])
    logger.info(
        "[Executor] ▶ 진입 | tools=%s | rejected=%s",
        [tc["name"] for tc in pending_tools],
        state.get("execution_rejected", False),
    )

    tool_messages = []
    results_summary = []

    # 거절된 경우: 모든 pending tool에 대해 "거절됨" ToolMessage 생성
    if state.get("execution_rejected", False):
        for tc in pending_tools:
            tool_messages.append(
                ToolMessage(
                    content="사용자가 Tool 실행을 거절했습니다. 다른 방법을 안내해주세요.",
                    tool_call_id=tc["id"],
                )
            )
        logger.info("[Executor] ◀ 완료 | 거절 처리 | tools=%d", len(tool_messages))
        return {
            "messages": tool_messages,
            "pending_tool_calls": [],
            "tool_results": [],
            "execution_rejected": False,
        }

    # 승인된 경우: 실제 Tool 실행
    error_occurred = False
    last_error_msg = ""

    for tc in pending_tools:
        tool_name = tc["name"]
        tool_args = tc["args"]
        tool_call_id = tc["id"]

        if tool_name not in tools_map:
            error_msg = f"[TOOL_ERROR] tool={tool_name} | error=UnknownTool | 존재하지 않는 도구입니다."
            content = error_msg
            error_occurred = True
            last_error_msg = error_msg
            logger.warning("[Executor] 알 수 없는 Tool: %s", tool_name)
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
                logger.info(
                    "[Executor] 성공: %s | args=%s | result_len=%d",
                    tool_name, json.dumps(tool_args, ensure_ascii=False), len(content),
                )
            except Exception as e:
                error_msg = (
                    f"[TOOL_ERROR] tool={tool_name} | "
                    f"error={type(e).__name__}: {e} | "
                    "파라미터를 수정하여 재시도하세요."
                )
                content = error_msg
                error_occurred = True
                last_error_msg = error_msg
                logger.warning(
                    "[Executor] 오류: %s | args=%s | %s: %s",
                    tool_name, json.dumps(tool_args, ensure_ascii=False), type(e).__name__, e,
                )

        tool_messages.append(
            ToolMessage(content=content, tool_call_id=tool_call_id)
        )

    logger.info(
        "[Executor] ◀ 완료 | results=%d | error_occurred=%s",
        len(results_summary), error_occurred,
    )

    result: dict = {
        "messages": tool_messages,
        "pending_tool_calls": [],
        "tool_results": results_summary,
        "execution_rejected": False,
    }

    if error_occurred:
        result["error_retries"] = state.get("error_retries", 0) + 1
        result["last_tool_error"] = last_error_msg
    else:
        # 성공 시 에러 카운터 리셋
        result["error_retries"] = 0
        result["last_tool_error"] = ""

    return result
