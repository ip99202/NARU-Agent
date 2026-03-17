"""
test_response_time_benchmark.py — 시맨틱 라우터 도입 전/후 응답시간 벤치마크

측정 항목:
  - 전체 end-to-end 응답 시간 (초)
  - 노드별 소요 시간 (planner, executor)
  - 총 LLM 호출 횟수 및 토큰 사용량 (usage_metadata 기반)
  - 호출된 Tool 목록

테스트 쿼리:
  "현재 기준으로 EIGW 오류가 가장 많은 인터페이스의 저번주 월요일 시간대별 호출량을 표로 정리해줘"

  → 멀티스텝 쿼리 (date 조회 → EIGW 오류 조회 → 인터페이스 필터 → 시간대별 호출량 조회)
  → 시맨틱 라우터 도입 시 "eigw" 카테고리 도구만 바인딩되므로 토큰 감소 효과 확인 가능

실행:
  cd /Users/a10886/Documents/github/NARU-Agent
  python3 test/test_response_time_benchmark.py

환경변수 (config.py):
  NARU_USER_ID, NARU_USER_PW  — NARU 로그인 계정
  AZURE_OPENAI_*              — Azure OpenAI 연결 정보
"""
import asyncio
import json
import os
import sys
import time
from dataclasses import dataclass, field
from typing import Any

# 프로젝트 루트를 PYTHONPATH에 추가
_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _root not in sys.path:
    sys.path.insert(0, _root)

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langchain_mcp_adapters.client import MultiServerMCPClient
from langchain_openai import AzureChatOpenAI

from config import (
    AZURE_OPENAI_API_KEY,
    AZURE_OPENAI_API_VERSION,
    AZURE_OPENAI_DEPLOYMENT,
    AZURE_OPENAI_ENDPOINT,
)
from graph.graph import build_graph

# NARU 계정 정보: config.py는 런타임 입력 방식이므로 .env에서 직접 로드
NARU_USER_ID: str = os.environ.get("NARU_USER_ID", "")
NARU_USER_PW: str = os.environ.get("NARU_USER_PW", "")

if not NARU_USER_ID or not NARU_USER_PW:
    print("⚠️  .env 파일에 NARU_USER_ID / NARU_USER_PW 를 설정하거나")
    print("   환경변수로 직접 전달하세요.")
    print("   예) NARU_USER_ID=myid NARU_USER_PW=mypw python3 test/test_response_time_benchmark.py")
    sys.exit(1)

# ── 테스트 설정 ───────────────────────────────────────────────────────────────

# 측정 대상 쿼리 (복잡한 멀티스텝: 날짜 계산 → EIGW 오류 조회 → 시간대별 호출량)
BENCHMARK_QUERY = (
    "현재 기준으로 EIGW 오류가 가장 많은 인터페이스의 "
    "저번주 월요일 시간대별 호출량을 표로 정리해줘"
)

SYSTEM_PROMPT = """당신은 NARU 포털 운영 에이전트입니다.
사용자의 요청에 답하기 위해 반드시 제공된 Tool을 사용해야 합니다.
절대로 Tool 없이 직접 추측하거나 답변하지 마세요.
데이터가 필요한 경우 항상 Tool을 먼저 호출하여 실제 데이터를 가져오세요.

[날짜 계산 규칙 - 반드시 준수]
- 사용자 질문에 "매주 ~요일", "~번째 주", "지난 주", "이번 달", "지난 달" 등
  요일이나 상대적 날짜 표현이 포함된 경우, 직접 날짜를 계산하지 마세요.
- 반드시 get_date_range 툴을 먼저 호출하여 정확한 날짜 목록(YYYYMMDD)을 확보한 뒤,
  그 날짜로 다른 통계 Tool을 호출하세요.

[답변 형식 제약사항]
- 숫자나 시간, 기간 범위를 나타낼 때 물결표(~) 대신 하이픈(-)을 사용하거나 'A부터 B까지'의 텍스트 형태로 출력하세요."""

# Human-in-the-loop 없이 모든 Tool을 자동 승인하는 테스트 그래프를 사용하기 위해
# interrupt_before 없는 별도 빌드 함수를 정의합니다.
MCP_CONFIG = {
    "naru": {
        "command": "python3",
        "args": ["mcp_server/server.py"],
        "transport": "stdio",
        "env": {
            "NARU_USER_ID": NARU_USER_ID,
            "NARU_USER_PW": NARU_USER_PW,
        },
    }
}


# ── 데이터 클래스 ──────────────────────────────────────────────────────────────

@dataclass
class NodeTiming:
    """개별 노드 실행 시간 기록"""
    node: str
    elapsed: float  # 초


