# Report Agent 시스템 구현 및 검증 결과 보고서

## 1. 프로젝트 개요
* **프로젝트명:** Report Agent (`Report Agent | 2026-11-21~23`, `v1.4.0`)
* **적용 레벨:** `advanced`
* **목적:** 6종 기술·업무 보고서(`EXPERIMENT`, `DAILY_WORK`, `RESEARCH_PLAN`, `DATA_PROCESSING`, `PROMPT`, `MEETING`)의 생명주기 관리(CRUD), 프롬프트 버전 제어, 키워드·의미 기반 하이브리드 검색, LLM 요약 및 Tool Calling 에이전트 기능을 통합 제공하는 백엔드 서비스 구현 및 검증
* **기술 스택:**
  * **Backend:** Python, FastAPI, Pydantic, SQLAlchemy
  * **Database & Vector:** PostgreSQL, `pgvector`
  * **Embedding & LLM:** `intfloat/multilingual-e5-small`, OpenAI Chat Completions API (`gpt-6-luna`)
  * **Verification:** Postman Automated Test Suite (`01 Basic` ~ `08 선택 실습`)

---

## 2. 시스템 아키텍처 및 주요 구현 내용

### 2.1 계층형 백엔드 구조
* **API 라우터 계층 (`app/api/reports.py`, `app/api/agent.py`):**
  * 보고서 및 프롬프트 도메인 엔드포인트(`API-01`~`API-06`, `API-08`, `API-10`~`API-13`)와 검색·에이전트 엔드포인트(`API-07`, `API-09`, `API-14`)를 분리하여 구성하였다.
  * 요청 바디 및 쿼리 파라미터 유효성 검증(공백 문자열 차단, `limit` 범위 제한 등)을 적용하고 도메인 예외(`ServiceError`)를 표준 HTTP 상태 코드(`400`, `404`, `422`, `503`)로 변환하였다.
* **서비스 계층 (`app/services/report_service.py`, `app/services/agent_service.py`):**
  * 6개 카테고리별 상세 테이블 조인 조회, 낙관적 동시성 제어(`revision` 증가), 임베딩 상태(`pending` / `ready`) 관리 및 강제 재색인(`reindex`) 로직을 구현하였다.
  * 키워드 검색과 의미 검색 후보를 RRF(Reciprocal Rank Fusion) 방식으로 병합하여 하이브리드 검색 순위를 산출하였다.
* **설정 및 LLM 연동 계층 (`app/core/config.py`, `app/integrations/llm_client.py`):**
  * `.env` 파일 파싱 및 OS 환경변수 연동을 통해 `OPENAI_API_KEY`, `LLM_MODEL`, 타임아웃·재시도 정책을 일관되게 관리하였다.
  * `brief` 및 `structured`(4개 필수 JSON 키: `purpose`, `key_points`, `conclusion`, `limitations`) 요약 생성과 `chat_with_tools` 기반 Tool Calling 호출을 캡슐화하였다.

---

## 3. 단계별 API 검증 결과 요약

Postman 테스트 스위트를 통해 시드 데이터(180건) 및 신규 생성 데이터(ID `181`~`186`)를 대상으로 전 구간 검증을 수행하였다.

| 단계 | 테스트 항목 | 엔드포인트 | 상태 코드 | 핵심 검증 결과 |
| :--- | :--- | :--- | :---: | :--- |
| **01 Basic** | Health & 카테고리 조회 (`API-00`, `01`) | `GET /health`, `/api/v1/categories` | `200` | DB/Vector `ready` 및 6종 카테고리 정상 반환 |
| **01 Basic** | 보고서 CRUD 및 검색 (`API-02`~`05`, `07`) | `/api/v1/reports`, `/api/v1/search/similar` | `201` / `200` | ID `181` 생성·수정(`revision: 2`)·조회 및 RRF 하이브리드 검색 확인, 무관 질의(`화성의 낙타 전용 미용실`) `total: 0` 반환 |
| **02 Intermediate** | 복합 필터 및 프롬프트 버전 (`API-04`, `10`, `11`) | `/api/v1/reports`, `/api/v1/prompts/{id}/versions` | `200` / `201` | `category_code` + `updated_after` 필터링 및 프롬프트 버전 `3` 생성·이력 조회 |
| **03 Advanced** | 활성 버전 전환·재색인·이력 (`API-12`~`14`) | `/active-version`, `/reindex`, `/agent/runs` | `200` | 활성 버전 `3` 전환(`revision: 2`), ID `1` 강제 재색인(`index_status: "ready"`), 실행 이력 조회 응답 확인 |
| **04 오류 사례** | 입력값 검증 및 미존재 처리 | `/reports`, `/search/similar` | `404` / `422` | 공백 제목(`422`), 공백 검색어(`422`), `limit=101`(`422`), 미존재 ID(`404 REPORT_NOT_FOUND`) 차단 |
| **05 선택 실습** | 5개 추가 카테고리 등록 (`API-02`) | `POST /api/v1/reports` | `201` | `DAILY_WORK`(182)~`MEETING`(186) 등록 및 E5 임베딩 색인 완료 |
| **06 유료 LLM** | Brief/Structured 요약 및 Agent 실행 (`API-08`, `09`) | `/summarize`, `/agent/run` | `200` | `gpt-6-luna` 기반 요약 생성, `search_and_summarize` 및 `tool_calling`(`find_report` 호출) 정상 동작 |
| **07~08 정리** | 테스트 데이터 삭제 및 사후 검증 (`API-06`, `03`) | `DELETE /api/v1/reports/{id}` | `204` / `404` | ID `181`~`186` 삭제 후 재조회 시 `404` 반환으로 데이터 정합성 유지 |

