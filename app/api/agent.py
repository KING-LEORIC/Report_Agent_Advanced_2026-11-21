"""유사도 검색, 에이전트 질의, 에이전트 실행, 실행 이력 및 보고서 조회 FastAPI 라우터를 정의하는 API 모듈"""

from __future__ import annotations

# 표준 라이브러리, FastAPI 라우터·의존성·예외 처리, Pydantic 및 SQLAlchemy 모듈 import
# - json : Tool Calling 인자(JSON 문자열) 파싱
# - APIRouter, Depends, HTTPException, Query, status : DB 세션 주입, 쿼리 파라미터 및 HTTP 상태 코드 예외 처리
# - BaseModel, Field, field_validator : 요청 바디 유효성 검사 스키마 및 필드 검증기 정의
# - Session : SQLAlchemy 세션 타입
import json
from collections.abc import Generator
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field, field_validator
from sqlalchemy.orm import Session

from app.integrations.llm_client import LLMClientError, chat_with_tools
from app.services import report_service
from app.services.agent_service import AgentService
from app.services.report_service import ServiceError

# 에이전트 및 검색 엔드포인트용 라우터 인스턴스 생성
router = APIRouter(prefix="/api/v1", tags=["Agent & Search"])

# Tool Calling 에이전트에 노출할 도구 스키마 정의
AGENT_TOOLS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "find_report",
            "description": "검색어(query)와 선택적 카테고리(category_code)로 관련 보고서를 검색합니다.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "검색 키워드 또는 질의"},
                    "category_code": {
                        "type": "string",
                        "description": "보고서 카테고리 코드",
                    },
                    "keyword_limit": {"type": "integer", "default": 20},
                    "semantic_limit": {"type": "integer", "default": 20},
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_report",
            "description": "report_id로 특정 보고서의 상세 내용을 조회합니다.",
            "parameters": {
                "type": "object",
                "properties": {
                    "report_id": {"type": "integer", "description": "조회할 보고서 ID"}
                },
                "required": ["report_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "summarize_report",
            "description": "report_id에 해당하는 보고서를 LLM으로 요약합니다.",
            "parameters": {
                "type": "object",
                "properties": {
                    "report_id": {"type": "integer", "description": "요약할 보고서 ID"},
                    "style": {"type": "string", "default": "brief"},
                    "max_sentences": {"type": "integer", "default": 3},
                },
                "required": ["report_id"],
            },
        },
    },
]


# 요청 단위 DB 세션 의존성 함수
# - SessionLocal을 동적으로 불러와 세션 생성 후 finally 블록에서 닫음
def get_db_session() -> Generator[Session, None, None]:
    """요청별 SQLAlchemy 세션을 생성하고 종료 시 정리하는 제너레이터 의존성 함수"""
    # 세션 팩토리 import 실패 시 500 예외 발생
    try:
        from app.db.session import SessionLocal  # type: ignore[import-not-found]
    except ImportError as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="데이터베이스 세션 팩토리를 불러올 수 없습니다.",
        ) from exc

    # DB 세션 생성 및 요청 처리 후 종료 보장
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


# 유사도 검색 요청 스키마 클래스
# - 검색어, 카테고리 필터 및 키워드/의미 검색 상한값 정의
class SimilarSearchRequest(BaseModel):
    """하이브리드 유사도 검색 POST 요청 본문 스키마"""

    query: str = Field(..., min_length=1)
    category_code: str | None = None
    keyword_limit: int = Field(default=20, ge=1, le=100)
    semantic_limit: int = Field(default=20, ge=1, le=100)

    # 공백만 포함된 검색어 입력 시 422 유효성 검증 오류 유발
    @field_validator("query")
    @classmethod
    def validate_query_not_blank(cls, value: str) -> str:
        """검색어가 공백만으로 구성되지 않았는지 검증하는 필드 검증기"""
        if not value.strip():
            raise ValueError("검색어(query)는 공백만 입력할 수 없습니다.")
        return value


# 에이전트 질의 요청 스키마 클래스
# - 질의 문자열, 카테고리 필터 및 상위 반환 문서 개수(top_k) 정의
class AgentQueryRequest(BaseModel):
    """에이전트 질의 응답 POST 요청 본문 스키마"""

    query: str = Field(..., min_length=1)
    category_code: str | None = None
    top_k: int = Field(default=5, ge=1, le=50)

    # 공백만 포함된 질의 문자열 입력 시 422 유효성 검증 오류 유발
    @field_validator("query")
    @classmethod
    def validate_query_not_blank(cls, value: str) -> str:
        """질의 문자열(query)이 공백만으로 구성되지 않았는지 검증하는 필드 검증기"""
        if not value.strip():
            raise ValueError("질의(query)는 공백만 입력할 수 없습니다.")
        return value


