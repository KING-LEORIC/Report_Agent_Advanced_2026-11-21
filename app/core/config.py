"""애플리케이션 환경 설정, 난이도 레벨 판별 및 설정 싱글턴 관리를 담당하는 설정 모듈"""

# 캐시 데코레이터, 경로 처리 및 환경변수 접근 표준 모듈 import
# - lru_cache : 설정 인스턴스 싱글턴 캐싱
# - os : 시스템 환경변수 조회
# - Path : .env 파일 경로 탐색 및 읽기
import os
from functools import lru_cache
from pathlib import Path

# 난이도 순서 정의 상수
# - basic < intermediate < advanced 순위 비교용 리스트
LEVEL_ORDER = ["basic", "intermediate", "advanced"]


# .env 파일 파싱 헬퍼 함수
# - KEY=VALUE 형식의 라인을 읽어 딕셔너리로 반환 (따옴표 및 주석 처리)
def _load_dotenv_file(env_path: Path) -> dict[str, str]:
    """지정된 경로의 .env 파일을 읽어 환경변수 딕셔너리로 반환하는 함수"""
    # 파싱 결과를 담을 딕셔너리 초기화
    env_values: dict[str, str] = {}
    # .env 파일이 존재하지 않으면 빈 딕셔너리 반환
    if not env_path.is_file():
        return env_values
    # UTF-8 인코딩으로 파일 라인 순회
    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        # 빈 줄 또는 주석 라인 건너뜀
        if not line or line.startswith("#"):
            continue
        # export 접두사가 붙은 경우 제거
        if line.startswith("export "):
            line = line[len("export ") :].strip()
        # '=' 구분자가 없으면 건너뜀
        if "=" not in line:
            continue
        key, val = line.split("=", 1)
        key = key.strip()
        val = val.strip()
        # 양끝이 같은 따옴표(' 또는 ")로 감싸져 있으면 제거
        if len(val) >= 2 and val[0] == val[-1] and val[0] in ("'", '"'):
            val = val[1:-1]
        # 유효한 키 이름이면 값 저장
        if key:
            env_values[key] = val
    # 파싱된 환경변수 딕셔너리 반환
    return env_values


# 설정 값 조회 헬퍼 함수
# - 시스템 환경변수 우선, 없으면 .env 값, 둘 다 없으면 기본값 반환
def _get_env_value(key: str, dotenv_map: dict[str, str], default: str) -> str:
    """환경변수 또는 .env 값에서 문자열 설정을 조회하는 헬퍼 함수"""
    # 시스템 환경변수에 값이 있으면 최우선 사용
    sys_val = os.environ.get(key)
    if sys_val is not None and sys_val != "":
        return sys_val
    # .env 파일에 값이 있으면 사용
    if key in dotenv_map and dotenv_map[key] != "":
        return dotenv_map[key]
    # 기본값 반환
    return default


# 불리언 설정 값 파싱 헬퍼 함수
# - true/1/yes/on 문자열을 True로 변환
def _parse_bool(raw: str) -> bool:
    """문자열 환경변수를 불리언 값으로 변환하는 헬퍼 함수"""
    # 소문자 정규화 후 참 값 여부 판별
    return raw.strip().lower() in ("1", "true", "yes", "on")


