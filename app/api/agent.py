"""유사도 검색, 에이전트 질의 및 보고서 조회 FastAPI 라우터를 정의하는 API 모듈"""

from __future__ import annotations

from collections.abc import Generator

# FastAPI 라우터·의존성·예외 처리 및 Pydantic 스키마 정의 모듈 import
# - APIRouter : 엔드포인트 그룹 라우터 생성
# - Depends, HTTPException, status : DB 세션 주입 및 HTTP 상태 코드 예외 처리
# - BaseModel, Field : 요청 바디 유효성 검사 스키마 정의
# - Session : SQLAlchemy 세션 타입
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.services.agent_service import AgentService

# 에이전트 및 검색 엔드포인트용 라우터 인스턴스 생성
router = APIRouter(prefix="/api/v1", tags=["Agent & Search"])


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


# 에이전트 질의 요청 스키마 클래스
# - 질의 문자열, 카테고리 필터 및 상위 반환 문서 개수(top_k) 정의
class AgentQueryRequest(BaseModel):
    """에이전트 질의 응답 POST 요청 본문 스키마"""

    query: str = Field(..., min_length=1)
    category_code: str | None = None
    top_k: int = Field(default=5, ge=1, le=50)


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
/api/v1/search/similar, /api/v1/agent/query 및 /api/v1/agent/reports/{report_id} 엔드포인트를 제공하는 라우터를 구현하였다.
Pydantic 요청 스키마 검증과 DB 세션 의존성 주입을 통해 AgentService 로직과 연결하였다.
"""
