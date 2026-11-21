"""보고서 도메인의 10개 물리 테이블(카테고리, 공통 메타, 임베딩, 6종 상세, 프롬프트 버전) ORM 모델을 정의하는 모듈"""

# SQLAlchemy 컬럼 타입, 외래키, 체크 제약, 관계 및 pgvector 타입 import
# - BigInteger, CheckConstraint, Column, Date, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint : RDB 스키마 타입 및 제약조건
# - func : DB 서버 시각(NOW()) 기본값 생성
# - relationship : ORM 테이블 간 1:N / 1:0..1 관계 선언
# - Vector : pgvector 384차원 벡터 컬럼 타입
from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    Column,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import relationship

# DB 세션 모듈의 선언적 베이스 클래스 import
# - Base : 모든 ORM 모델이 상속하는 메타데이터 베이스
from app.db.session import Base


# 보고서 분류(6종 고정) 테이블 ORM 모델
# - report_categories 테이블 매핑 (category_id, code, name, description)
class ReportCategory(Base):
    """보고서 6개 분류(EXPERIMENT, DAILY_WORK, RESEARCH_PLAN, DATA_PROCESSING, PROMPT, MEETING) 모델"""

    # 물리 테이블명 및 체크 제약조건 선언
    __tablename__ = "report_categories"
    __table_args__ = (
        CheckConstraint("category_id >= 1", name="ck_report_categories_id_min"),
        CheckConstraint(
            "code IN ('EXPERIMENT','DAILY_WORK','RESEARCH_PLAN','DATA_PROCESSING','PROMPT','MEETING')",
            name="ck_report_categories_code",
        ),
        CheckConstraint(
            "char_length(btrim(name)) >= 1", name="ck_report_categories_name_len"
        ),
    )

    # 컬럼 정의
    category_id = Column(Integer, primary_key=True, nullable=False)
    code = Column(String(40), unique=True, nullable=False)
    name = Column(Text, nullable=False)
    description = Column(Text, nullable=True)

    # 하위 reports 테이블과의 1:N 관계
    reports = relationship("Report", back_populates="category")


