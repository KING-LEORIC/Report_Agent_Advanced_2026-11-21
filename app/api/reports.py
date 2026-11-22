"""보고서 카테고리 조회, 보고서 CRUD, LLM 요약, 프롬프트 버전 관리 및 재색인 REST API 라우터 모듈"""

# FastAPI 라우터, 쿼리/경로 파라미터 및 HTTP 상태 코드 import
# - APIRouter : 보고서 도메인 엔드포인트 그룹핑
# - Depends : DB 세션 의존성 주입
# - Query : 목록/요약/재색인 쿼리 파라미터 검증
# - status : 201 Created, 204 No Content 등 상태 코드 상수
from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.orm import Session

# DB 세션 팩토리 및 보고서 서비스 계층 import
# - get_db : 요청 단위 SQLAlchemy 세션 제공
# - report_service : 도메인 비즈니스 로직 및 예외(ServiceError) 정의
from app.db.session import get_db
from app.schemas.report import (
    CategoryListResponse,
    PromptActiveVersionRequest,
    PromptActiveVersionResponse,
    PromptVersionCreateRequest,
    PromptVersionCreateResponse,
    PromptVersionListResponse,
    ReindexResponse,
    ReportCreateRequest,
    ReportCreateResponse,
    ReportDetailResponse,
    ReportListResponse,
    ReportUpdateRequest,
    ReportUpdateResponse,
    SummarizeResponse,
)
from app.services import report_service

# 보고서 도메인 APIRouter 인스턴스 생성
# - /api/v1 접두사는 상위 main.py 또는 라우터 등록 시 부여
router = APIRouter(tags=["reports"])


# API-01: 전체 보고서 카테고리 조회 엔드포인트
# - 등록된 6종 카테고리 목록 반환
@router.get("/api/v1/categories", response_model=CategoryListResponse)
def get_categories(db: Session = Depends(get_db)) -> CategoryListResponse:
    """등록된 보고서 카테고리 목록(6종)을 조회하는 엔드포인트"""
    # 서비스 계층 호출 후 카테고리 목록 반환
    return report_service.get_categories(db=db)