@dataclass
class LLMUsage:
    """LLM 단일 호출 토큰 사용량"""
    input_tokens: int = 0
    output_tokens: int = 0


@dataclass
class BenchmarkResult:
    """벤치마크 전체 결과"""
    label: str                          # 라벨 (e.g., "현재 (라우터 없음)")
    total_elapsed: float = 0.0          # 전체 실행 시간 (초)
    node_timings: list[NodeTiming] = field(default_factory=list)
    llm_calls: list[LLMUsage] = field(default_factory=list)
    tools_called: list[str] = field(default_factory=list)
    tools_bound: int = 0                # planner에 바인딩된 도구 수
    final_answer: str = ""
    error: str = ""

    @property
    def total_input_tokens(self) -> int:
        return sum(u.input_tokens for u in self.llm_calls)

    @property
    def total_output_tokens(self) -> int:
        return sum(u.output_tokens for u in self.llm_calls)

    @property
    def llm_call_count(self) -> int:
        return len(self.llm_calls)

    def planner_elapsed(self) -> float:
        return sum(t.elapsed for t in self.node_timings if t.node == "planner")

    def executor_elapsed(self) -> float:
        return sum(t.elapsed for t in self.node_timings if t.node == "executor")


# ── interrupt 없는 그래프 빌드 ────────────────────────────────────────────────

def _build_graph_no_interrupt_baseline(llm: Any, tools_map: dict) -> Any:
    """
    [베이스라인] router 없이 전체 도구를 한 번에 bind_tools한 그래프 (interrupt 없음).
    라우터 도입 이전 아키텍처를 재현합니다.
    """
    import functools
    from langgraph.graph import END, StateGraph
    from graph.nodes import executor_node, planner_node
    from graph.state import AgentState

    def route_after_planner(state: AgentState) -> str:
        return "need_execution" if state.get("pending_tool_calls") else "final_answer"

    llm_with_tools = llm.bind_tools(list(tools_map.values()))

    async def _planner(state, **_):
        import json
        from langchain_core.messages import AIMessage
        current_iter = state.get("iteration_count", 0) + 1
        response: AIMessage = await llm_with_tools.ainvoke(state["messages"])
        if response.tool_calls:
            pending = [{"id": tc["id"], "name": tc["name"], "args": tc["args"]} for tc in response.tool_calls]
            plan = "\n".join(f"• {tc['name']}({json.dumps(tc['args'], ensure_ascii=False)})" for tc in pending)
            return {"messages": [response], "pending_tool_calls": pending, "plan": plan, "iteration_count": current_iter}
        return {"messages": [response], "pending_tool_calls": [], "plan": "", "iteration_count": current_iter}

    builder = StateGraph(AgentState)
    builder.add_node("planner", _planner)
    builder.add_node("executor", functools.partial(executor_node, tools_map=tools_map))
    builder.set_entry_point("planner")
    builder.add_conditional_edges("planner", route_after_planner, {"need_execution": "executor", "final_answer": END})
    builder.add_edge("executor", "planner")
    return builder.compile()


def _build_graph_no_interrupt_router(llm: Any, tools_map: dict) -> Any:
    """
    [라우터 포함] router → planner → executor 흐름, interrupt 없음.
    시맨틱 라우터 도입 후 아키텍처를 재현합니다.
    """
    import functools
    from langgraph.graph import END, StateGraph
    from graph.nodes import executor_node, planner_node, router_node
    from graph.state import AgentState

    def route_after_planner(state: AgentState) -> str:
        return "need_execution" if state.get("pending_tool_calls") else "final_answer"

    builder = StateGraph(AgentState)
    builder.add_node("router",  functools.partial(router_node,  llm=llm, tools_map=tools_map))
    builder.add_node("planner", functools.partial(planner_node, llm=llm, tools_map=tools_map))
    builder.add_node("executor", functools.partial(executor_node, tools_map=tools_map))
    builder.set_entry_point("router")
    builder.add_edge("router", "planner")
    builder.add_conditional_edges("planner", route_after_planner, {"need_execution": "executor", "final_answer": END})
    builder.add_edge("executor", "planner")
    return builder.compile()


# ── 실제 벤치마크 실행 ────────────────────────────────────────────────────────

