"""
app.py — Chainlit 진입점 (NARU Agent UI)

핵심 설계:
  - interrupt_before=["executor"]로 executor 직전에 Human-in-the-loop 구현
  - 승인: Command(resume=None) → executor 정상 실행 → ToolMessages 생성 → planner 최종 답변
  - 거절: graph.update_state()로 synthetic ToolMessages 주입 후 Command(resume=None)
    (synthetic ToolMessage로 state를 정상 시퀀스로 유지하여 400 에러 방지)
  - 새 메시지 도착 시: pending interrupt가 있으면 먼저 state를 정상화
"""
import json

import chainlit as cl
from langchain_core.messages import HumanMessage, SystemMessage, ToolMessage
from langchain_openai import AzureChatOpenAI
from langchain_mcp_adapters.client import MultiServerMCPClient
from langgraph.types import Command

from config import (
    AZURE_OPENAI_API_KEY,
    AZURE_OPENAI_ENDPOINT,
    AZURE_OPENAI_DEPLOYMENT,
    AZURE_OPENAI_API_VERSION,
)
from graph.graph import build_graph

MCP_CONFIG = {
    "naru": {
        "command": "python3",
        "args": ["mcp_server/server.py"],
        "transport": "stdio",
    }
}

SYSTEM_PROMPT = """당신은 NARU 포털 운영 에이전트입니다.
사용자의 요청에 답하기 위해 반드시 제공된 Tool을 사용해야 합니다.
절대로 Tool 없이 직접 추측하거나 답변하지 마세요.
데이터가 필요한 경우 항상 Tool을 먼저 호출하여 실제 데이터를 가져오세요.

[날짜 계산 규칙 - 반드시 준수]
- 사용자 질문에 "매주 ~요일", "~번째 주", "지난 주", "이번 달", "지난 달" 등
  요일이나 상대적 날짜 표현이 포함된 경우, 직접 날짜를 계산하지 마세요.
- 반드시 get_date_range 툴을 먼저 호출하여 정확한 날짜 목록(YYYYMMDD)을 확보한 뒤,
  그 날짜로 다른 통계 Tool을 호출하세요.
- 예: "2026년 2월 매주 월요일" → get_date_range(year=2026, month=2, weekday="mon") 먼저 호출"""


async def _update_msg(msg: cl.Message, new_content: str):
    """Chainlit 2.x 호환 방식으로 메시지 내용 업데이트"""
    msg.content = new_content
    await msg.update()


def _inject_abort_tool_messages(graph, config: dict, pending_tool_calls: list):
    """
    거절 또는 중단 시 synthetic ToolMessage를 state에 주입하여
    AIMessage(tool_calls) 뒤에 반드시 ToolMessage가 오도록 state 정상화.
    """
    if not pending_tool_calls:
        return
    synthetic_msgs = [
        ToolMessage(
            content="사용자가 Tool 실행을 거절했습니다.",
            tool_call_id=tc["id"],
        )
        for tc in pending_tool_calls
    ]
    graph.update_state(config, {"messages": synthetic_msgs, "pending_tool_calls": []})


@cl.on_chat_start
async def on_chat_start():
    await cl.Message(content="⏳ NARU Agent 초기화 중...").send()

    mcp_client = MultiServerMCPClient(MCP_CONFIG)
    tools = await mcp_client.get_tools()
    tools_map = {t.name: t for t in tools}

    llm = AzureChatOpenAI(
        azure_endpoint=AZURE_OPENAI_ENDPOINT,
        api_key=AZURE_OPENAI_API_KEY,
        azure_deployment=AZURE_OPENAI_DEPLOYMENT,
        api_version=AZURE_OPENAI_API_VERSION,
        temperature=0,
    )
    graph = build_graph(llm_with_tools=llm.bind_tools(tools), tools_map=tools_map)

    thread_id = cl.context.session.id
    cl.user_session.set("graph", graph)
    cl.user_session.set("thread_id", thread_id)

    tool_names = ", ".join(tools_map.keys())
    await cl.Message(
        content=(
            f"✅ NARU Agent 준비 완료!\n\n"
            f"**로드된 Tool ({len(tools)}개):** {tool_names}\n\n"
            f"무엇을 도와드릴까요?"
        )
    ).send()


@cl.on_message
async def on_message(message: cl.Message):
    graph = cl.user_session.get("graph")
    thread_id = cl.user_session.get("thread_id")
    config = {"configurable": {"thread_id": thread_id}}

    print(f"\n{'='*50}")
    print(f"[User] {message.content}")

    # ── 이전 interrupt가 남아있으면 먼저 state 정상화 ────────────────────
    snapshot = graph.get_state(config)
    if snapshot.next and "executor" in snapshot.next:
        pending = snapshot.values.get("pending_tool_calls", [])
        print(f"[State] 이전 interrupt 감지, synthetic ToolMessage 주입: {[tc['name'] for tc in pending]}")
        _inject_abort_tool_messages(graph, config, pending)
        # 그래프를 executor 통해 완전히 종료시킴 (pending_tool_calls가 비어있으므로 executor는 아무것도 안 함)
        async for _ in graph.astream(None, config=config):
            pass

    input_state = {
        "messages": [
            SystemMessage(content=SYSTEM_PROMPT),
            HumanMessage(content=message.content),
        ]
    }
    await _run_graph(graph, input_state, config)


