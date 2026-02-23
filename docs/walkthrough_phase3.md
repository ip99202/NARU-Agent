# Phase 3: LangGraph 오케스트레이터 구현 완료

## 구현 결과

### ✅ 최종 동작 확인

**테스트 쿼리:** "하나카드 기관코드 알려줘"

```
[User] 하나카드 기관코드 알려줘
[Planner] Tool 계획:
• search_institution_code({"instNm": "하나카드", "size": 1})

[Approval] 최종 결정: approved
[Executor] tool_messages: ['call_WSGp8fiFlX9OGOrANiquJPU8']
  → NARU API /api/bizcomm/inst_cd 실제 호출 성공
[Planner2] 최종 답변: 하나카드의 기관코드는 HNCD입니다.
```

---

## 해결된 이슈들

| 이슈 | 원인 | 수정 |
|---|---|---|
| Python 3.14 + Chainlit 충돌 | anyio 이벤트 루프 비호환 | Python 3.11 `.venv311` venv 재구성 |
| `Message.update(content=...)` 오류 | Chainlit 2.x API 변경 | `msg.content = ...; await msg.update()` |
| `BadRequestError 400` | `interrupt()` 내부 + `interrupt_before` 이중 충돌로 executor 생략, ToolMessage 없이 LLM 재호출 | `interrupt_before=["executor"]` 단일 방식으로 재설계 |
| `UnboundLocalError: resume_is_map` | `Command(resume=None)` LangGraph 내부 버그 | `graph.astream(None, config=config)` 사용 |
| 승인 클릭 시 거절됨 처리 | Chainlit `AskActionMessage` res에 `value` 키 없음 (`name` 필드만 존재) | `res.get("name") == "approve"` 3가지 방식 체크로 강화 |
| 거절/새 메시지 시 state 오염 | `AIMessage(tool_calls)` 뒤에 `ToolMessage` 없이 새 메시지 추가 | [_inject_abort_tool_messages()](file:///Users/a10886/Documents/github/NARU-Agent/app.py#47-62) — `graph.update_state()`로 synthetic ToolMessage 주입 |

---

## 최종 아키텍처

```
Start → planner → [conditional_edge]
                    ├─ pending_tool_calls → executor ← interrupt_before 여기서 멈춤
                    └─ no tool calls     → END
         executor → planner (루프백)
```

**Human-in-the-loop 흐름:**
1. Planner가 Tool 호출 결정 → interrupt_before executor 에서 멈춤
2. 앱이 `graph.get_state()`로 `pending_tool_calls` 읽어 승인 UI 표시
3. 승인: `graph.astream(None, config)` → executor 정상 실행 → ToolMessages → planner 답변
4. 거절: `graph.update_state()`로 synthetic ToolMessages 주입 → `astream(None)` → planner 대안 답변
5. 새 메시지 도착 시: pending interrupt 자동 감지 및 정상화 후 처리

---

## 생성된 파일

| 파일 | 역할 |
|---|---|
| [graph/state.py](file:///Users/a10886/Documents/github/NARU-Agent/graph/state.py) | [AgentState](file:///Users/a10886/Documents/github/NARU-Agent/graph/state.py#10-25) TypedDict |
| [graph/nodes.py](file:///Users/a10886/Documents/github/NARU-Agent/graph/nodes.py) | [planner_node](file:///Users/a10886/Documents/github/NARU-Agent/graph/nodes.py#19-52), [executor_node](file:///Users/a10886/Documents/github/NARU-Agent/graph/nodes.py#55-114) |
| [graph/graph.py](file:///Users/a10886/Documents/github/NARU-Agent/graph/graph.py) | LangGraph 빌드 (`interrupt_before=["executor"]`) |
| [app.py](file:///Users/a10886/Documents/github/NARU-Agent/app.py) | Chainlit UI + Human-in-the-loop 처리 |

## 실행 방법

```bash
source .venv311/bin/activate
chainlit run app.py --port 8000
```
