"""FastAPI 애플리케이션 진입점, 헬스체크, 라우터 등록 및 전역 예외 처리를 담당하는 모듈"""

# 타이핑, FastAPI 앱/요청/응답 객체 및 Uvicorn 서버 import
# - Any : JSON 응답 본문 타입 힌트
# - FastAPI : 웹 애플리케이션 인스턴스
# - Request : HTTP 요청 컨텍스트
# - JSONResponse : 표준 에러 포맷 JSON 응답 반환
# - uvicorn : 개발/실행 서버 러너
from typing import Any

import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

# API 라우터, 설정, DB 상태 점검 및 커스텀 예외 클래스 import
# - agent_router : 유사도 검색 및 에이전트 질의 API 라우터
# - reports_router : 보고서 도메인 API 라우터
# - settings : 앱 이름, 버전, 난이도 레벨 설정 조회
# - check_db_and_vector_status : DB 및 pgvector 확장 연결 점검
# - LLMClientError : LLM 클라이언트 호출/파싱 예외
# - ServiceError : 도메인 서비스 비즈니스 예외
from app.api.agent import router as agent_router
from app.api.reports import router as reports_router
from app.core.config import settings
from app.db.session import check_db_and_vector_status
from app.integrations.llm_client import LLMClientError
from app.services.report_service import ServiceError


# 공통 에러 응답 페이로드 생성 헬퍼 함수
# - code, message, detail 일관된 구조 반환
def _error_payload(code: str, message: str, detail: Any = None) -> dict[str, Any]:
    """표준화된 에러 JSON 딕셔너리를 구성하는 헬퍼 함수"""
    # 기본 에러 필드 구성
    payload: dict[str, Any] = {"error": {"code": code, "message": message}}
    # 선택적 상세 정보가 있으면 포함
    if detail is not None:
        payload["error"]["detail"] = detail
    return payload


# FastAPI 애플리케이션 인스턴스 생성 함수
def create_app() -> FastAPI:
    """설정과 라우터, 예외 핸들러가 반영된 FastAPI 앱을 생성하는 함수"""
    # 앱 메타데이터 초기화
    app = FastAPI(title=settings.app_name, version=settings.app_version)

    # ServiceError 전역 예외 핸들러 등록
    @app.exception_handler(ServiceError)
    async def handle_service_error(
        _request: Request, exc: ServiceError
    ) -> JSONResponse:
        """도메인 서비스 예외를 지정된 HTTP 상태 코드와 JSON 포맷으로 변환하는 핸들러"""
        # 서비스 예외 상태 코드 및 메시지 반영
        return JSONResponse(
            status_code=exc.status,
            content=_error_payload(code=exc.code, message=exc.message),
        )

    # LLMClientError 전역 예외 핸들러 등록
    @app.exception_handler(LLMClientError)
    async def handle_llm_client_error(
        _request: Request, exc: LLMClientError
    ) -> JSONResponse:
        """LLM 호출 실패 예외를 HTTP 응답으로 변환하는 핸들러"""
        # LLM 클라이언트 에러 코드 및 상태 코드 반환
        return JSONResponse(
            status_code=exc.status,
            content=_error_payload(code=exc.code, message=exc.message),
        )

    # 헬스체크 엔드포인트 등록
    @app.get("/health")
    def health() -> dict[str, Any]:
        """애플리케이션 상태 및 DB/pgvector 연결 상태를 반환하는 엔드포인트"""
        # DB 및 pgvector 상태 조회
        db_status = check_db_and_vector_status()
        return {
            "status": "ok",
            "app_name": settings.app_name,
            "version": settings.app_version,
            "project_level": settings.project_level,
            "db": db_status,
        }

    # 보고서 및 에이전트/검색 도메인 라우터 등록
    app.include_router(reports_router)
    app.include_router(agent_router)

    return app


# 전역 ASGI 애플리케이션 인스턴스 생성
app = create_app()


# 모듈 직접 실행 시 Uvicorn 서버 구동
if __name__ == "__main__":
    # 개발 모드(reload) 및 호스트/포트 지정 실행
    uvicorn.run("app.main:app", host="127.0.0.1", port=8000, reload=settings.debug)

"""
FastAPI 앱 팩토리, 헬스체크(/health), 보고서 및 에이전트/검색 라우터와 ServiceError/LLMClientError 전역 예외 핸들러를 구성하였다.
도메인 예외를 일관된 JSON 응답으로 직렬화해 API 계약 준수성을 높였다.
"""
