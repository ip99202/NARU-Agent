# NARU-Agent

### 프로젝트 명

NARU-Agent: MCP 기반의 NARU 포털 대화형 에이전트 구축

### 배경 및 문제 정의

- 현재 상황 (As-Is):
    - 복잡한 메뉴 구조: NARU 포털은 메인메뉴 > 하위메뉴 > 상세 등으로 이어지는 깊은 계층 구조를 가짐.
    - 번거로운 조회 절차: 특정 데이터를 보려면 단순히 메뉴 클릭 한 번이 아니라, '대외기관 조회 → 목록 조회 → 상세 조회'와 같이 순서를 지켜야 하는 경우가 많음.
    - 수동 모니터링의 한계: 장애 감지나 특정 수치 확인을 위해 담당자가 수시로 접속하여 여러 화면을 확인해야 함.
- Pain Point:
    - 프로세스 복잡성: 정확한 정보를 모르면 원하는 데이터를 확인하기 힘듦.
    - 비효율적 시간 소모: 단순 조회 및 신청 업무를 위해 반복적인 탐색과 입력 과정 필요.
    - 인사이트 도출 어려움: 통계 데이터가 화면에 산재되어 있어, 통합적인 추이 분석이 어려움.
- 기회 요인:
    - LLM & MCP 활용: 에이전트가 복잡한 조회 순서(Workflow)를 학습하여, 사용자의 말 한마디에 필요한 선행 절차를 자동으로 수행 가능.
    - 업무 자동화: 단순 조회 및 신청서 작성을 대화형으로 전환하여 업무 효율 극대화.

### 목표 사용자 (Target User)

인터페이스 담당 개발자 : 연동 상태 확인 및 신규 신청 업무를 수행하는 실무자.

시스템 운영자 : 큐 적체량, 오류 건수 등 시스템 지표를 모니터링하는 담당자.

### 프로젝트 목표

- 정성적 목표
    - 목표 1: 복잡한 클릭과 순서 암기 없이 채팅만으로 NARU 기능 활용.
    - 목표 2: '선행 조회 -> 후행 조회'의 복잡한 로직을 에이전트가 추상화하여 제공.
    - 목표 3: 사내 레거시 시스템에 최신 AI 에이전트 기술(MCP)을 접목하여 기술 역량 확보.
- 정량적 목표 (KPI)

| **성과 지표** | **목표 수치** | **측정 방법** | **현재 수준** |
| --- | --- | --- | --- |
| 데이터 조회 및 답변 정확도 | 95% 이상 | 에이전트가 답변한 수치/정보와 실제 NARU 시스템 조회 결과값의 일치 여부 테스트. |  |
| 정보 탐색 시간 단축 | 20초 이내 탐색완료 | 특정 시나리오수행 시 에이전트 응답 시간 확인. |  |
| Task 성공률 | 90% 이상 | 복합 명령(예: "A기관 관련 EIGW 상세 내역 보여줘") 수행 시 중간 단계 오류 없이 최종 결과 도출 성공 비율. |  |

### 핵심 기능 정의

1. 지능형 순차 조회 및 모니터링 : 사용자가 "A기관 오류 건수 알려줘"라고 하면, 에이전트가 스스로 ①대외기관 목록 조회 → ②해당 기관 코드 식별 → ③오류 건수 상세 조회 API 호출 순서를 판단하여 실행.
2. 문맥 기반 신청서 작성 가이드 : 복잡한 신청 단계를 대화형으로 진행. 사용자가 빠뜨린 정보를 에이전트가 역으로 질문하여 보완.
3. 통계 분석 및 요약 : 단순 수치 나열이 아니라 통계 데이터를 분석하여 증감 추이와 수치를 요약 제공.

### 기대 효과

- 업무 효율화: 복잡한 절차(Depth)를 건너뛰고 결과만 즉시 확인하여 업무 속도 증대.
- 품질 향상: 신청서 작성 시 필수 선행 조건을 에이전트가 챙겨주므로 휴먼 에러 감소.
- 비용 절감: 시스템 로직을 완벽히 모르더라도 자연어로 업무 수행 가능.

### 범위 및 제약사항

- In Scope:
    - MCP Server 구축 (NARU 시스템과 통신).
    - LLM 에이전트 인터페이스 구현.
    - 순차적 워크플로우(Sequence Workflow) 구현: 조회/신청 시 필수적인 선행/후행 프로세스 로직 개발.
- Out of Scope:
    - 최종 승인/결재 행위 (조회 및 신청 요청 단계까지만 수행).
