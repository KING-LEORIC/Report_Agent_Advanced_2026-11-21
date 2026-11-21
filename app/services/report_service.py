"""보고서 비즈니스 로직, 낙관적 동시성 제어, 임베딩 인덱싱, 프롬프트 버전 및 LLM 요약을 조율하는 서비스 모듈"""

# 타이핑 및 SQLAlchemy 세션 타입 import
# - Any : 상세 필드 직렬화 및 요약 결과 타입 힌트
# - Session : DB 트랜잭션 세션 타입
from typing import Any

from sqlalchemy.orm import Session

# 설정, 임베딩/LLM 클라이언트 및 리포지토리 함수 import
# - settings : 임베딩 모델명 조회
# - compute_overview_hash, embed_overview : 개요 해시 계산 및 384차원 벡터 생성
# - generate_report_summary : 보고서 요약 생성 클라이언트 함수
# - repo : 보고서/카테고리/임베딩/프롬프트 버전 DB 접근 함수군
from app.core.config import settings
from app.integrations.embedding_client import compute_overview_hash, embed_overview
from app.integrations.llm_client import generate_report_summary
from app.repositories import report_repository as repo
from app.schemas.report import (
    CategoryListResponse,
    PromptActiveVersionResponse,
    PromptVersionCreateResponse,
    PromptVersionItem,
    PromptVersionListResponse,
    ReindexResponse,
    ReportCreateRequest,
    ReportCreateResponse,
    ReportDetailResponse,
    ReportListItemResponse,
    ReportListResponse,
    ReportUpdateRequest,
    ReportUpdateResponse,
    SummarizeResponse,
    validate_details_for_category,
)


# 도메인 서비스 예외 클래스
# - 전역 에러 핸들러에서 표준 에러 응답(code, message, status)으로 변환
class ServiceError(Exception):
    """비즈니스 규칙 위반 또는 리소스 부재/충돌을 표현하는 서비스 예외 클래스"""

    def __init__(self, code: str, message: str, status: int = 400) -> None:
        """에러 코드, 사용자 메시지 및 HTTP 상태 코드를 초기화하는 생성자"""
        super().__init__(message)
        self.code = code
        self.message = message
        self.status = status


# 상세 ORM 객체로부터 공통(title, content, author, create_at, update_at) 및 고유 details 추출 함수
def _extract_detail_fields(
    report, detail_obj
) -> tuple[str, str, str, Any, Any, dict[str, Any]]:
    """상세 레코드에서 공통 필드와 카테고리별 고유 details 딕셔너리를 추출하는 헬퍼 함수"""
    # 상세 레코드가 없는 비정상 상태 방어
    if detail_obj is None:
        raise ServiceError(
            code="DETAIL_NOT_FOUND",
            message=f"보고서 {report.report_id}의 상세 데이터를 찾을 수 없습니다.",
            status=404,
        )

    code = report.category.code
    title = detail_obj.title
    content = detail_obj.content
    author = detail_obj.author
    created_at = detail_obj.create_at
    updated_at = detail_obj.update_at

    # 카테고리별 고유 필드 딕셔너리 구성
    if code == "EXPERIMENT":
        details: dict[str, Any] = {
            "experiment_date": detail_obj.experiment_date,
            "hypothesis": detail_obj.hypothesis,
            "result_summary": detail_obj.result_summary,
        }
    elif code == "DAILY_WORK":
        details = {
            "work_date": detail_obj.work_date,
            "progress": detail_obj.progress,
            "blockers": detail_obj.blockers,
        }
    elif code == "RESEARCH_PLAN":
        details = {
            "research_goal": detail_obj.research_goal,
            "methodology": detail_obj.methodology,
            "target_date": detail_obj.target_date,
        }
    elif code == "DATA_PROCESSING":
        details = {
            "dataset_name": detail_obj.dataset_name,
            "processing_steps": detail_obj.processing_steps,
            "quality_notes": detail_obj.quality_notes,
        }
    elif code == "PROMPT":
        details = {
            "purpose": detail_obj.purpose,
            "active_version_no": detail_obj.active_version_no,
        }
    elif code == "MEETING":
        details = {
            "meeting_at": detail_obj.meeting_at,
            "attendees": detail_obj.attendees,
            "decisions": detail_obj.decisions,
        }
    else:
        details = {}

    return title, content, author, created_at, updated_at, details


# API-01: 전체 보고서 카테고리 조회 서비스 함수
def get_categories(db: Session) -> CategoryListResponse:
    """등록된 보고서 카테고리 목록을 조회해 응답 스키마로 반환하는 함수"""
    # 카테고리 목록 조회
    categories = repo.list_categories(db)
    return CategoryListResponse(items=categories)


