"""
test_agent_improvements.py — 구현한 개선 사항 단위 테스트

외부 의존성(NARU API, Azure OpenAI) 없이 순수 로직을 검증합니다.

테스트 항목:
  A. Self-Correction: error_retries 추적, last_tool_error 전파, 힌트 주입, MAX_RETRIES 차단
  B. Stagnation: _plan_signature 정확성, 동일 시그니처 연속 시 graceful 종료
  C. Router 리셋: router_node 반환 시 iteration_count / last_plan_signature 초기화
  D. current_plan 구조화: tool_calls → structured list 변환
  E. executor 오류 처리: error_retries 증가 / 성공 시 리셋

실행:
  cd /Users/a10886/Documents/github/NARU-Agent
  python3 -m pytest test/test_agent_improvements.py -v
  또는
  python3 test/test_agent_improvements.py
"""
import asyncio
import json
import os
import sys
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _root not in sys.path:
    sys.path.insert(0, _root)

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage

from graph.nodes import MAX_RETRIES, _plan_signature, executor_node, planner_node, router_node
from graph.state import AgentState


# ── 헬퍼: 기본 AgentState 생성 ───────────────────────────────────────────────
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


# ════════════════════════════════════════════════════════════
# A. Self-Correction 테스트
# ════════════════════════════════════════════════════════════

class TestSelfCorrection(unittest.IsolatedAsyncioTestCase):

    async def test_error_retries_increments_on_tool_failure(self):
        """executor_node: 도구 오류 시 error_retries +1, last_tool_error 기록."""
        failing_tool = MagicMock()
        failing_tool.ainvoke = AsyncMock(side_effect=ValueError("잘못된 파라미터"))
        tools_map = {"bad_tool": failing_tool}

        state = make_state(
            pending_tool_calls=[{"id": "tc1", "name": "bad_tool", "args": {"x": 1}}],
            error_retries=0,
        )
        result = await executor_node(state, tools_map)

        self.assertEqual(result["error_retries"], 1, "오류 1회 → error_retries=1")
        self.assertIn("bad_tool", result["last_tool_error"])
        self.assertIn("TOOL_ERROR", result["last_tool_error"])

    async def test_error_retries_resets_on_success(self):
        """executor_node: 성공 시 error_retries=0, last_tool_error='' 리셋."""
        ok_tool = MagicMock()
        ok_tool.ainvoke = AsyncMock(return_value="정상 결과")
        tools_map = {"ok_tool": ok_tool}

        state = make_state(
            pending_tool_calls=[{"id": "tc1", "name": "ok_tool", "args": {}}],
            error_retries=2,
            last_tool_error="이전 오류",
        )
        result = await executor_node(state, tools_map)

        self.assertEqual(result["error_retries"], 0, "성공 → error_retries=0 리셋")
        self.assertEqual(result["last_tool_error"], "", "성공 → last_tool_error 초기화")

    async def test_planner_injects_correction_hint_on_error(self):
        """planner_node: last_tool_error 있을 때 SystemMessage 힌트가 LLM 입력에 포함."""
        received_messages = []

        async def mock_ainvoke(messages):
            received_messages.extend(messages)
            return AIMessage(content="수정된 계획으로 재시도합니다.", tool_calls=[])

        mock_bound_llm = MagicMock()
        mock_bound_llm.ainvoke = mock_ainvoke

        mock_llm = MagicMock()
        mock_llm.bind_tools = MagicMock(return_value=mock_bound_llm)

        state = make_state(
            last_tool_error="[TOOL_ERROR] tool=search_code | error=ValueError: 코드 없음",
            selected_tools=["search_institution_code"],
        )
        tools_map = {"search_institution_code": MagicMock()}

        await planner_node(state, mock_llm, tools_map)

        system_msgs = [m for m in received_messages if isinstance(m, SystemMessage)]
        self.assertTrue(
            any("Self-Correction" in (m.content or "") for m in system_msgs),
            "Self-Correction 힌트 SystemMessage가 LLM 입력에 포함되어야 함"
        )

    async def test_planner_graceful_exit_on_max_retries(self):
        """planner_node: error_retries >= MAX_RETRIES 시 graceful AIMessage 반환."""
        mock_llm = MagicMock()

        state = make_state(
            error_retries=MAX_RETRIES,
            last_tool_error="반복 오류",
        )
        result = await planner_node(state, mock_llm, tools_map={})

        msgs = result.get("messages", [])
        self.assertTrue(len(msgs) > 0, "graceful 메시지가 반환되어야 함")
        content = getattr(msgs[0], "content", "")
        self.assertIn(str(MAX_RETRIES), content, "오류 횟수가 메시지에 포함되어야 함")
        self.assertEqual(result["pending_tool_calls"], [], "tool_calls 없어야 함")
        # LLM이 호출되지 않았어야 함
        mock_llm.bind_tools.assert_not_called()


# ════════════════════════════════════════════════════════════
# B. Stagnation 감지 테스트
# ════════════════════════════════════════════════════════════

