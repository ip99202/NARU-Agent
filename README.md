# NARU-Agent

NARU-Agent는 사내 포털 연동 관리 및 인터페이스(EAI, EIGW, MCG) 모니터링/통계 조회를 돕는 AI 챗봇(Agent)입니다. 
Chainlit을 활용한 직관적인 채팅 인터페이스와 LangGraph를 활용한 Agentic Workflow, 그리고 MCP(Model Context Protocol) 기반의 Tool 통합 구조를 가집니다.

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
│   ├── nodes.py               # 각 Node(planner, executor) 상세 동작 구현
│   └── state.py               # TypedDict 기반의 공통 Agent State 정의
│
└── mcp_server/                # MCP (Model Context Protocol) Server & Tools
    ├── server.py              # FastMCP 기반 툴 제공 서버 진입점
    ├── app.py                 # FastMCP 인스턴스 싱글톤 관리
    └── tools/                 # 도메인/기능별 분리된 API 연동 Tool 목록
        ├── auth.py            # 사내 포털 로그인 / 세션 관리
        ├── datetime_utils.py  # 날짜 계산 및 조회 유틸 툴
        ├── monitoring_*.py    # 운영 환경 (EAI/EIGW/MCG) 모니터링 API 도구
        ├── statistic_*.py     # 운영 환경 (EAI/EIGW/MCG) 통계 조회 API 도구
        └── application.py     # 인터페이스(API) 사용 신청 프로세스 처리 툴
