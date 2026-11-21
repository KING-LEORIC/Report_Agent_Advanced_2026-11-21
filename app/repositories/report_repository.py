"""보고서 도메인 10개 테이블에 대한 DB CRUD, 목록 조회, 유사도 검색 및 버전 관리 리포지토리 모듈"""

# 해시 계산, 날짜/시간 및 SQLAlchemy 쿼리 구성 요소 import
# - hashlib : 개요 변경 여부 판별용 SHA-256 해시 계산
# - datetime, timezone : 타임스탬프 갱신 시각 생성
# - func, select, text : 집계, 조회, pgvector 거리 연산 표현식
# - Session : SQLAlchemy 동기 세션 타입
import hashlib
from datetime import UTC, datetime

from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

# 보고서 도메인 ORM 모델 import
# - 10개 물리 테이블에 대응하는 모델 클래스
from app.models.report import (
    DailyWorkReport,
    DataProcessingReport,
    ExperimentReport,
    MeetingMinute,
    PromptReport,
    PromptVersion,
    Report,
    ReportCategory,
    ReportEmbedding,
    ResearchPlan,
)

# 고정 6개 보고서 카테고리 초기 시드 정의 상수
# - 명세서 기준 6종(EXPERIMENT, DAILY_WORK, RESEARCH_PLAN, DATA_PROCESSING, PROMPT, MEETING)
DEFAULT_CATEGORIES: tuple[tuple[int, str, str, str], ...] = (
    (1, "EXPERIMENT", "실험 결과 보고서", "실험 수행 일자, 가설, 결과 요약 기록"),
    (2, "DAILY_WORK", "일일 업무 보고서", "일자별 업무 진행 사항 및 이슈 기록"),
    (3, "RESEARCH_PLAN", "연구 계획서", "연구 목표, 연구 방법 및 목표일 기록"),
    (
        4,
        "DATA_PROCESSING",
        "데이터 처리 보고서",
        "데이터셋, 전처리/가공 절차 및 품질 비고 기록",
    ),
    (5, "PROMPT", "프롬프트 보고서", "프롬프트 목적, 활성 버전 및 버전 이력 관리"),
    (6, "MEETING", "회의록", "회의 일시, 참석자 및 주요 결정 사항 기록"),
)


# 6개 기본 카테고리가 비어 있을 경우 초기 적재하는 헬퍼 함수
# - 멱등성을 보장하여 중복 삽입 없이 6건 상태 유지
def ensure_default_categories(db: Session) -> list[ReportCategory]:
    """report_categories 테이블에 6종 기본 카테고리가 없으면 시드 데이터를 생성하는 함수"""
    # 기존 카테고리 조회
    existing = list(
        db.scalars(select(ReportCategory).order_by(ReportCategory.category_id)).all()
    )
    existing_codes = {item.code for item in existing}
    added = False

    # 누락된 기본 카테고리만 추가
    for cat_id, code, name, description in DEFAULT_CATEGORIES:
        if code not in existing_codes:
            db.add(
                ReportCategory(
                    category_id=cat_id, code=code, name=name, description=description
                )
            )
            added = True

    if added:
        db.commit()
        existing = list(
            db.scalars(
                select(ReportCategory).order_by(ReportCategory.category_id)
            ).all()
        )

    return existing


# 전체 카테고리 목록 조회 함수
# - category_id 오름차순 반환
def list_categories(db: Session) -> list[ReportCategory]:
    """등록된 보고서 카테고리 목록을 조회하는 함수"""
    # 기본 6종 보장 후 조회
    ensure_default_categories(db)
    return list(
        db.scalars(select(ReportCategory).order_by(ReportCategory.category_id)).all()
    )


# 카테고리 코드로 단일 카테고리 조회 함수
def get_category_by_code(db: Session, category_code: str) -> ReportCategory | None:
    """카테고리 코드(예: EXPERIMENT)로 ReportCategory 레코드를 조회하는 함수"""
    # 대문자 정규화 후 단건 조회
    normalized_code = category_code.strip().upper()
    stmt = select(ReportCategory).where(ReportCategory.code == normalized_code)
    return db.scalar(stmt)


# 보고서 ID로 공통 Report 레코드 조회 함수
def get_report_by_id(db: Session, report_id: int) -> Report | None:
    """report_id로 공통 reports 레코드를 조회하는 함수"""
    # 기본키 단건 조회
    return db.get(Report, report_id)


