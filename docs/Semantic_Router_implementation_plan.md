# 시맨틱 라우터(Semantic Router) 구현 계획

이 계획의 목표는 LangGraph 아키텍처에 **시맨틱 라우터(Semantic Router)** 노드를 추가하는 것입니다. 현재 모든 MCP 도구(EAI, EIGW, MCG, apply, Date 등)가 한 번에 `planner` 노드에 바인딩되어 있습니다. 도구의 수가 늘어날수록 LLM 컨텍스트 공간(Token)을 많이 차지하게 되어 응답 속도가 느려지고 비용이 증가합니다.

이 문제를 해결하기 위해 `planner` 실행 전에 가벼운 필터링 단계("router")를 추가할 것입니다.

---

## 제안하는 변경 사항

### 1. `graph/state.py`

라우터가 선택한 도구들의 이름을 저장하도록 `AgentState`를 수정합니다.

#### [MODIFY] `state.py`
- `AgentState`에 `selected_tools: list[str]` 필드 추가
  - 현재 턴에서 유효하다고 판단된 도구들의 이름 목록을 보관합니다.

> **상태 초기화 방식 결정**
>
> `selected_tools`의 초기화 방식으로 두 가지 옵션을 검토했습니다:
>
> | 옵션 | 방식 | 장점 | 단점 |
> |---|---|---|---|
> | **A. router_node에서 리셋** | 매 `router_node` 실행 시 `selected_tools`를 덮어씀 | 구현이 단순 | 없음 (채택) |
> | **B. turn_id 기반 추적** | 상태에 `turn_id`를 두고 라우터가 새 ID 부여, planner가 다른 turn_id면 무시 | 정교한 Loopback 구분 가능 | 코드 복잡도 증가, 현재 요구사항 대비 과도한 설계 |
>
> → **옵션 A (router_node에서 덮어쓰기)** 를 채택합니다. `executor → planner` 루프백 구간에서는 `router_node`를 통과하지 않으므로 `selected_tools`가 변경되지 않아 자연스럽게 보존됩니다.

---

### 2. `graph/nodes.py`

새로운 `router_node`를 만들고 기존 `planner_node` 로직을 수정합니다.

#### [MODIFY] `nodes.py`

**[NEW] `router_node(state, llm, tools_map)`**:
- 가장 최근의 `HumanMessage`(사용자 질문)를 기반으로 경량 LLM 호출(`with_structured_output`)을 수행합니다.
- **분류 카테고리 (복수 선택 가능)**:

  | 카테고리 | 포함 도구 예시 |
  |---|---|
  | `eai` | `get_eai_*` 시리즈 |
  | `eigw` | `get_eigw_*` 시리즈 |
  | `mcg` | `get_mcg_*` 시리즈 |
  | `apply` | `save_eigw_request_*`, `search_external_*` 시리즈 |
  | `all` | 전체 도구 (Fallback / 불명확한 질의) |

- **멀티 도메인 지원**: 반환 타입을 `list[str]` (카테고리 목록)으로 정의하여 복수 도메인 선택 가능.
  - 예: `["eai", "eigw"]` → 두 도메인 도구를 합산하여 `selected_tools`에 저장.
- **Fallback**: 분류가 불명확하거나 복합적인 경우 `["all"]`을 반환하여 전체 도구를 포함.
- **필수 공통 도구**: `get_date_range` 등 공통 도구는 카테고리와 무관하게 항상 포함.
- 상태값에 `{"selected_tools": [...]}` 업데이트 (이전 턴 값을 덮어씀으로써 자동 초기화).
- 디버깅을 위해 선택된 카테고리와 도구 목록을 터미널에 로깅:
  ```python
  print(f"[Router] categories={categories}, tools={selected_tools}")
  ```

**[MODIFY] `planner_node(state, llm, tools_map)`**:
- 기존 `llm_with_tools: Any` 인자를 `llm: Any`, `tools_map: dict`로 변경합니다.
- `state.get("selected_tools")`에서 도구 목록을 읽어옵니다.
- 동적으로 도구를 바인딩합니다:
  ```python
  bound_llm = llm.bind_tools([tools_map[name] for name in selected_tools if name in tools_map])
  ```
- 이후 `bound_llm.ainvoke(state["messages"])`를 호출합니다.

---

### 3. `graph/graph.py`

