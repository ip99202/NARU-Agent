"""
AgentState — LangGraph 그래프 전체에서 공유되는 상태 정의

Python 3.14 + Pydantic V1 호환성 문제를 피하기 위해 TypedDict 방식 사용
"""
from typing import Annotated, TypedDict
from langgraph.graph.message import add_messages


class AgentState(TypedDict):
    # 대화 히스토리 (HumanMessage, AIMessage, ToolMessage 누적)
    messages: Annotated[list, add_messages]

    # Planner가 수립한 실행 계획 문자열 — Approval 화면에 표시
    plan: str

    # Planner가 수립한 구조화된 실행 계획 리스트
    # [{"step": 1, "tool": "search_institution_code", "args": {...}}, ...]
    # 프론트엔드에서 카드/스텝 UI로 렌더링 가능
    current_plan: list

    # 승인 대기 중인 Tool 호출 목록 [{name, args, id}, ...]
    pending_tool_calls: list

    # 마지막 Executor 실행 결과 요약
    tool_results: list

    # 사용자 거절 플래그 — True이면 executor가 실제 실행 대신 "거절" ToolMessage 생성
    execution_rejected: bool

    # planner-executor 루프 횟수 — router_node 실행 시마다 0으로 리셋 (메시지 단위)
    iteration_count: int

    # 시맨틱 라우터가 선택한 도구 이름 목록
    # - router_node 실행 시 덮어씀 → 자동 초기화
    # - executor → planner 루프백 구간에서는 router를 통과하지 않으므로 그대로 유지
    selected_tools: list

    # Self-Correction: 연속 오류 재시도 횟수 (MAX_RETRIES=3 초과 시 graceful 종료)
    error_retries: int

    # Self-Correction: 마지막 도구 오류 메시지 — planner가 읽어 파라미터 수정 유도
    last_tool_error: str

    # Stagnation 감지: 이전 planner 호출의 tool+args 시그니처
    # 동일한 시그니처가 연속으로 나타나면 무한루프로 판단하여 차단
    last_plan_signature: str
