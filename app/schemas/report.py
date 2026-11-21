"""보고서 CRUD, 버전 관리, 재색인, 검색, LLM 요약 및 Agent API(API-01~14) Pydantic 스키마 모듈"""

# 날짜/시간, 리터럴 및 Pydantic 검증·직렬화 모듈 import
# - date, datetime : 날짜 및 시각 필드 타입
# - Literal : 허용 문자열 코드 및 스타일·액션 제한
# - BaseModel, ConfigDict, Field, model_validator : 스키마 정의 및 교차 필드 검증
from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

# 허용되는 6개 보고서 카테고리 코드 타입 정의
CategoryCode = Literal[
    "EXPERIMENT", "DAILY_WORK", "RESEARCH_PLAN", "DATA_PROCESSING", "PROMPT", "MEETING"
]


# 공백만 입력된 문자열을 거부하는 검증 헬퍼 함수
# - strip() 결과가 비어 있으면 ValueError 발생
def _require_non_blank(value: str, field_name: str) -> str:
    """문자열 앞뒤 공백 제거 후 빈 문자열 여부를 검사하는 검증 헬퍼 함수"""
    # 앞뒤 공백 제거 후 비어 있는지 확인
    if not value or not value.strip():
        raise ValueError(f"{field_name} 필드는 공백만 입력할 수 없습니다.")
    # 원본 문자열 반환
    return value


# 카테고리 조회(API-01) 항목 및 목록 응답 스키마
class CategoryItemResponse(BaseModel):
    """단일 보고서 카테고리 응답 스키마"""

    # ORM 속성 읽기 허용 설정
    model_config = ConfigDict(from_attributes=True)

    category_id: int
    code: CategoryCode
    name: str
    description: str | None = None


class CategoryListResponse(BaseModel):
    """카테고리 목록 응답 스키마"""

    items: list[CategoryItemResponse]


# 6종 카테고리별 details 입력 스키마 정의
class ExperimentDetailsIn(BaseModel):
    """EXPERIMENT 분류 상세 입력 스키마"""

    experiment_date: date
    hypothesis: str = Field(..., min_length=1)
    result_summary: str = Field(..., min_length=1)

    @model_validator(mode="after")
    def validate_non_blank(self):
        """필수 문자열 필드의 공백 입력을 차단하는 검증기"""
        # 가설 및 결과 요약 공백 여부 점검
        _require_non_blank(self.hypothesis, "hypothesis")
        _require_non_blank(self.result_summary, "result_summary")
        return self


class DailyWorkDetailsIn(BaseModel):
    """DAILY_WORK 분류 상세 입력 스키마"""

    work_date: date
    progress: str = Field(..., min_length=1)
    blockers: str = ""

    @model_validator(mode="after")
    def validate_progress(self):
        """진행 내용의 공백 입력을 차단하는 검증기"""
        # 진행 내용 공백 여부 점검 (blockers는 빈 문자열 허용)
        _require_non_blank(self.progress, "progress")
        return self


class ResearchPlanDetailsIn(BaseModel):
    """RESEARCH_PLAN 분류 상세 입력 스키마"""

    research_goal: str = Field(..., min_length=1)
    methodology: str = Field(..., min_length=1)
    target_date: date

    @model_validator(mode="after")
    def validate_non_blank(self):
        """연구 목표 및 방법론의 공백 입력을 차단하는 검증기"""
        # 연구 목표 및 방법 공백 여부 점검
        _require_non_blank(self.research_goal, "research_goal")
        _require_non_blank(self.methodology, "methodology")
        return self


class DataProcessingDetailsIn(BaseModel):
    """DATA_PROCESSING 분류 상세 입력 스키마"""

    dataset_name: str = Field(..., min_length=1)
    processing_steps: str = Field(..., min_length=1)
    quality_notes: str = ""

    @model_validator(mode="after")
    def validate_non_blank(self):
        """데이터셋명 및 처리 절차의 공백 입력을 차단하는 검증기"""
        # 데이터셋명 및 처리 절차 공백 여부 점검 (quality_notes는 빈 문자열 허용)
        _require_non_blank(self.dataset_name, "dataset_name")
        _require_non_blank(self.processing_steps, "processing_steps")
        return self


