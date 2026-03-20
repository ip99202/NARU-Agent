"""
test_self_correction.py — Self-Correction 실제 API 오류 시나리오 테스트

실제 NARU API 오류 패턴을 기반으로
planner → executor → planner(hint) → executor 전체 루프를 시뮬레이션합니다.

검증 항목:
  1. 날짜 포맷 오류      (HTTPStatusError 400) 
  2. 기관코드 미조회     (KeyError)            
  3. 파라미터 이름 오타  (TypeError)          
  4. 필수 파라미터 누락  (TypeError)          


실행:
  cd /Users/a10886/Documents/github/NARU-Agent
  python3 -m pytest test/test_self_correction.py -v
"""
import os
import sys
import unittest
from unittest.mock import MagicMock

_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _root not in sys.path:
    sys.path.insert(0, _root)

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from graph.nodes import MAX_RETRIES, executor_node, planner_node
from graph.state import AgentState


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


# ════════════════════════════════════════════════════════════════════════════
# TestSelfCorrectionWithRealErrors
#   실제 API 오류 기반 Self-Correction 시나리오
#   planner → executor → planner(hint) → executor 전체 루프 시뮬레이션
# ════════════════════════════════════════════════════════════════════════════

class TestSelfCorrectionWithRealErrors(unittest.IsolatedAsyncioTestCase):
    """
    실제 NARU API 오류 패턴 기반 Self-Correction 루프 테스트.

    Mock LLM이 messages 안의 Self-Correction 힌트를 감지하여
    파라미터를 수정하는 전체 흐름(planner→executor→planner→executor)을 시뮬레이션합니다.
    """

    @staticmethod
    def _make_smart_llm(tool_calls_without_hint: list, tool_calls_with_hint: list):
        """Self-Correction 힌트 유무에 따라 다른 tool_calls를 반환하는 LLM Mock."""
        async def smart_ainvoke(messages):
            has_hint = any(
                isinstance(m, SystemMessage) and "Self-Correction" in (m.content or "")
                for m in messages
            )
            calls = tool_calls_with_hint if has_hint else tool_calls_without_hint
            return AIMessage(content="", tool_calls=calls)

        bound = MagicMock()
        bound.ainvoke = smart_ainvoke
        llm = MagicMock()
        llm.bind_tools = MagicMock(return_value=bound)
        return llm

    # ── 시나리오 1: 날짜 포맷 오류 (HTTPStatusError 400) ─────────────────────

    async def test_date_format_error_corrects_in_1_retry(self):
        """
        날짜 포맷 오류 시나리오:
          Round 1: stat_date="2026-03-17" (하이픈 포함 잘못된 포맷)
                   → httpx.HTTPStatusError: 400 Bad Request
          Round 2: stat_date="20260317" (YYYYMMDD 수정)
                   → 성공
        """
        import httpx

        call_count = 0

        async def stat_tool_ainvoke(args):
            nonlocal call_count
            call_count += 1
            stat_date = args.get("stat_date", "")
            if "-" in stat_date:
                raise httpx.HTTPStatusError(
                    "400 Bad Request",
                    request=MagicMock(),
                    response=MagicMock(status_code=400, text="Bad Request"),
                )
            return {"stat_date": stat_date, "records": [{"ifNm": "IF_EAI_001", "cnt": 120}]}

        mock_tool = MagicMock()
        mock_tool.ainvoke = stat_tool_ainvoke
        tools_map = {"get_statistic_daily_eai": mock_tool}

        llm = self._make_smart_llm(
            tool_calls_without_hint=[{
                "id": "tc1", "name": "get_statistic_daily_eai",
                "args": {"stat_date": "2026-03-17", "inst_code": "HNCD"},
            }],
            tool_calls_with_hint=[{
                "id": "tc2", "name": "get_statistic_daily_eai",
                "args": {"stat_date": "20260317", "inst_code": "HNCD"},
            }],
        )

        base_msgs = [HumanMessage(content="하나카드 오늘 EAI 통계 알려줘")]

        s1 = make_state(messages=base_msgs, error_retries=0, last_tool_error="",
                        selected_tools=["get_statistic_daily_eai"])
        p1 = await planner_node(s1, llm, tools_map)
        self.assertIn("-", p1["pending_tool_calls"][0]["args"]["stat_date"])

        e1_state = make_state(
            messages=base_msgs + p1["messages"],
            pending_tool_calls=p1["pending_tool_calls"],
            error_retries=0, last_tool_error="",
        )
        e1 = await executor_node(e1_state, tools_map)
        self.assertEqual(e1["error_retries"], 1)
        self.assertIn("400", e1["last_tool_error"])
        self.assertIn("get_statistic_daily_eai", e1["last_tool_error"])

        s2 = make_state(
            messages=base_msgs + p1["messages"] + e1["messages"],
            error_retries=e1["error_retries"],
            last_tool_error=e1["last_tool_error"],
            selected_tools=["get_statistic_daily_eai"],
        )
        p2 = await planner_node(s2, llm, tools_map)
        corrected_date = p2["pending_tool_calls"][0]["args"]["stat_date"]
        self.assertNotIn("-", corrected_date)
        self.assertEqual(corrected_date, "20260317")

        e2_state = make_state(
            messages=s2["messages"] + p2["messages"],
            pending_tool_calls=p2["pending_tool_calls"],
            error_retries=e1["error_retries"],
            last_tool_error=e1["last_tool_error"],
        )
        e2 = await executor_node(e2_state, tools_map)
        self.assertEqual(e2["error_retries"], 0)
        self.assertEqual(call_count, 2)

    # ── 시나리오 2: 기관코드 미조회 오류 (KeyError) ───────────────────────────

    async def test_missing_inst_code_corrects_in_1_retry(self):
        """
        기관코드 미조회 오류 시나리오:
          Round 1: inst_code="하나카드" (기관명 직접 입력)
                   → KeyError: '하나카드'  (실제 dict key 접근 실패)
          Round 2: inst_code="HNCD" (올바른 코드로 수정)
                   → 성공
        """
        call_count = 0

        async def stat_tool_ainvoke(args):
            nonlocal call_count
            call_count += 1
            inst_code = args.get("inst_code", "")
            if any("\uac00" <= ch <= "\ud7a3" for ch in inst_code):
                raise KeyError(inst_code)
            return {"inst_code": inst_code, "records": [{"ifNm": "IF_EAI_002", "cnt": 55}]}

        mock_stat = MagicMock()
        mock_stat.ainvoke = stat_tool_ainvoke
        tools_map = {"get_statistic_daily_eai": mock_stat}

        llm = self._make_smart_llm(
            tool_calls_without_hint=[{
                "id": "tc1", "name": "get_statistic_daily_eai",
                "args": {"inst_code": "하나카드", "stat_date": "20260317"},
            }],
            tool_calls_with_hint=[{
                "id": "tc2", "name": "get_statistic_daily_eai",
                "args": {"inst_code": "HNCD", "stat_date": "20260317"},
            }],
        )

        base_msgs = [HumanMessage(content="하나카드 EAI 일별 통계 알려줘")]

        s1 = make_state(messages=base_msgs, error_retries=0, last_tool_error="",
                        selected_tools=["get_statistic_daily_eai"])
        p1 = await planner_node(s1, llm, tools_map)
        self.assertEqual(p1["pending_tool_calls"][0]["args"]["inst_code"], "하나카드")

        e1_state = make_state(
            messages=base_msgs + p1["messages"],
            pending_tool_calls=p1["pending_tool_calls"],
            error_retries=0, last_tool_error="",
        )
        e1 = await executor_node(e1_state, tools_map)
        self.assertEqual(e1["error_retries"], 1)
        self.assertIn("KeyError", e1["last_tool_error"])
        self.assertIn("get_statistic_daily_eai", e1["last_tool_error"])

        s2 = make_state(
            messages=base_msgs + p1["messages"] + e1["messages"],
            error_retries=e1["error_retries"],
            last_tool_error=e1["last_tool_error"],
            selected_tools=["get_statistic_daily_eai"],
        )
        p2 = await planner_node(s2, llm, tools_map)
        self.assertEqual(p2["pending_tool_calls"][0]["args"]["inst_code"], "HNCD")

        e2_state = make_state(
            messages=s2["messages"] + p2["messages"],
            pending_tool_calls=p2["pending_tool_calls"],
            error_retries=e1["error_retries"],
            last_tool_error=e1["last_tool_error"],
        )
        e2 = await executor_node(e2_state, tools_map)
        self.assertEqual(e2["error_retries"], 0)
        self.assertEqual(call_count, 2)

    # ── 시나리오 3: 파라미터 이름 오타 (TypeError) ────────────────────────────

    async def test_wrong_param_name_corrects_in_1_retry(self):
        """
        파라미터 이름 오타 시나리오:
          Round 1: statDate="20260317" (camelCase — 실제 파라미터명은 stat_date)
                   → TypeError: got an unexpected keyword argument 'statDate'
          Round 2: stat_date="20260317" (snake_case로 수정)
                   → 성공
        """
        call_count = 0

        async def stat_tool_ainvoke(args):
            nonlocal call_count
            call_count += 1
            if "statDate" in args and "stat_date" not in args:
                raise TypeError("got an unexpected keyword argument 'statDate'")
            return {"stat_date": args.get("stat_date"), "records": []}

        mock_tool = MagicMock()
        mock_tool.ainvoke = stat_tool_ainvoke
        tools_map = {"get_statistic_daily_eai": mock_tool}

        llm = self._make_smart_llm(
            tool_calls_without_hint=[{
                "id": "tc1", "name": "get_statistic_daily_eai",
                "args": {"statDate": "20260317", "inst_code": "HNCD"},
            }],
            tool_calls_with_hint=[{
                "id": "tc2", "name": "get_statistic_daily_eai",
                "args": {"stat_date": "20260317", "inst_code": "HNCD"},
            }],
        )

        base_msgs = [HumanMessage(content="하나카드 EAI 통계 알려줘")]

        s1 = make_state(messages=base_msgs, error_retries=0, last_tool_error="",
                        selected_tools=["get_statistic_daily_eai"])
        p1 = await planner_node(s1, llm, tools_map)
        self.assertIn("statDate", p1["pending_tool_calls"][0]["args"])

        e1_state = make_state(
            messages=base_msgs + p1["messages"],
            pending_tool_calls=p1["pending_tool_calls"],
            error_retries=0, last_tool_error="",
        )
        e1 = await executor_node(e1_state, tools_map)
        self.assertEqual(e1["error_retries"], 1)
        self.assertIn("TypeError", e1["last_tool_error"])
        self.assertIn("statDate", e1["last_tool_error"])

        s2 = make_state(
            messages=base_msgs + p1["messages"] + e1["messages"],
            error_retries=e1["error_retries"],
            last_tool_error=e1["last_tool_error"],
            selected_tools=["get_statistic_daily_eai"],
        )
        p2 = await planner_node(s2, llm, tools_map)
        corrected_args = p2["pending_tool_calls"][0]["args"]
        self.assertNotIn("statDate", corrected_args)
        self.assertIn("stat_date", corrected_args)

        e2_state = make_state(
            messages=s2["messages"] + p2["messages"],
            pending_tool_calls=p2["pending_tool_calls"],
            error_retries=e1["error_retries"],
            last_tool_error=e1["last_tool_error"],
        )
        e2 = await executor_node(e2_state, tools_map)
        self.assertEqual(e2["error_retries"], 0)
        self.assertEqual(call_count, 2)

    # ── 시나리오 4: 필수 파라미터 누락 (TypeError) ────────────────────────────

    async def test_missing_required_param_corrects_in_1_retry(self):
        """
        필수 파라미터 누락 시나리오:
          Round 1: search_institution_code를 instNm 없이 호출
                   → TypeError: missing 1 required positional argument: 'instNm'
          Round 2: instNm="하나카드" 추가
                   → 성공
        """
        call_count = 0

        async def search_tool_ainvoke(args):
            nonlocal call_count
            call_count += 1
            if not args.get("instNm"):
                raise TypeError("missing 1 required positional argument: 'instNm'")
            return {"keyword": args["instNm"], "total": 1,
                    "results": [{"instCd": "HNCD", "instNm": "하나카드"}]}

        mock_search = MagicMock()
        mock_search.ainvoke = search_tool_ainvoke
        tools_map = {"search_institution_code": mock_search}

        llm = self._make_smart_llm(
            tool_calls_without_hint=[{
                "id": "tc1", "name": "search_institution_code",
                "args": {},
            }],
            tool_calls_with_hint=[{
                "id": "tc2", "name": "search_institution_code",
                "args": {"instNm": "하나카드"},
            }],
        )

        base_msgs = [HumanMessage(content="하나카드 기관코드 알려줘")]

        s1 = make_state(messages=base_msgs, error_retries=0, last_tool_error="",
                        selected_tools=["search_institution_code"])
        p1 = await planner_node(s1, llm, tools_map)
        self.assertEqual(p1["pending_tool_calls"][0]["args"], {})

        e1_state = make_state(
            messages=base_msgs + p1["messages"],
            pending_tool_calls=p1["pending_tool_calls"],
            error_retries=0, last_tool_error="",
        )
        e1 = await executor_node(e1_state, tools_map)
        self.assertEqual(e1["error_retries"], 1)
        self.assertIn("TypeError", e1["last_tool_error"])
        self.assertIn("instNm", e1["last_tool_error"])

        s2 = make_state(
            messages=base_msgs + p1["messages"] + e1["messages"],
            error_retries=e1["error_retries"],
            last_tool_error=e1["last_tool_error"],
            selected_tools=["search_institution_code"],
        )
        p2 = await planner_node(s2, llm, tools_map)
        corrected_args = p2["pending_tool_calls"][0]["args"]
        self.assertIn("instNm", corrected_args)
        self.assertTrue(corrected_args["instNm"])

        e2_state = make_state(
            messages=s2["messages"] + p2["messages"],
            pending_tool_calls=p2["pending_tool_calls"],
            error_retries=e1["error_retries"],
            last_tool_error=e1["last_tool_error"],
        )
        e2 = await executor_node(e2_state, tools_map)
        self.assertEqual(e2["error_retries"], 0)
        self.assertEqual(call_count, 2)


# ════════════════════════════════════════════════════════════════════════════
# 실행 진입점
# ════════════════════════════════════════════════════════════════════════════
if __name__ == "__main__":
    print("=" * 60)
    print("TestSelfCorrectionWithRealErrors — 실제 API 오류 Self-Correction 루프")
    print("=" * 60)
    unittest.main(verbosity=2)
