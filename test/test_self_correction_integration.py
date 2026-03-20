"""
test_self_correction_integration.py — 실제 LLM Self-Correction 통합 테스트

실제 Azure OpenAI(GPT-4.1)를 사용하여 Self-Correction 루프가
LLM 스스로 오류를 인지하고 파라미터를 수정하는지 검증합니다.

설계 방식:
  - Round 1: 잘못된 파라미터 상태를 수동 주입 (총 시도 1번째)
  - Round 2~: 실제 LLM이 Self-Correction 힌트를 읽고 파라미터를 수정, 성공할 때까지 자동 루프
  - call_count: Round 2 이후 실제 tool 호출 횟수를 추적
  - 총 시도 횟수(round) = 1(수동 주입) + 재시도 횟수

- AZURE_OPENAI_API_KEY 환경변수 없으면 자동 skip

실행:
  cd /Users/a10886/Documents/github/NARU-Agent
  python3 -m pytest test/test_self_correction_integration.py -v -m integration -s
"""
import os
import re
import sys
import unittest
from unittest.mock import MagicMock

_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _root not in sys.path:
    sys.path.insert(0, _root)

import pytest
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langchain_core.tools import tool

import config
from graph.nodes import MAX_RETRIES, executor_node, planner_node
from graph.state import AgentState


# ── 환경 체크 ─────────────────────────────────────────────────────────────────

_SKIP = not config.AZURE_OPENAI_API_KEY
_SKIP_REASON = "AZURE_OPENAI_API_KEY 없음 — 통합 테스트 건너뜀"


# ── LLM 초기화 ────────────────────────────────────────────────────────────────

def _make_real_llm():
    from langchain_openai import AzureChatOpenAI
    return AzureChatOpenAI(
        azure_deployment=config.AZURE_OPENAI_DEPLOYMENT,
        azure_endpoint=config.AZURE_OPENAI_ENDPOINT,
        api_key=config.AZURE_OPENAI_API_KEY,
        api_version=config.AZURE_OPENAI_API_VERSION,
        temperature=0,
    )


# ── 헬퍼 ──────────────────────────────────────────────────────────────────────

def make_state(**overrides) -> AgentState:
    base: AgentState = {
        "messages": [HumanMessage(content="테스트 질문")],
        "plan": "",
        "current_plan": [],
        "pending_tool_calls": [],
        "tool_results": [],
        "execution_rejected": False,
        "iteration_count": 0,
        "selected_tools": [],
        "error_retries": 0,
        "last_tool_error": "",
        "last_plan_signature": "",
    }
    base.update(overrides)
    return base


def _inject_round1_error(base_msgs, tool_name, wrong_args, error_msg) -> tuple:
    """
    Round 1 오류 상태를 수동으로 주입한다.
    nodes.py executor가 만드는 실제 포맷과 동일하게 구성.
    """
    ai_msg = AIMessage(content="", tool_calls=[{
        "id": "r1_tc", "name": tool_name, "args": wrong_args,
    }])
    last_tool_error = (
        f"[TOOL_ERROR] tool={tool_name} | error={error_msg} | 파라미터를 수정하여 재시도하세요."
    )
    tool_msg = ToolMessage(content=last_tool_error, tool_call_id="r1_tc")
    return base_msgs + [ai_msg, tool_msg], last_tool_error


# ── 자동 루프 헬퍼 ────────────────────────────────────────────────────────────

async def _run_correction_rounds(
    llm, tools_map, r1_msgs, last_tool_error, selected_tools, call_counter: list
) -> int:
    """
    Round 2부터 성공할 때까지 planner → executor를 자동으로 반복한다.

    Args:
        call_counter: [0] 형태의 mutable list — executor가 tool을 호출할 때마다 증가.
                      각 시나리오의 mock tool에서 call_counter[0] += 1 하도록 클로저로 공유.
    Returns:
        성공한 round 번호 (2, 3, ...). 실패하면 -1.
    """
    msgs = r1_msgs
    error_retries = 1
    cur_error = last_tool_error

    for round_num in range(2, MAX_RETRIES + 2):
        s = make_state(
            messages=msgs,
            error_retries=error_retries,
            last_tool_error=cur_error,
            selected_tools=selected_tools,
        )
        p = await planner_node(s, llm, tools_map)

        if not p.get("pending_tool_calls"):
            return round_num  # LLM이 직접 최종 답변 → tool 없이 종료

        e_s = make_state(
            messages=msgs + p["messages"],
            pending_tool_calls=p["pending_tool_calls"],
            error_retries=error_retries,
            last_tool_error=cur_error,
        )
        e = await executor_node(e_s, tools_map)

        msgs = msgs + p["messages"] + e["messages"]
        error_retries = e["error_retries"]
        cur_error = e["last_tool_error"]

        if error_retries == 0:
            return round_num  # 성공

    return -1  # MAX_RETRIES 초과 실패


