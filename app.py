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
2. (신청 완결성) 인터페이스 신청(EAI, EIGW, MCG)은 기초정보(Step 1), 상세정보(regTemp), 최종 승인자(Step 3)의 3단계 임시저장 과정으로 구성됩니다. 신청 프로세스가 시작되면 반드시 최종 단계인 Step 3까지 모두 완료하도록 안내하고 실행하세요. 중간 과정에서 멈추지 말고 사용자에게 필요한 정보를 물어봐서라도 마지막 단계까지 도달해야 합니다.

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


async def _ask_approval(pending: list) -> bool:
    """
    승인/거절 UI만 표시하고 결과(bool)를 반환합니다.
    스트리밍이나 그래프 실행을 하지 않는 순수 UI 함수입니다.
    """
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
    if not res:
        return False
    is_approved = (
        res.get("value") == "approved"
        or res.get("name") == "approve"
        or (res.get("payload") or {}).get("decision") == "approved"
    )
    print(f"[Approval] 최종 결정: {'approved' if is_approved else 'rejected'}")
    return is_approved


async def _stream_graph(
    graph,
    input_state,        # None이면 resume, dict이면 새 입력
    config: dict,
    result_msg,         # 스트리밍 대상 메시지
    step_ctx=None,      # cl.Step 컨텍스트 (executor 단계에서 사용)
    planner_label: str = "planner",
):
    """
    graph.astream()을 소비하며:
    - planner AIMessageChunk → result_msg 스트리밍
    - updates 이벤트 → step_ctx 및 로그 업데이트

    Returns:
        plan_step_ref (dict | None): {'name': ..., 'output': ...} — plan_step 업데이트용
        final_answer_content (str): 직접 답변(fallback) 내용, 없으면 ""
    """
    plan_info = {}
    final_answer_content = ""

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
            if node == planner_label and isinstance(msg_chunk, AIMessageChunk) and chunk_content:
                await result_msg.stream_token(chunk_content)

        elif mode == "updates":
            event = payload if isinstance(payload, dict) else {}
            node_name = list(event.keys())[0] if event else ""
            raw_output = event.get(node_name, {})
            node_output = dict(raw_output) if isinstance(raw_output, dict) else {}

            if node_name == "executor":
                tool_ids = [getattr(m, "tool_call_id", "?") for m in node_output.get("messages", [])]
                print(f"[Executor] tool_messages: {tool_ids}")
                if step_ctx:
                    step_ctx.name = "✅ 도구 실행 완료"

            elif node_name == "planner":
                if node_output.get("pending_tool_calls"):
                    plan = node_output.get("plan", "")
                    print(f"[{planner_label.capitalize()}] Tool 계획:\n{plan}")
                    plan_info = {"plan": plan, "has_pending": True}
                    if step_ctx:
                        step_ctx.name = "✅ 도구 실행 완료"
                else:
                    plan_info = {"has_pending": False}
                    if step_ctx:
                        pass  # step은 이미 완료
                    # 스트리밍 없었으면 fallback
                    if not result_msg.content:
                        msgs = node_output.get("messages", [])
                        if msgs:
                            content = getattr(msgs[-1], "content", "")
                            if content:
                                print(f"[{planner_label.capitalize()}] 직접 답변: {content[:100]}")
                                final_answer_content = content

    return plan_info, final_answer_content


async def _run_graph(graph, input_state: dict, config: dict):
    """
    그래프 스트림 실행 메인 루프.

    설계:
      Phase 1) 최초 planner 실행 → interrupt_before executor에서 멈춤
      Phase 2) while 루프:
               ① 승인 UI 표시 (_ask_approval — 순수 UI, bool 반환)
               ② 승인 → executor 실행 → 다음 planner 실행
                  거절 → synthetic ToolMessage 주입 → planner 재실행
               ③ 다음 interrupt가 없으면 루프 종료

    재귀 호출 없이 단일 루프로 처리하여 Chainlit AskActionMessage 중첩 문제 해결.
    """
    # ── Phase 1: 최초 플래닝 ────────────────────────────────────────────
    result_msg = await cl.Message(content="").send()
    try:
        async with cl.Step(name="🔍 계획 수립 중...") as plan_step:
            plan_step.output = ""
            plan_info, fallback = await _stream_graph(
                graph, input_state, config, result_msg, step_ctx=None, planner_label="planner"
            )

            if plan_info.get("has_pending"):
                plan_step.name = "📋 실행 계획"
                plan_step.output = plan_info.get("plan", "")
            else:
                plan_step.name = "✅ 분석 완료"
                if fallback:
                    await _update_msg(result_msg, fallback)

        await result_msg.update()

    except Exception as e:
        await _update_msg(result_msg, f"❌ 오류: {type(e).__name__}: {e}")
        return

    # ── Phase 2: 승인 루프 ─────────────────────────────────────────────
    iteration = 0
    while True:
        snapshot = graph.get_state(config)
        if not (snapshot.next and "executor" in snapshot.next):
            break  # 더 이상 executor 대기 없음 → 종료

        iteration += 1
        pending = snapshot.values.get("pending_tool_calls", [])

        # ① 승인 UI (순수 UI, 그래프 실행 없음)
        is_approved = await _ask_approval(pending)

        # ② 거절 처리: synthetic ToolMessage 주입
        if not is_approved:
            _inject_abort_tool_messages(graph, config, pending)

        # ③ 실행(또는 거절 후 재플래닝) 스트리밍
        result_msg = await cl.Message(content="").send()
        try:
            step_label = f"⚙️ 도구 실행 중... (단계 {iteration})" if is_approved else "🔄 거절 후 재계획 중..."
            async with cl.Step(name=step_label) as exec_step:
                if is_approved:
                    exec_step.output = "\n".join(
                        f"• {tc['name']}({json.dumps(tc['args'], ensure_ascii=False)})"
                        for tc in pending
                    )
                plan_info, fallback = await _stream_graph(
                    graph, None, config, result_msg, step_ctx=exec_step, planner_label="planner"
                )

                if not is_approved and not plan_info.get("has_pending"):
                    exec_step.name = "✅ 재계획 완료"

            await result_msg.update()
            if fallback:
                await _update_msg(result_msg, fallback)

        except Exception as e:
            print(f"[Error] iteration={iteration} 실행 오류: {type(e).__name__}: {e}")
            await _update_msg(result_msg, f"❌ 오류: {type(e).__name__}: {e}")
            break


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