class PromptDetailsIn(BaseModel):
    """PROMPT 분류 상세 입력 스키마"""

    purpose: str = Field(..., min_length=1)
    prompt_text: str = Field(..., min_length=1, max_length=20000)

    @model_validator(mode="after")
    def validate_non_blank(self):
        """목적 및 프롬프트 본문의 공백 입력을 차단하는 검증기"""
        # 목적 및 프롬프트 텍스트 공백 여부 점검
        _require_non_blank(self.purpose, "purpose")
        _require_non_blank(self.prompt_text, "prompt_text")
        return self


class MeetingDetailsIn(BaseModel):
    """MEETING 분류 상세 입력 스키마"""

    meeting_at: datetime
    attendees: str = Field(..., min_length=1)
    decisions: str = Field(..., min_length=1)

    @model_validator(mode="after")
    def validate_non_blank(self):
        """참석자 및 결정 사항의 공백 입력을 차단하는 검증기"""
        # 참석자 및 결정 사항 공백 여부 점검
        _require_non_blank(self.attendees, "attendees")
        _require_non_blank(self.decisions, "decisions")
        return self


# 카테고리 코드와 details 스키마 매핑 딕셔너리
DETAIL_SCHEMA_BY_CATEGORY: dict[str, type[BaseModel]] = {
    "EXPERIMENT": ExperimentDetailsIn,
    "DAILY_WORK": DailyWorkDetailsIn,
    "RESEARCH_PLAN": ResearchPlanDetailsIn,
    "DATA_PROCESSING": DataProcessingDetailsIn,
    "PROMPT": PromptDetailsIn,
    "MEETING": MeetingDetailsIn,
}


# 카테고리별 details 딕셔너리를 검증하는 헬퍼 함수
def validate_details_for_category(category_code: str, details: dict) -> dict:
    """카테고리 코드에 맞는 상세 스키마로 details 딕셔너리를 검증하고 정규화하는 함수"""
    # 카테고리에 해당하는 상세 Pydantic 모델 조회
    schema_cls = DETAIL_SCHEMA_BY_CATEGORY.get(category_code)
    if schema_cls is None:
        raise ValueError(f"지원하지 않는 category_code입니다: {category_code}")
    # 상세 모델 검증 후 딕셔너리로 반환
    validated = schema_cls.model_validate(details)
    return validated.model_dump()


# 보고서 등록(API-02) 요청 및 응답 스키마
class ReportCreateRequest(BaseModel):
    """보고서 생성(POST /api/v1/reports) 요청 스키마"""

    category_code: CategoryCode
    title: str = Field(..., min_length=1, max_length=200)
    author: str = Field(..., min_length=1, max_length=100)
    content: str = Field(..., min_length=1, max_length=20000)
    overview: str = Field(..., min_length=10, max_length=1000)
    details: dict

    @model_validator(mode="after")
    def validate_fields_and_details(self):
        """공통 필드 공백 여부, 카테고리별 details 및 PROMPT 본문 일치 여부를 검증하는 검증기"""
        # 공통 텍스트 필드 공백 차단
        _require_non_blank(self.title, "title")
        _require_non_blank(self.author, "author")
        _require_non_blank(self.content, "content")
        _require_non_blank(self.overview, "overview")
        # 카테고리별 상세 필드 검증
        normalized_details = validate_details_for_category(
            self.category_code, self.details
        )
        # PROMPT 보고서는 content와 details.prompt_text가 일치해야 함
        if (
            self.category_code == "PROMPT"
            and self.content != normalized_details["prompt_text"]
        ):
            raise ValueError(
                "PROMPT 보고서의 content는 details.prompt_text와 같아야 합니다."
            )
        self.details = normalized_details
        return self


class ReportCreateResponse(BaseModel):
    """보고서 생성(201) 응답 스키마"""

    report_id: int
    category_code: CategoryCode
    title: str
    author: str
    revision: int
    index_status: str
    embedding_model: str