# 에이전트 통합 실행 요청 스키마 클래스
# - action 또는 agent_mode(tool_calling) 및 액션별 선택 파라미터 정의
class AgentRunRequest(BaseModel):
    """에이전트 액션 실행 POST /api/v1/agent/run 요청 본문 스키마"""

    action: str | None = None
    agent_mode: str | None = None
    message: str | None = None
    report_id: int | None = None
    query: str | None = None
    category_code: str | None = None
    keyword_limit: int = Field(default=20, ge=1, le=100)
    semantic_limit: int = Field(default=20, ge=1, le=100)
    top_k: int = Field(default=5, ge=1, le=50)
    style: str = Field(default="brief")
    max_sentences: int = Field(default=3, ge=1, le=10)


# Tool Calling 실행 헬퍼 함수
# - LLM이 선택한 도구를 호출하고 결과를 바탕으로 최종 답변과 tool_calls 목록 반환
def _execute_tool_calling(
    payload: AgentRunRequest, service: AgentService, db: Session
) -> dict[str, Any]:
    """Tool Calling 모드로 사용자 메시지를 처리하고 실행된 도구 목록과 답변을 반환하는 함수"""
    user_text = (payload.message or payload.query or "").strip()
    if not user_text:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="tool_calling 모드에는 message 또는 query가 필요합니다.",
        )

    messages: list[dict[str, Any]] = [
        {
            "role": "system",
            "content": (
                "당신은 보고서 관리 시스템 에이전트입니다. "
                "필요한 경우 제공된 도구(find_report, get_report, summarize_report)를 호출해 "
                "관련 보고서를 찾고 요약하여 한국어로 알기 쉽게 설명하세요."
            ),
        },
        {"role": "user", "content": user_text},
    ]

    executed_tools: list[str] = []
    sources: list[dict[str, Any]] = []
    summary_text: str | None = None

    try:
        assistant_msg = chat_with_tools(messages=messages, tools=AGENT_TOOLS)
        tool_calls = getattr(assistant_msg, "tool_calls", None) or []

        if tool_calls:
            messages.append(
                {
                    "role": "assistant",
                    "content": getattr(assistant_msg, "content", None) or "",
                    "tool_calls": [
                        {
                            "id": tc.id,
                            "type": "function",
                            "function": {
                                "name": tc.function.name,
                                "arguments": tc.function.arguments or "{}",
                            },
                        }
                        for tc in tool_calls
                    ],
                }
            )

            for tc in tool_calls:
                fn_name = tc.function.name
                try:
                    fn_args = json.loads(tc.function.arguments or "{}")
                except json.JSONDecodeError:
                    fn_args = {}

                if fn_name in ("find_report", "search_similar", "search"):
                    executed_tools.append("find_report")
                    search_query = str(fn_args.get("query") or user_text)
                    search_cat = fn_args.get("category_code", payload.category_code)
                    search_res = service.search_similar_reports(
                        query=search_query,
                        category_code=search_cat,
                        keyword_limit=int(
                            fn_args.get("keyword_limit", payload.keyword_limit)
                        ),
                        semantic_limit=int(
                            fn_args.get("semantic_limit", payload.semantic_limit)
                        ),
                    )
                    matched = search_res.get("results") or []
                    sources.extend(matched[: payload.top_k])
                    tool_output: Any = search_res

                elif fn_name in ("get_report", "get_report_by_id"):
                    executed_tools.append("get_report")
                    target_id = int(fn_args.get("report_id") or payload.report_id or 0)
                    report_row = service.get_report_by_id(report_id=target_id)
                    tool_output = report_row or {"error": f"보고서 {target_id} 없음"}

                elif fn_name in ("summarize_report", "summarize"):
                    executed_tools.append("summarize_report")
                    target_id = int(fn_args.get("report_id") or payload.report_id or 0)
                    if target_id <= 0 and sources:
                        target_id = int(sources[0]["report_id"])
                    try:
                        sum_res = report_service.summarize_report(
                            db=db,
                            report_id=target_id,
                            style=str(fn_args.get("style") or payload.style),
                            max_sentences=int(
                                fn_args.get("max_sentences") or payload.max_sentences
                            ),
                        )
                        summary_text = (
                            sum_res.summary
                            if isinstance(sum_res.summary, str)
                            else json.dumps(sum_res.summary, ensure_ascii=False)
                        )
                        tool_output = {
                            "report_id": sum_res.report_id,
                            "summary": sum_res.summary,
                            "status": sum_res.status,
                        }
                    except ServiceError as exc:
                        tool_output = {"error": exc.message}

                else:
                    executed_tools.append(fn_name)
                    tool_output = {"info": f"도구 {fn_name} 실행됨"}

                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tc.id,
                        "content": json.dumps(
                            tool_output, ensure_ascii=False, default=str
                        ),
                    }
                )

            final_msg = chat_with_tools(messages=messages, tools=AGENT_TOOLS)
            final_answer = (getattr(final_msg, "content", None) or "").strip()
        else:
            final_answer = (getattr(assistant_msg, "content", None) or "").strip()

    except LLMClientError as exc:
        raise HTTPException(status_code=exc.status, detail=exc.message) from exc

    if not final_answer:
        final_answer = summary_text or f"'{user_text}'에 대한 처리가 완료되었습니다."

    return {
        "action": payload.action or "tool_calling",
        "agent_mode": payload.agent_mode or "tool_calling",
        "message": user_text,
        "status": "completed",
        "answer": final_answer,
        "summary": summary_text or final_answer,
        "sources": sources,
        "tool_calls": executed_tools,
    }


