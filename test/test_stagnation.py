"""
test_stagnation.py — Stagnation Detection 전용 단위 테스트

검증 항목:
  A. _plan_signature() 순수 함수 정확성 (11개)
     - 시그니처 포맷, 동일/다름 판별, 순서 독립성, 엣지 케이스
  B. planner_node Stagnation 감지 동작 (10개)
     - 첫 호출(prev_sig 없음), 동일 반복 감지, 다른 args/tool 허용
     - graceful 메시지 내용, 반환 상태, 정상 워크플로 비차단

PPT 근거 수치: "100% — 동일 도구 및 변수(tool+args)의 중복 호출을 완벽히 식별 및 차단"

실행:
  cd /Users/a10886/Documents/github/NARU-Agent
  python3 -m pytest test/test_stagnation.py -v
"""
import asyncio
import json
import os
import sys
import unittest
from unittest.mock import AsyncMock, MagicMock

_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _root not in sys.path:
    sys.path.insert(0, _root)

from langchain_core.messages import AIMessage, HumanMessage

from graph.nodes import _plan_signature, planner_node
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


def make_mock_llm(tool_calls: list) -> MagicMock:
    """지정된 tool_calls를 반환하는 Mock LLM 생성."""
    async def mock_ainvoke(messages):
        return AIMessage(content="", tool_calls=tool_calls)

    bound = MagicMock()
    bound.ainvoke = mock_ainvoke
    llm = MagicMock()
    llm.bind_tools = MagicMock(return_value=bound)
    return llm


# ════════════════════════════════════════════════════════════════════════════
# A. _plan_signature() 순수 단위 테스트
# ════════════════════════════════════════════════════════════════════════════

class TestStagnation(unittest.TestCase):
    """
    _plan_signature() 함수의 정확성을 검증합니다.
    PPT: 동일 tool+args 중복 호출 100% 식별 근거
    """

    # ── 포맷 검증 ────────────────────────────────────────────────────────────

    def test_empty_tool_calls_returns_empty_string(self):
        """빈 tool_calls → '' 반환."""
        self.assertEqual(_plan_signature([]), "")

    def test_single_tool_no_args_format(self):
        """단일 tool, args 없음 → 'tool_a:{}' 포맷."""
        sig = _plan_signature([{"name": "tool_a", "args": {}}])
        self.assertEqual(sig, 'tool_a:{}')

    def test_single_tool_with_args_format(self):
        """단일 tool, args 있음 → 'tool_a:{"key":"val"}' 포맷."""
        sig = _plan_signature([{"name": "tool_a", "args": {"key": "val"}}])
        self.assertEqual(sig, 'tool_a:{"key": "val"}')

    def test_multiple_tools_joined_with_pipe(self):
        """멀티 tool → '|' 구분자로 연결, 이름순 정렬."""
        sig = _plan_signature([
            {"name": "tool_b", "args": {}},
            {"name": "tool_a", "args": {}},
        ])
        self.assertEqual(sig, "tool_a:{}|tool_b:{}")

    # ── 동일 / 다름 판별 ─────────────────────────────────────────────────────

    def test_same_tool_same_args_identical_signature(self):
        """동일 tool + 동일 args → 시그니처 일치."""
        calls = [{"name": "search_code", "args": {"name": "하나카드"}}]
        self.assertEqual(_plan_signature(calls), _plan_signature(calls))

    def test_same_tool_different_args_different_signature(self):
        """동일 tool + 다른 args → 시그니처 불일치."""
        a = [{"name": "get_stat", "args": {"date": "20260310"}}]
        b = [{"name": "get_stat", "args": {"date": "20260317"}}]
        self.assertNotEqual(_plan_signature(a), _plan_signature(b))

    def test_different_tool_same_args_different_signature(self):
        """다른 tool + 동일 args → 시그니처 불일치."""
        a = [{"name": "tool_a", "args": {"x": 1}}]
        b = [{"name": "tool_b", "args": {"x": 1}}]
        self.assertNotEqual(_plan_signature(a), _plan_signature(b))

    # ── 순서 독립성 ───────────────────────────────────────────────────────────

    def test_tool_list_order_independent(self):
        """tool 목록 순서 달라도 동일 시그니처 (정렬 적용)."""
        calls_1 = [
            {"name": "tool_b", "args": {"x": 1}},
            {"name": "tool_a", "args": {"y": 2}},
        ]
        calls_2 = [
            {"name": "tool_a", "args": {"y": 2}},
            {"name": "tool_b", "args": {"x": 1}},
        ]
        self.assertEqual(_plan_signature(calls_1), _plan_signature(calls_2))

    def test_args_key_order_independent(self):
        """args 딕셔너리 키 순서 달라도 동일 시그니처 (sort_keys=True)."""
        calls_1 = [{"name": "tool_a", "args": {"b": 2, "a": 1}}]
        calls_2 = [{"name": "tool_a", "args": {"a": 1, "b": 2}}]
        self.assertEqual(_plan_signature(calls_1), _plan_signature(calls_2))

    # ── 엣지 케이스 ───────────────────────────────────────────────────────────

    def test_unicode_args_handled(self):
        """유니코드 args (한글) → 시그니처에 그대로 포함."""
        calls = [{"name": "search_institution_code", "args": {"name": "하나카드"}}]
        sig = _plan_signature(calls)
        self.assertIn("하나카드", sig)

    def test_int_vs_string_args_distinguished(self):
        """숫자 1 vs 문자열 '1' → 다른 시그니처 (타입 구분)."""
        calls_int = [{"name": "tool_a", "args": {"x": 1}}]
        calls_str = [{"name": "tool_a", "args": {"x": "1"}}]
        self.assertNotEqual(_plan_signature(calls_int), _plan_signature(calls_str))

    def test_nested_dict_args(self):
        """중첩 dict args → 시그니처에 올바르게 직렬화."""
        calls = [{"name": "tool_a", "args": {"filter": {"inst": "HNCD", "date": "20260310"}}}]
        sig = _plan_signature(calls)
        self.assertIn("tool_a", sig)
        self.assertIn("HNCD", sig)