- 제약사항:
    - 단일 API 호출로 끝나지 않고, 앞 단계의 결과가 뒷 단계의 입력이 되는 로직이 다수 존재함. 이를 논리적으로 순서를 틀리지 않고 수행하도록 설계가 필요.

# Project NARU-Agent 기술 구현 전략

## 1. 핵심 변경 사항

- **Orchestration 강화:** 단순 호출이 아닌, **LangGraph**를 활용한 상태 관리(State Management)

## 2. 시스템 아키텍처 (Agentic Architecture)

이 프로젝트는 **"단순 챗봇"**이 아니라, **"생각하고 행동하는 에이전트"**입니다.

- **Frontend (UI):** **Chainlit** (LLM 채팅 UI 특화, LangGraph 공식 통합, Human-in-the-loop 내장 지원, async 네이티브)
- **Brain (Orchestrator):** **LangGraph (Python)**
    - **Planner Node:** 사용자 질문을 분석하여 실행 계획 수립 (예: "기관 조회 먼저 하고 -> 상세 조회 하자")
    - **Executor Node:** 실제 MCP Tool 호출 및 결과 수신
- **Body (Tools):** **MCP Server (NARU Wrapper)**
    - NARU 시스템의 API를 표준 MCP 프로토콜로 맵핑 (기관조회, 오류통계, 인터페이스상세 등)

## 3. 기술적 고도화 포인트 (Master Pjt 평가 방어 논리)

RAG가 빠진 빈자리를 다음의 **3가지 Advanced Agent Pattern**으로 채웁니다.

### ① 동적 계획 수립 (Dynamic Planning)

- **기존:** 개발자가 `if A then B`로 코딩해 둔 순서대로만 동작.
- **고도화:** 에이전트가 API 명세(Schema)만 보고 스스로 순서를 짭니다.
    - *상황:* 사용자가 "어제 A기관 오류가 평소랑 어떻게 달라?"라고 모호하게 질문.
    - *에이전트 판단:* "평소(평균) 데이터를 먼저 구해야겠군" → `get_monthly_avg()` 호출 → "어제 데이터를 구하자" → `get_daily_stats()` 호출 → "두 값을 비교 분석하자".

### ② Human-in-the-loop (인간 개입 프로세스)

- **상황:** 신청서 작성(Write)과 같은 민감한 작업.
- **동작:** 에이전트가 신청서 초안을 다 작성한 후, **"이대로 신청하시겠습니까?"**라고 멈춰서 사용자 승인(Yes/No)을 기다리는 상태(State) 관리 구현.

## 4. 핵심 시나리오 (Revised)

**시나리오 1: 지능형 트러블슈팅 (조회)**

> **User:** "오늘 하나카드 오류가 좀 튀는 거 같은데 확인해줘."
**Agent:** (생각: 하나카드 코드를 먼저 찾아야지 -> `HNK` 확인 -> 오늘 오류 조회 -> 10건 확인 -> 평소 2건임 -> 급증 판단)
**Agent:** "네, 현재 하나카드(HNK) 오류가 10건으로 평소 대비 5배 급증했습니다. 주로 TimeOut 유형입니다."
> 

**시나리오 2: 대화형 인터페이스 신청 (작성)**

> **User:** "EAI 신청 좀 도와줘."
**Agent:** (생각: 필수값인 ID, 송수신 시스템이 필요해 -> 사용자에게 물어보자) "송신/수신 시스템이 어디인가요?"
**User:** "스윙멤버십에서 IMAS로."
**Agent:** (생각: 데이터 수집 완료 -> 검증 -> 승인 요청) "신청서 초안을 만들었습니다. 전송할까요?"
> 

---

### Agent 페르소나 및 시스템 프롬프트 (Identity)

Agent의 정체성, 역할, 그리고 답변의 톤앤매너를 정의합니다. 실제 LLM의 System Prompt에 들어갈 핵심 내용입니다.

| **항목** | **정의 내용** |
| --- | --- |
| **Agent 이름** | NARU Agent |
| **주요 역할** | NARU 포털의 복잡한 메뉴를 대신 조작하여 실시간 모니터링 데이터를 분석하고, 인터페이스 신청 업무를 보조하는 가상 운영자 |
| **핵심 목표** | 1. Zero-UI: 사용자가 메뉴 위치를 몰라도 자연어로 즉시 데이터 조회.
2. Insight: 단순 수치 나열이 아닌, 과거 데이터와 비교하여 '특이사항(Anomaly)'을 능동적으로 진단.
3. Accuracy: 신청서 작성 시 누락된 필수 정보를 대화로 완벽하게 수집(Slot Filling). |
| **톤앤매너** | 전문적이고 간결하며, 분석적인 태도
- 불필요한 미사여구(ex. "안녕하세요, 날씨가 좋네요")는 생략하고 핵심 데이터 위주로 답변.
- 오류 분석 시에는 "TimeOut이 80%로 주 원인입니다"와 같이 명확한 근거 제시. |
| **제약 사항** | - 추측 금지: 데이터가 없으면 "조회된 데이터가 없습니다"라고 명확히 밝힐 것.
- 승인 권한 없음: 신청서 '작성(Draft)'까지는 가능하나, 최종 '승인/결재'는 수행하지 않음. |

