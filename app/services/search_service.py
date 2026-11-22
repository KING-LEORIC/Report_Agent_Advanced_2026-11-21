"""키워드 매칭과 pgvector 코사인 유사도를 결합한 보고서 검색(API-07) 서비스 모듈"""

# SQLAlchemy 세션 타입 import
# - Session : DB 트랜잭션 및 조회 세션 타입
from sqlalchemy.orm import Session

# 임베딩 클라이언트 및 리포지토리 함수 import
# - embed_query : 검색 질의(query)를 E5 384차원 벡터로 변환
# - repo : 키워드 검색, 벡터 검색 및 보고서/상세 조회 함수군
from app.integrations.embedding_client import embed_query
from app.repositories import report_repository as repo
from app.schemas.report import (
    SimilarSearchMatch,
    SimilarSearchRequest,
    SimilarSearchResponse,
)


# API-07: 키워드 + pgvector 시맨틱 유사도 결합 검색 서비스 함수
def search_similar_reports(
    db: Session, payload: SimilarSearchRequest
) -> SimilarSearchResponse:
    """질의어와 일치하는 키워드 후보 및 pgvector 코사인 유사도 후보를 결합해 최고 일치 보고서를 반환하는 함수"""
    # 질의 문자열 앞뒤 공백 정리
    cleaned_query = payload.query.strip()

    # 1. 키워드 기반 후보 조회
    keyword_ids = repo.search_reports_by_keyword(
        db=db,
        query=cleaned_query,
        category_code=payload.category_code,
        limit=payload.keyword_limit,
    )
    keyword_set = set(keyword_ids)

    # 2. 질의 임베딩 생성 및 pgvector 코사인 유사도 후보 조회
    similarity_by_id: dict[int, float] = {}
    try:
        query_vector = embed_query(cleaned_query)
        vector_rows = repo.search_reports_by_vector(
            db=db,
            query_vector=query_vector,
            category_code=payload.category_code,
            limit=payload.semantic_limit,
        )
        similarity_by_id = {rep_id: score for rep_id, score in vector_rows}
    except (ValueError, RuntimeError, OSError):
        # 임베딩/벡터 조회 실패 시 키워드 매칭 결과만으로 폴백 진행
        similarity_by_id = {}

    # 후보 report_id 통합 (키워드 후보 + 시맨틱 후보)
    candidate_ids: list[int] = []
    for rep_id in keyword_ids:
        if rep_id not in candidate_ids:
            candidate_ids.append(rep_id)
    for rep_id in similarity_by_id:
        if rep_id not in candidate_ids:
            candidate_ids.append(rep_id)

    # 후보가 전혀 없으면 not_found 응답 반환
    if not candidate_ids:
        return SimilarSearchResponse(
            status="not_found", query=cleaned_query, best_match=None
        )

    # 후보별 점수 산정: 키워드 일치 가중치 + 코사인 유사도
    best_match: SimilarSearchMatch | None = None
    best_score: float = -1.0

    for rep_id in candidate_ids:
        report = repo.get_report_by_id(db, rep_id)
        if report is None:
            continue
        detail_obj = repo.get_detail_record(db, report)
        if detail_obj is None:
            continue

        is_kw_match = rep_id in keyword_set
        cos_sim = similarity_by_id.get(rep_id)
        # 결합 점수 계산 (키워드 일치 시 0.5 보너스 부여)
        combined_score = (0.5 if is_kw_match else 0.0) + (
            cos_sim if cos_sim is not None else 0.0
        )

        if combined_score > best_score:
            best_score = combined_score
            best_match = SimilarSearchMatch(
                report_id=int(report.report_id),
                title=detail_obj.title,
                category_code=report.category.code,
                overview=report.overview,
                keyword_match=is_kw_match,
                cosine_similarity=round(cos_sim, 6) if cos_sim is not None else None,
            )

    if best_match is None:
        return SimilarSearchResponse(
            status="not_found", query=cleaned_query, best_match=None
        )

    return SimilarSearchResponse(
        status="found", query=cleaned_query, best_match=best_match
    )


"""
키워드 매칭 후보와 pgvector 코사인 유사도 검색 결과를 결합해 최고 일치 보고서(best_match)를 선정하는 서비스를 구현하였다.
벡터 임베딩 조회 실패 시에도 키워드 검색 결과로 안전하게 폴백되도록 구성하였다.
"""