# API-02: 보고서 등록 엔드포인트
# - 카테고리별 상세 테이블 저장 및 개요 임베딩 색인 수행
@router.post(
    "/api/v1/reports",
    response_model=ReportCreateResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_report(
    payload: ReportCreateRequest, db: Session = Depends(get_db)
) -> ReportCreateResponse:
    """신규 보고서를 등록하고 개요 임베딩 색인을 시도하는 엔드포인트"""
    # 보고서 생성 및 임베딩 동기화 위임
    return report_service.create_report(db=db, payload=payload)


# API-04: 보고서 목록 조회 엔드포인트
# - category_code 필터 및 limit/offset 페이지네이션 지원
@router.get("/api/v1/reports", response_model=ReportListResponse)
def get_reports(
    category_code: str | None = Query(default=None),
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
) -> ReportListResponse:
    """조건에 맞는 보고서 목록과 전체 개수를 조회하는 엔드포인트"""
    # 필터 및 페이징 파라미터 전달
    return report_service.get_reports(
        db=db, category_code=category_code, limit=limit, offset=offset
    )


# API-03: 보고서 단건 상세 조회 엔드포인트
@router.get("/api/v1/reports/{report_id}", response_model=ReportDetailResponse)
def get_report_detail(
    report_id: int, db: Session = Depends(get_db)
) -> ReportDetailResponse:
    """report_id로 보고서 공통 정보와 카테고리별 상세 정보를 조회하는 엔드포인트"""
    # 단건 상세 조회 위임
    return report_service.get_report_detail(db=db, report_id=report_id)


# API-05: 보고서 전체 수정 엔드포인트
# - expected_revision 낙관적 동시성 검사 및 개요 변경 시 임베딩 갱신
@router.put("/api/v1/reports/{report_id}", response_model=ReportUpdateResponse)
def update_report(
    report_id: int, payload: ReportUpdateRequest, db: Session = Depends(get_db)
) -> ReportUpdateResponse:
    """보고서 메타/본문/상세를 수정하고 리비전을 증가시키는 엔드포인트"""
    # 수정 로직 실행
    return report_service.update_report(db=db, report_id=report_id, payload=payload)


# API-06: 보고서 삭제 엔드포인트
@router.delete("/api/v1/reports/{report_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_report(report_id: int, db: Session = Depends(get_db)) -> None:
    """report_id에 해당하는 보고서를 삭제하는 엔드포인트"""
    # 삭제 로직 실행 (성공 시 204 No Content)
    report_service.delete_report(db=db, report_id=report_id)


# API-08: 보고서 LLM 요약 생성 엔드포인트
@router.post("/api/v1/reports/{report_id}/summarize", response_model=SummarizeResponse)
def summarize_report(
    report_id: int,
    style: str = Query(default="brief"),
    max_sentences: int = Query(default=3, ge=1, le=10),
    db: Session = Depends(get_db),
) -> SummarizeResponse:
    """지정 보고서의 brief 또는 structured 요약을 생성하는 엔드포인트"""
    # 요약 생성 서비스 호출
    return report_service.summarize_report(
        db=db, report_id=report_id, style=style, max_sentences=max_sentences
    )


# API-10: 프롬프트 새 버전 추가 엔드포인트 (/prompts/{report_id}/versions 및 /reports/{report_id}/prompt-versions 지원)
@router.post(
    "/api/v1/prompts/{report_id}/versions",
    response_model=PromptVersionCreateResponse,
    status_code=status.HTTP_201_CREATED,
)
@router.post(
    "/api/v1/reports/{report_id}/prompt-versions",
    response_model=PromptVersionCreateResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_prompt_version(
    report_id: int, payload: PromptVersionCreateRequest, db: Session = Depends(get_db)
) -> PromptVersionCreateResponse:
    """PROMPT 보고서에 새 프롬프트 버전을 등록하는 엔드포인트"""
    # 새 버전 생성 호출
    return report_service.create_prompt_version(
        db=db, report_id=report_id, prompt_text=payload.prompt_text
    )


# API-11: 프롬프트 버전 이력 조회 엔드포인트 (/prompts/{report_id}/versions 및 /reports/{report_id}/prompt-versions 지원)
@router.get(
    "/api/v1/prompts/{report_id}/versions", response_model=PromptVersionListResponse
)
@router.get(
    "/api/v1/reports/{report_id}/prompt-versions",
    response_model=PromptVersionListResponse,
)
def get_prompt_versions(
    report_id: int, db: Session = Depends(get_db)
) -> PromptVersionListResponse:
    """PROMPT 보고서의 버전 이력 및 활성 버전 번호를 조회하는 엔드포인트"""
    # 버전 목록 조회 호출
    return report_service.get_prompt_versions(db=db, report_id=report_id)


# API-12: 프롬프트 활성 버전 전환 엔드포인트
@router.post(
    "/api/v1/reports/{report_id}/prompt-versions/active",
    response_model=PromptActiveVersionResponse,
)
def activate_prompt_version(
    report_id: int, payload: PromptActiveVersionRequest, db: Session = Depends(get_db)
) -> PromptActiveVersionResponse:
    """PROMPT 보고서의 활성 버전을 지정 버전으로 전환하는 엔드포인트"""
    # 활성 버전 전환 호출
    return report_service.activate_prompt_version(
        db=db, report_id=report_id, version_no=payload.version_no
    )


# API-13: 보고서 임베딩 재색인 엔드포인트
@router.post("/api/v1/reports/{report_id}/reindex", response_model=ReindexResponse)
def reindex_report(
    report_id: int, force: bool = Query(default=False), db: Session = Depends(get_db)
) -> ReindexResponse:
    """보고서 개요 임베딩 재색인을 수행하는 엔드포인트"""
    # 재색인 서비스 호출
    return report_service.reindex_report(db=db, report_id=report_id, force=force)


"""
카테고리 조회, 보고서 CRUD, 요약 생성, 프롬프트 버전 관리 및 임베딩 재색인 REST API 라우터를 구현하였다.
/api/v1/prompts/{report_id}/versions 경로에 GET 버전 이력 조회 라우트를 추가해 405 오류를 해소하였다.
"""