# 애플리케이션 환경 설정 클래스
# - .env 및 시스템 환경변수에서 DB, 임베딩, LLM, 검색 임계값 로드
class Settings:
    """환경변수 및 .env 설정값을 파싱하여 보관하는 설정 모델"""

    def __init__(self) -> None:
        """프로젝트 루트의 .env와 환경변수를 읽어 설정 필드를 초기화하는 생성자"""
        # 현재 파일(app/core/config.py) 기준 프로젝트 루트(.env 위치) 계산
        project_root = Path(__file__).resolve().parents[2]
        dotenv_map = _load_dotenv_file(project_root / ".env")

        # .env에 존재하는 값 중 OS 환경변수에 비어 있는 항목은 기본값으로 주입
        for k, v in dotenv_map.items():
            if v != "" and not os.environ.get(k):
                os.environ[k] = v

        # 서비스 기본 메타데이터 설정
        self.app_name: str = _get_env_value(
            "APP_NAME", dotenv_map, "Report Agent | 2026-11-20"
        )
        self.app_version: str = _get_env_value("APP_VERSION", dotenv_map, "1.4.0")
        self.project_level: str = _get_env_value(
            "PROJECT_LEVEL", dotenv_map, "advanced"
        )
        self.debug: bool = _parse_bool(_get_env_value("DEBUG", dotenv_map, "false"))

        # PostgreSQL 접속 설정 (DATABASE_URL이 비어 있으면 None 처리)
        raw_db_url = _get_env_value("DATABASE_URL", dotenv_map, "").strip()
        self.database_url: str | None = raw_db_url if raw_db_url else None
        self.db_host: str = _get_env_value("DB_HOST", dotenv_map, "127.0.0.1")
        self.db_port: int = int(_get_env_value("DB_PORT", dotenv_map, "5432"))
        self.db_name: str = _get_env_value("DB_NAME", dotenv_map, "report_agent_lab")
        self.db_user: str = _get_env_value("DB_USER", dotenv_map, "postgres")
        self.db_password: str = _get_env_value("DB_PASSWORD", dotenv_map, "")

        # E5 임베딩 및 유사도 검색 설정
        self.embedding_model_name: str = _get_env_value(
            "EMBEDDING_MODEL_NAME", dotenv_map, "intfloat/multilingual-e5-small"
        )
        self.embedding_dimension: int = int(
            _get_env_value("EMBEDDING_DIMENSION", dotenv_map, "384")
        )
        self.search_min_similarity: float = float(
            _get_env_value("SEARCH_MIN_SIMILARITY", dotenv_map, "0.75")
        )

        # LLM API 키, 호출 모델, 타임아웃, 재시도 및 Tool Calling 제한 설정
        self.openai_api_key: str = _get_env_value(
            "OPENAI_API_KEY", dotenv_map, ""
        ).strip()
        self.llm_model: str = _get_env_value(
            "LLM_MODEL", dotenv_map, "configured-llm-model"
        )
        self.llm_timeout_seconds: float = float(
            _get_env_value("LLM_TIMEOUT_SECONDS", dotenv_map, "30.0")
        )
        self.llm_max_retries: int = int(
            _get_env_value("LLM_MAX_RETRIES", dotenv_map, "2")
        )
        raw_max_tool_calls = _get_env_value(
            "LLM_MAX_TOOL_CALLS",
            dotenv_map,
            _get_env_value("LLM_MAX_TOOL_calls", dotenv_map, "3"),
        )
        self.llm_max_tool_calls: int = int(raw_max_tool_calls)

    # SQLAlchemy 접속 URL 생성 프로퍼티
    # - 명시적 database_url이 있으면 반환하고 없으면 개별 항목으로 조합
    @property
    def sqlalchemy_database_url(self) -> str:
        """SQLAlchemy 엔진 연결용 PostgreSQL DSN 문자열을 반환하는 프로퍼티"""
        # 직접 지정된 DATABASE_URL이 있으면 공백 제거 후 반환
        if self.database_url and self.database_url.strip():
            return self.database_url.strip()
        # 개별 DB 접속 설정값을 조합하여 접속 문자열 생성
        return (
            f"postgresql+psycopg://{self.db_user}:{self.db_password}"
            f"@{self.db_host}:{self.db_port}/{self.db_name}"
        )


# 설정 싱글턴 생성 함수
# - lru_cache로 프로세스 내 Settings 인스턴스 재사용
@lru_cache
def get_settings() -> Settings:
    """애플리케이션 설정 인스턴스를 캐싱하여 반환하는 함수"""
    # 새 Settings 객체 생성 및 반환
    return Settings()


# 현재 설정 레벨이 요구 레벨 이상인지 판별하는 함수
# - basic < intermediate < advanced 순서로 비교
# - 알 수 없는 레벨 문자열은 basic(0)으로 처리
def at_least(required_level: str) -> bool:
    """현재 project_level이 지정된 최소 요구 난이도 이상인지 확인하는 함수"""
    # 현재 설정 레벨과 요구 레벨을 소문자로 정규화
    current = get_settings().project_level.strip().lower()
    target = required_level.strip().lower()
    # 순위 목록에서 인덱스 조회 (미등록 값은 0)
    current_idx = LEVEL_ORDER.index(current) if current in LEVEL_ORDER else 0
    target_idx = LEVEL_ORDER.index(target) if target in LEVEL_ORDER else 0
    # 현재 레벨 순위가 요구 레벨 이상인지 반환
    return current_idx >= target_idx


# 전역 설정 참조 객체 생성
settings = get_settings()

"""
외부 패키지(pydantic-settings) 없이 Python 표준 라이브러리만으로 .env 및 환경변수를 읽는 Settings 클래스를 구현하였다.
OPENAI_API_KEY 로드 및 os.environ 반영을 추가해 외부 SDK가 .env 설정값을 일관되게 참조하도록 구성하였다.
"""