```

---

## 3. Core Logic Flow (동작 흐름)

NARU Agent의 가장 큰 특징은 **사용자 실행 승인 (Human-in-the-loop)**과 **에이전트 자율 계획 (Agentic Planning)**의 조화입니다.
이 흐름은 `app.py` (사용자 UI) ↔ `graph/...` (두뇌) ↔ `mcp_server/...` (손발)로 강건하게 연결되어 있습니다.

### 1단계: 인증 및 에이전트 초기화 (`app.py`)
1. Chainlit 초기 접속 시 `.chainlit/config.toml` 등의 설정에 따라 `@cl.password_auth_callback`이 트리거되어 자체 로그인 창을 띄웁니다.
2. 사용자가 ID/PW를 입력하면 `mcp_server.tools.auth.login()`을 통해 실제 NARU 포털 로그인을 수행하고 세션을 획득합니다.
3. 인증 성공 시, 서브 프로세스(stdio)를 통해 `mcp_server/server.py`를 실행하고 MCP 프로토콜을 이용해 가용한 Tool 목록을 불러옵니다. `mcp_client.get_tools()`
4. 그 후 AzureChatOpenAI 객체에 바인딩되고 LangGraph가 메모리에 로드됩니다.

### 2단계: 요청 분석 및 계획 수립 (`graph/nodes.py - planner`)
1. 사용자가 질문을 입력하면, 메시지 배열과 함께 LangGraph의 최초 진입 노드인 `planner`가 실행됩니다.
2. LLM(Azure OpenAI)은 보유하고 있는 Tool들의 Description과 사용자의 질문을 매칭하여 **어떤 Tool을 어떤 파라미터로 호출할지 계획**(Tool Calls)합니다.
3. Tool Calls가 존재한다면 `pending_tool_calls` State에 보관하고, 그래프의 라우터(`route_after_planner`)는 `need_execution` 엣지를 반환하여 `executor` 노드로 가록 지시합니다.
4. 이때 `graph.py`에 적용된 `interrupt_before=["executor"]` 설정 때문에, **실제 실행 노드에 진입하기 직전 그래프가 멈춥니다(Interrupt).**

### 3단계: 사용자 승인 대기 (`app.py - _ask_approval`)
1. 앱은 멈춘 위치를 감지하고, `cl.AskActionMessage`를 띄워 사용자에게 *어떤 Tool을 실행하려는지* 목록을 보여주며 승인(Approve) 혹은 거절(Reject)을 요구합니다.
2. **승인할 경우:** 
   - 중단됐던 그래프를 `None` 입력으로 재개(`Command(resume=None)`)합니다. 
   - 그래프가 `executor` 노드로 넘어가면서 `mcp_server`를 통해 실제 API가 호출됩니다.
3. **거절할 경우:** 
   - `_inject_abort_tool_messages` 함수를 통해 `ToolMessage(content="사용자 거절")` 형태의 가짜 메시지(Synthetic Message)를 State에 강제로 밀어 넣습니다.
   - LLM에서 에러가 나지 않도록 시퀀스를 맞춘 뒤 `resume`을 수행해 재계획(Re-plan)을 유도합니다.

### 4단계: 도구 실행 및 결과 도출 (`graph/nodes.py - executor`)
1. 승인받은 경우 `executor` 노드에서 대상 Tool 함수들(예: `get_eigw_online_error_graph`)을 `ainvoke`로 비동기 실행합니다.
2. JSON/Dictionary 형식으로 획득된 결과를 문자열로 일차 변환하거나 JSON 포맷 그대로 `ToolMessage`에 감싸서 State에 반환합니다.
3. 그래프는 자동으로 `planner` 로 노드를 순환(루프백)합니다.
4. `planner`는 실행된 결과를 컨텍스트로 읽고 **최종 자연어 답변을 구성**하거나 **추가 Tool 조회가 필요한지 2차 판단**을 내립니다.
5. `planner`에서 더 이상 `tool_calls`가 반환되지 않으면 (`final_answer`), Chainlit UI를 통해 최종 결론이 스트리밍 모드로 출력되며 한 사이클이 종료됩니다.

---

## 4. Module Implementation Details (주요 구현 사항 상세)

### A. 스트리밍과 메시징 안전성 보호
- `app.py` 에서는 LangGraph의 `stream_mode=["messages", "updates"]`를 이중으로 청취합니다.
- `metadata["langgraph_node"] == "planner"`에서 나온 `AIMessageChunk` 만 화면에 **글자 단위 스트리밍**(실시간 타자 치듯)을 허용합니다.
- 이 과정에서 Tool Call 쿼리를 요청하는 JSON 페이로드나 RAW 데이터 로그 등 사용자가 보기에 불필요한 값은 숨기고 순전히 **최종 결과만** 전달하도록 깔끔하게 제어됩니다. (Chainlit Step 객체로 폴딩UI 구현)

### B. Prompt Engineering Guardrails (시스템 프롬프트 예방)
- 날짜를 "오늘", "지난주 월요일", "첫 주" 등으로 모호하게 질의할 때 LLM이 임의로 요일을 착각하거나 환각(Hallucination) 계산하는 것을 막고자 `datetime_utils.py` 툴을 구축했습니다.
- 시스템 프롬프트에 **"특정 요일이나 시점이 포함된 문의 시 항상 \`get_date_range\` 툴을 먼저 써라"** 라고 명시하여 날짜 계산에 있어서 100% 명확한 Rule-based 검증을 거치도록 통제합니다.

### C. 인터페이스 프로세스 보호 (Safety)
- 사용자가 운영계 인터페이스를 마음대로 생성/결재처리하는 치명적인 상황을 방지하고자, 에이전트의 권한을 **"임시 저장 기능까지만"(Step 3)**으로 시스템 프롬프트 상위 단에서 강력하게 차단하고 있습니다.

### D. MCP(Model Context Protocol) 도입
- Tool의 확장성을 위해 FastMCP 프레임워크를 기반으로 Tool 모음을 분리했습니다.
- `auth_callback`을 통해 포털에서 인가된 사용자 Session 객체가 생성되면, 그 Session 상태를 유지하며 EAI / EIGW / MCG 모니터링 API에 HTTP Proxy 형태로 접근합니다 (예: `monitoring_eigw.py` - `get_session()` 호출 등).
- 이는 향후 추가 사내망/레거시 시스템이 도입되더라도 `mcp_server/tools` 내에 파일 하나만 추가 정의하고 `@mcp.tool()` 데코레이터만 달면 코어 에이전트에 자동으로 흡수되는 **극도의 플러그인(Plug-in) 아키텍처**를 보장합니다.
