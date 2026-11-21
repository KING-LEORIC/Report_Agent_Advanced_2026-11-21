"""SQLAlchemy 엔진, 세션 팩토리, 의존성 주입 및 DB/pgvector 상태 점검을 담당하는 세션 모듈"""

# 제너레이터 타입 및 SQLAlchemy 핵심 모듈 import
# - Generator : FastAPI 의존성 세션 생명주기 관리 타입
# - create_engine, text : DB 엔진 생성 및 원시 SQL 구문 실행
# - SQLAlchemyError : SQLAlchemy 데이터베이스 예외 기본 클래스
# - Session, declarative_base, sessionmaker : ORM 세션 및 베이스 클래스 관리
from collections.abc import Generator

# 애플리케이션 설정 객체 import
# - settings : DB 접속 문자열 등 설정값 조회
from app.core.config import settings
from sqlalchemy import create_engine, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, declarative_base, sessionmaker

# SQLAlchemy 엔진 및 세션 팩토리 초기화
# - pool_pre_ping=True로 끊어진 커넥션 사전 감지
engine = create_engine(settings.sqlalchemy_database_url, pool_pre_ping=True)
SessionLocal = sessionmaker(
    bind=engine, autocommit=False, autoflush=False, class_=Session
)

# ORM 모델 선언용 베이스 클래스 생성
Base = declarative_base()


# 세션 팩토리 반환 함수
# - 호출 시 SessionLocal 팩토리 객체를 반환
def get_session_factory():
    """SQLAlchemy 세션 팩토리(SessionLocal)를 반환하는 함수"""
    # 미리 생성된 세션 팩토리 반환
    return SessionLocal


# FastAPI 요청 단위 DB 세션 의존성 함수
# - 요청 처리 중 세션을 제공하고 종료 시 안전하게 닫음
def get_db() -> Generator[Session, None, None]:
    """요청별 SQLAlchemy 세션을 생성하고 종료 시 정리하는 의존성 함수"""
    # 새 DB 세션 인스턴스 생성
    db = SessionLocal()
    try:
        # 라우터/서비스 계층에 세션 전달
        yield db
    finally:
        # 예외 발생 여부와 관계없이 세션 종료
        db.close()


# DB 연결 및 pgvector 확장 준비 상태 점검 함수
# - SELECT 1 연결 확인 및 pg_extension에서 vector 설치 여부 조회
def check_db_and_vector_status() -> dict[str, str]:
    """PostgreSQL 연결 상태와 pgvector 확장 활성화 여부를 점검하는 함수"""
    try:
        # 엔진 커넥션 오픈 후 기본 쿼리 및 vector 확장 존재 여부 확인
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
            vector_installed = bool(
                conn.execute(
                    text(
                        "SELECT EXISTS (SELECT 1 FROM pg_extension WHERE extname = 'vector')"
                    )
                ).scalar()
            )
        # DB 정상 연결 및 vector 확장 설치 여부 반환
        return {"db": "ready", "vector": "ready" if vector_installed else "unavailable"}
    except SQLAlchemyError:
        # DB 연결 실패 시 양쪽 모두 unavailable로 반환
        return {"db": "unavailable", "vector": "unavailable"}


"""
SQLAlchemy 엔진, SessionLocal 팩토리, 요청별 get_db 의존성 및 헬스체크용 상태 점검 함수를 구현하였다.
커넥션 풀 사전 핑과 pgvector 확장 설치 확인을 통해 DB 및 벡터 저장소 준비 상태를 판별하도록 구성하였다.
"""