async def run_benchmark(llm: Any, tools_map: dict, label: str, use_router: bool = False) -> BenchmarkResult:
    """
    단일 벤치마크 실행.

    Args:
        llm:        AzureChatOpenAI 인스턴스 (bind_tools 미적용)
        tools_map:  {tool_name: tool} 전체 딕셔너리
        label:      결과 출력 시 사용할 라벨
        use_router: True면 시맨틱 라우터 포함 그래프 사용
    """
    result = BenchmarkResult(label=label)

    print(f"\n{'━'*60}")
    print(f"🚀 벤치마크 시작: {label}")
    print(f"   쿼리: \"{BENCHMARK_QUERY}\"")
    print(f"{'━'*60}")

    if use_router:
        graph = _build_graph_no_interrupt_router(llm, tools_map)
        entry_nodes = {"router", "planner"}
    else:
        graph = _build_graph_no_interrupt_baseline(llm, tools_map)
        entry_nodes = {"planner"}
        result.tools_bound = len(tools_map)

    input_state = {
        "messages": [
            SystemMessage(content=SYSTEM_PROMPT),
            HumanMessage(content=BENCHMARK_QUERY),
        ]
    }
    config = {"configurable": {"thread_id": f"benchmark_{label}_{int(time.time())}"}}

    total_start = time.perf_counter()

    try:
        async for mode, payload in graph.astream(
            input_state, config=config, stream_mode=["messages", "updates"]
        ):
            if mode == "updates":
                event = payload if isinstance(payload, dict) else {}
                node_name = list(event.keys())[0] if event else ""
                node_output = event.get(node_name, {})

                if node_name == "router" and isinstance(node_output, dict):
                    selected = node_output.get("selected_tools", [])
                    result.tools_bound = len(selected)
                    print(f"  [Router] 선택된 도구 수: {result.tools_bound}개 → {selected}")

                elif node_name == "planner":
                    msgs = node_output.get("messages", []) if isinstance(node_output, dict) else []
                    for msg in msgs:
                        if isinstance(msg, AIMessage) and hasattr(msg, "usage_metadata") and msg.usage_metadata:
                            usage = msg.usage_metadata
                            result.llm_calls.append(LLMUsage(
                                input_tokens=usage.get("input_tokens", 0),
                                output_tokens=usage.get("output_tokens", 0),
                            ))
                            print(
                                f"  [Planner #{result.llm_call_count}] "
                                f"input={usage.get('input_tokens',0)} / "
                                f"output={usage.get('output_tokens',0)} tokens"
                            )
                    if isinstance(node_output, dict):
                        for tc in node_output.get("pending_tool_calls", []):
                            tool_name = tc.get("name", "")
                            if tool_name:
                                result.tools_called.append(tool_name)
                                print(f"  [Tool 선택] {tool_name}({json.dumps(tc.get('args',{}), ensure_ascii=False)[:80]})")

                elif node_name == "executor":
                    msgs = node_output.get("messages", []) if isinstance(node_output, dict) else []
                    print(f"  [Executor] {len(msgs)}개 Tool 실행 완료")

    except Exception as e:
        result.error = f"{type(e).__name__}: {e}"
        print(f"  ❌ 오류 발생: {result.error}")

    total_end = time.perf_counter()
    result.total_elapsed = total_end - total_start

    # 최종 상태에서 답변 추출
    try:
        snapshot = graph.get_state(config)
        messages = snapshot.values.get("messages", [])
        for msg in reversed(messages):
            if isinstance(msg, AIMessage) and msg.content and not msg.tool_calls:
                result.final_answer = msg.content
                break
    except Exception:
        pass

    return result


# ── 결과 출력 ─────────────────────────────────────────────────────────────────

def print_result(result: BenchmarkResult) -> None:
    sep = "─" * 60
    print(f"\n{sep}")
    print(f"📊 결과: {result.label}")
    print(sep)

    if result.error:
        print(f"  ❌ 실행 오류: {result.error}")
        return

    print(f"  ⏱  전체 응답시간   : {result.total_elapsed:.2f}초")
    print(f"  🔧 바인딩된 도구   : {result.tools_bound}개")
    print(f"  🤖 LLM 호출 횟수  : {result.llm_call_count}회")
    print(f"  📥 총 Input 토큰  : {result.total_input_tokens:,}")
    print(f"  📤 총 Output 토큰 : {result.total_output_tokens:,}")
    print(f"  🛠  호출된 Tool    : {result.tools_called}")

    if result.final_answer:
        preview = result.final_answer[:300].replace("\n", " ")
        print(f"\n  💬 최종 답변 (앞 300자):\n  {preview}{'...' if len(result.final_answer) > 300 else ''}")

    print(sep)