# 하이브리드 유사도 검색 엔드포인트
# - POST /api/v1/search/similar 요청을 받아 AgentService.search_similar_reports 호출
@router.post("/search/similar")
def search_similar(
    payload: SimilarSearchRequest, db: Session = Depends(get_db_session)
) -> dict[str, Any]:
    """키워드 및 유사도 검색을 수행해 관련 보고서 목록을 반환하는 엔드포인트"""
    # 서비스 인스턴스 생성 및 검색 실행
    service = AgentService(db=db)
    return service.search_similar_reports(
        query=payload.query,
        category_code=payload.category_code,
        keyword_limit=payload.keyword_limit,
        semantic_limit=payload.semantic_limit,
    )


# 에이전트 질의 응답 엔드포인트
# - POST /api/v1/agent/query 요청을 받아 AgentService.answer_report_query 호출
@router.post("/agent/query")
def query_agent(
    payload: AgentQueryRequest, db: Session = Depends(get_db_session)
) -> dict[str, Any]:
    """질의에 맞는 보고서를 검색해 요약 답변과 출처를 반환하는 엔드포인트"""
    # 서비스 인스턴스 생성 및 질의 응답 처리
    service = AgentService(db=db)
    return service.answer_report_query(
        query=payload.query, category_code=payload.category_code, top_k=payload.top_k
    )