async def _run_graph(graph, input_state: dict, config: dict):
    """그래프 스트림 실행: planner까지 실행 후 interrupt_before executor 에서 멈춤"""
    thinking_msg = await cl.Message(content="🔍 분석 중...").send()

    try:
        async for event in graph.astream(input_state, config=config):
            node_name = list(event.keys())[0] if event else ""
            node_output = event.get(node_name, {})

            # Planner 직접 답변 (Tool 없는 경우)
            if node_name == "planner" and not node_output.get("pending_tool_calls"):
                messages = node_output.get("messages", [])
                if messages:
                    content = getattr(messages[-1], "content", "")
                    if content:
                        print(f"[Planner] 직접 답변: {content[:100]}")
                        await _update_msg(thinking_msg, content)

            # Planner가 Tool 호출 계획 수립
            if node_name == "planner" and node_output.get("pending_tool_calls"):
                plan = node_output.get("plan", "")
                print(f"[Planner] Tool 계획:\n{plan}")
                await _update_msg(thinking_msg, f"📋 실행 계획:\n```\n{plan}\n```")

        # 스트림 완료 후 interrupt 여부 확인
        snapshot = graph.get_state(config)
        if snapshot.next and "executor" in snapshot.next:
            await _show_approval_ui(graph, config, snapshot)

    except Exception as e:
        await _update_msg(thinking_msg, f"❌ 오류: {type(e).__name__}: {e}")


async def _show_approval_ui(graph, config: dict, snapshot):
    """executor 실행 전 사용자 승인/거절 요청"""
    pending = snapshot.values.get("pending_tool_calls", [])

    tool_list = "\n".join(
        f"  • `{tc['name']}`  {json.dumps(tc['args'], ensure_ascii=False)}"
        for tc in pending
    )
    approval_text = f"🔧 **다음 Tool을 실행하려고 합니다. 승인하시겠습니까?**\n\n{tool_list}"

    res = await cl.AskActionMessage(
        content=approval_text,
        actions=[
            cl.Action(name="approve", label="✅ 승인", value="approved", payload={"decision": "approved"}),
            cl.Action(name="reject",  label="❌ 거절", value="rejected", payload={"decision": "rejected"}),
        ],
        timeout=120,
    ).send()

    # Chainlit 2.x: res는 dict {'name':..,'value':..,'label':..,'payload':..} 형태
    print(f"[Approval] res 원본: {res}")
    is_approved = False
    if res:
        is_approved = (
            res.get("value") == "approved"
            or res.get("name") == "approve"
            or (res.get("payload") or {}).get("decision") == "approved"
        )
    decision = "approved" if is_approved else "rejected"
    print(f"[Approval] 최종 결정: {decision}")

    if decision == "rejected":
        # 거절: synthetic ToolMessage 주입으로 state 정상화 → planner가 대안 답변
        pending_now = graph.get_state(config).values.get("pending_tool_calls", [])
        _inject_abort_tool_messages(graph, config, pending_now)
        result_msg = await cl.Message(content="❌ 거절됨 — 대안 답변 생성 중...").send()
        try:
            async for event in graph.astream(None, config=config):
                node_name = list(event.keys())[0] if event else ""
                node_output = event.get(node_name, {})
                if node_name == "planner" and not node_output.get("pending_tool_calls"):
                    messages = node_output.get("messages", [])
                    if messages:
                        content = getattr(messages[-1], "content", "")
                        if content:
                            await _update_msg(result_msg, content)
        except Exception as e:
            await _update_msg(result_msg, f"❌ 오류: {type(e).__name__}: {e}")
        return

    # 승인: executor 정상 실행
    result_msg = await cl.Message(content="✅ 승인됨 — Tool 실행 중...").send()
    try:
        async for event in graph.astream(None, config=config):
            node_name = list(event.keys())[0] if event else ""
            node_output = event.get(node_name, {})

            if node_name == "executor":
                print(f"[Executor] tool_messages: {[getattr(m, 'tool_call_id', '?') for m in node_output.get('messages', [])]}")

            if node_name == "planner" and not node_output.get("pending_tool_calls"):
                messages = node_output.get("messages", [])
                if messages:
                    content = getattr(messages[-1], "content", "")
                    if content:
                        print(f"[Planner2] 최종 답변: {content[:200]}")
                        await _update_msg(result_msg, content)

            # 연속 Tool 호출이 필요한 경우
            if node_name == "planner" and node_output.get("pending_tool_calls"):
                plan = node_output.get("plan", "")
                print(f"[Planner2] 연속 Tool 계획:\n{plan}")
                await _update_msg(result_msg, f"📋 추가 계획:\n```\n{plan}\n```")
                new_snapshot = graph.get_state(config)
                if new_snapshot.next and "executor" in new_snapshot.next:
                    await _show_approval_ui(graph, config, new_snapshot)
                break

    except Exception as e:
        print(f"[Error] 승인 후 실행 오류: {type(e).__name__}: {e}")
        await _update_msg(result_msg, f"❌ 오류: {type(e).__name__}: {e}")