# 보고서 공통 메타/개요/리비전 테이블 ORM 모델
# - reports 테이블 매핑 (제목/본문/작성자/시각은 6종 상세 테이블에 저장)
class Report(Base):
    """전 종류 보고서의 공통 식별자, 분류, 검색용 개요, 인덱싱 상태 및 리비전 모델"""

    # 물리 테이블명 및 체크 제약조건 선언
    __tablename__ = "reports"
    __table_args__ = (
        CheckConstraint(
            "char_length(btrim(overview)) BETWEEN 10 AND 1000",
            name="ck_reports_overview_len",
        ),
        CheckConstraint(
            "index_status IN ('pending','ready','failed')",
            name="ck_reports_index_status",
        ),
        CheckConstraint("revision >= 1", name="ck_reports_revision_min"),
    )

    # 컬럼 정의
    report_id = Column(BigInteger, primary_key=True, autoincrement=True, nullable=False)
    category_id = Column(
        Integer,
        ForeignKey("report_categories.category_id", ondelete="RESTRICT"),
        nullable=False,
    )
    overview = Column(String(1000), nullable=False)
    index_status = Column(
        String(20), nullable=False, server_default="pending", default="pending"
    )
    revision = Column(Integer, nullable=False, server_default="1", default=1)

    # 카테고리 및 1:0..1 / 1:N 연관 테이블 관계 선언
    category = relationship("ReportCategory", back_populates="reports")
    embedding_record = relationship(
        "ReportEmbedding",
        back_populates="report",
        uselist=False,
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    experiment_detail = relationship(
        "ExperimentReport",
        back_populates="report",
        uselist=False,
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    daily_work_detail = relationship(
        "DailyWorkReport",
        back_populates="report",
        uselist=False,
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    research_plan_detail = relationship(
        "ResearchPlan",
        back_populates="report",
        uselist=False,
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    data_processing_detail = relationship(
        "DataProcessingReport",
        back_populates="report",
        uselist=False,
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    prompt_detail = relationship(
        "PromptReport",
        back_populates="report",
        uselist=False,
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    meeting_detail = relationship(
        "MeetingMinute",
        back_populates="report",
        uselist=False,
        cascade="all, delete-orphan",
        passive_deletes=True,
    )


# 보고서 개요 384차원 pgvector 임베딩 테이블 ORM 모델
# - report_embeddings 테이블 매핑
class ReportEmbedding(Base):
    """보고서 개요의 E5 384차원 벡터, 해시 및 인덱싱 리비전 추적 모델"""

    # 물리 테이블명 및 체크 제약조건 선언
    __tablename__ = "report_embeddings"
    __table_args__ = (
        CheckConstraint(
            "char_length(btrim(model_name)) >= 1", name="ck_report_embeddings_model"
        ),
        CheckConstraint(
            "overview_hash ~ '^[0-9a-f]{64}$'", name="ck_report_embeddings_hash_hex"
        ),
        CheckConstraint("indexed_revision >= 1", name="ck_report_embeddings_rev_min"),
    )

    # 컬럼 정의
    report_id = Column(
        BigInteger,
        ForeignKey("reports.report_id", ondelete="CASCADE"),
        primary_key=True,
        nullable=False,
    )
    embedding = Column(Vector(384), nullable=False)
    model_name = Column(Text, nullable=False)
    overview_hash = Column(String(64), nullable=False)
    indexed_revision = Column(Integer, nullable=False)
    indexed_at = Column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    # 상위 Report와의 1:0..1 관계
    report = relationship("Report", back_populates="embedding_record")


# 실험 결과 보고서 상세 테이블 ORM 모델
# - experiment_reports 테이블 매핑
class ExperimentReport(Base):
    """EXPERIMENT 분류 보고서의 공통 본문 및 실험 수행일·가설·결과 요약 상세 모델"""

    # 물리 테이블명 및 체크 제약조건 선언
    __tablename__ = "experiment_reports"
    __table_args__ = (
        CheckConstraint(
            "char_length(btrim(title)) BETWEEN 1 AND 200", name="ck_exp_title_len"
        ),
        CheckConstraint(
            "char_length(btrim(content)) BETWEEN 1 AND 20000", name="ck_exp_content_len"
        ),
        CheckConstraint(
            "char_length(btrim(author)) BETWEEN 1 AND 100", name="ck_exp_author_len"
        ),
        CheckConstraint("update_at >= create_at", name="ck_exp_time_order"),
        CheckConstraint(
            "char_length(btrim(hypothesis)) >= 1", name="ck_exp_hypothesis_len"
        ),
        CheckConstraint(
            "char_length(btrim(result_summary)) >= 1", name="ck_exp_result_len"
        ),
    )

    # 컬럼 정의 (DB 실제 컬럼명 create_at, update_at 유지)
    report_id = Column(
        BigInteger,
        ForeignKey("reports.report_id", ondelete="CASCADE"),
        primary_key=True,
        nullable=False,
    )
    title = Column(String(200), nullable=False)
    content = Column(Text, nullable=False)
    author = Column(String(100), nullable=False)
    create_at = Column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    update_at = Column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    experiment_date = Column(Date, nullable=False)
    hypothesis = Column(Text, nullable=False)
    result_summary = Column(Text, nullable=False)

    # 상위 Report 관계
    report = relationship("Report", back_populates="experiment_detail")


# 일일 업무 보고서 상세 테이블 ORM 모델
# - daily_work_reports 테이블 매핑
class DailyWorkReport(Base):
    """DAILY_WORK 분류 보고서의 공통 본문 및 업무일·진행 내용·이슈 상세 모델"""

    # 물리 테이블명 및 체크 제약조건 선언
    __tablename__ = "daily_work_reports"
    __table_args__ = (
        CheckConstraint(
            "char_length(btrim(title)) BETWEEN 1 AND 200", name="ck_dw_title_len"
        ),
        CheckConstraint(
            "char_length(btrim(content)) BETWEEN 1 AND 20000", name="ck_dw_content_len"
        ),
        CheckConstraint(
            "char_length(btrim(author)) BETWEEN 1 AND 100", name="ck_dw_author_len"
        ),
        CheckConstraint("update_at >= create_at", name="ck_dw_time_order"),
        CheckConstraint("char_length(btrim(progress)) >= 1", name="ck_dw_progress_len"),
    )

    # 컬럼 정의
    report_id = Column(
        BigInteger,
        ForeignKey("reports.report_id", ondelete="CASCADE"),
        primary_key=True,
        nullable=False,
    )
    title = Column(String(200), nullable=False)
    content = Column(Text, nullable=False)
    author = Column(String(100), nullable=False)
    create_at = Column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    update_at = Column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    work_date = Column(Date, nullable=False)
    progress = Column(Text, nullable=False)
    blockers = Column(Text, nullable=False, server_default="", default="")

    # 상위 Report 관계
    report = relationship("Report", back_populates="daily_work_detail")


# 연구 계획서 상세 테이블 ORM 모델
# - research_plans 테이블 매핑
class ResearchPlan(Base):
    """RESEARCH_PLAN 분류 보고서의 공통 본문 및 연구 목표·방법·목표일 상세 모델"""

    # 물리 테이블명 및 체크 제약조건 선언
    __tablename__ = "research_plans"
    __table_args__ = (
        CheckConstraint(
            "char_length(btrim(title)) BETWEEN 1 AND 200", name="ck_rp_title_len"
        ),
        CheckConstraint(
            "char_length(btrim(content)) BETWEEN 1 AND 20000", name="ck_rp_content_len"
        ),
        CheckConstraint(
            "char_length(btrim(author)) BETWEEN 1 AND 100", name="ck_rp_author_len"
        ),
        CheckConstraint("update_at >= create_at", name="ck_rp_time_order"),
        CheckConstraint(
            "char_length(btrim(research_goal)) >= 1", name="ck_rp_goal_len"
        ),
        CheckConstraint(
            "char_length(btrim(methodology)) >= 1", name="ck_rp_method_len"
        ),
    )

    # 컬럼 정의
    report_id = Column(
        BigInteger,
        ForeignKey("reports.report_id", ondelete="CASCADE"),
        primary_key=True,
        nullable=False,
    )
    title = Column(String(200), nullable=False)
    content = Column(Text, nullable=False)
    author = Column(String(100), nullable=False)
    create_at = Column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    update_at = Column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    research_goal = Column(Text, nullable=False)
    methodology = Column(Text, nullable=False)
    target_date = Column(Date, nullable=False)

    # 상위 Report 관계
    report = relationship("Report", back_populates="research_plan_detail")


# 데이터 처리 보고서 상세 테이블 ORM 모델
# - data_processing_reports 테이블 매핑
class DataProcessingReport(Base):
    """DATA_PROCESSING 분류 보고서의 공통 본문 및 데이터셋·처리 절차·품질 비고 상세 모델"""

    # 물리 테이블명 및 체크 제약조건 선언
    __tablename__ = "data_processing_reports"
    __table_args__ = (
        CheckConstraint(
            "char_length(btrim(title)) BETWEEN 1 AND 200", name="ck_dp_title_len"
        ),
        CheckConstraint(
            "char_length(btrim(content)) BETWEEN 1 AND 20000", name="ck_dp_content_len"
        ),
        CheckConstraint(
            "char_length(btrim(author)) BETWEEN 1 AND 100", name="ck_dp_author_len"
        ),
        CheckConstraint("update_at >= create_at", name="ck_dp_time_order"),
        CheckConstraint(
            "char_length(btrim(dataset_name)) >= 1", name="ck_dp_dataset_len"
        ),
        CheckConstraint(
            "char_length(btrim(processing_steps)) >= 1", name="ck_dp_steps_len"
        ),
    )

    # 컬럼 정의
    report_id = Column(
        BigInteger,
        ForeignKey("reports.report_id", ondelete="CASCADE"),
        primary_key=True,
        nullable=False,
    )
    title = Column(String(200), nullable=False)
    content = Column(Text, nullable=False)
    author = Column(String(100), nullable=False)
    create_at = Column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    update_at = Column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    dataset_name = Column(Text, nullable=False)
    processing_steps = Column(Text, nullable=False)
    quality_notes = Column(Text, nullable=False, server_default="", default="")

    # 상위 Report 관계
    report = relationship("Report", back_populates="data_processing_detail")


# 프롬프트 보고서 상세 테이블 ORM 모델
# - prompt_reports 테이블 매핑
class PromptReport(Base):
    """PROMPT 분류 보고서의 공통 본문 및 목적·활성 버전 번호 상세 모델"""

    # 물리 테이블명 및 체크 제약조건 선언
    __tablename__ = "prompt_reports"
    __table_args__ = (
        CheckConstraint(
            "char_length(btrim(title)) BETWEEN 1 AND 200", name="ck_pr_title_len"
        ),
        CheckConstraint(
            "char_length(btrim(content)) BETWEEN 1 AND 20000", name="ck_pr_content_len"
        ),
        CheckConstraint(
            "char_length(btrim(author)) BETWEEN 1 AND 100", name="ck_pr_author_len"
        ),
        CheckConstraint("update_at >= create_at", name="ck_pr_time_order"),
        CheckConstraint("char_length(btrim(purpose)) >= 1", name="ck_pr_purpose_len"),
        CheckConstraint("active_version_no >= 1", name="ck_pr_active_ver_min"),
    )

    # 컬럼 정의
    report_id = Column(
        BigInteger,
        ForeignKey("reports.report_id", ondelete="CASCADE"),
        primary_key=True,
        nullable=False,
    )
    title = Column(String(200), nullable=False)
    content = Column(Text, nullable=False)
    author = Column(String(100), nullable=False)
    create_at = Column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    update_at = Column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    purpose = Column(Text, nullable=False)
    active_version_no = Column(Integer, nullable=False, server_default="1", default=1)

    # 상위 Report 및 하위 PromptVersion 관계
    report = relationship("Report", back_populates="prompt_detail")
    versions = relationship(
        "PromptVersion",
        back_populates="prompt_report",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )


# 프롬프트 버전 이력 테이블 ORM 모델
# - prompt_versions 테이블 매핑
class PromptVersion(Base):
    """PROMPT 보고서의 버전별 불변 프롬프트 텍스트 이력 모델"""

    # 물리 테이블명, 복합 유니크 및 체크 제약조건 선언
    __tablename__ = "prompt_versions"
    __table_args__ = (
        UniqueConstraint(
            "report_id", "version_no", name="uq_prompt_versions_report_ver"
        ),
        CheckConstraint("version_no >= 1", name="ck_pv_version_min"),
        CheckConstraint(
            "char_length(btrim(prompt_text)) BETWEEN 1 AND 20000",
            name="ck_pv_prompt_text_len",
        ),
    )

    # 컬럼 정의
    prompt_version_id = Column(
        BigInteger, primary_key=True, autoincrement=True, nullable=False
    )
    report_id = Column(
        BigInteger,
        ForeignKey("prompt_reports.report_id", ondelete="CASCADE"),
        nullable=False,
    )
    version_no = Column(Integer, nullable=False)
    prompt_text = Column(Text, nullable=False)
    created_at = Column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    # 상위 PromptReport 관계
    prompt_report = relationship("PromptReport", back_populates="versions")


# 회의록 상세 테이블 ORM 모델
# - meeting_minutes 테이블 매핑
class MeetingMinute(Base):
    """MEETING 분류 보고서의 공통 본문 및 회의 시각·참석자·결정 사항 상세 모델"""

    # 물리 테이블명 및 체크 제약조건 선언
    __tablename__ = "meeting_minutes"
    __table_args__ = (
        CheckConstraint(
            "char_length(btrim(title)) BETWEEN 1 AND 200", name="ck_mm_title_len"
        ),
        CheckConstraint(
            "char_length(btrim(content)) BETWEEN 1 AND 20000", name="ck_mm_content_len"
        ),
        CheckConstraint(
            "char_length(btrim(author)) BETWEEN 1 AND 100", name="ck_mm_author_len"
        ),
        CheckConstraint("update_at >= create_at", name="ck_mm_time_order"),
        CheckConstraint(
            "char_length(btrim(attendees)) >= 1", name="ck_mm_attendees_len"
        ),
        CheckConstraint(
            "char_length(btrim(decisions)) >= 1", name="ck_mm_decisions_len"
        ),
    )

    # 컬럼 정의
    report_id = Column(
        BigInteger,
        ForeignKey("reports.report_id", ondelete="CASCADE"),
        primary_key=True,
        nullable=False,
    )
    title = Column(String(200), nullable=False)
    content = Column(Text, nullable=False)
    author = Column(String(100), nullable=False)
    create_at = Column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    update_at = Column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    meeting_at = Column(DateTime(timezone=True), nullable=False)
    attendees = Column(Text, nullable=False)
    decisions = Column(Text, nullable=False)

    # 상위 Report 관계
    report = relationship("Report", back_populates="meeting_detail")


"""
보고서 도메인의 10개 물리 테이블과 체크 제약조건, 유니크 제약, CASCADE/RESTRICT 참조 규칙을 SQLAlchemy ORM으로 정의하였다.
공통 메타/개요/리비전은 reports에, 종류별 본문·작성자·시각 및 고유 속성은 각 상세 테이블에 1:1로 분리 매핑하였다.
"""
