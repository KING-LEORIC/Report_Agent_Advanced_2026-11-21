"""보고서 요약(brief/structured) 및 Tool Calling 에이전트 추론을 담당하는 LLM 클라이언트 모듈"""

# JSON 파싱, 타이핑 및 OpenAI SDK 클라이언트 import
# - json : 구조화 요약 JSON 응답 파싱
# - Any : 도구 정의 및 클라이언트 타입 힌트
# - OpenAI : OpenAI 호환 Chat Completions API 클라이언트
import json
from typing import Any

from openai import OpenAI

# 애플리케이션 설정 객체 import
# - settings : LLM 모델명, 타임아웃, 재시도 횟수 조회
from app.core.config import settings


# LLM 호출 실패를 나타내는 커스텀 예외 클래스
# - 타임아웃, 빈 응답, JSON 형식 오류 등 구분
class LLMClientError(RuntimeError):
    """LLM API 호출 또는 응답 파싱 과정에서 발생하는 예외 클래스"""

    def __init__(
        self, message: str, code: str = "LLM_ERROR", status: int = 502
    ) -> None:
        """에러 메시지와 표준 에러 코드, HTTP 상태 코드를 저장하는 생성자"""
        super().__init__(message)
        self.message = message
        self.code = code
        self.status = status


# OpenAI 클라이언트 인스턴스 생성 헬퍼 함수
# - 설정된 llm_timeout_seconds 적용
def _create_client() -> OpenAI:
    """타임아웃 설정이 반영된 OpenAI 클라이언트를 생성하는 헬퍼 함수"""
    # 환경변수(OPENAI_API_KEY 등) 및 타임아웃으로 클라이언트 초기화
    return OpenAI(timeout=settings.llm_timeout_seconds)


# 보고서 요약 생성 함수 (brief / structured 스타일 지원)
# - 설정된 재시도 횟수만큼 호출 시도 후 결과 반환
def generate_report_summary(
    title: str,
    category_code: str,
    content: str,
    overview: str,
    style: str = "brief",
    max_sentences: int = 3,
) -> str | dict[str, Any]:
    """보고서 본문과 개요를 바탕으로 brief 또는 structured 요약을 생성하는 함수"""
    # OpenAI 클라이언트 생성
    client = _create_client()
    # 요약 스타일별 시스템 프롬프트 구성
    if style == "structured":
        system_prompt = (
            "당신은 기술/업무 보고서를 분석하는 요약 도우미입니다. "
            "반드시 다음 4개 키를 가진 JSON 객체만 출력하세요: "
            '{"purpose": "...", "key_points": ["..."], "conclusion": "...", "limitations": "..."}. '
            "마크다운 코드블록 없이 순수 JSON만 반환하세요."
        )
    else:
        system_prompt = (
            f"당신은 보고서 요약 도우미입니다. 핵심 내용을 최대 {max_sentences}문장 이내의 "
            "간결한 한국어로 요약하세요."
        )
    # 요약 대상 보고서 정보 구성
    user_prompt = (
        f"[분류] {category_code}\n[제목] {title}\n[개요] {overview}\n[본문]\n{content}"
    )

    last_error: Exception | None = None
    max_attempts = max(1, settings.llm_max_retries + 1)
    # 설정된 최대 시도 횟수만큼 LLM 호출 반복
    for _ in range(max_attempts):
        try:
            # Chat Completions API 호출
            response = client.chat.completions.create(
                model=settings.llm_model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
            )
            raw_content = response.choices[0].message.content or ""
            cleaned = raw_content.strip()
            if not cleaned:
                raise LLMClientError(
                    "LLM 요약 응답이 비어 있습니다.", code="LLM_EMPTY_RESPONSE"
                )
            # 구조화 요약인 경우 JSON 파싱 및 필수 필드 검증
            if style == "structured":
                if cleaned.startswith("```"):
                    cleaned = cleaned.strip("`").removeprefix("json").strip()
                parsed = json.loads(cleaned)
                required_keys = {"purpose", "key_points", "conclusion", "limitations"}
                if not isinstance(parsed, dict) or not required_keys.issubset(
                    parsed.keys()
                ):
                    raise LLMClientError(
                        "구조화 요약 필수 키가 누락되었습니다.", code="LLM_INVALID_JSON"
                    )
                return parsed
            # 간결 요약 문자열 반환
            return cleaned
        except LLMClientError as exc:
            last_error = exc
        except (json.JSONDecodeError, ValueError, TypeError) as exc:
            last_error = exc

    # 모든 재시도 실패 시 예외 발생
    raise LLMClientError(
        f"LLM 요약 생성에 실패했습니다: {last_error}",
        code="LLM_UNAVAILABLE",
        status=503,
    )


# Tool Calling 에이전트 채팅/도구 선택 호출 함수
# - 메시지 히스토리와 도구 스키마를 전달하여 응답 메시지 객체 반환
def chat_with_tools(messages: list[dict[str, Any]], tools: list[dict[str, Any]]) -> Any:
    """대화 메시지와 Tool 정의를 전달해 LLM 응답 메시지를 반환하는 함수"""
    # OpenAI 클라이언트 생성
    client = _create_client()
    try:
        # 도구 호출을 포함한 Chat Completions 실행
        response = client.chat.completions.create(
            model=settings.llm_model, messages=messages, tools=tools, tool_choice="auto"
        )
        # 첫 번째 선택지의 메시지 객체 반환
        return response.choices[0].message
    except Exception as exc:
        # 호출 실패 시 도메인/서비스 계층에서 처리할 수 있는 LLMClientError로 래핑
        raise LLMClientError(
            f"LLM Tool Calling 실행에 실패했습니다: {exc}",
            code="LLM_UNAVAILABLE",
            status=503,
        ) from exc


"""
OpenAI 호환 Chat Completions 기반의 보고서 요약(brief/structured) 및 Tool Calling 호출 클라이언트를 구현하였다.
재시도 횟수·타임아웃 설정 반영, 구조화 요약 JSON 필드 검증 및 예외 래핑을 통해 상위 서비스 계층과 분리하였다.
"""