# 카테고리별 상세 레코드 조회 헬퍼 함수
# - 카테고리 코드에 따라 1:1 상세 테이블 레코드 반환
def get_detail_record(db: Session, report: Report):
    """Report 인스턴스의 카테고리에 대응하는 상세 테이블 레코드를 조회하는 함수"""
    # 카테고리 코드 확인
    code = report.category.code if report.category else None
    if code == "EXPERIMENT":
        return db.get(ExperimentReport, report.report_id)
    if code == "DAILY_WORK":
        return db.get(DailyWorkReport, report.report_id)
    if code == "RESEARCH_PLAN":
        return db.get(ResearchPlan, report.report_id)
    if code == "DATA_PROCESSING":
        return db.get(DataProcessingReport, report.report_id)
    if code == "PROMPT":
        return db.get(PromptReport, report.report_id)
    if code == "MEETING":
        return db.get(MeetingMinute, report.report_id)
    return None


# 신규 보고서 및 카테고리별 상세·프롬프트 초기 버전 생성 함수
def create_report_with_detail(
    db: Session,
    category: ReportCategory,
    title: str,
    author: str,
    content: str,
    overview: str,
    details: dict,
) -> Report:
    """공통 reports 레코드와 카테고리별 상세 테이블 레코드를 원자적으로 생성하는 함수"""
    # 공통 reports 엔티티 생성
    report = Report(
        category_id=category.category_id,
        overview=overview,
        index_status="pending",
        revision=1,
    )
    db.add(report)
    db.flush()

    now = datetime.now(UTC)
    code = category.code

    # 카테고리 코드별 상세 테이블 레코드 생성
    if code == "EXPERIMENT":
        detail_obj = ExperimentReport(
            report_id=report.report_id,
            title=title,
            content=content,
            author=author,
            create_at=now,
            update_at=now,
            experiment_date=details["experiment_date"],
            hypothesis=details["hypothesis"],
            result_summary=details["result_summary"],
        )
        db.add(detail_obj)
    elif code == "DAILY_WORK":
        detail_obj = DailyWorkReport(
            report_id=report.report_id,
            title=title,
            content=content,
            author=author,
            create_at=now,
            update_at=now,
            work_date=details["work_date"],
            progress=details["progress"],
            blockers=details.get("blockers", ""),
        )
        db.add(detail_obj)
    elif code == "RESEARCH_PLAN":
        detail_obj = ResearchPlan(
            report_id=report.report_id,
            title=title,
            content=content,
            author=author,
            create_at=now,
            update_at=now,
            research_goal=details["research_goal"],
            methodology=details["methodology"],
            target_date=details["target_date"],
        )
        db.add(detail_obj)
    elif code == "DATA_PROCESSING":
        detail_obj = DataProcessingReport(
            report_id=report.report_id,
            title=title,
            content=content,
            author=author,
            create_at=now,
            update_at=now,
            dataset_name=details["dataset_name"],
            processing_steps=details["processing_steps"],
            quality_notes=details.get("quality_notes", ""),
        )
        db.add(detail_obj)
    elif code == "PROMPT":
        detail_obj = PromptReport(
            report_id=report.report_id,
            title=title,
            content=content,
            author=author,
            create_at=now,
            update_at=now,
            purpose=details["purpose"],
            active_version_no=1,
        )
        db.add(detail_obj)
        db.flush()
        # 1번 프롬프트 버전 이력 등록
        version_obj = PromptVersion(
            report_id=report.report_id,
            version_no=1,
            prompt_text=details["prompt_text"],
            created_at=now,
        )
        db.add(version_obj)
    elif code == "MEETING":
        detail_obj = MeetingMinute(
            report_id=report.report_id,
            title=title,
            content=content,
            author=author,
            create_at=now,
            update_at=now,
            meeting_at=details["meeting_at"],
            attendees=details["attendees"],
            decisions=details["decisions"],
        )
        db.add(detail_obj)

    db.commit()
    db.refresh(report)
    return report


# 보고서 목록 조회 및 전체 건수 반환 함수
def list_reports(
    db: Session, category_code: str | None = None, limit: int = 20, offset: int = 0
) -> tuple[list[Report], int]:
    """카테고리 필터와 페이지네이션을 적용해 보고서 목록과 총 개수를 조회하는 함수"""
    # 기본 조회 및 카운트 쿼리 구성
    stmt = select(Report).join(
        ReportCategory, Report.category_id == ReportCategory.category_id
    )
    count_stmt = select(func.count(Report.report_id)).join(
        ReportCategory, Report.category_id == ReportCategory.category_id
    )

    if category_code:
        normalized = category_code.strip().upper()
        stmt = stmt.where(ReportCategory.code == normalized)
        count_stmt = count_stmt.where(ReportCategory.code == normalized)

    total = int(db.scalar(count_stmt) or 0)
    rows = list(
        db.scalars(
            stmt.order_by(Report.report_id.desc()).limit(limit).offset(offset)
        ).all()
    )
    return rows, total