---

## 4. 주요 트러블슈팅 및 해결 과정

### 4.1 API 라우팅 및 요청 스키마 불일치 해결
* **현상:** 프롬프트 활성 버전 전환(`PUT /api/v1/prompts/{report_id}/active-version`) 및 에이전트 실행 이력 조회(`GET /api/v1/agent/runs`) 호출 시 `404 Not Found`가 발생하고, `/agent/run`의 `search_and_summarize` 액션 호출 시 `400 Bad Request`가 반환되었다.
* **원인:** 초기 라우터 경로와 클라이언트 호출 경로 간 메서드/경로 매핑이 누락되었고, `AgentRunRequest` 스키마가 `action` 단일 문자열만 필수로 요구하여 `agent_mode="tool_calling"` 및 `message` 입력을 수용하지 못했다.
* **해결:** `app/api/reports.py`와 `app/api/agent.py`에 해당 엔드포인트 및 액션 분기를 추가하고, `AgentRunRequest`가 `action`과 `agent_mode`/`message`를 모두 처리하도록 확장하였다.

### 4.2 공백 입력값 유효성 검증 보완 (`200` → `422`)
* **현상:** `POST /api/v1/search/similar`에 `{"query": "   "}`를 전송했을 때 `422` 오류 대신 빈 검색 결과(`200 OK`)가 반환되었다.
* **원인:** Pydantic의 `min_length=1` 검증만으로는 공백 문자 3개로 이루어진 문자열이 통과되었다.
* **해결:** `SimilarSearchRequest`와 `AgentQueryRequest`에 `@field_validator("query")`를 구현하여 `value.strip()`이 빈 문자열일 경우 `ValueError`를 발생시켜 `422 Unprocessable Entity`를 반환하도록 수정하였다.

### 4.3 `.env` 환경변수 로드 및 OpenAI 인증 연동
* **현상:** 유료 LLM 요약 요청(`POST /api/v1/reports/181/summarize`) 시 `openai.OpenAIError: Missing credentials`와 함께 `500 Internal Server Error`가 발생하였다.
* **원인:** `app/core/config.py`가 `.env` 파일을 딕셔너리로만 파싱하고 `os.environ` 또는 `Settings.openai_api_key`에 반영하지 않아 `OpenAI()` 클라이언트 초기화 시 API 키를 참조하지 못했다.
* **해결:** `Settings.__init__`에서 `.env`의 유효한 키를 `os.environ`에 주입하고 `self.openai_api_key` 필드로 보관한 뒤, `_create_client()`에서 `api_key`를 명시적으로 전달하도록 개선하였다.

### 4.4 추론 모델(`gpt-6-luna`)의 Tool Calling 파라미터 호환성 확보
* **현상:** `agent_mode="tool_calling"` 실행 시 `Function tools with reasoning_effort are not supported for gpt-6-luna in /v1/chat/completions` 오류와 함께 `503` 응답이 반환되었다.
* **원인:** 추론 기능이 포함된 모델에서 `/v1/chat/completions`로 Function Tools를 호출할 때 `reasoning_effort`를 `"none"`으로 명시하지 않으면 API가 요청을 거부하였다.
* **해결:** `app/integrations/llm_client.py`의 `chat_with_tools` 함수에 `reasoning_effort="none"` 옵션을 기본 적용하고, 해당 파라미터를 지원하지 않는 일반 모델을 위한 fallback 재시도 로직을 추가하였다.

---

## 5. 기술적 고찰 및 향후 개선 과제

1. **미색인(`pending`) 시드 데이터의 검색 품질 고도화:**
   * 검증 결과 시드 데이터 중 `index_status`가 `pending`인 항목은 `semantic_score`가 `0.0`으로 계산되어 키워드 점수 위주로 정렬되었다. 운영 환경에서는 초기 적재 시 배치 색인 파이프라인을 실행해 전수 `ready` 상태를 보장할 필요가 있다.
2. **Agent 실행 이력 영속화 (`API-14`):**
   * 현재 `/api/v1/agent/runs`는 `agent_runs` 테이블 부재 시 빈 목록(`total: 0`)을 안전하게 반환하도록 구현되어 있다. 추후 `agent_runs` 테이블 마이그레이션과 실행 로그 기록 로직을 연동하면 감사 추적 및 실패 모니터링이 가능해진다.
3. **Tool Calling 최종 자연어 답변 정교화:**
   * `API-09` Tool Calling 검증에서 `find_report` 도구 호출과 `sources` 반환은 정상 수행되었으나, 2차 LLM 호출 응답이 비어 있을 때 기본 안내 문구로 대체되었다. 도구 실행 결과를 컨텍스트로 요약해 자연어 답변을 생성하는 프롬프트를 보강하면 응답 완성도를 더욱 높일 수 있다.