# 보고서 단건 조회(API-03) 및 목록 조회(API-04) 응답 스키마
class ReportDetailResponse(BaseModel):
    """보고서 단건 상세 조회(200) 응답 스키마"""

    report_id: int
    category_code: CategoryCode
    title: str
    content: str
    author: str
    overview: str
    details: dict
    revision: int
    index_status: str
    created_at: datetime
    updated_at: datetime


class ReportListItemResponse(BaseModel):
    """보고서 목록 조회 항목 스키마"""

    report_id: int
    category_code: CategoryCode
    title: str
    revision: int


class ReportListResponse(BaseModel):
    """보고서 목록 조회(200) 응답 스키마"""

    items: list[ReportListItemResponse]
    total: int
    limit: int
    offset: int


# 보고서 전체 수정(API-05) 요청 및 응답 스키마
class ReportUpdateRequest(BaseModel):
    """보고서 전체 수정(PUT /api/v1/reports/{report_id}) 요청 스키마"""

    title: str = Field(..., min_length=1, max_length=200)
    author: str = Field(..., min_length=1, max_length=100)
    content: str = Field(..., min_length=1, max_length=20000)
    overview: str = Field(..., min_length=10, max_length=1000)
    details: dict
    expected_revision: int | None = Field(default=None, ge=1)

    @model_validator(mode="after")
    def validate_common_fields(self):
        """수정 요청 공통 텍스트 필드의 공백 입력을 차단하는 검증기"""
        # 제목, 작성자, 본문, 개요 공백 차단
        _require_non_blank(self.title, "title")
        _require_non_blank(self.author, "author")
        _require_non_blank(self.content, "content")
        _require_non_blank(self.overview, "overview")
        return self


class ReportUpdateResponse(BaseModel):
    """보고서 수정(200) 응답 스키마"""

    report_id: int
    revision: int
    index_status: str
    embedding_updated: bool


# Keyword + Semantic 유사도 검색(API-07) 요청 및 응답 스키마
class SimilarSearchRequest(BaseModel):
    """유사도 검색(POST /api/v1/search/similar) 요청 스키마"""

    query: str = Field(..., min_length=1, max_length=200)
    category_code: CategoryCode | None = None
    keyword_limit: int = Field(default=20, ge=1, le=100)
    semantic_limit: int = Field(default=20, ge=1, le=100)

    @model_validator(mode="after")
    def validate_query(self):
        """검색 질의의 공백만 입력된 경우를 차단하는 검증기"""
        # 검색 질의 공백 여부 확인
        _require_non_blank(self.query, "query")
        return self


class SimilarSearchMatch(BaseModel):
    """검색 최고 일치 보고서 스키마"""

    report_id: int
    title: str
    category_code: CategoryCode
    overview: str
    keyword_match: bool
    cosine_similarity: float | None = None


class SimilarSearchResponse(BaseModel):
    """유사도 검색(200) 응답 스키마"""

    status: Literal["found", "not_found"]
    query: str
    best_match: SimilarSearchMatch | None = None


# LLM 보고서 요약(API-08) 요청 및 응답 스키마
class SummarizeRequest(BaseModel):
    """보고서 요약(POST /api/v1/reports/{report_id}/summarize) 요청 스키마"""

    style: Literal["brief", "structured"] = "brief"
    max_sentences: int = Field(default=3, ge=1, le=10)


class StructuredSummaryPayload(BaseModel):
    """구조화 요약 필수 항목 스키마"""

    purpose: str = Field(..., min_length=1)
    key_points: list[str] = Field(..., min_length=1)
    conclusion: str = Field(..., min_length=1)
    limitations: str = Field(..., min_length=1)


class SummarizeResponse(BaseModel):
    """보고서 요약(200) 응답 스키마"""

    report_id: int
    source_revision: int
    summary: str | StructuredSummaryPayload
    model: str
    status: str