# API-02: 보고서 등록 및 임베딩 색인 서비스 함수
def create_report(db: Session, payload: ReportCreateRequest) -> ReportCreateResponse:
    """보고서를 저장하고 개요 임베딩을 생성하여 인덱싱 상태를 반영하는 함수"""
    # 카테고리 존재 여부 확인
    category = repo.get_category_by_code(db, payload.category_code)
    if category is None:
        raise ServiceError(
            code="CATEGORY_NOT_FOUND",
            message=f"유효하지 않은 카테고리 코드입니다: {payload.category_code}",
            status=400,
        )

    # 보고서 및 상세 테이블 레코드 생성
    report = repo.create_report_with_detail(
        db=db,
        category=category,
        title=payload.title,
        author=payload.author,
        content=payload.content,
        overview=payload.overview,
        details=payload.details,
    )

    # 개요 임베딩 생성 및 저장 시도 (실패 시 failed 상태 반영)
    try:
        vector = embed_overview(report.overview)
        overview_hash = compute_overview_hash(report.overview)
        repo.upsert_report_embedding(
            db=db,
            report=report,
            embedding=vector,
            model_name=settings.embedding_model_name,
            overview_hash=overview_hash,
        )
    except (ValueError, RuntimeError, OSError):
        report.index_status = "failed"
        db.commit()
        db.refresh(report)

    return ReportCreateResponse(
        report_id=int(report.report_id),
        category_code=category.code,
        title=payload.title,
        author=payload.author,
        revision=int(report.revision),
        index_status=report.index_status,
        embedding_model=settings.embedding_model_name,
    )


# API-03: 보고서 단건 상세 조회 서비스 함수
def get_report_detail(db: Session, report_id: int) -> ReportDetailResponse:
    """report_id로 보고서 공통 정보와 카테고리 상세 정보를 조회해 반환하는 함수"""
    # 보고서 조회
    report = repo.get_report_by_id(db, report_id)
    if report is None:
        raise ServiceError(
            code="REPORT_NOT_FOUND",
            message=f"보고서(id={report_id})를 찾을 수 없습니다.",
            status=404,
        )

    detail_obj = repo.get_detail_record(db, report)
    title, content, author, created_at, updated_at, details = _extract_detail_fields(
        report, detail_obj
    )

    return ReportDetailResponse(
        report_id=int(report.report_id),
        category_code=report.category.code,
        title=title,
        content=content,
        author=author,
        overview=report.overview,
        details=details,
        revision=int(report.revision),
        index_status=report.index_status,
        created_at=created_at,
        updated_at=updated_at,
    )


# API-04: 보고서 목록 조회 서비스 함수
def get_reports(
    db: Session, category_code: str | None = None, limit: int = 20, offset: int = 0
) -> ReportListResponse:
    """카테고리 필터 및 페이지네이션이 적용된 보고서 목록 응답을 생성하는 함수"""
    # 목록 및 전체 개수 조회
    reports, total = repo.list_reports(
        db=db, category_code=category_code, limit=limit, offset=offset
    )
    items = [
        ReportListItemResponse(
            report_id=int(r.report_id),
            category_code=r.category.code,
            title=(
                repo.get_detail_record(db, r).title
                if repo.get_detail_record(db, r)
                else ""
            ),
            revision=int(r.revision),
        )
        for r in reports
    ]
    return ReportListResponse(items=items, total=total, limit=limit, offset=offset)


