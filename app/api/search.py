"""보고서 유사도 검색(API-07) REST API 라우터 모듈"""

# FastAPI 라우터 및 의존성 주입 도구 import
# - APIRouter : 검색 도메인 엔드포인트 등록
# - Depends : DB 세션 의존성 주입
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

# DB 세션 팩토리, 요청/응답 스키마 및 검색 서비스 import
# - get_db : 요청 단위 SQLAlchemy 세션 제공
# - SimilarSearchRequest, SimilarSearchResponse : 검색 요청·응답 스키마
# - search_service : 하이브리드 유사도 검색 비즈니스 로직
from app.db.session import get_db
from app.schemas.report import SimilarSearchRequest, SimilarSearchResponse
from app.services import search_service

# 검색 도메인 APIRouter 인스턴스 생성
router = APIRouter(tags=["search"])


# API-07: 키워드 + 시맨틱 유사도 검색 엔드포인트
@router.post("/api/v1/search/similar", response_model=SimilarSearchResponse)
def search_similar(
    payload: SimilarSearchRequest, db: Session = Depends(get_db)
) -> SimilarSearchResponse:
    """질의어와 유사한 보고서를 키워드 및 벡터 유사도로 검색하는 엔드포인트"""
    # 검색 서비스 호출 후 best_match 반환
    return search_service.search_similar_reports(db=db, payload=payload)


"""
POST /api/v1/search/similar 유사도 검색 엔드포인트를 구현하고 검색 서비스 계층과 연결하였다.
"""
