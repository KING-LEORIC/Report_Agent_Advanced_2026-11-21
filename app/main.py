"""FastAPI 앱 초기화, 전역 예외 핸들러, DB/pgvector 헬스체크 및 Uvicorn 실행을 담당하는 애플리케이션 진입점 모듈"""

# FastAPI 애플리케이션, 요청 객체, 예외 및 JSON 응답 클래스 import
# - FastAPI : 웹 애플리케이션 인스턴스 생성
# - Request : HTTP 요청 컨텍스트 객체
# - HTTPException : HTTP 상태 예외 클래스
# - RequestValidationError : 요청 파라미터/본문 검증 실패 예외
# - JSONResponse : 상태 코드와 JSON 본문을 담은 응답 객체
# 설정 및 DB 상태 점검 함수 import
# - at_least : 설정된 난이도 레벨 판별
# - settings : 앱 이름 및 버전 조회
# - check_db_and_vector_status : DB 및 pgvector 준비 상태 확인
from app.core.config import at_least, settings
from app.db.session import check_db_and_vector_status
from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

# FastAPI 애플리케이션 인스턴스 생성
# - 설정의 app_name과 app_version으로 초기화
app = FastAPI(title=settings.app_name, version=settings.app_version)


# 표준 에러 응답 딕셔너리 생성 헬퍼 함수
# - {"error": {"code": ..., "message": ..., "details": ...}} 구조 통일
def build_error_content(code: str, message: str, details: dict | None = None) -> dict:
    """요구사항 명세의 공통 에러 응답 포맷을 생성하는 헬퍼 함수"""
    # 코드, 메시지, 세부 정보를 담은 표준 에러 구조 반환
    return {"error": {"code": code, "message": message, "details": details or {}}}


# HTTPException 전역 핸들러 함수
# - 상태 코드에 맞는 에러 코드와 메시지로 변환
@app.exception_handler(HTTPException)
def on_http_exception(request: Request, exc: HTTPException):
    """HTTPException을 공통 JSON 에러 포맷으로 변환하는 핸들러"""
    # HTTP 상태 코드별 기본 에러 코드 매핑
    code_map = {
        400: "BAD_REQUEST",
        404: "NOT_FOUND",
        409: "REVISION_CONFLICT",
        422: "VALIDATION_ERROR",
        503: "SERVICE_UNAVAILABLE",
        504: "GATEWAY_TIMEOUT",
    }
    # 상태 코드에 대응하는 에러 코드 결정
    code = code_map.get(exc.status_code, "INTERNAL_ERROR")
    # 문자열 detail은 메시지로, 딕셔너리 detail은 details로 분리
    message = (
        exc.detail if isinstance(exc.detail, str) else "요청을 처리할 수 없습니다."
    )
    details = exc.detail if isinstance(exc.detail, dict) else {}
    # 표준 JSON 에러 응답 반환
    return JSONResponse(
        status_code=exc.status_code,
        content=build_error_content(code=code, message=message, details=details),
    )


# intermediate 레벨 이상일 때 요청 유효성 검증 예외 핸들러 등록
if at_least("intermediate"):
    # 요청 검증 실패 핸들러 함수
    # - 422 상태 코드와 VALIDATION_ERROR 응답 반환
    # - 원문 입력 및 민감 정보 노출 방지
    @app.exception_handler(RequestValidationError)
    def on_request_error(request: Request, exc: RequestValidationError):
        """요청 스키마/파라미터 검증 실패 시 422 JSON 에러 응답을 반환하는 핸들러"""
        # 표준 422 VALIDATION_ERROR 응답 반환
        return JSONResponse(
            status_code=422,
            content=build_error_content(
                code="VALIDATION_ERROR", message="요청 값을 확인하세요.", details={}
            ),
        )


# advanced 레벨 이상일 때 SQLAlchemy 데이터베이스 예외 핸들러 등록
if at_least("advanced"):
    # SQLAlchemy 예외 클래스 import
    # - OperationalError : DB 연결/운영 장애 예외
    # - SQLAlchemyError : SQLAlchemy 최상위 예외
    from sqlalchemy.exc import OperationalError, SQLAlchemyError

    # 데이터베이스 예외 핸들러 함수
    # - 연결 불가(503)와 일반 DB 오류(500) 구분
    # - SQL 구문 및 접속/인증 정보 마스킹
    @app.exception_handler(SQLAlchemyError)
    def on_database_error(request: Request, exc: SQLAlchemyError):
        """데이터베이스 예외를 안전하게 마스킹하여 503 또는 500 JSON 응답으로 반환하는 핸들러"""
        # OperationalError 여부로 DB 연결 불가 상태 판별
        unavailable = isinstance(exc, OperationalError)
        # 마스킹된 메시지와 상태 코드로 JSON 응답 반환
        return JSONResponse(
            status_code=503 if unavailable else 500,
            content=build_error_content(
                code="DB_UNAVAILABLE" if unavailable else "INTERNAL_ERROR",
                message="데이터베이스 처리를 완료하지 못했습니다.",
                details={},
            ),
        )


# 시스템 헬스체크 엔드포인트 함수
# - GET /health 요청 처리
# - DB 연결 및 pgvector 확장 준비 상태 점검
# - 정상 시 200, 미준비/장애 시 503 반환
@app.get("/health", tags=["System"])
def health():
    """데이터베이스 연결 상태와 pgvector 확장 활성화 여부를 점검하는 헬스체크 엔드포인트"""
    # DB 및 vector 확장 상태 조회
    status_info = check_db_and_vector_status()
    is_ready = status_info["db"] == "ready" and status_info["vector"] == "ready"
    # 하나라도 준비되지 않았으면 503 응답 반환
    if not is_ready:
        return JSONResponse(
            status_code=503,
            content=build_error_content(
                code="DB_UNAVAILABLE",
                message="DB 또는 pgvector를 확인하세요.",
                details=status_info,
            ),
        )
    # 정상 준비 상태 200 JSON 반환
    return {"status": "ok", "db": status_info["db"], "vector": status_info["vector"]}


# 개발 서버 실행 함수
# - Uvicorn으로 127.0.0.1:8000에서 app.main:app 실행
def main():
    """Uvicorn ASGI 서버를 실행하여 FastAPI 애플리케이션을 구동하는 함수"""
    # Uvicorn 모듈 import
    import uvicorn

    # 로컬 호스트 8000 포트로 FastAPI 앱 실행
    uvicorn.run("app.main:app", host="127.0.0.1", port=8000, reload=False)


# 스크립트 직접 실행 시 main() 호출
if __name__ == "__main__":
    main()

"""
FastAPI 앱과 난이도별 전역 예외 핸들러를 구성하여 입력 검증 실패 및 DB 장애 시 민감 정보를 마스킹하도록 구현하였다.
DB 연결과 pgvector 확장 상태를 점검하는 /health 엔드포인트와 Uvicorn 실행 진입점을 연결하여 서비스 구동 기반을 갖추었다.
"""