### 워크플로우 및 오케스트레이션 (Workflow & Logic)

사용자 입력부터 최종 응답까지 Agent의 사고 과정과 행동 순서를 기술합니다.

**2.1 처리 로직**

- **Step 1 (Input Analysis):** [사용자 의도 파악 방법 기술]
    - 사용자의 발화가 '단순 조회(Read)', '신청/변경(Write)', '분석(Analyze)' 중 무엇인지 파악.
    - 필요한 API 호출 순서(Plan)를 수립. (예: "기관명만 주어졌으니 search_institution_code 호출 후 get_error_stats를 호출해야겠다")
- **Step 2 (Tool Selection):** [도구 선택 기준 및 분기 처리 로직]
    - 앞 단계의 실행 결과(Output)를 다음 단계의 입력(Input)으로 사용하여 연속 호출 수행.
- **Step 3 (Execution & Response):** [결과 통합 및 최종 답변 생성 방식]
    - 조회된 Raw Data를 종합하여 자연어로 요약.
    - 단순 수치 제공을 넘어 증감 추이(Trend)를 분석하여 Insight 제공

**2.2 상태 관리**

**State Schema (LangGraph):**

| **State 변수명** | **다이어그램 내 매칭 영역** | **역할 및 설명** |
| --- | --- | --- |
| `messages` | 사용자 입력, 실행 결과 전달 | 사용자의 최초 입력값과 Executor Node에서 반환된 MCP Server(NARU API)의 '결과 반환(Data)'을 누적하여 저장합니다. |
| `next_step` | 현재 상태 분석 -> 분기점 | Planner Node가 의도를 파악한 후, 다음으로 가야 할 방향(도구 호출, 승인 요청, 답변 완료)을 라우터(Conditional Edge)에 알려주기 위한 상태값입니다. |
| `pending_tool_calls` | 승인 필요 (Need Approval) | 도구를 바로 실행하지 않고 사용자 승인을 받아야 할 때, 어떤 API를 어떤 파라미터로 호출할 것인지 임시로 담아두는 공간입니다. |
| `is_approved` | 승인 (Yes) / 거절 (No) | Human Approval Node에서 사용자가 내린 결정 상태를 저장합니다. `True`면 Executor Node로, `False`면 Planner Node로 돌아갑니다. |
| `user_feedback` | 거절/수정 (No) | 사용자가 승인을 거절하면서 "이 조건을 수정해서 다시 찾아봐"라고 입력한 피드백을 저장하여 Planner Node에 전달합니다. |
| `final_answer` | 답변 완료 -> End | 모든 과정이 끝나고 최종적으로 사용자에게 반환할 정제된 텍스트 응답을 저장합니다. |

```
graph TD
    %% 노드 및 스타일 정의
    User((사용자 입력))
    Start([Start])
    End([End / 답변 출력])
    
    subgraph "LangGraph (Orchestrator)"
        Planner["Benefit: Planner Node<br/>(의도 파악 & 계획 수립)"]
        Router{"분기점<br/>(Conditional Edge)"}
        Executor["Executor Node<br/>(MCP 도구 실행)"]
        Approval["Human Approval Node<br/>(사용자 승인 대기)"]
    end

    subgraph "External System"
        MCPServer["MCP Server<br/>(NARU API 호출)"]
    end

    %% 흐름 연결
    User --> Start
    Start --> Planner
    
    %% Planner의 판단 로직
    Planner -- "현재 상태 분석" --> Router
    
    %% 분기점 (Router)
    Router -- "도구 호출 필요 (Call Tool)" --> Executor
    Router -- "승인 필요 (Need Approval)" --> Approval
    Router -- "답변 완료 (Final Answer)" --> End

    %% Executor (실행) 로직
    Executor -- "API 요청" --> MCPServer
    MCPServer -- "결과 반환 (Data)" --> Executor
    Executor -- "실행 결과 전달" --> Planner

    %% Approval (승인) 로직 [Human-in-the-loop]
    Approval -- "승인 (Yes)" --> Executor
    Approval -- "거절/수정 (No)" --> Planner
```

![Mermaid Chart - Create complex, visual diagrams with text.-2026-02-20-015933.png](Mermaid_Chart.png)

