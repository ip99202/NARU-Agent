"""
Phase 3 사전 단위 테스트: Azure OpenAI Function Calling + MCP Tool 인식 검증

테스트 시나리오:
  1. MCP Server를 stdio로 기동하여 Tool 목록 로드
  2. AzureChatOpenAI 에 Tool 바인딩
  3. 테스트 메시지를 보내 LLM이 올바른 Tool을 선택(Function Calling)하는지 확인
  4. 선택된 Tool을 실제로 실행(Executor 역할)하여 NARU API 응답 반환 확인

실행: python3 test_function_calling.py
"""
import asyncio
import json
from langchain_openai import AzureChatOpenAI
from langchain_mcp_adapters.client import MultiServerMCPClient
from langchain_core.messages import HumanMessage, AIMessage, ToolMessage
from config import (
    AZURE_OPENAI_API_KEY,
    AZURE_OPENAI_ENDPOINT,
    AZURE_OPENAI_DEPLOYMENT,
    AZURE_OPENAI_API_VERSION,
)

# ── LLM 초기화 ─────────────────────────────────────────────
llm = AzureChatOpenAI(
    azure_endpoint=AZURE_OPENAI_ENDPOINT,
    api_key=AZURE_OPENAI_API_KEY,
    azure_deployment=AZURE_OPENAI_DEPLOYMENT,
    api_version=AZURE_OPENAI_API_VERSION,
    temperature=0,
)

# ── MCP Server 설정 ─────────────────────────────────────────
MCP_CONFIG = {
    "naru": {
        "command": "python3",
        "args": ["mcp_server/server.py"],
        "transport": "stdio",
    }
}

# ── 테스트 케이스 ────────────────────────────────────────────
TEST_CASES = [
    {
        "name": "① 기관 코드 조회",
        "message": "하나카드 기관코드 알려줘",
        "expected_tool": "search_institution_code",
    },
    {
        "name": "② EIGW 오류 통계 조회",
        "message": "오늘 EIGW 오류 통계 보여줘",
        "expected_tool": "get_eigw_error_stats",
    },
    {
        "name": "③ 큐 적체량 조회",
        "message": "현재 MQ 큐 적체량 어떻게 돼?",
        "expected_tool": "get_queue_depth",
    },
    {
        "name": "④ 연속 Tool 호출 (기관 조회 → 인터페이스 검색)",
        "message": "하나카드 관련 인터페이스 목록 찾아줘",
        "expected_tool": "search_institution_code",  # 첫 번째 호출 기대
    },
]


async def run_test(llm_with_tools, tools_map: dict, test: dict):
    print(f"\n{'─'*60}")
    print(f"{test['name']}")
    print(f"  입력: \"{test['message']}\"")
    print(f"  기대 Tool: {test['expected_tool']}")

    messages = [HumanMessage(content=test["message"])]

    # ── Step 1: LLM이 Tool을 선택하는지 확인 ──────────────────
    response = await llm_with_tools.ainvoke(messages)
    messages.append(response)

    if not response.tool_calls:
        print(f"  ❌ LLM이 Tool을 호출하지 않고 직접 답변함:")
        print(f"     {response.content[:200]}")
        return

    called_tools = [tc["name"] for tc in response.tool_calls]
    print(f"  ✅ LLM이 선택한 Tool: {called_tools}")

    first_tool = called_tools[0]
    match = "✅" if first_tool == test["expected_tool"] else "⚠️ (예상과 다름)"
    print(f"  {match} 첫 번째 Tool 선택: {first_tool}")

    # ── Step 2: 선택된 Tool 실제 실행 ─────────────────────────
    for tool_call in response.tool_calls:
        tool_name = tool_call["name"]
        tool_args = tool_call["args"]

        if tool_name not in tools_map:
            print(f"  ❌ 알 수 없는 Tool: {tool_name}")
            continue

        print(f"\n  [실행] {tool_name}({json.dumps(tool_args, ensure_ascii=False)})")
        try:
            tool_result = await tools_map[tool_name].ainvoke(tool_args)
            result_str = json.dumps(tool_result, ensure_ascii=False) if isinstance(tool_result, dict) else str(tool_result)
            print(f"  [결과] {result_str[:400]}")

            # Tool 결과를 messages에 추가 후 최종 LLM 응답 생성
            messages.append(ToolMessage(content=result_str, tool_call_id=tool_call["id"]))
        except Exception as e:
            print(f"  ❌ Tool 실행 오류: {type(e).__name__}: {e}")
            messages.append(ToolMessage(content=f"오류: {e}", tool_call_id=tool_call["id"]))

    # ── Step 3: Tool 결과 기반 최종 답변 ───────────────────────
    final = await llm_with_tools.ainvoke(messages)
    print(f"\n  [최종 답변] {final.content[:300]}")


async def main():
    print("=" * 60)
    print("Azure OpenAI × MCP Tool Function Calling 단위 테스트")
    print("=" * 60)

    try:
        # langchain-mcp-adapters 0.2.1+: context manager 미지원, 직접 await 사용
        client = MultiServerMCPClient(MCP_CONFIG)
        tools = await client.get_tools()
        tools_map = {t.name: t for t in tools}

        print(f"\n✅ MCP Server 연결 성공")
        print(f"   로드된 Tool 목록 ({len(tools)}개):")
        for t in tools:
            print(f"   - {t.name}: {t.description[:60]}...")

        llm_with_tools = llm.bind_tools(tools)
        print(f"\n✅ AzureChatOpenAI ({AZURE_OPENAI_DEPLOYMENT}) Tool 바인딩 완료")

        # 각 테스트 케이스 실행
        for test in TEST_CASES:
            await run_test(llm_with_tools, tools_map, test)

    except Exception as e:
        print(f"\n❌ MCP 연결 오류: {type(e).__name__}: {e}")
        import traceback
        traceback.print_exc()

    print(f"\n{'='*60}")
    print("테스트 완료")


if __name__ == "__main__":
    asyncio.run(main())