# 보고서 전체 수정 및 revision 증가 처리 함수
def update_report_with_detail(
    db: Session,
    report: Report,
    title: str,
    author: str,
    content: str,
    overview: str,
    details: dict,
    overview_changed: bool,
) -> Report:
    """보고서 공통 메타/개요와 상세 테이블 필드를 갱신하고 revision을 증가시키는 함수"""
    # 공통 reports 필드 갱신
    report.overview = overview
    report.revision = int(report.revision) + 1
    if overview_changed:
        report.index_status = "pending"

    now = datetime.now(UTC)
    detail_obj = get_detail_record(db, report)
    code = report.category.code

    # 공통 상세 필드(title, content, author, update_at) 및 고유 필드 갱신
    if detail_obj is not None:
        detail_obj.title = title
        detail_obj.content = content
        detail_obj.author = author
        detail_obj.update_at = now

        if code == "EXPERIMENT":
            detail_obj.experiment_date = details["experiment_date"]
            detail_obj.hypothesis = details["hypothesis"]
            detail_obj.result_summary = details["result_summary"]
        elif code == "DAILY_WORK":
            detail_obj.work_date = details["work_date"]
            detail_obj.progress = details["progress"]
            detail_obj.blockers = details.get("blockers", "")
        elif code == "RESEARCH_PLAN":
            detail_obj.research_goal = details["research_goal"]
            detail_obj.methodology = details["methodology"]
            detail_obj.target_date = details["target_date"]
        elif code == "DATA_PROCESSING":
            detail_obj.dataset_name = details["dataset_name"]
            detail_obj.processing_steps = details["processing_steps"]
            detail_obj.quality_notes = details.get("quality_notes", "")
        elif code == "PROMPT":
            detail_obj.purpose = details["purpose"]
            if "prompt_text" in details:
                next_ver = int(detail_obj.active_version_no) + 1
                db.add(
                    PromptVersion(
                        report_id=report.report_id,
                        version_no=next_ver,
                        prompt_text=details["prompt_text"],
                        created_at=now,
                    )
                )
                detail_obj.active_version_no = next_ver
        elif code == "MEETING":
            detail_obj.meeting_at = details["meeting_at"]
            detail_obj.attendees = details["attendees"]
            detail_obj.decisions = details["decisions"]

    db.commit()
    db.refresh(report)
    return report


# 보고서 삭제 함수
def delete_report(db: Session, report: Report) -> None:
    """보고서 레코드를 삭제하는 함수"""
    # CASCADE 설정에 따라 연관 상세/임베딩/버전 레코드 함께 정리
    db.delete(report)
    db.commit()


# 보고서 개요 임베딩 업서트 및 인덱싱 상태 ready 갱신 함수
def upsert_report_embedding(
    db: Session,
    report: Report,
    embedding: list[float],
    model_name: str,
    overview_hash: str,
) -> ReportEmbedding:
    """report_embeddings 레코드를 삽입 또는 갱신하고 보고서 index_status를 ready로 변경하는 함수"""
    # 기존 임베딩 레코드 조회
    existing = db.get(ReportEmbedding, report.report_id)
    now = datetime.now(UTC)

    if existing is None:
        existing = ReportEmbedding(
            report_id=report.report_id,
            embedding=embedding,
            model_name=model_name,
            overview_hash=overview_hash,
            indexed_revision=int(report.revision),
            indexed_at=now,
        )
        db.add(existing)
    else:
        existing.embedding = embedding
        existing.model_name = model_name
        existing.overview_hash = overview_hash
        existing.indexed_revision = int(report.revision)
        existing.indexed_at = now

    report.index_status = "ready"
    db.commit()
    db.refresh(existing)
    return existing


# 프롬프트 버전 이력 조회 함수
def list_prompt_versions(
    db: Session, report_id: int
) -> tuple[PromptReport | None, list[PromptVersion]]:
    """PROMPT 보고서의 상세 정보와 버전 이력 목록(version_no 오름차순)을 조회하는 함수"""
    # 프롬프트 상세 조회
    prompt_report = db.get(PromptReport, report_id)
    if prompt_report is None:
        return None, []
    versions = list(
        db.scalars(
            select(PromptVersion)
            .where(PromptVersion.report_id == report_id)
            .order_by(PromptVersion.version_no.asc())
        ).all()
    )
    return prompt_report, versions


