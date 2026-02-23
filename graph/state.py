"""
AgentState — LangGraph 그래프 전체에서 공유되는 상태 정의

Python 3.14 + Pydantic V1 호환성 문제를 피하기 위해 TypedDict 방식 사용
"""
from typing import Annotated, TypedDict
from langgraph.graph.message import add_messages


class AgentState(TypedDict):
    # 대화 히스토리 (HumanMessage, AIMessage, ToolMessage 누적)
    messages: Annotated[list, add_messages]

    # Planner가 수립한 실행 계획 — Approval 화면에 표시
    plan: str

    # 승인 대기 중인 Tool 호출 목록 [{name, args, id}, ...]
    pending_tool_calls: list

    # 마지막 Executor 실행 결과 요약
    tool_results: list

    # 사용자 거절 플래그 — True이면 executor가 실제 실행 대신 "거절" ToolMessage 생성
    execution_rejected: bool