# API-05: 보고서 전체 수정 서비스 함수
def update_report(
    db: Session, report_id: int, payload: ReportUpdateRequest
) -> ReportUpdateResponse:
    """낙관적 리비전 검증 후 보고서를 수정하고 필요 시 임베딩을 갱신하는 함수"""
    # 기존 보고서 확인
    report = repo.get_report_by_id(db, report_id)
    if report is None:
        raise ServiceError(
            code="REPORT_NOT_FOUND",
            message=f"보고서(id={report_id})를 찾을 수 없습니다.",
            status=404,
        )

    # expected_revision 낙관적 동시성 검사
    if (
        payload.expected_revision is not None
        and int(report.revision) != payload.expected_revision
    ):
        raise ServiceError(
            code="REVISION_CONFLICT",
            message=(
                f"리비전 충돌이 발생했습니다: 현재 revision={report.revision}, "
                f"요청 expected_revision={payload.expected_revision}"
            ),
            status=409,
        )

    # 카테고리별 상세 필드 검증
    code = report.category.code
    try:
        normalized_details = validate_details_for_category(code, payload.details)
    except ValueError as exc:
        raise ServiceError(
            code="INVALID_DETAILS", message=str(exc), status=422
        ) from exc

    if code == "PROMPT" and payload.content != normalized_details["prompt_text"]:
        raise ServiceError(
            code="INVALID_PROMPT_CONTENT",
            message="PROMPT 보고서의 content는 details.prompt_text와 같아야 합니다.",
            status=422,
        )

    # 개요 변경 여부 판별
    old_hash = compute_overview_hash(report.overview)
    new_hash = compute_overview_hash(payload.overview)
    overview_changed = old_hash != new_hash

    updated = repo.update_report_with_detail(
        db=db,
        report=report,
        title=payload.title,
        author=payload.author,
        content=payload.content,
        overview=payload.overview,
        details=normalized_details,
        overview_changed=overview_changed,
    )

    embedding_updated = False
    if overview_changed:
        try:
            vector = embed_overview(updated.overview)
            repo.upsert_report_embedding(
                db=db,
                report=updated,
                embedding=vector,
                model_name=settings.embedding_model_name,
                overview_hash=new_hash,
            )
            embedding_updated = True
        except (ValueError, RuntimeError, OSError):
            updated.index_status = "failed"
            db.commit()
            db.refresh(updated)

    return ReportUpdateResponse(
        report_id=int(updated.report_id),
        revision=int(updated.revision),
        index_status=updated.index_status,
        embedding_updated=embedding_updated,
    )


# API-06: 보고서 삭제 서비스 함수
def delete_report(db: Session, report_id: int) -> None:
    """report_id로 보고서를 조회한 뒤 삭제하는 함수"""
    # 대상 보고서 존재 확인
    report = repo.get_report_by_id(db, report_id)
    if report is None:
        raise ServiceError(
            code="REPORT_NOT_FOUND",
            message=f"보고서(id={report_id})를 찾을 수 없습니다.",
            status=404,
        )
    repo.delete_report(db, report)


# API-08: 보고서 요약 생성 서비스 함수
def summarize_report(
    db: Session, report_id: int, style: str = "brief", max_sentences: int = 3
) -> SummarizeResponse:
    """보고서 본문과 개요를 기반으로 LLM 요약을 생성해 반환하는 함수"""
    # 대상 보고서 및 상세 조회
    report = repo.get_report_by_id(db, report_id)
    if report is None:
        raise ServiceError(
            code="REPORT_NOT_FOUND",
            message=f"보고서(id={report_id})를 찾을 수 없습니다.",
            status=404,
        )
    detail_obj = repo.get_detail_record(db, report)
    title, content, _, _, _, _ = _extract_detail_fields(report, detail_obj)

    summary_result = generate_report_summary(
        title=title,
        category_code=report.category.code,
        content=content,
        overview=report.overview,
        style=style,
        max_sentences=max_sentences,
    )

    return SummarizeResponse(
        report_id=int(report.report_id),
        source_revision=int(report.revision),
        summary=summary_result,
        model=settings.llm_model,
        status="completed",
    )


# API-10: 프롬프트 새 버전 추가 서비스 함수
def create_prompt_version(
    db: Session, report_id: int, prompt_text: str
) -> PromptVersionCreateResponse:
    """PROMPT 분류 보고서에 새 프롬프트 버전을 추가하는 함수"""
    # 보고서 및 PROMPT 상세 확인
    report = repo.get_report_by_id(db, report_id)
    if report is None:
        raise ServiceError(
            code="REPORT_NOT_FOUND",
            message=f"보고서(id={report_id})를 찾을 수 없습니다.",
            status=404,
        )
    if report.category.code != "PROMPT":
        raise ServiceError(
            code="INVALID_CATEGORY",
            message="프롬프트 버전 관리는 PROMPT 카테고리 보고서만 지원합니다.",
            status=400,
        )
    prompt_report = repo.get_detail_record(db, report)
    if prompt_report is None:
        raise ServiceError(
            code="DETAIL_NOT_FOUND",
            message="프롬프트 상세 레코드를 찾을 수 없습니다.",
            status=404,
        )

    created_ver = repo.add_prompt_version(
        db=db,
        report=report,
        prompt_report=prompt_report,
        prompt_text=prompt_text,
        set_active=False,
    )
    return PromptVersionCreateResponse(
        version_no=int(created_ver.version_no),
        active=(int(prompt_report.active_version_no) == int(created_ver.version_no)),
    )