class TestStagnation(unittest.TestCase):

    def test_plan_signature_same_tool_same_args(self):
        """_plan_signature: 동일 tool + args → 동일 시그니처."""
        calls = [{"name": "tool_a", "args": {"k": "v"}}]
        sig1 = _plan_signature(calls)
        sig2 = _plan_signature(calls)
        self.assertEqual(sig1, sig2)

    def test_plan_signature_different_args(self):
        """_plan_signature: 동일 tool + 다른 args → 다른 시그니처."""
        calls_a = [{"name": "tool_a", "args": {"date": "20260310"}}]
        calls_b = [{"name": "tool_a", "args": {"date": "20260317"}}]
        self.assertNotEqual(_plan_signature(calls_a), _plan_signature(calls_b))

    def test_plan_signature_different_tools(self):
        """_plan_signature: 다른 tool → 다른 시그니처."""
        calls_a = [{"name": "tool_a", "args": {}}]
        calls_b = [{"name": "tool_b", "args": {}}]
        self.assertNotEqual(_plan_signature(calls_a), _plan_signature(calls_b))

    def test_plan_signature_order_independent(self):
        """_plan_signature: tool 목록 순서가 달라도 동일한 시그니처."""
        calls_1 = [
            {"name": "tool_b", "args": {"x": 1}},
            {"name": "tool_a", "args": {"y": 2}},
        ]
        calls_2 = [
            {"name": "tool_a", "args": {"y": 2}},
            {"name": "tool_b", "args": {"x": 1}},
        ]
        self.assertEqual(_plan_signature(calls_1), _plan_signature(calls_2))

    def test_plan_signature_args_key_order_independent(self):
        """_plan_signature: args 딕셔너리 키 순서가 달라도 동일한 시그니처 (sort_keys=True)."""
        calls_1 = [{"name": "tool_a", "args": {"b": 2, "a": 1}}]
        calls_2 = [{"name": "tool_a", "args": {"a": 1, "b": 2}}]
        self.assertEqual(_plan_signature(calls_1), _plan_signature(calls_2))


class TestStagnationInPlanner(unittest.IsolatedAsyncioTestCase):

    async def test_planner_detects_stagnation(self):
        """planner_node: 동일 시그니처 반복 시 graceful 종료."""
        tool_calls = [{"id": "tc1", "name": "search_code", "args": {"name": "하나"}}]
        prev_sig = _plan_signature(tool_calls)

        async def mock_ainvoke(messages):
            return AIMessage(
                content="",
                tool_calls=[{"id": "tc2", "name": "search_code", "args": {"name": "하나"}}],
            )

        mock_bound_llm = MagicMock()
        mock_bound_llm.ainvoke = mock_ainvoke
        mock_llm = MagicMock()
        mock_llm.bind_tools = MagicMock(return_value=mock_bound_llm)

        state = make_state(
            last_plan_signature=prev_sig,
            selected_tools=["search_code"],
        )
        tools_map = {"search_code": MagicMock()}

        result = await planner_node(state, mock_llm, tools_map)

        self.assertEqual(result["pending_tool_calls"], [], "stagnation → tool_calls 없어야 함")
        content = getattr(result["messages"][0], "content", "")
        self.assertIn("동일한 도구", content, "stagnation 메시지 내용 확인")

    async def test_planner_allows_different_args(self):
        """planner_node: args가 다르면 stagnation 아님 → 정상 진행."""
        prev_calls = [{"name": "stat_tool", "args": {"date": "20260310"}}]
        prev_sig = _plan_signature(prev_calls)

        async def mock_ainvoke(messages):
            return AIMessage(
                content="",
                tool_calls=[{"id": "tc1", "name": "stat_tool", "args": {"date": "20260317"}}],
            )

        mock_bound_llm = MagicMock()
        mock_bound_llm.ainvoke = mock_ainvoke
        mock_llm = MagicMock()
        mock_llm.bind_tools = MagicMock(return_value=mock_bound_llm)

        state = make_state(
            last_plan_signature=prev_sig,
            selected_tools=["stat_tool"],
        )
        tools_map = {"stat_tool": MagicMock()}

        result = await planner_node(state, mock_llm, tools_map)

        self.assertNotEqual(result["pending_tool_calls"], [], "다른 args → 정상 진행")


# ════════════════════════════════════════════════════════════
# C. Router 리셋 테스트
# ════════════════════════════════════════════════════════════