# Agent 실행(API-09) 및 실행 이력 조회(API-14) 스키마
class AgentRunRequest(BaseModel):
    """Agent 동작 실행(POST /api/v1/agent/run) 요청 스키마"""

    action: (
        Literal["get_report", "find_report", "summarize_report", "search_and_summarize"]
        | None
    ) = None
    report_id: int | None = Field(default=None, ge=1)
    query: str | None = Field(default=None, min_length=1, max_length=200)
    agent_mode: Literal["deterministic", "tool_calling"] | None = None
    message: str | None = Field(default=None, min_length=1, max_length=1000)

    @model_validator(mode="after")
    def validate_mode_or_action(self):
        """명시적 action 또는 tool_calling 모드의 필수 인자를 검증하는 검증기"""
        # tool_calling 모드인 경우 message 필수 확인
        if self.agent_mode == "tool_calling":
            if not self.message or not self.message.strip():
                raise ValueError("tool_calling 모드에서는 message가 필수입니다.")
            return self
        # 명시적 action 필수 및 액션별 인자 검사
        if self.action is None:
            raise ValueError(
                "action 또는 agent_mode='tool_calling' 중 하나를 지정해야 합니다."
            )
        if self.action in ("get_report", "summarize_report") and self.report_id is None:
            raise ValueError(f"{self.action}에는 report_id가 필수입니다.")
        if self.action in ("find_report", "search_and_summarize"):
            if not self.query or not self.query.strip():
                raise ValueError(f"{self.action}에는 query가 필수입니다.")
        return self


class AgentRunResponse(BaseModel):
    """Agent 실행(200) 응답 스키마"""

    action: str
    status: str
    tool_calls: list[str]
    data: dict


class AgentRunHistoryItem(BaseModel):
    """Agent 실행 이력 단건 스키마"""

    run_id: str
    action: str
    status: str
    tool_calls: int
    created_at: datetime


class AgentRunHistoryResponse(BaseModel):
    """Agent 실행 이력 조회(API-14) 응답 스키마"""

    items: list[AgentRunHistoryItem]
    total: int
    limit: int
    offset: int


# Prompt 버전 관리 및 활성 전환(API-10~12) 스키마
class PromptVersionCreateRequest(BaseModel):
    """Prompt 버전 추가(API-10) 요청 스키마"""

    prompt_text: str = Field(..., min_length=1, max_length=20000)

    @model_validator(mode="after")
    def validate_prompt_text(self):
        """프롬프트 텍스트의 공백 입력을 차단하는 검증기"""
        # prompt_text 공백 여부 확인
        _require_non_blank(self.prompt_text, "prompt_text")
        return self


class PromptVersionCreateResponse(BaseModel):
    """Prompt 버전 추가(201) 응답 스키마"""

    version_no: int
    active: bool


class PromptVersionItem(BaseModel):
    """Prompt 버전 이력 단건 스키마"""

    version_no: int
    created_at: datetime


class PromptVersionListResponse(BaseModel):
    """Prompt 버전 목록 조회(API-11) 응답 스키마"""

    items: list[PromptVersionItem]
    active_version_no: int


class PromptActiveVersionRequest(BaseModel):
    """Prompt 활성 버전 변경(API-12) 요청 스키마"""

    version_no: int = Field(..., ge=1)


class PromptActiveVersionResponse(BaseModel):
    """Prompt 활성 버전 변경(200) 응답 스키마"""

    active_version_no: int
    revision: int
    index_status: str


# 보고서 재색인(API-13) 요청 및 응답 스키마
class ReindexRequest(BaseModel):
    """보고서 재색인(API-13) 요청 스키마"""

    force: bool = False


class ReindexResponse(BaseModel):
    """보고서 재색인(200) 응답 스키마"""

    report_id: int
    index_status: str
    indexed_revision: int
    embedding_updated: bool


"""
API-01~14 계약에 맞춘 요청/응답 Pydantic 스키마와 카테고리별 details 유효성 검증 로직을 구현하였다.
공백 문자열 차단, PROMPT 본문 일치 확인, 구조화 요약 및 Agent 모드·액션별 인자 검증 규칙을 스키마 계층에 반영하였다.
"""