# API-11: 프롬프트 버전 목록 조회 서비스 함수
def get_prompt_versions(db: Session, report_id: int) -> PromptVersionListResponse:
    """PROMPT 보고서의 전체 버전 이력과 현재 활성 버전 번호를 반환하는 함수"""
    # 보고서 및 버전 이력 조회
    report = repo.get_report_by_id(db, report_id)
    if report is None:
        raise ServiceError(
            code="REPORT_NOT_FOUND",
            message=f"보고서(id={report_id})를 찾을 수 없습니다.",
            status=404,
        )
    if report.category.code != "PROMPT":
        raise ServiceError(
            code="INVALID_CATEGORY",
            message="프롬프트 버전 관리는 PROMPT 카테고리 보고서만 지원합니다.",
            status=400,
        )

    prompt_report, versions = repo.list_prompt_versions(db, report_id)
    if prompt_report is None:
        raise ServiceError(
            code="DETAIL_NOT_FOUND",
            message="프롬프트 상세 레코드를 찾을 수 없습니다.",
            status=404,
        )

    items = [
        PromptVersionItem(version_no=int(v.version_no), created_at=v.created_at)
        for v in versions
    ]
    return PromptVersionListResponse(
        items=items, active_version_no=int(prompt_report.active_version_no)
    )


# API-12: 프롬프트 활성 버전 전환 서비스 함수
def activate_prompt_version(
    db: Session, report_id: int, version_no: int
) -> PromptActiveVersionResponse:
    """PROMPT 보고서의 활성 버전을 지정 버전으로 전환하고 revision을 증가시키는 함수"""
    # 보고서 및 버전 목록 조회
    report = repo.get_report_by_id(db, report_id)
    if report is None:
        raise ServiceError(
            code="REPORT_NOT_FOUND",
            message=f"보고서(id={report_id})를 찾을 수 없습니다.",
            status=404,
        )
    if report.category.code != "PROMPT":
        raise ServiceError(
            code="INVALID_CATEGORY",
            message="프롬프트 버전 관리는 PROMPT 카테고리 보고서만 지원합니다.",
            status=400,
        )

    prompt_report, versions = repo.list_prompt_versions(db, report_id)
    if prompt_report is None:
        raise ServiceError(
            code="DETAIL_NOT_FOUND",
            message="프롬프트 상세 레코드를 찾을 수 없습니다.",
            status=404,
        )

    target = next((v for v in versions if int(v.version_no) == version_no), None)
    if target is None:
        raise ServiceError(
            code="VERSION_NOT_FOUND",
            message=f"버전 {version_no} 이력을 찾을 수 없습니다.",
            status=404,
        )

    updated_prompt = repo.set_active_prompt_version(
        db=db, report=report, prompt_report=prompt_report, target_version=target
    )
    return PromptActiveVersionResponse(
        active_version_no=int(updated_prompt.active_version_no),
        revision=int(report.revision),
        index_status=report.index_status,
    )


# API-13: 보고서 임베딩 재색인 서비스 함수
def reindex_report(db: Session, report_id: int, force: bool = False) -> ReindexResponse:
    """보고서 개요의 해시/리비전 변경 여부 또는 force 옵션에 따라 임베딩을 재색인하는 함수"""
    # 대상 보고서 조회
    report = repo.get_report_by_id(db, report_id)
    if report is None:
        raise ServiceError(
            code="REPORT_NOT_FOUND",
            message=f"보고서(id={report_id})를 찾을 수 없습니다.",
            status=404,
        )

    current_hash = compute_overview_hash(report.overview)
    existing_emb = report.embedding_record
    already_synced = (
        not force
        and report.index_status == "ready"
        and existing_emb is not None
        and existing_emb.overview_hash == current_hash
        and int(existing_emb.indexed_revision) == int(report.revision)
    )

    if already_synced:
        return ReindexResponse(
            report_id=int(report.report_id),
            index_status=report.index_status,
            indexed_revision=int(existing_emb.indexed_revision),
            embedding_updated=False,
        )

    vector = embed_overview(report.overview)
    saved_emb = repo.upsert_report_embedding(
        db=db,
        report=report,
        embedding=vector,
        model_name=settings.embedding_model_name,
        overview_hash=current_hash,
    )
    return ReindexResponse(
        report_id=int(report.report_id),
        index_status=report.index_status,
        indexed_revision=int(saved_emb.indexed_revision),
        embedding_updated=True,
    )


"""
보고서 CRUD, 낙관적 리비전 충돌 검증, 개요 임베딩 동기화, 프롬프트 버전 이력·활성 전환, 재색인 및 LLM 요약 서비스를 구현하였다.
도메인 예외를 ServiceError로 통일해 라우터 및 전역 에러 핸들러와 일관되게 연동되도록 구성하였다.
"""