# ════════════════════════════════════════════════════════════════════════════
# B. planner_node Stagnation 감지 동작
# ════════════════════════════════════════════════════════════════════════════

class TestStagnationInPlanner(unittest.IsolatedAsyncioTestCase):
    """
    planner_node의 Stagnation 감지 및 차단 동작을 검증합니다.
    PPT: 무한 루프(Stagnation) 발생 0건 근거
    """

    # ── 정상 진행 케이스 ──────────────────────────────────────────────────────

    async def test_first_call_no_stagnation(self):
        """첫 호출(prev_sig='') → stagnation 아님, 정상 tool_calls 반환."""
        tool_calls = [{"id": "tc1", "name": "search_code", "args": {"name": "하나"}}]
        llm = make_mock_llm(tool_calls)
        state = make_state(
            last_plan_signature="",  # 첫 호출
            selected_tools=["search_code"],
        )
        result = await planner_node(state, llm, {"search_code": MagicMock()})
        self.assertNotEqual(result["pending_tool_calls"], [], "첫 호출은 stagnation 아님")

    async def test_different_args_not_stagnation(self):
        """동일 tool + 다른 args → stagnation 아님, 정상 진행."""
        prev_calls = [{"name": "get_stat_eai", "args": {"date": "20260310"}}]
        prev_sig = _plan_signature(prev_calls)
        new_tool_calls = [{"id": "tc1", "name": "get_stat_eai", "args": {"date": "20260317"}}]
        llm = make_mock_llm(new_tool_calls)
        state = make_state(
            last_plan_signature=prev_sig,
            selected_tools=["get_stat_eai"],
        )
        result = await planner_node(state, llm, {"get_stat_eai": MagicMock()})
        self.assertNotEqual(result["pending_tool_calls"], [], "다른 args → 정상 진행")

    async def test_different_tool_not_stagnation(self):
        """다른 tool → stagnation 아님."""
        prev_calls = [{"name": "tool_a", "args": {"x": 1}}]
        prev_sig = _plan_signature(prev_calls)
        new_tool_calls = [{"id": "tc1", "name": "tool_b", "args": {"x": 1}}]
        llm = make_mock_llm(new_tool_calls)
        state = make_state(
            last_plan_signature=prev_sig,
            selected_tools=["tool_b"],
        )
        result = await planner_node(state, llm, {"tool_b": MagicMock()})
        self.assertNotEqual(result["pending_tool_calls"], [], "다른 tool → 정상 진행")

    async def test_multistep_workflow_step1_step2_step3_no_stagnation(self):
        """Step1→Step2→Step3 순차 워크플로 — 매 단계 다른 tool, stagnation 없이 전부 진행."""
        steps = [
            ([{"id": "tc1", "name": "search_institution_code", "args": {"name": "하나카드"}}], ""),
            ([{"id": "tc2", "name": "get_statistic_monthly_eai", "args": {"inst_code": "HNCD"}}],
             _plan_signature([{"name": "search_institution_code", "args": {"name": "하나카드"}}])),
            ([{"id": "tc3", "name": "get_statistic_daily_eai", "args": {"inst_code": "HNCD", "date": "20260317"}}],
             _plan_signature([{"name": "get_statistic_monthly_eai", "args": {"inst_code": "HNCD"}}])),
        ]
        for step_calls, prev_sig in steps:
            tool_name = step_calls[0]["name"]
            llm = make_mock_llm(step_calls)
            state = make_state(
                last_plan_signature=prev_sig,
                selected_tools=[tool_name],
            )
            result = await planner_node(state, llm, {tool_name: MagicMock()})
            self.assertNotEqual(
                result["pending_tool_calls"], [],
                f"Step '{tool_name}' — 정상 진행해야 함"
            )

    async def test_partial_change_in_multi_tool_not_stagnation(self):
        """멀티 tool 중 하나라도 args가 다르면 stagnation 아님."""
        prev_calls = [
            {"name": "tool_a", "args": {"x": 1}},
            {"name": "tool_b", "args": {"y": 2}},
        ]
        prev_sig = _plan_signature(prev_calls)
        # tool_b의 args가 바뀜
        new_tool_calls = [
            {"id": "tc1", "name": "tool_a", "args": {"x": 1}},
            {"id": "tc2", "name": "tool_b", "args": {"y": 999}},
        ]
        llm = make_mock_llm(new_tool_calls)
        state = make_state(
            last_plan_signature=prev_sig,
            selected_tools=["tool_a", "tool_b"],
        )
        result = await planner_node(state, llm, {"tool_a": MagicMock(), "tool_b": MagicMock()})
        self.assertNotEqual(result["pending_tool_calls"], [], "부분 변경 → stagnation 아님")

    # ── Stagnation 감지 및 차단 케이스 ───────────────────────────────────────

    async def test_same_tool_same_args_triggers_stagnation(self):
        """동일 tool + 동일 args 반복 → stagnation 감지, pending_tool_calls=[]."""
        prev_calls = [{"name": "search_code", "args": {"name": "하나"}}]
        prev_sig = _plan_signature(prev_calls)
        same_tool_calls = [{"id": "tc1", "name": "search_code", "args": {"name": "하나"}}]
        llm = make_mock_llm(same_tool_calls)
        state = make_state(
            last_plan_signature=prev_sig,
            selected_tools=["search_code"],
        )
        result = await planner_node(state, llm, {"search_code": MagicMock()})
        self.assertEqual(result["pending_tool_calls"], [], "stagnation → tool_calls 없어야 함")

    async def test_stagnation_graceful_message_content(self):
        """stagnation 감지 시 graceful AIMessage에 '동일한 도구' 텍스트 포함."""
        prev_calls = [{"name": "search_code", "args": {"name": "하나"}}]
        prev_sig = _plan_signature(prev_calls)
        same_tool_calls = [{"id": "tc1", "name": "search_code", "args": {"name": "하나"}}]
        llm = make_mock_llm(same_tool_calls)
        state = make_state(
            last_plan_signature=prev_sig,
            selected_tools=["search_code"],
        )
        result = await planner_node(state, llm, {"search_code": MagicMock()})
        content = getattr(result["messages"][0], "content", "")
        self.assertIn("동일한 도구", content, "graceful 메시지에 '동일한 도구' 포함")

    async def test_stagnation_resets_last_plan_signature(self):
        """stagnation 감지 후 last_plan_signature='' 리셋."""
        prev_calls = [{"name": "search_code", "args": {"name": "하나"}}]
        prev_sig = _plan_signature(prev_calls)
        same_tool_calls = [{"id": "tc1", "name": "search_code", "args": {"name": "하나"}}]
        llm = make_mock_llm(same_tool_calls)
        state = make_state(
            last_plan_signature=prev_sig,
            selected_tools=["search_code"],
        )
        result = await planner_node(state, llm, {"search_code": MagicMock()})
        self.assertEqual(result.get("last_plan_signature", ""), "", "stagnation 후 시그니처 리셋")

    async def test_stagnation_multi_tool_all_same_triggers_stagnation(self):
        """멀티 tool 모두 동일 → stagnation 감지."""
        prev_calls = [
            {"name": "tool_a", "args": {"x": 1}},
            {"name": "tool_b", "args": {"y": 2}},
        ]
        prev_sig = _plan_signature(prev_calls)
        same_tool_calls = [
            {"id": "tc1", "name": "tool_a", "args": {"x": 1}},
            {"id": "tc2", "name": "tool_b", "args": {"y": 2}},
        ]
        llm = make_mock_llm(same_tool_calls)
        state = make_state(
            last_plan_signature=prev_sig,
            selected_tools=["tool_a", "tool_b"],
        )
        result = await planner_node(state, llm, {"tool_a": MagicMock(), "tool_b": MagicMock()})
        self.assertEqual(result["pending_tool_calls"], [], "멀티 tool 전부 동일 → stagnation")

    async def test_stagnation_does_not_call_llm_again_after_graceful(self):
        """stagnation graceful 반환 후 current_plan=[], plan='' 확인."""
        prev_calls = [{"name": "search_code", "args": {"name": "하나"}}]
        prev_sig = _plan_signature(prev_calls)
        same_tool_calls = [{"id": "tc1", "name": "search_code", "args": {"name": "하나"}}]
        llm = make_mock_llm(same_tool_calls)
        state = make_state(
            last_plan_signature=prev_sig,
            selected_tools=["search_code"],
        )
        result = await planner_node(state, llm, {"search_code": MagicMock()})
        self.assertEqual(result.get("current_plan", []), [], "stagnation → current_plan=[]")
        self.assertEqual(result.get("plan", ""), "", "stagnation → plan=''")


# ════════════════════════════════════════════════════════════════════════════
# 실행 진입점
# ════════════════════════════════════════════════════════════════════════════
if __name__ == "__main__":
    print("=" * 60)
    print("TestStagnation — _plan_signature + planner_node Stagnation 감지")
    print("PPT 수치 근거: 100% 무의미한 반복 호출 차단")
    print("=" * 60)
    unittest.main(verbosity=2)
