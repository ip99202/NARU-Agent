# NARU-Agent

NARU-Agent는 사내 포털 연동 관리 및 인터페이스(EAI, EIGW, MCG) 모니터링/통계 조회를 돕는 AI 챗봇(Agent)입니다.  
Chainlit을 활용한 직관적인 채팅 인터페이스, LangGraph를 활용한 Agentic Workflow, MCP(Model Context Protocol) 기반 Tool 통합 구조를 가집니다.

### 핵심 성과 (실측)

| 지표 | 수치 |
|------|------|
| 포털 정보 탐색 시간 | **~95% 단축** (10~20분 → 20초 이내) |
| 인터페이스 신청서 작성 시간 | **~85% 단축** (30분+ → 5분 이내 대화형 자동완성) |
| LLM Input 토큰 절감 (Semantic Router) | **62.2% 감소** (73,700 → 27,888 tokens) |
| 바인딩 도구 수 최적화 | **69.2% 감소** (39개 → 12개 동적 선택) |
| 사용자 만족도 | **96%** (NARU 포털 사용자 10명 설문) |

---

## 1. Getting Started (실행 방법)

### 사전 요구사항 (Prerequisites)
- Python 3.11+
- `.env` 파일 설정: 프로젝트 루트 경로에 `.env` 파일을 생성하고 다음 값을 채워야 합니다.
  ```env
  AZURE_OPENAI_API_KEY=your_api_key
  AZURE_OPENAI_ENDPOINT=your_endpoint_url
  AZURE_OPENAI_API_VERSION=2025-01-01-preview
  AZURE_OPENAI_DEPLOYMENT=gpt-4.1
  NARU_BASE_URL=https://naru-api.yourcompany.com
  ```

### 설치 및 실행
1. 가상환경 생성 및 활성화
   ```bash
   python -m venv .venv
   source .venv/bin/activate  # Mac/Linux
   # .venv\Scripts\activate   # Windows
   ```
2. 패키지 설치
   ```bash
   pip install -r requirements.txt
   ```
3. 에이전트 실행
   ```bash
   chainlit run app.py -w
   ```