라우터를 포함하도록 LangGraph 흐름을 변경합니다.

#### [MODIFY] `graph.py`

- `build_graph` 함수 시그니처를 `build_graph(llm, tools_map)` (순수 `llm`)으로 변경.
- 라우터 노드 등록:
  ```python
  builder.add_node("router", functools.partial(router_node, llm=llm, tools_map=tools_map))
  builder.add_node("planner", functools.partial(planner_node, llm=llm, tools_map=tools_map))
  ```
- 그래프 연결 흐름:

  ```
  START → router → planner → [conditional_edge]
                               ├─ "need_execution" → executor → planner (루프백, 재라우팅 없음)
                               └─ "final_answer"   → END
  ```

  > **핵심**: `executor → planner` 루프백 시 `router`를 거치지 않습니다.
  > `selected_tools`는 최초 라우팅 결과를 유지하여 기존 도구 호출 컨텍스트가 보존됩니다.

- 진입점: `builder.set_entry_point("router")`
- `executor → planner` 엣지는 기존대로 유지: `builder.add_edge("executor", "planner")`

---

### 4. `app.py`

Agent 초기화 및 호출 로직 변경

#### [MODIFY] `app.py`
- `on_chat_start` 함수 안에서 `llm.bind_tools(tools)`로 생성하는 `llm_with_tools` 변수를 제거합니다.
- `build_graph()` 호출 시 원본 `llm`과 `tools_map`을 전달하도록 변경합니다.

---

## 필요한 사용자 리뷰

> [!IMPORTANT]
> - 라우팅 방식: 정규식 대신 LLM `with_structured_output`을 활용한 구조적 반환(카테고리 목록)으로 분류합니다. 약간의 추가 LLM 호출이 발생하지만 정확도가 극대화됩니다.
> - **멀티 도메인**: 반환 타입이 `list[str]`이므로 `["eai", "eigw"]`처럼 복수 카테고리를 동시에 선택하여 도구를 합산합니다.
> - **Fallback**: 분류가 불가능하거나 전체 도메인에 걸친 질의는 `"all"` 카테고리로 처리하여 전체 도구를 바인딩합니다.
> - **상태 초기화**: `router_node`가 매 새 질의마다 `selected_tools`를 덮어쓰는 방식으로 초기화를 대신합니다. `executor → planner` 루프백 중에는 `router`를 통과하지 않으므로 별도 초기화 로직이 불필요합니다.

---

## 테스트 계획 (Verification Plan)

### 수동 테스트

`chainlit run app.py -hw`로 로컬 서버 실행 후 아래 케이스들을 순서대로 테스트합니다.

#### ✅ 기본 케이스

| # | 질문 | 기대 결과 |
|---|---|---|
| 1 | *"오늘 EIGW 에러난거 있어?"* | `router`가 `["eigw"]` 분류 → EIGW 도구 + 공통 도구만 바인딩 |
| 2 | *"EAI 연동량은 어때?"* | `router`가 `["eai"]` 분류 → EAI 전용 도구만 바인딩 |

#### ⚠️ 엣지 케이스

| # | 질문 | 기대 결과 |
|---|---|---|
| 3 | *"EAI랑 EIGW 에러 둘 다 알려줘"* | `router`가 `["eai", "eigw"]` 멀티 도메인 분류 → 두 도메인 도구 합산 바인딩 |
| 4 | *"오늘 시스템 상태 어때?"* (도메인 불명확) | `router`가 `["all"]` Fallback → 전체 도구 바인딩 |
| 5 | *"EAI 연동량 알려줘"* 후 *"EIGW도 같이"* (연속 질의) | 두 번째 질의에서 `selected_tools`가 새로 갱신되는지 확인 (이전 턴 오염 없음) |
| 6 | *"EAI 신청하고 싶어, IMAS 관련 기존 신청 참고하고싶어"* | `router`가 `["apply"]` 분류 → 신청 관련 도구만 바인딩 |
| 7 | 도구 실행 후 후속 도구 필요 시 (Loopback) | `executor → planner` 루프백 중 `selected_tools`가 변경되지 않고 유지되는지 터미널 로그로 확인 |

### 검증 지표
- 터미널 `[Router] categories=..., tools=...` 로그로 도구 선택 확인
- Loopback 케이스(케이스 7)에서 `router_node`가 재실행되지 않는지 확인