### 도구(Tools) 및 함수 명세 (Capability)

Agent가 외부 세상과 상호작용하기 위해 사용할 도구(Function Calling)를 정의합니다.

| **도구명 (Function Name)** | **기능 설명 (Description)** | **입력 파라미터 (Input Schema)** | **출력 데이터 (Output)** |
| --- | --- | --- | --- |
| `search_institution_code` | 기관명(한글)으로 시스템 내부 기관코드(instCd)를 조회.+2 | `instNm`: string (예: "하나카드") | `instCd`: string (예: "HNCD"), `instNm`: string |
| `get_eigw_error_stats` | 특정 기관의 시간대별/일별 EIGW 온라인 오류 건수 및 그래프 데이터 조회.+2 | `instCd`: string (필수), `date`: string (YYYYMMDD) | `error_count`: int, `error_types`: list |
| `get_queue_depth` | 특정 큐(Queue)의 현재 적체량을 조회하여 시스템 부하 상태 확인.+1 | `queueNm`: string (옵션), `date`: string | `current_depth`: int, `threshold`: int |
| `draft_application_step1` | 인터페이스 연동 신청서의 기본 정보(1단계)를 작성.+2 | `req_user`: string, `snd_sys`: string, `rcv_sys`: string | `reqNum`: string (생성된 신청번호) |
| `request_approval` | 작성된 신청서에 대해 최종 승인 요청을 수행 (Human Approval 후 실행).+1 | `reqNum`: string | `status`: string (성공/실패) |
| `get_faq_list` | 자주 묻는 질문(FAQ) 게시판에서 키워드로 관련 정보를 검색. | `keyword`: string | `faq_list`: list[dict] |

### 지식 베이스 및 메모리 전략 (Context & Memory)

LLM이 기억해야 할 단기 대화 내역과 참조해야 할 장기 데이터(RAG) 전략을 수립합니다.

**4.1 RAG (검색 증강 생성) 전략**

- **참조 데이터 소스:** [참조할 문서, DB, 매뉴얼 등]
- **청킹(Chunking) 방식:** [텍스트 분할 기준 및 사이즈]
- **임베딩 모델:** [사용할 임베딩 모델명]
- **Vector DB:** [사용할 벡터 데이터베이스명]

RAG는 사용안함

**4.2 대화 메모리 (Conversation History)**

- **메모리 유형:** **LangGraph Checkpointer** 기반 자체 상태 관리.
    - `AgentState.messages`에 대화 히스토리가 자동 누적되므로 별도 메모리 객체 불필요.
    - `ConversationSummaryBufferMemory` 같은 LangChain 레거시 메모리는 **사용하지 않음**.
- **저장 전략:**
    - **개발 환경:** `MemorySaver()` (인메모리, 서버 재시작 시 초기화)
    - **운영 환경:** `SqliteSaver.from_conn_string("naru_agent.db")` (파일 기반 영속)
    - **세션 격리:** Chainlit 세션 ID를 LangGraph `thread_id`로 사용 → 사용자별 대화 맥락 자동 격리.
    - **초기화:** 주제가 완전히 변경되거나(예: "모니터링 그만하고 신청서 쓸래"), 사용자가 명시적으로 "처음으로"를 외칠 때 초기화.

### 핵심 에이전트 기술 스택

일반적인 웹 개발 스택이 아닌, LLM의 답변 품질과 구조를 제어하기 위한 기술적 의사결정을 기입합니다.

| **구분** | **선정 전략/기술** | **선정 사유 (논리적 근거)** |
| --- | --- | --- |
| **LLM Model** | Claude 3.5 Sonnet | 복잡한 Tool Use와 코딩 능력에서 우수함 |
| **Agent Framework** | LangGraph | 순차적 워크플로우(Sequence Workflow)와 루프(Loop), 분기(Branching) 처리가 필수적인 프로젝트임. |
| **Prompt Strategy** | MCP (Model Context Protocol) | NARU 레거시 시스템과 LLM 간의 표준화된 연결 인터페이스 제공 |
| **Output Parsing** | ReAct (Reason + Act) & CoT | "기관 코드를 먼저 찾고, 그 다음 오류를 조회한다"는 식의 동적 계획 수립(Dynamic Planning)이 핵심이므로 추론 과정이 포함된 프롬프팅 필수. |
| **UI Framework** | **Chainlit** | LLM 채팅 UI에 특화. LangGraph 공식 통합, async 네이티브, `cl.AskActionMessage`로 Human-in-the-loop 버튼 UI 즉시 구현 가능. Streamlit 대비 그래프 `interrupt()` 상태 유지에 적합. |