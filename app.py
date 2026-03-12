"""
app.py — Chainlit 진입점 (NARU Agent UI)

핵심 설계:
  - interrupt_before=["executor"]로 executor 직전에 Human-in-the-loop 구현
  - 승인: Command(resume=None) → executor 정상 실행 → ToolMessages 생성 → planner 최종 답변
  - 거절: graph.update_state()로 synthetic ToolMessages 주입 후 Command(resume=None)
    (synthetic ToolMessage로 state를 정상 시퀀스로 유지하여 400 에러 방지)
  - 새 메시지 도착 시: pending interrupt가 있으면 먼저 state를 정상화

로그인:
  - @cl.password_auth_callback 로 채팅 전 별도 로그인 페이지에서 ID/PW 입력 (비밀번호 마스킹)
  - 로그인 성공 시 cl.User 반환 → on_chat_start에서 MCP 초기화

스트리밍 설계:
  - stream_mode=["messages", "updates"] 사용
  - "messages" 이벤트 중 metadata["langgraph_node"]=="planner" 인 AIMessageChunk만 스트리밍
    (ToolMessage JSON 원본 노출 차단)
  - "updates" 이벤트는 cl.Step으로 "계획 수립"/"도구 실행" 과정을 접힌 토글로 표시
"""
import json

import chainlit as cl
from langchain_core.messages import HumanMessage, SystemMessage, ToolMessage, AIMessageChunk
from langchain_openai import AzureChatOpenAI
from langchain_mcp_adapters.client import MultiServerMCPClient

from config import (
    AZURE_OPENAI_API_KEY,
    AZURE_OPENAI_ENDPOINT,
    AZURE_OPENAI_DEPLOYMENT,
    AZURE_OPENAI_API_VERSION,
)
from graph.graph import build_graph
from mcp_server.tools.auth import login