def print_comparison(baseline: BenchmarkResult, *others: BenchmarkResult) -> None:
    """기준(baseline)과 다른 결과들을 비교 출력합니다."""
    print(f"\n{'═'*60}")
    print("📈 비교 요약")
    print(f"{'═'*60}")

    header = f"{'항목':<22} | {baseline.label:<22}"
    for o in others:
        header += f" | {o.label:<22}"
    print(header)
    print("─" * (22 + (26 * (1 + len(others)))))

    rows = [
        ("전체 응답시간 (초)",    f"{baseline.total_elapsed:.2f}",         lambda o: f"{o.total_elapsed:.2f}"),
        ("바인딩 도구 수",        f"{baseline.tools_bound}개",              lambda o: f"{o.tools_bound}개"),
        ("LLM 호출 횟수",         f"{baseline.llm_call_count}회",           lambda o: f"{o.llm_call_count}회"),
        ("총 Input 토큰",         f"{baseline.total_input_tokens:,}",       lambda o: f"{o.total_input_tokens:,}"),
        ("총 Output 토큰",        f"{baseline.total_output_tokens:,}",      lambda o: f"{o.total_output_tokens:,}"),
    ]

    for label, base_val, getter in rows:
        row = f"  {label:<20} | {base_val:<22}"
        for o in others:
            val = getter(o)
            row += f" | {val:<22}"
        print(row)

    # 시간 단축률
    if others:
        for o in others:
            if baseline.total_elapsed > 0:
                delta = baseline.total_elapsed - o.total_elapsed
                pct = (delta / baseline.total_elapsed) * 100
                sign = "↓" if delta > 0 else "↑"
                print(f"\n  [{baseline.label}] → [{o.label}]")
                print(f"    응답시간 변화: {abs(delta):.2f}초 {sign} ({abs(pct):.1f}%{'  단축' if delta > 0 else '  증가'})")
                if baseline.total_input_tokens > 0:
                    tok_delta = baseline.total_input_tokens - o.total_input_tokens
                    tok_pct = (tok_delta / baseline.total_input_tokens) * 100
                    tok_sign = "↓" if tok_delta > 0 else "↑"
                    print(f"    Input 토큰 변화: {abs(tok_delta):,} {tok_sign} ({abs(tok_pct):.1f}%{'  감소' if tok_delta > 0 else '  증가'})")

    print(f"{'═'*60}")


# ── 메인 ─────────────────────────────────────────────────────────────────────

async def main():
    print("=" * 60)
    print("🏁 NARU Agent 응답시간 벤치마크")
    print("   시맨틱 라우터 도입 전/후 비교용")
    print("=" * 60)
    print(f"   대상 쿼리: \"{BENCHMARK_QUERY}\"")

    # ── LLM 초기화 ────────────────────────────────────────────
    llm = AzureChatOpenAI(
        azure_endpoint=AZURE_OPENAI_ENDPOINT,
        api_key=AZURE_OPENAI_API_KEY,
        azure_deployment=AZURE_OPENAI_DEPLOYMENT,
        api_version=AZURE_OPENAI_API_VERSION,
        temperature=0,
    )

    # ── MCP 클라이언트 초기화 ──────────────────────────────────
    print("\n⏳ MCP Server 연결 중...")
    client = MultiServerMCPClient(MCP_CONFIG)
    tools = await client.get_tools()
    tools_map = {t.name: t for t in tools}
    print(f"✅ MCP 연결 성공 — 총 {len(tools)}개 도구 로드")
    print(f"   도구 목록: {', '.join(tools_map.keys())}")

    # ── [현재 기준] 전체 도구 바인딩 (라우터 없음) ───────────────
    baseline_result = await run_benchmark(
        llm=llm,
        tools_map=tools_map,
        label="현재 (라우터 없음, 전체 도구)",
        use_router=False,
    )
    print_result(baseline_result)

    # ── [라우터 도입 후] 동적 도구 바인딩 ─────────────────────────
    router_result = await run_benchmark(
        llm=llm,
        tools_map=tools_map,
        label="시맨틱 라우터 (동적 바인딩)",
        use_router=True,
    )
    print_result(router_result)

    # ── before/after 비교 ─────────────────────────────────────────
    print_comparison(baseline_result, router_result)

    # ── JSON 결과 저장 ─────────────────────────────────────────
    results_for_json = [baseline_result, router_result]
    output = {
        "query": BENCHMARK_QUERY,
        "results": [
            {
                "label": r.label,
                "total_elapsed_sec": round(r.total_elapsed, 3),
                "tools_bound": r.tools_bound,
                "llm_call_count": r.llm_call_count,
                "total_input_tokens": r.total_input_tokens,
                "total_output_tokens": r.total_output_tokens,
                "tools_called": r.tools_called,
                "error": r.error,
            }
            for r in results_for_json
        ],
    }

    result_path = os.path.join(_root, "test", "benchmark_result.json")
    with open(result_path, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)
    print(f"\n💾 결과 저장: {result_path}")

    print(f"\n{'='*60}")
    print("벤치마크 완료")
    print(f"{'='*60}")


if __name__ == "__main__":
    asyncio.run(main())