# ════════════════════════════════════════════════════════════════════════════
# TestSelfCorrectionIntegration
# ════════════════════════════════════════════════════════════════════════════

@pytest.mark.integration
@pytest.mark.skipif(_SKIP, reason=_SKIP_REASON)
class TestSelfCorrectionIntegration(unittest.IsolatedAsyncioTestCase):

    def setUp(self):
        self.llm = _make_real_llm()

    # ── 시나리오 1: 날짜 포맷 오류 (HTTPStatusError 400) ─────────────────────

    async def test_date_format_error_real_llm(self):
        """
        Round 1(수동): stat_date='2026-03-19' (하이픈) → HTTPStatusError 400
        Round 2+(자동): LLM이 힌트를 읽고 YYYYMMDD로 수정 → 성공
        측정: 총 시도 횟수, 실제 tool 호출 횟수(call_count)
        """
        import httpx

        call_counter = [0]

        @tool
        async def get_statistic_daily_eai(stat_date: str = None, inst_code: str = None) -> dict:
            """
            특정 날짜의 EAI 일별 트랜잭션 통계를 조회합니다.

            Args:
                stat_date: 조회 날짜 (YYYYMMDD 형식, 예: 20260317)
                inst_code: 기관코드 (예: HNCD)
            """
            call_counter[0] += 1
            if stat_date and "-" in stat_date:
                raise httpx.HTTPStatusError(
                    "400 Bad Request",
                    request=MagicMock(),
                    response=MagicMock(status_code=400, text="Bad Request"),
                )
            return {"stat_date": stat_date, "records": [{"ifNm": "IF_EAI_001", "cnt": 120}]}

        tools_map = {"get_statistic_daily_eai": get_statistic_daily_eai}
        base_msgs = [HumanMessage(content="하나카드(HNCD) 2026-03-19 날짜 EAI 일별 통계 알려줘")]

        r1_msgs, last_tool_error = _inject_round1_error(
            base_msgs,
            tool_name="get_statistic_daily_eai",
            wrong_args={"stat_date": "2026-03-19", "inst_code": "HNCD"},
            error_msg="HTTPStatusError: 400 Bad Request (stat_date: invalid format, expected YYYYMMDD)",
        )

        success_round = await _run_correction_rounds(
            self.llm, tools_map, r1_msgs, last_tool_error,
            selected_tools=["get_statistic_daily_eai"],
            call_counter=call_counter,
        )

        total_attempts = 1 + (success_round - 1)  # Round 1(수동) + 재시도 횟수
        print(
            f"\n[날짜 포맷] 총 {total_attempts}회 시도 "
            f"(Round 1: 실패·수동주입, Round {success_round}: 성공) "
            f"| 실제 tool 호출: {call_counter[0]}회"
        )

        self.assertGreater(success_round, 0, "최종적으로 성공해야 함")
        self.assertGreater(call_counter[0], 0, "tool이 최소 1회는 실제 호출돼야 함")

    # ── 시나리오 2: 기관코드 미조회 오류 (KeyError) ───────────────────────────

    async def test_missing_inst_code_real_llm(self):
        """
        Round 1(수동): inst_code='하나카드' → KeyError: '하나카드'
        Round 2+(자동): LLM이 힌트를 읽고 ASCII 코드(HNCD)로 수정 → 성공
        측정: 총 시도 횟수, 실제 tool 호출 횟수(call_count)
        """
        call_counter = [0]

        @tool
        async def get_statistic_daily_eai(stat_date: str = None, inst_code: str = None) -> dict:
            """
            특정 날짜의 EAI 일별 트랜잭션 통계를 조회합니다.

            Args:
                stat_date: 조회 날짜 (YYYYMMDD 형식, 예: 20260317)
                inst_code: 기관코드 영문 대문자 (예: HNCD). 기관명(한글) 직접 입력 불가.
            """
            call_counter[0] += 1
            if inst_code and any("\uac00" <= ch <= "\ud7a3" for ch in inst_code):
                raise KeyError(inst_code)
            return {"inst_code": inst_code, "records": [{"ifNm": "IF_EAI_002", "cnt": 55}]}

        tools_map = {"get_statistic_daily_eai": get_statistic_daily_eai}
        base_msgs = [HumanMessage(content="하나카드(inst_code=HNCD) 오늘 EAI 일별 통계 알려줘")]

        r1_msgs, last_tool_error = _inject_round1_error(
            base_msgs,
            tool_name="get_statistic_daily_eai",
            wrong_args={"stat_date": "20260319", "inst_code": "하나카드"},
            error_msg="KeyError: '하나카드'",
        )

        success_round = await _run_correction_rounds(
            self.llm, tools_map, r1_msgs, last_tool_error,
            selected_tools=["get_statistic_daily_eai"],
            call_counter=call_counter,
        )

        total_attempts = 1 + (success_round - 1)
        print(
            f"\n[기관코드] 총 {total_attempts}회 시도 "
            f"(Round 1: 실패·수동주입, Round {success_round}: 성공) "
            f"| 실제 tool 호출: {call_counter[0]}회"
        )

        self.assertGreater(success_round, 0, "최종적으로 성공해야 함")
        self.assertGreater(call_counter[0], 0, "tool이 최소 1회는 실제 호출돼야 함")

    # ── 시나리오 3: 파라미터 이름 오타 (TypeError) ────────────────────────────

    async def test_wrong_param_name_real_llm(self):
        """
        Round 1(수동): statDate='20260317' → TypeError: unexpected keyword argument 'statDate'
        Round 2+(자동): LLM이 힌트를 읽고 stat_date로 수정 → 성공
        측정: 총 시도 횟수, 실제 tool 호출 횟수(call_count)
        """
        call_counter = [0]

        @tool
        async def get_statistic_daily_eai(stat_date: str = None, inst_code: str = None) -> dict:
            """
            특정 날짜의 EAI 일별 트랜잭션 통계를 조회합니다.

            Args:
                stat_date: 조회 날짜 (YYYYMMDD). 파라미터명은 반드시 stat_date (snake_case).
                inst_code: 기관코드 (예: HNCD)
            """
            call_counter[0] += 1
            return {"stat_date": stat_date, "records": []}

        tools_map = {"get_statistic_daily_eai": get_statistic_daily_eai}
        base_msgs = [HumanMessage(content="HNCD 기관의 20260317 날짜 EAI 일별 통계 알려줘")]

        r1_msgs, last_tool_error = _inject_round1_error(
            base_msgs,
            tool_name="get_statistic_daily_eai",
            wrong_args={"statDate": "20260317", "inst_code": "HNCD"},
            error_msg="TypeError: got an unexpected keyword argument 'statDate'",
        )

        success_round = await _run_correction_rounds(
            self.llm, tools_map, r1_msgs, last_tool_error,
            selected_tools=["get_statistic_daily_eai"],
            call_counter=call_counter,
        )

        total_attempts = 1 + (success_round - 1)
        print(
            f"\n[파라미터 오타] 총 {total_attempts}회 시도 "
            f"(Round 1: 실패·수동주입, Round {success_round}: 성공) "
            f"| 실제 tool 호출: {call_counter[0]}회"
        )

        self.assertGreater(success_round, 0, "최종적으로 성공해야 함")
        self.assertGreater(call_counter[0], 0, "tool이 최소 1회는 실제 호출돼야 함")

    # ── 시나리오 4: 필수 파라미터 누락 (TypeError) ────────────────────────────

    async def test_missing_required_param_real_llm(self):
        """
        Round 1(수동): instNm 없이 호출 → TypeError: missing 1 required positional argument
        Round 2+(자동): LLM이 힌트를 읽고 instNm 채워 넣음 → 성공
        측정: 총 시도 횟수, 실제 tool 호출 횟수(call_count)
        """
        call_counter = [0]

        @tool
        async def search_institution_code(instNm: str, size: int = 10) -> dict:
            """
            기관명(한글 또는 영문) 키워드로 기관코드를 조회합니다.

            Args:
                instNm: 기관명 키워드 (필수, 예: "하나카드", "SKCC")
                size:   최대 반환 건수 (기본 10)
            """
            call_counter[0] += 1
            if not instNm:
                raise TypeError("missing 1 required positional argument: 'instNm'")
            return {"keyword": instNm, "total": 1,
                    "results": [{"instCd": "HNCD", "instNm": "하나카드"}]}

        tools_map = {"search_institution_code": search_institution_code}
        base_msgs = [HumanMessage(content="하나카드의 기관코드를 조회해줘")]

        r1_msgs, last_tool_error = _inject_round1_error(
            base_msgs,
            tool_name="search_institution_code",
            wrong_args={},
            error_msg="TypeError: missing 1 required positional argument: 'instNm'",
        )

        success_round = await _run_correction_rounds(
            self.llm, tools_map, r1_msgs, last_tool_error,
            selected_tools=["search_institution_code"],
            call_counter=call_counter,
        )

        total_attempts = 1 + (success_round - 1)
        print(
            f"\n[파라미터 누락] 총 {total_attempts}회 시도 "
            f"(Round 1: 실패·수동주입, Round {success_round}: 성공) "
            f"| 실제 tool 호출: {call_counter[0]}회"
        )

        self.assertGreater(success_round, 0, "최종적으로 성공해야 함")
        self.assertGreater(call_counter[0], 0, "tool이 최소 1회는 실제 호출돼야 함")


# ════════════════════════════════════════════════════════════════════════════
# 실행 진입점
# ════════════════════════════════════════════════════════════════════════════
if __name__ == "__main__":
    if _SKIP:
        print(f"[SKIP] {_SKIP_REASON}")
        sys.exit(0)
    print("=" * 60)
    print("TestSelfCorrectionIntegration — 실제 LLM Self-Correction")
    print("=" * 60)
    unittest.main(verbosity=2)