def _build_mcp_config(naru_user_id: str, naru_user_pw: str) -> dict:
    """MCP 서버 서브프로세스에 자격증명을 환경변수로 주입한 설정 반환."""
    return {
        "naru": {
            "command": "python3",
            "args": ["mcp_server/server.py"],
            "transport": "stdio",
            "env": {
                "NARU_USER_ID": naru_user_id,
                "NARU_USER_PW": naru_user_pw,
            },
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
- 예: "2026년 2월 매주 월요일" → get_date_range(year=2026, month=2, weekday="mon") 먼저 호출

[신청 프로세스 제약사항 - 반드시 준수]
1. (권한 한계) NARU 에이전트는 신청 프로세스에서 '임시저장'까지만 기능을 수행할 수 있습니다. 사용자에게 답변할 때 실제 신청을 완료해주거나 다음 결재를 진행해준다는 식의 표현을 절대 사용하지 마세요. 항상 "임시저장 상태로 준비해드릴 수 있습니다"와 같이 한계를 명확히 설명하세요.

[답변 형식 제약사항 - 반드시 준수]
- 숫자나 시간, 기간 범위를 나타낼 때 물결표(~) 대신 하이픈(-)을 사용하거나 'A부터 B까지'의 텍스트 형태로 출력하세요. (물결표는 취소선 마크다운으로 오인될 수 있습니다.)"""


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


def _get_node_from_metadata(metadata) -> str:
    """LangGraph 메시지 스트림 metadata에서 노드 이름 추출."""
    if isinstance(metadata, dict):
        return metadata.get("langgraph_node", "")
    return ""


# ── 로그인 (비밀번호 마스킹 로그인 페이지) ──────────────────────────────
@cl.password_auth_callback
async def auth_callback(username: str, password: str) -> cl.User | None:
    """Chainlit 로그인 페이지에서 ID/PW를 받아 NARU 로그인.
    성공 시 cl.User 반환, 실패 시 None 반환 (Chainlit이 오류 표시).
    """
    try:
        from mcp_server.tools import auth as _auth_module
        new_sess = await login(username, password)
        _auth_module._session = new_sess
        print(f"[Auth] Chainlit 로그인 성공: {username}")
        return cl.User(
            identifier=username,
            metadata={"naru_user_id": username, "naru_user_pw": password},
        )
    except Exception as e:
        print(f"[Auth] 로그인 실패: {e}")
        return None


# ── 에이전트 초기화 ────────────────────────────────────────────────────
@cl.on_chat_start
async def on_chat_start():
    """로그인 완료 후 MCP + LangGraph 초기화."""
    user: cl.User = cl.user_session.get("user")
    naru_id = user.metadata.get("naru_user_id", "") if user and user.metadata else ""
    naru_pw = user.metadata.get("naru_user_pw", "") if user and user.metadata else ""

    if not naru_id or not naru_pw:
        await cl.Message(content="⚠️ 로그인 정보를 찾을 수 없습니다. 새로고침 후 다시 로그인해 주세요.").send()
        return

    init_msg = await cl.Message(content="⏳ NARU Agent 초기화 중...").send()

    # 자격증명을 MCP 서브프로세스 환경변수로 주입
    mcp_config = _build_mcp_config(naru_id, naru_pw)
    mcp_client = MultiServerMCPClient(mcp_config)
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
    await _update_msg(
        init_msg,
        (
            f"✅ NARU Agent 준비 완료!\n\n"
            f"**로드된 Tool ({len(tools)}개):** {tool_names}\n\n"
            f"무엇을 도와드릴까요?"
        ),
    )


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
    """
    그래프 스트림 실행: planner까지 실행 후 interrupt_before executor에서 멈춤.
    - cl.Step으로 계획 수립 과정을 접힌 토글로 표시
    - planner AIMessageChunk만 result_msg에 실시간 스트리밍
    """
    result_msg = await cl.Message(content="").send()

    try:
        async with cl.Step(name="🔍 계획 수립 중...") as plan_step:
            plan_step.output = ""

            async for mode, payload in graph.astream(
                input_state, config=config, stream_mode=["messages", "updates"]
            ):
                if mode == "messages":
                    if isinstance(payload, tuple) and len(payload) == 2:
                        msg_chunk, metadata = payload
                    else:
                        msg_chunk, metadata = payload, {}

                    node = _get_node_from_metadata(metadata)
                    chunk_content = getattr(msg_chunk, "content", "")
                    if node == "planner" and isinstance(msg_chunk, AIMessageChunk) and chunk_content:
                        await result_msg.stream_token(chunk_content)

                elif mode == "updates":
                    event = payload if isinstance(payload, dict) else {}
                    node_name = list(event.keys())[0] if event else ""
                    raw_output = event.get(node_name, {})
                    node_output = dict(raw_output) if isinstance(raw_output, dict) else {}

                    if node_name == "planner":
                        if node_output.get("pending_tool_calls"):
                            plan = node_output.get("plan", "")
                            print(f"[Planner] Tool 계획:\n{plan}")
                            plan_step.name = "📋 실행 계획"
                            plan_step.output = plan
                        else:
                            plan_step.name = "✅ 분석 완료"
                            # 스트리밍이 없었으면 fallback으로 한번에 출력
                            if not result_msg.content:
                                msgs = node_output.get("messages", [])
                                if msgs:
                                    content = getattr(msgs[-1], "content", "")
                                    if content:
                                        print(f"[Planner] 직접 답변: {content[:100]}")
                                        await _update_msg(result_msg, content)

        await result_msg.update()

        # 스트림 완료 후 interrupt 여부 확인
        snapshot = graph.get_state(config)
        if snapshot.next and "executor" in snapshot.next:
            await _show_approval_ui(graph, config, snapshot)

    except Exception as e:
        await _update_msg(result_msg, f"❌ 오류: {type(e).__name__}: {e}")


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

    # ── 거절 ────────────────────────────────────────────────────────────
    if decision == "rejected":
        pending_now = graph.get_state(config).values.get("pending_tool_calls", [])
        _inject_abort_tool_messages(graph, config, pending_now)
        result_msg = await cl.Message(content="").send()
        try:
            async for mode, payload in graph.astream(None, config=config, stream_mode=["messages", "updates"]):
                if mode == "messages":
                    if isinstance(payload, tuple) and len(payload) == 2:
                        msg_chunk, metadata = payload
                    else:
                        msg_chunk, metadata = payload, {}
                    node = _get_node_from_metadata(metadata)
                    chunk_content = getattr(msg_chunk, "content", "")
                    if node == "planner" and isinstance(msg_chunk, AIMessageChunk) and chunk_content:
                        await result_msg.stream_token(chunk_content)

                elif mode == "updates":
                    event = payload if isinstance(payload, dict) else {}
                    node_name = list(event.keys())[0] if event else ""
                    raw_output = event.get(node_name, {})
                    node_output = dict(raw_output) if isinstance(raw_output, dict) else {}
                    if node_name == "planner" and not node_output.get("pending_tool_calls"):
                        if not result_msg.content:
                            msgs = node_output.get("messages", [])
                            if msgs:
                                content = getattr(msgs[-1], "content", "")
                                if content:
                                    await _update_msg(result_msg, content)

            await result_msg.update()
        except Exception as e:
            await _update_msg(result_msg, f"❌ 오류: {type(e).__name__}: {e}")
        return

    # ── 승인: executor 정상 실행 ────────────────────────────────────────
    result_msg = await cl.Message(content="").send()

    try:
        async with cl.Step(name="⚙️ 도구 실행 중...") as exec_step:
            # Step 내용: 어떤 도구를 실행하는지 미리 표시
            exec_step.output = "\n".join(
                f"• {tc['name']}({json.dumps(tc['args'], ensure_ascii=False)})"
                for tc in pending
            )

            async for mode, payload in graph.astream(None, config=config, stream_mode=["messages", "updates"]):
                if mode == "messages":
                    if isinstance(payload, tuple) and len(payload) == 2:
                        msg_chunk, metadata = payload
                    else:
                        msg_chunk, metadata = payload, {}
                    node = _get_node_from_metadata(metadata)
                    chunk_content = getattr(msg_chunk, "content", "")
                    if node == "planner" and isinstance(msg_chunk, AIMessageChunk) and chunk_content:
                        await result_msg.stream_token(chunk_content)

                elif mode == "updates":
                    event = payload if isinstance(payload, dict) else {}
                    node_name = list(event.keys())[0] if event else ""
                    raw_output = event.get(node_name, {})
                    node_output = dict(raw_output) if isinstance(raw_output, dict) else {}

                    if node_name == "executor":
                        tool_ids = [getattr(m, "tool_call_id", "?") for m in node_output.get("messages", [])]
                        print(f"[Executor] tool_messages: {tool_ids}")
                        exec_step.name = "✅ 도구 실행 완료"

                    if node_name == "planner":
                        if node_output.get("pending_tool_calls"):
                            # 연속 Tool 호출
                            plan = node_output.get("plan", "")
                            print(f"[Planner2] 연속 Tool 계획:\n{plan}")
                            exec_step.name = "✅ 도구 실행 완료"
                            await result_msg.update()

                            new_snapshot = graph.get_state(config)
                            if new_snapshot.next and "executor" in new_snapshot.next:
                                await _show_approval_ui(graph, config, new_snapshot)
                            break
                        else:
                            # 최종 답변 (스트리밍 안됐을 경우 fallback)
                            if not result_msg.content:
                                msgs = node_output.get("messages", [])
                                if msgs:
                                    content = getattr(msgs[-1], "content", "")
                                    if content:
                                        print(f"[Planner2] 최종 답변(fallback): {content[:200]}")
                                        await _update_msg(result_msg, content)

        await result_msg.update()

    except Exception as e:
        print(f"[Error] 승인 후 실행 오류: {type(e).__name__}: {e}")
        await _update_msg(result_msg, f"❌ 오류: {type(e).__name__}: {e}")