class TestRouterReset(unittest.IsolatedAsyncioTestCase):

    async def test_router_resets_iteration_and_signature(self):
        """router_node: 새 메시지마다 iteration_count / last_plan_signature / error 상태 리셋."""
        mock_result = MagicMock()
        mock_result.categories = ["eai"]

        mock_router_llm = MagicMock()
        mock_router_llm.ainvoke = AsyncMock(return_value=mock_result)

        mock_llm = MagicMock()
        mock_llm.with_structured_output = MagicMock(return_value=mock_router_llm)

        tools_map = {"get_eai_status": MagicMock(), "get_date_range": MagicMock()}

        state = make_state(
            messages=[HumanMessage(content="EAI 상태 알려줘")],
            iteration_count=7,
            last_plan_signature="old_sig",
            error_retries=2,
            last_tool_error="이전 오류",
        )

        result = await router_node(state, mock_llm, tools_map)

        self.assertEqual(result["iteration_count"], 0, "iteration_count → 0 리셋")
        self.assertEqual(result["last_plan_signature"], "", "last_plan_signature → '' 리셋")
        self.assertEqual(result["error_retries"], 0, "error_retries → 0 리셋")
        self.assertEqual(result["last_tool_error"], "", "last_tool_error → '' 리셋")


# ════════════════════════════════════════════════════════════
# D. current_plan 구조화 테스트
# ════════════════════════════════════════════════════════════

class TestCurrentPlan(unittest.IsolatedAsyncioTestCase):

    async def test_current_plan_structure(self):
        """planner_node: tool_calls → current_plan 구조화 리스트 생성."""
        async def mock_ainvoke(messages):
            return AIMessage(
                content="",
                tool_calls=[
                    {"id": "tc1", "name": "search_institution_code", "args": {"name": "하나카드"}},
                    {"id": "tc2", "name": "get_eai_status", "args": {"inst_code": "123"}},
                ],
            )

        mock_bound_llm = MagicMock()
        mock_bound_llm.ainvoke = mock_ainvoke
        mock_llm = MagicMock()
        mock_llm.bind_tools = MagicMock(return_value=mock_bound_llm)

        state = make_state(selected_tools=["search_institution_code", "get_eai_status"])
        tools_map = {
            "search_institution_code": MagicMock(),
            "get_eai_status": MagicMock(),
        }

        result = await planner_node(state, mock_llm, tools_map)

        cp = result.get("current_plan", [])
        self.assertEqual(len(cp), 2, "tool_calls 2개 → current_plan 2개")
        self.assertEqual(cp[0]["step"], 1)
        self.assertEqual(cp[1]["step"], 2)
        self.assertEqual(cp[0]["tool"], "search_institution_code")
        self.assertIn("args", cp[0], "args 필드 존재")

    async def test_current_plan_empty_when_no_tool_calls(self):
        """planner_node: tool_calls 없으면 current_plan=[]."""
        async def mock_ainvoke(messages):
            return AIMessage(content="직접 답변입니다.", tool_calls=[])

        mock_bound_llm = MagicMock()
        mock_bound_llm.ainvoke = mock_ainvoke
        mock_llm = MagicMock()
        mock_llm.bind_tools = MagicMock(return_value=mock_bound_llm)

        state = make_state(selected_tools=[])
        result = await planner_node(state, mock_llm, {})

        self.assertEqual(result.get("current_plan", []), [], "tool_calls 없음 → current_plan=[]")


# ════════════════════════════════════════════════════════════
# E. Executor 오류 처리 추가 케이스
# ════════════════════════════════════════════════════════════

class TestExecutorErrorHandling(unittest.IsolatedAsyncioTestCase):

    async def test_unknown_tool_increments_error_retries(self):
        """executor_node: 존재하지 않는 tool → error_retries 증가."""
        state = make_state(
            pending_tool_calls=[{"id": "tc1", "name": "nonexistent_tool", "args": {}}],
            error_retries=0,
        )
        result = await executor_node(state, tools_map={})

        self.assertEqual(result["error_retries"], 1)
        self.assertIn("TOOL_ERROR", result["last_tool_error"])

    async def test_rejection_does_not_affect_error_retries(self):
        """executor_node: 거절 처리 시 error_retries 변경 없음."""
        state = make_state(
            pending_tool_calls=[{"id": "tc1", "name": "some_tool", "args": {}}],
            execution_rejected=True,
            error_retries=1,
        )
        result = await executor_node(state, tools_map={})

        self.assertFalse(result.get("execution_rejected", True))
        self.assertNotIn("error_retries", result, "거절 처리 시 error_retries 키 없어야 함")

    async def test_tool_message_content_contains_error_details(self):
        """executor_node: 오류 ToolMessage에 tool명과 에러 타입이 포함되어야 함."""
        failing_tool = MagicMock()
        failing_tool.ainvoke = AsyncMock(side_effect=KeyError("missing_key"))
        tools_map = {"target_tool": failing_tool}

        state = make_state(
            pending_tool_calls=[{"id": "tc1", "name": "target_tool", "args": {"k": "v"}}],
        )
        result = await executor_node(state, tools_map)

        tool_msg = result["messages"][0]
        self.assertIsInstance(tool_msg, ToolMessage)
        self.assertIn("target_tool", tool_msg.content)
        self.assertIn("KeyError", tool_msg.content)


# ════════════════════════════════════════════════════════════
# 실행 진입점
# ════════════════════════════════════════════════════════════
if __name__ == "__main__":
    print("=" * 60)
    print("NARU Agent 개선사항 단위 테스트")
    print("=" * 60)
    unittest.main(verbosity=2)