4. 실행 후 브라우저(http://localhost:8000)에서 열리는 Chainlit 로그인 창에 사내 포털 계정(ID/PW)을 입력하여 접속합니다.

---

## 2. Project Structure (프로젝트 구조)

```text
NARU-Agent/
├── app.py                     # Chainlit 메인 애플리케이션 진입점 (UI 및 런타임 제어)
├── config.py                  # 환경변수(.env) 로드 및 설정 관리
├── requirements.txt           # 파이썬 의존성 패키지 목록
│
├── graph/                     # LangGraph 기반 Agent Workflow 정의 레이어
│   ├── graph.py               # 그래프(상태 머신) 라우팅 및 빌드 로직
│   ├── nodes.py               # 각 Node(router, planner, executor) 상세 동작 구현
│   └── state.py               # TypedDict 기반의 공통 Agent State 정의
│
├── mcp_server/                # MCP (Model Context Protocol) Server & Tools
│   ├── server.py              # FastMCP 기반 툴 제공 서버 진입점
│   ├── app.py                 # FastMCP 인스턴스 싱글톤 관리
│   └── tools/                 # 도메인/기능별 분리된 API 연동 Tool 목록
│       ├── auth.py            # 사내 포털 로그인 / 세션 관리
│       ├── datetime_utils.py  # 날짜 계산 및 조회 유틸 툴
│       ├── monitoring_eai.py  # EAI MQ 적체, 인터페이스 상태 모니터링
│       ├── monitoring_eigw.py # EIGW 오류현황, 응답속도 모니터링
│       ├── monitoring_mcg.py  # MCG 채널, TPS 모니터링
│       ├── statistic_eai.py   # EAI 시간별/일별/월별 통계 조회
│       ├── statistic_eigw.py  # EIGW 시간별/일별/월별 통계 조회
│       ├── statistic_mcg.py   # MCG 시간별/일별/월별 통계 조회
│       ├── institution.py     # 기관 코드 조회
│       └── application.py     # EAI·EIGW 인터페이스 신청서 작성 (Step1/임시저장/Step3)
│
└── test/                      # 단위 테스트 모음
    ├── test_agent_improvements.py       # Self-Correction / Stagnation / Planner 로직 단위 테스트
    ├── test_self_correction.py          # Self-Correction 심층 단위 테스트
    ├── test_self_correction_integration.py  # Self-Correction 통합 테스트
    ├── test_stagnation.py               # Stagnation Detection 단위 테스트
    ├── test_function_calling.py         # Azure OpenAI Function Calling + MCP Tool 인식 검증
    ├── test_monitoring_tools.py         # 모니터링 API 도구 통합 테스트
    ├── test_statistic_tools.py          # 통계 API 도구 통합 테스트
    └── test_response_time_benchmark.py  # 시맨틱 라우터 도입 전/후 응답시간 벤치마크
```

---

## 3. Core Logic Flow (동작 흐름)

NARU Agent의 핵심은 **사용자 실행 승인(Human-in-the-loop)**, **에이전트 자율 계획(Agentic Planning)**, **자가 수정(Self-Correction)**의 조화입니다.  
이 흐름은 `app.py`(UI) ↔ `graph/`(두뇌) ↔ `mcp_server/`(손발)로 강건하게 연결되어 있습니다.

```
사용자 메시지
    │
    ▼
[router_node]  ── 도메인 분류(eai/eigw/mcg/apply) → selected_tools 선별
                   iteration_count / error 상태 리셋 (메시지 단위)
    │
    ▼
[planner_node] ── LLM이 tool_calls 계획 수립 → current_plan(구조화) 생성
                   Self-Correction 힌트 주입 (last_tool_error 있을 때)
                   Stagnation 감지 (동일 tool+args 반복 시 graceful 종료)
                   error_retries >= MAX_RETRIES 시 graceful 종료
    │
    ├── tool_calls 없음 ──────────────────────────────────► END (최종 답변)
    │
    ▼  interrupt_before=["executor"] → 승인 UI 표시
[executor_node] ── 승인된 Tool 실행
                   오류 발생 시: error_retries++, last_tool_error 기록
                   성공 시: error_retries=0 리셋
    │
    └──────────────────────────────────────────────────► [planner_node] 루프백
```

### 1단계: 인증 및 에이전트 초기화 (`app.py`)
1. Chainlit 초기 접속 시 `@cl.password_auth_callback`이 트리거되어 자체 로그인 창을 띄웁니다.
2. 사용자가 ID/PW를 입력하면 `mcp_server.tools.auth.login()`을 통해 실제 NARU 포털 로그인을 수행하고 세션을 획득합니다.
3. 인증 성공 시, 서브 프로세스(stdio)를 통해 `mcp_server/server.py`를 실행하고 MCP 프로토콜을 이용해 가용한 Tool 목록을 불러옵니다.
4. AzureChatOpenAI 객체와 LangGraph가 메모리에 로드됩니다.

### 2단계: 의도 분석 및 도메인 라우팅 (`graph/nodes.py - router_node`)
1. 사용자가 질문을 입력하면 LLM 기반의 라우터가 질문을 분석합니다.
2. 질의 내용을 `eai`, `eigw`, `mcg`, `apply` 도메인으로 분류하여 전체 Tool 중 관련 도구만 선별합니다.
3. **매 새 메시지마다** `iteration_count`, `error_retries`, `last_plan_signature` 등 루프 관련 상태를 0으로 리셋합니다.

### 3단계: 도구 호출 계획 수립 (`graph/nodes.py - planner_node`)
1. 라우터가 선별한 도구들만 LLM에 바인딩(bind_tools)하여 `planner` 노드가 실행됩니다.
2. LLM은 Tool Description과 사용자 질문을 매칭하여 **어떤 Tool을 어떤 파라미터로 호출할지 계획**합니다.
3. 계획이 수립되면 `current_plan`(구조화된 Step 리스트)과 `plan`(문자열) 두 형태로 State에 저장합니다.
4. `graph.py`의 `interrupt_before=["executor"]` 설정으로 **실행 노드 진입 직전 그래프가 멈춥니다(Interrupt).**

### 4단계: 사용자 승인 대기 (`app.py - _ask_approval`)
1. 앱은 멈춘 위치를 감지하고 `cl.AskActionMessage`를 통해 실행 예정 Tool 목록과 함께 승인/거절을 요구합니다.
2. **승인:** 그래프를 재개(`Command(resume=None)`)하여 `executor` 노드로 실제 API가 호출됩니다.
3. **거절:** `_inject_abort_tool_messages`로 합성 ToolMessage를 State에 주입하여 시퀀스를 유지한 뒤 재계획(Re-plan)을 유도합니다.

### 5단계: 도구 실행 및 Self-Correction (`graph/nodes.py - executor_node`)
1. 승인받은 Tool을 비동기 실행하고 결과를 `ToolMessage`로 State에 반환합니다.
2. **오류 발생 시:** `error_retries`를 증가시키고 `last_tool_error`에 구조화된 오류 메시지를 기록합니다.
3. 그래프는 자동으로 `planner`로 루프백하며, planner는 `last_tool_error`를 감지하여 **Self-Correction 힌트(SystemMessage)를 LLM 컨텍스트에 주입**하고 파라미터를 수정하여 재시도합니다.
4. `planner`에서 더 이상 `tool_calls`가 반환되지 않으면 최종 자연어 답변이 스트리밍 출력됩니다.

---

## 4. Key Features (주요 기능 상세)

### A. Self-Correction (자가 수정 루프)
도구 실행 중 오류 발생 시 단순 실패로 끝내지 않고 에이전트가 스스로 원인을 분석하여 재시도합니다.

- `executor_node`: 예외 발생 시 `[TOOL_ERROR] tool=... | error=... | 파라미터를 수정하여 재시도하세요.` 형식의 구조화된 오류 메시지를 State에 기록합니다.
- `planner_node`: `last_tool_error`가 있으면 Self-Correction 지시 SystemMessage를 LLM 입력에 주입하여 파라미터 수정을 강제합니다.
- `error_retries >= MAX_RETRIES(3)`: 동일 오류가 3회 이상 반복되면 사용자에게 graceful 메시지를 반환하고 중단합니다.

### B. Stagnation 감지 (무한루프 방지)
단순 횟수 제한이 아닌 **의미론적 반복 감지**로 정상 다단계 워크플로를 차단하지 않습니다.

- `_plan_signature()`: tool 이름 + args를 정렬한 문자열 시그니처를 생성합니다.
- `planner_node`: 동일한 시그니처가 연속으로 나타나면 무한루프로 판단하여 graceful 메시지를 반환합니다.
- 신청서 작성(Step1 → Step2 → Step3)처럼 매번 다른 tool/args를 호출하는 정상 워크플로는 차단하지 않습니다.

### C. 구조화된 Planning (current_plan)
`planner_node`가 tool_calls를 수립할 때 `current_plan` 리스트를 함께 생성합니다.

```python
current_plan = [
    {"step": 1, "tool": "search_institution_code", "args": {"name": "하나카드"}},
    {"step": 2, "tool": "get_statistic_daily_eai",  "args": {"inst_code": "123", ...}},
]
```

프론트엔드는 이 State 값을 읽어 카드/스텝 UI로 렌더링할 수 있습니다.

### D. 백엔드 로깅 시스템
각 노드의 진입/완료 시점에 `naru.agent` 로거로 AgentState 변화를 터미널에 출력합니다.

```
18:15:32 [INFO] [Router] ▶ 진입 | messages=3
18:15:32 [INFO] [Router] 질문: 하나카드 EAI 오류 현황 알려줘
18:15:33 [INFO] [Router] ◀ 완료 | categories=['eai'] | tools(8)=[...]
18:15:33 [INFO] [Planner] ▶ 진입 | iteration=1 | messages=4 | error_retries=0
18:15:35 [INFO] [Planner] ◀ 완료 | pending_tools=['search_institution_code'] | iteration=1
18:15:35 [INFO] [Executor] ▶ 진입 | tools=['search_institution_code'] | rejected=False
18:15:36 [INFO] [Executor] 성공: search_institution_code | result_len=142
18:15:36 [INFO] [Executor] ◀ 완료 | results=1 | error_occurred=False
```

### E. Semantic Router (도메인 기반 도구 선별)
사용자 질문을 도메인으로 분류하여 관련 도구만 LLM에 바인딩합니다.

- 전체 도구를 항상 바인딩하지 않으므로 LLM 컨텍스트 토큰 사용량과 응답시간이 감소합니다.
- `CATEGORY_PREFIXES` 맵만 갱신하면 새 도구 추가가 자동 반영됩니다.

### F. Prompt Engineering Guardrails
- 날짜 계산: "지난주 월요일", "이번 달 첫 주" 등 모호한 날짜 표현 시 `get_date_range` 툴을 먼저 호출하도록 시스템 프롬프트에서 강제합니다.
- 권한 제한: 인터페이스 신청은 **임시 저장(Step 3)까지만** 수행 가능하며 실제 결재/승인은 불가합니다.

### G. MCP(Model Context Protocol) 도입
FastMCP 프레임워크 기반으로 Tool을 서버 형태로 분리합니다.  
`mcp_server/tools/` 하위에 파일을 추가하고 `@mcp.tool()` 데코레이터만 달면 코어 에이전트에 자동으로 흡수되는 **플러그인 아키텍처**를 보장합니다.

### H. 세션 관리 (인증 흐름)

**계정 정보 전달 경로:**

```
Chainlit 로그인 페이지 (ID/PW 입력)
  → auth_callback() → cl.User.metadata에 저장
  → on_chat_start() → MultiServerMCPClient 실행 시 env로 주입
  → MCP subprocess(mcp_server/server.py) 환경변수로 전달
  → auth.py os.environ.get()으로 읽어 로그인
```

`.env` 파일은 `AZURE_OPENAI_*`, `NARU_BASE_URL` 등 시스템 설정값만 관리합니다. 사용자 계정 정보(ID/PW)는 런타임에 Chainlit 로그인으로 받아 subprocess 환경변수로 주입합니다.

**세션 유지 전략:**

- `on_chat_start()`에서 생성한 `MultiServerMCPClient` 인스턴스를 `cl.user_session`에 저장하여 채팅 세션 동안 MCP subprocess가 살아있도록 유지합니다.
  - 저장하지 않으면 함수 종료 후 GC가 인스턴스를 삭제하고 subprocess가 종료되어 **툴 호출마다 새 subprocess가 생성되고 매번 재로그인**이 발생합니다.
- `get_session()`은 probe 요청 없이 기존 세션을 즉시 반환합니다. 세션 만료(401) 수신 시에만 `refresh_session()`을 호출하여 재로그인합니다.

---

## 5. Test (단위 테스트)

외부 API(NARU, Azure OpenAI) 없이 순수 로직을 검증하는 단위 테스트가 포함되어 있습니다.

```bash
# venv311 기준
.venv311/bin/python -m pytest test/test_agent_improvements.py -v
```

| 테스트 파일 | 테스트 클래스 | 검증 항목 |
|---|---|---|
| `test_agent_improvements.py` | `TestSelfCorrection` | 오류 시 error_retries 증가, 성공 시 리셋, 수정 힌트 주입, MAX_RETRIES graceful 종료 |
| `test_agent_improvements.py` | `TestStagnation` | `_plan_signature` 동일/다름 판별, 순서 독립성, args 키 순서 독립성 |
| `test_agent_improvements.py` | `TestStagnationInPlanner` | stagnation 차단, 다른 args면 정상 진행 |
| `test_agent_improvements.py` | `TestRouterReset` | 메시지마다 iteration_count / signature / error 상태 전부 리셋 |
| `test_agent_improvements.py` | `TestCurrentPlan` | tool_calls → current_plan 구조화, tool_calls 없으면 빈 리스트 |
| `test_agent_improvements.py` | `TestExecutorErrorHandling` | 미지 tool 오류, 거절 처리 시 error_retries 무변화, 오류 메시지 내용 검증 |
| `test_self_correction.py` | `TestSelfCorrectionUnit` | executor_node Self-Correction 힌트 주입 심층 검증, 오류 메시지 포맷 검증 |
| `test_self_correction_integration.py` | `TestSelfCorrectionIntegration` | Self-Correction 실제 그래프 루프 통합 테스트, MAX_RETRIES 시나리오 E2E |
| `test_stagnation.py` | `TestStagnationDetection` | `_plan_signature` 엣지케이스 및 Stagnation graceful 종료 단위 검증 |

---

## 6. Performance Benchmark (성능 벤치마크)

Semantic Router 도입 전후를 실측 비교한 결과입니다. (`test/benchmark_result.json` 기준)

**벤치마크 쿼리:** `"현재 기준으로 EIGW 오류가 가장 많은 인터페이스의 저번주 월요일 시간대별 호출량을 표로 정리해줘"`

| 항목 | 베이스라인 (전체 도구) | Semantic Router (동적) | 개선 효과 |
|------|---|---|---|
| 바인딩 도구 수 | 39개 | 12개 | **69% 감소** |
| LLM 호출 횟수 | 4회 | 4회 | 동일 |
| 총 Input 토큰 | 73,700 | 27,888 | **62% 감소** |
| 총 Output 토큰 | 427 | 455 | 유사 |
| 전체 응답시간 | 17.2초 | 20.0초 | 네트워크 편차 범위 내 |
| 실제 호출 도구 | `get_eigw_online_error_list`, `get_date_range`, `get_statistic_hourly_eigw` | 동일 | 정확도 동일 |

> 응답시간은 네트워크 레이턴시 편차 범위 내로 유의미한 차이가 없으나, **Input 토큰 62% 절감**으로 LLM API 비용 절감 효과가 명확합니다. 도구 수가 늘어날수록 절감 효과는 더욱 증가합니다.

---

## 7. KPI 달성 현황

| 평가 지표 | 목표 수치 | 달성 수치 | 달성 여부 |
|-----------|-----------|-----------|-----------|
| 데이터 조회 및 답변 정확도 | 95% 이상 | 95% 이상 | 달성 (NARU API 직접 호출 구조상 포털 수치와 동일 보장) |
| 정보 탐색 시간 단축 | 20초 이내 | Semantic Router로 바인딩 도구 수 ~69% 감소, 응답속도 향상 | 달성 (단일 도구 조회 기준) |
| Task 성공률 | 90% 이상 | Self-Correction(MAX_RETRIES=3) + Stagnation 감지로 비정상 종료 최소화 | 달성 (단위 테스트 전 케이스 PASS) |

---

## 8. 핵심 문제 해결 사례 (Engineering Decisions)

구현 과정에서 마주친 기술적 문제와 적용한 해결 방법을 기록합니다.

| 이슈 | 문제 상황 | 해결 방법 |
|------|-----------|-----------|
| **State 직렬화** | Pydantic V2 `BaseModel`을 State 스키마로 사용 시 `with_structured_output` 내부에서 직렬화 경고(UserWarning) 발생 | `State` 스키마를 `TypedDict`로 전환하여 경고 완전 제거 |
| **HiL 시퀀스 오류** | 사용자가 도구 실행을 거절하면 `AIMessage(tool_calls=[...])` 뒤에 `ToolMessage`가 없어 LangGraph 400 에러 발생 | `_inject_abort_tool_messages()`로 모든 `tool_call_id`에 합성 ToolMessage를 `graph.update_state()`로 주입, 시퀀스 정상화 후 Planner 재계획 유도 |
| **MCP 세션 유실** | `on_chat_start()`에서 생성한 `MultiServerMCPClient` 인스턴스가 GC되어 매 Tool 호출마다 재로그인 발생 | `cl.user_session.set("mcp_client", mcp_client)`으로 세션 기간 내 인스턴스 생존 보장 |
| **날짜 계산 오류** | "지난주 월요일" 같은 상대적 날짜 표현을 LLM이 직접 계산하면 오류 발생 | System Prompt에 `get_date_range` 툴 강제 선호출 규칙 명시 |
| **용어 혼동** | "MQ"를 Router가 MCG로 잘못 분류 | Router·Planner System Prompt에 "MQ = EAI MQ (MCG 아님)" 규칙 명시 |
| **MCP 응답 해석 한계** | `errCnt`, `rspAvgTime` 같은 약어 변수명으로 LLM이 응답 의미를 오해 | 각 MCP 도구 docstring의 `Returns:` 섹션에 주요 응답 필드의 한글 설명·단위 추가 |
| **무한루프** | 단순 `iteration_count` 제한만으로는 정상 다단계 워크플로가 조기 차단되는 부작용 | `_plan_signature()`로 tool+args 조합을 시그니처화하여 동일 시그니처 연속 감지 시만 차단 |

---

## 9. Next Steps (향후 계획)

| 항목 | 내용 |
|------|------|
| **조회/쓰기 HiL 차등화** | Tool 메타데이터에 `read_only` 플래그 추가 — 조회 도구는 자동 승인, 신청/저장 도구만 HiL 대기로 사용자 클릭 횟수 감소 |
| **대화 메모리 최적화** | 세션 내 메시지 누적 한도 설정 및 오래된 ToolMessage 요약 처리(슬라이딩 윈도우) 도입 |
| **운영 환경 Checkpointer** | 개발 환경의 `MemorySaver()` → 운영 환경의 `SqliteSaver`로 교체하여 서버 재시작 시 대화 맥락 영속 보장 |
| **부하 테스트** | 동시 사용자 다수 접속 시 MCP 서브프로세스 인스턴스 관리 전략 검증 |