# 에이전트 액션 실행 엔드포인트
# - POST /api/v1/agent/run 요청의 agent_mode 또는 action 값에 따라 실행
@router.post("/agent/run")
def run_agent(
    payload: AgentRunRequest, db: Session = Depends(get_db_session)
) -> dict[str, Any]:
    """agent_mode 또는 action 파라미터에 따라 보고서 조회, 검색, 요약 또는 Tool Calling을 실행하는 엔드포인트"""
    # 서비스 인스턴스 생성
    service = AgentService(db=db)

    mode_name = (payload.agent_mode or "").strip().lower()
    action_name = (payload.action or "").strip().lower()

    # Tool Calling 모드 분기 처리
    if mode_name in ("tool_calling", "tools", "agent") or action_name in (
        "tool_calling",
        "chat_with_tools",
    ):
        return _execute_tool_calling(payload=payload, service=service, db=db)

    if not action_name:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="action 또는 agent_mode 값이 필요합니다.",
        )

    # 보고서 단건 조회 액션 처리
    if action_name in ("get_report", "get_report_by_id", "report"):
        if payload.report_id is None:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="get_report 액션에는 report_id가 필요합니다.",
            )
        report = service.get_report_by_id(report_id=payload.report_id)
        if report is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"보고서(id={payload.report_id})를 찾을 수 없습니다.",
            )
        return {
            "action": payload.action,
            "report_id": payload.report_id,
            "report": report,
            "tool_calls": ["get_report"],
        }

    # 유사도·의미 검색 액션 처리 (find_report / search_similar / search)
    if action_name in ("find_report", "search_similar", "search"):
        if not payload.query or not payload.query.strip():
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"{payload.action} 액션에는 query가 필요합니다.",
            )
        result = service.search_similar_reports(
            query=payload.query,
            category_code=payload.category_code,
            keyword_limit=payload.keyword_limit,
            semantic_limit=payload.semantic_limit,
        )
        result["tool_calls"] = ["find_report"]
        return result

    # 에이전트 질의 액션 처리
    if action_name in ("query", "answer_query"):
        if not payload.query or not payload.query.strip():
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="query 액션에는 query가 필요합니다.",
            )
        result = service.answer_report_query(
            query=payload.query,
            category_code=payload.category_code,
            top_k=payload.top_k,
        )
        result["tool_calls"] = ["query"]
        return result

    # 검색 후 요약 액션 처리 (search_and_summarize)
    if action_name == "search_and_summarize":
        if not payload.query or not payload.query.strip():
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="search_and_summarize 액션에는 query가 필요합니다.",
            )
        search_res = service.search_similar_reports(
            query=payload.query,
            category_code=payload.category_code,
            keyword_limit=payload.keyword_limit,
            semantic_limit=payload.semantic_limit,
        )
        matched_items = search_res.get("results") or []
        top_items = matched_items[: payload.top_k]

        if top_items:
            target_report_id = int(top_items[0]["report_id"])
            try:
                summary_res = report_service.summarize_report(
                    db=db,
                    report_id=target_report_id,
                    style=payload.style,
                    max_sentences=payload.max_sentences,
                )
            except ServiceError as exc:
                raise HTTPException(status_code=exc.status, detail=exc.message) from exc

            return {
                "action": payload.action,
                "query": payload.query,
                "report_id": target_report_id,
                "status": summary_res.status,
                "summary": summary_res.summary,
                "model": summary_res.model,
                "source_revision": summary_res.source_revision,
                "results": top_items,
                "tool_calls": [
                    "find_report",
                    "summarize_report",
                    "search_and_summarize",
                ],
            }

        return {
            "action": payload.action,
            "query": payload.query,
            "status": "completed",
            "summary": f"'{payload.query}'와(과) 관련된 보고서를 찾지 못해 요약을 생성하지 못했습니다.",
            "results": [],
            "tool_calls": ["find_report", "search_and_summarize"],
        }

    # 보고서 요약 액션 처리 (summarize_report)
    if action_name in ("summarize_report", "summarize"):
        if payload.report_id is None:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="summarize_report 액션에는 report_id가 필요합니다.",
            )
        try:
            summary_res = report_service.summarize_report(
                db=db,
                report_id=payload.report_id,
                style=payload.style,
                max_sentences=payload.max_sentences,
            )
        except ServiceError as exc:
            raise HTTPException(status_code=exc.status, detail=exc.message) from exc

        return {
            "action": payload.action,
            "report_id": payload.report_id,
            "status": summary_res.status,
            "summary": summary_res.summary,
            "model": summary_res.model,
            "source_revision": summary_res.source_revision,
            "tool_calls": ["summarize_report"],
        }

    # 지원하지 않는 action 입력 시 400 예외 반환
    raise HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail=f"지원하지 않는 action입니다: {payload.action}",
    )


# 에이전트 실행 이력 조회 엔드포인트
# - GET /api/v1/agent/runs 요청 처리 (limit, offset, status 쿼리 지원)
@router.get("/agent/runs")
def list_agent_runs(
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    status_filter: str | None = Query(default=None, alias="status"),
    db: Session = Depends(get_db_session),
) -> dict[str, Any]:
    """에이전트 실행 이력 목록을 페이지네이션 및 상태 필터와 함께 반환하는 엔드포인트"""
    # 서비스 인스턴스 생성 후 실행 이력 조회
    service = AgentService(db=db)
    return service.list_agent_runs(limit=limit, offset=offset, run_status=status_filter)


# 단일 보고서 조회 엔드포인트
# - GET /api/v1/agent/reports/{report_id} 요청 처리 및 미존재 시 404 반환
@router.get("/agent/reports/{report_id}")
def get_agent_report(
    report_id: int, db: Session = Depends(get_db_session)
) -> dict[str, Any]:
    """report_id로 단일 보고서를 조회하고 없을 경우 404 예외를 발생시키는 엔드포인트"""
    # 보고서 단건 조회 및 존재 여부 검증
    service = AgentService(db=db)
    report = service.get_report_by_id(report_id=report_id)
    if report is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"보고서(id={report_id})를 찾을 수 없습니다.",
        )
    return report


"""
/api/v1/search/similar, /api/v1/agent/query, /api/v1/agent/run, /api/v1/agent/runs 및 /api/v1/agent/reports/{report_id} 엔드포인트를 제공하는 라우터를 구현하였다.
agent_mode="tool_calling" 및 message 입력을 지원하고 LLM Tool Calling 기반 도구 실행 및 응답 반환을 추가하였다.
"""