# 새 프롬프트 버전 추가 함수
def add_prompt_version(
    db: Session,
    report: Report,
    prompt_report: PromptReport,
    prompt_text: str,
    set_active: bool = False,
) -> PromptVersion:
    """PROMPT 보고서에 새 버전(최대 version_no + 1)을 추가하고 필요 시 활성 버전을 전환하는 함수"""
    # 현재 최대 version_no 조회
    max_ver = db.scalar(
        select(func.max(PromptVersion.version_no)).where(
            PromptVersion.report_id == report.report_id
        )
    )
    next_version_no = int(max_ver or 0) + 1
    now = datetime.now(UTC)

    new_version = PromptVersion(
        report_id=report.report_id,
        version_no=next_version_no,
        prompt_text=prompt_text,
        created_at=now,
    )
    db.add(new_version)

    prompt_report.content = prompt_text
    prompt_report.update_at = now
    if set_active:
        prompt_report.active_version_no = next_version_no
        report.revision = int(report.revision) + 1

    db.commit()
    db.refresh(new_version)
    return new_version


# 프롬프트 활성 버전 전환 함수
def set_active_prompt_version(
    db: Session,
    report: Report,
    prompt_report: PromptReport,
    target_version: PromptVersion,
) -> PromptReport:
    """PROMPT 보고서의 활성 버전을 지정 버전으로 변경하고 content/revision을 동기화하는 함수"""
    # 활성 버전 번호 및 본문 반영
    now = datetime.now(UTC)
    prompt_report.active_version_no = int(target_version.version_no)
    prompt_report.content = target_version.prompt_text
    prompt_report.update_at = now
    report.revision = int(report.revision) + 1

    db.commit()
    db.refresh(prompt_report)
    return prompt_report


# 키워드 일치 보고서 조회 함수 (ILIKE 기반)
def search_reports_by_keyword(
    db: Session, query: str, category_code: str | None = None, limit: int = 20
) -> list[int]:
    """overview 또는 제목/본문 텍스트에 키워드가 포함된 report_id 목록을 조회하는 함수"""
    # 검색 패턴 생성
    pattern = f"%{query.strip()}%"
    stmt = (
        select(Report.report_id)
        .join(ReportCategory, Report.category_id == ReportCategory.category_id)
        .where(Report.overview.ilike(pattern))
    )
    if category_code:
        stmt = stmt.where(ReportCategory.code == category_code.strip().upper())

    rows = db.scalars(stmt.order_by(Report.report_id.desc()).limit(limit)).all()
    return [int(r) for r in rows]


# pgvector 코사인 유사도 기반 시맨틱 검색 함수
def search_reports_by_vector(
    db: Session,
    query_vector: list[float],
    category_code: str | None = None,
    limit: int = 20,
) -> list[tuple[int, float]]:
    """pgvector 코사인 거리(<=>)를 이용해 (report_id, cosine_similarity) 목록을 반환하는 함수"""
    # pgvector 리터럴 문자열 생성
    vector_literal = "[" + ",".join(f"{float(v):.8f}" for v in query_vector) + "]"
    params: dict[str, object] = {"vec": vector_literal, "limit": int(limit)}
    category_filter = ""
    if category_code:
        category_filter = "AND rc.code = :category_code"
        params["category_code"] = category_code.strip().upper()

    sql = text(
        f"""
        SELECT
            re.report_id,
            1.0 - (re.embedding <=> CAST(:vec AS vector)) AS cosine_similarity
        FROM report_embeddings re
        JOIN reports r ON r.report_id = re.report_id
        JOIN report_categories rc ON rc.category_id = r.category_id
        WHERE r.index_status = 'ready'
        {category_filter}
        ORDER BY re.embedding <=> CAST(:vec AS vector) ASC
        LIMIT :limit
        """
    )
    rows = db.execute(sql, params).all()
    return [(int(row[0]), float(row[1])) for row in rows]


# 개요 문자열 해시 계산 헬퍼 함수
def hash_overview(overview: str) -> str:
    """개요 문자열의 SHA-256 16진수 해시를 계산하는 헬퍼 함수"""
    # UTF-8 인코딩 기준 SHA-256 해시 반환
    return hashlib.sha256(overview.encode("utf-8")).hexdigest()


"""
보고서 도메인 10개 테이블에 대한 조회, 생성, 수정, 삭제, 임베딩 업서트, 프롬프트 버전 전환 및 키워드·pgvector 검색 쿼리를 구현하였다.
카테고리별 1:1 상세 테이블 동기화와 트랜잭션 무결성을 리포지토리 계층에 캡슐화하였다.
"""
