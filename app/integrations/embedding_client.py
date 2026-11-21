"""보고서 개요 텍스트를 E5 384차원 벡터로 변환하고 정규화 및 SHA-256 해시를 생성하는 임베딩 클라이언트 모듈"""

# 해시 생성, 타이핑, 수치 연산 및 SentenceTransformer 모델 로더 import
# - hashlib : 개요 원문 SHA-256 해시 계산
# - Any : SentenceTransformer 동적/지연 로딩 타입 힌트
# - numpy : 벡터 정규화 및 리스트 변환
# - SentenceTransformer : HuggingFace 임베딩 모델 로더
import hashlib
from typing import Any

import numpy as np
from sentence_transformers import SentenceTransformer

# 애플리케이션 설정 객체 import
# - settings : 임베딩 모델명 및 벡터 차원 설정 조회
from app.core.config import settings

# 임베딩 모델 싱글턴 캐시 변수
# - 최초 요청 시 모델을 메모리에 로드하여 재사용
_EMBEDDING_MODEL: Any = None


# 임베딩 모델 인스턴스 반환 헬퍼 함수
# - 로드되지 않은 경우 settings.embedding_model_name으로 초기화
def get_embedding_model() -> Any:
    """SentenceTransformer 임베딩 모델을 지연 로딩하여 반환하는 함수"""
    global _EMBEDDING_MODEL
    # 모델이 아직 로드되지 않았을 때만 초기화
    if _EMBEDDING_MODEL is None:
        _EMBEDDING_MODEL = SentenceTransformer(settings.embedding_model_name)
    # 캐시된 모델 객체 반환
    return _EMBEDDING_MODEL


# 개요 텍스트의 SHA-256 해시 계산 함수
# - 64자리 16진수 소문자 문자열 반환
def compute_overview_hash(overview: str) -> str:
    """보고서 개요 문자열의 SHA-256 16진수 해시값을 계산하는 함수"""
    # UTF-8 인코딩 후 SHA-256 다이제스트 생성
    return hashlib.sha256(overview.encode("utf-8")).hexdigest()


# E5 입력 접두사 정규화 헬퍼 함수
# - multilingual-e5 계열 권장 접두사('passage: ' / 'query: ') 부여
def _format_e5_text(text: str, is_query: bool = False) -> str:
    """E5 모델 특성에 맞게 'query: ' 또는 'passage: ' 접두사를 부여하는 헬퍼 함수"""
    # 앞뒤 공백 제거 후 접두사 중복 여부 확인
    cleaned = text.strip()
    prefix = "query: " if is_query else "passage: "
    if cleaned.startswith(("query: ", "passage: ")):
        return cleaned
    # 접두사가 없으면 해당 접두사를 붙여 반환
    return f"{prefix}{cleaned}"


# 단일 텍스트를 384차원 임베딩 벡터로 변환하는 함수
# - L2 정규화 적용 및 차원 검증 수행
def embed_text(text: str, is_query: bool = False) -> list[float]:
    """입력 텍스트를 설정된 차원(기본 384)의 정규화된 부동소수점 벡터로 변환하는 함수"""
    # 빈 문자열 입력 방지
    if not text or not text.strip():
        raise ValueError("임베딩할 텍스트가 비어 있습니다.")
    # E5 접두사를 적용한 입력 문자열 구성
    formatted = _format_e5_text(text, is_query=is_query)
    # 임베딩 모델 호출 및 numpy 배열 변환
    model = get_embedding_model()
    raw_vec = model.encode([formatted], normalize_embeddings=True)
    vector = np.asarray(raw_vec[0], dtype=np.float32)
    # 설정된 임베딩 차원 일치 여부 검증
    expected_dim = settings.embedding_dimension
    if vector.shape[0] != expected_dim:
        raise ValueError(
            f"임베딩 차원 불일치: 기대값={expected_dim}, 실제값={vector.shape[0]}"
        )
    # Python float 리스트로 변환하여 반환
    return [float(x) for x in vector.tolist()]


# 보고서 개요 전용 임베딩 생성 헬퍼 함수
# - passage 접두사 기준으로 384차원 벡터 반환
def embed_overview(overview: str) -> list[float]:
    """보고서 개요(overview)를 저장/검색용 패시지 벡터로 변환하는 함수"""
    # is_query=False로 개요 벡터 생성
    return embed_text(overview, is_query=False)


# 검색 질의 전용 임베딩 생성 헬퍼 함수
# - query 접두사 기준으로 384차원 벡터 반환
def embed_query(query: str) -> list[float]:
    """검색 질의(query)를 유사도 비교용 쿼리 벡터로 변환하는 함수"""
    # is_query=True로 질의 벡터 생성
    return embed_text(query, is_query=True)


"""
SentenceTransformer 기반의 E5 임베딩 클라이언트와 SHA-256 개요 해시 계산 함수를 구현하였다.
query/passage 접두사 처리, L2 정규화, 설정 차원(384) 검증 및 모델 지연 로딩으로 재사용성과 안정성을 확보하였다.
"""
