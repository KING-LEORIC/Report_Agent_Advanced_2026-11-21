"""보고서 조회, 하이브리드 유사도 검색 및 에이전트 질의 응답을 처리하는 서비스 모듈"""

from __future__ import annotations

# 타입 힌트 및 SQLAlchemy SQL 실행·세션 모듈 import
# - Any : 동적 딕셔너리 및 반환 타입 표현
# - text : 파라미터 바인딩이 포함된 SQL 쿼리 실행
# - Session : SQLAlchemy 데이터베이스 세션 타입
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session


# 보고서 도메인 서비스 클래스
# - 단일 보고서 조회, 키워드+의미 하이브리드 검색 및 에이전트 질의 응답 조합
class AgentService:
    """보고서 조회, 하이브리드 검색 및 에이전트 질의 처리를 담당하는 서비스 클래스"""

    def __init__(self, db: Session) -> None:
        """데이터베이스 세션을 주입받아 AgentService 인스턴스를 초기화하는 생성자"""
        # SQLAlchemy 세션 인스턴스 보관
        self.db = db

    # 단일 보고서 상세 조회 메서드
    # - reports와 6종 상세 테이블을 LEFT JOIN하여 제목·본문·작성자·시각까지 통합 조회
    def get_report_by_id(self, report_id: int) -> dict[str, Any] | None:
        """지정한 report_id에 해당하는 보고서 한 건을 딕셔너리로 반환하는 메서드"""
        # 6종 상세 테이블과 조인하여 공통 메타 및 상세 필드 조회
        row = (
            self.db.execute(
                text(
                    """
                    SELECT
                        r.report_id,
                        r.category_id,
                        rc.code AS category_code,
                        r.overview,
                        r.index_status,
                        r.revision,
                        COALESCE(
                            er.title, dw.title, rp.title, dp.title, pr.title, mm.title
                        ) AS title,
                        COALESCE(
                            er.content, dw.content, rp.content, dp.content, pr.content, mm.content
                        ) AS content,
                        COALESCE(
                            er.author, dw.author, rp.author, dp.author, pr.author, mm.author
                        ) AS author,
                        COALESCE(
                            er.create_at, dw.create_at, rp.create_at, dp.create_at, pr.create_at, mm.create_at
                        ) AS create_at,
                        COALESCE(
                            er.update_at, dw.update_at, rp.update_at, dp.update_at, pr.update_at, mm.update_at
                        ) AS update_at
                    FROM reports AS r
                    LEFT JOIN report_categories AS rc ON rc.category_id = r.category_id
                    LEFT JOIN experiment_reports AS er ON er.report_id = r.report_id
                    LEFT JOIN daily_work_reports AS dw ON dw.report_id = r.report_id
                    LEFT JOIN research_plans AS rp ON rp.report_id = r.report_id
                    LEFT JOIN data_processing_reports AS dp ON dp.report_id = r.report_id
                    LEFT JOIN prompt_reports AS pr ON pr.report_id = r.report_id
                    LEFT JOIN meeting_minutes AS mm ON mm.report_id = r.report_id
                    WHERE r.report_id = :report_id
                    """
                ),
                {"report_id": report_id},
            )
            .mappings()
            .first()
        )
        # 조회 결과가 없으면 None 반환, 있으면 일반 dict로 변환하여 반환
        return dict(row) if row is not None else None

    # category_code(카테고리 코드 문자열 또는 숫자 문자열)를 category_id 정수로 변환하는 헬퍼 메서드
    # - 코드 문자열(예: EXPERIMENT) 조회 및 숫자 문자열 정수 변환 지원
    def _resolve_category_id(self, category_code: str | None) -> int | None:
        """category_code를 reports.category_id 정수 값으로 변환하는 헬퍼 메서드"""
        # 입력값이 없으면 None 반환
        if category_code is None:
            return None
        cleaned = str(category_code).strip()
        if not cleaned:
            return None
        # 숫자 문자열인 경우 그대로 정수로 변환
        if cleaned.isdigit():
            return int(cleaned)
        # report_categories 테이블에서 코드명으로 category_id 조회
        row = (
            self.db.execute(
                text(
                    """
                    SELECT category_id
                    FROM report_categories
                    WHERE UPPER(code) = UPPER(:code)
                    """
                ),
                {"code": cleaned},
            )
            .mappings()
            .first()
        )
        return int(row["category_id"]) if row is not None else None

    # 하이브리드 유사도 검색 메서드
    # - 키워드 검색 결과와 의미 검색 후보를 RRF 기반으로 합산 및 정렬
    def search_similar_reports(
        self,
        query: str,
        category_code: str | None = None,
        keyword_limit: int = 20,
        semantic_limit: int = 20,
    ) -> dict[str, Any]:
        """질의어와 카테고리 필터를 바탕으로 하이브리드 검색 결과를 반환하는 메서드"""
        # 검색어 양끝 공백 제거 및 빈 질의어 조기 반환 처리
        cleaned_query = query.strip()
        if not cleaned_query:
            return {
                "query": query,
                "category_code": category_code,
                "keyword_limit": keyword_limit,
                "semantic_limit": semantic_limit,
                "results": [],
                "total": 0,
            }

        # 카테고리 필터를 정수형 category_id로 변환
        resolved_category_id = self._resolve_category_id(category_code)

        # 개요 및 6종 상세 테이블 제목/본문 대상 ILIKE 및 전문 검색 쿼리 정의 (CAST로 파라미터 타입 명시)
        keyword_sql = """
            SELECT
                r.report_id,
                r.category_id,
                rc.code AS category_code,
                r.overview,
                r.index_status,
                r.revision,
                COALESCE(
                    er.title, dw.title, rp.title, dp.title, pr.title, mm.title, ''
                ) AS title,
                ts_rank_cd(
                    to_tsvector(
                        'simple',
                        COALESCE(r.overview, '') || ' ' ||
                        COALESCE(
                            er.title, dw.title, rp.title, dp.title, pr.title, mm.title, ''
                        ) || ' ' ||
                        COALESCE(
                            er.content, dw.content, rp.content, dp.content, pr.content, mm.content, ''
                        )
                    ),
                    plainto_tsquery('simple', CAST(:query AS text))
                ) AS keyword_score
            FROM reports AS r
            LEFT JOIN report_categories AS rc ON rc.category_id = r.category_id
            LEFT JOIN experiment_reports AS er ON er.report_id = r.report_id
            LEFT JOIN daily_work_reports AS dw ON dw.report_id = r.report_id
            LEFT JOIN research_plans AS rp ON rp.report_id = r.report_id
            LEFT JOIN data_processing_reports AS dp ON dp.report_id = r.report_id
            LEFT JOIN prompt_reports AS pr ON pr.report_id = r.report_id
            LEFT JOIN meeting_minutes AS mm ON mm.report_id = r.report_id
            WHERE (
                r.overview ILIKE CAST(:like_query AS text)
                OR COALESCE(er.title, dw.title, rp.title, dp.title, pr.title, mm.title, '') ILIKE CAST(:like_query AS text)
                OR COALESCE(er.content, dw.content, rp.content, dp.content, pr.content, mm.content, '') ILIKE CAST(:like_query AS text)
                OR to_tsvector(
                    'simple',
                    COALESCE(r.overview, '') || ' ' ||
                    COALESCE(
                        er.title, dw.title, rp.title, dp.title, pr.title, mm.title, ''
                    ) || ' ' ||
                    COALESCE(
                        er.content, dw.content, rp.content, dp.content, pr.content, mm.content, ''
                    )
                ) @@ plainto_tsquery('simple', CAST(:query AS text))
            )
            AND (CAST(:category_id AS integer) IS NULL OR r.category_id = CAST(:category_id AS integer))
            ORDER BY keyword_score DESC, r.report_id DESC
            LIMIT CAST(:keyword_limit AS integer)
        """
        # 키워드 검색 쿼리 실행 및 매핑 행 목록 추출
        keyword_rows = (
            self.db.execute(
                text(keyword_sql),
                {
                    "query": cleaned_query,
                    "like_query": f"%{cleaned_query}%",
                    "category_id": resolved_category_id,
                    "keyword_limit": keyword_limit,
                },
            )
            .mappings()
            .all()
        )

        # 의미 검색 후보 목록 조회 쿼리 정의 (CAST로 NULL 파라미터 타입 모호성 방지)
        semantic_sql = """
            SELECT
                r.report_id,
                r.category_id,
                rc.code AS category_code,
                r.overview,
                r.index_status,
                r.revision,
                COALESCE(
                    er.title, dw.title, rp.title, dp.title, pr.title, mm.title, ''
                ) AS title,
                0.0::float AS semantic_score
            FROM reports AS r
            LEFT JOIN report_categories AS rc ON rc.category_id = r.category_id
            LEFT JOIN experiment_reports AS er ON er.report_id = r.report_id
            LEFT JOIN daily_work_reports AS dw ON dw.report_id = r.report_id
            LEFT JOIN research_plans AS rp ON rp.report_id = r.report_id
            LEFT JOIN data_processing_reports AS dp ON dp.report_id = r.report_id
            LEFT JOIN prompt_reports AS pr ON pr.report_id = r.report_id
            LEFT JOIN meeting_minutes AS mm ON mm.report_id = r.report_id
            WHERE (CAST(:category_id AS integer) IS NULL OR r.category_id = CAST(:category_id AS integer))
            ORDER BY r.report_id DESC
            LIMIT CAST(:semantic_limit AS integer)
        """
        # 의미 검색 후보 쿼리 실행
        semantic_rows = (
            self.db.execute(
                text(semantic_sql),
                {"category_id": resolved_category_id, "semantic_limit": semantic_limit},
            )
            .mappings()
            .all()
        )

        # 키워드 검색 결과에 RRF(k=60) 순위 점수를 부여하여 병합 맵 구성
        merged: dict[int, dict[str, Any]] = {}
        for rank, row in enumerate(keyword_rows, start=1):
            rid = int(row["report_id"])
            k_score = float(row["keyword_score"] or 0.0)
            rrf_k = 1.0 / (60.0 + rank)
            merged[rid] = {
                "report_id": rid,
                "category_id": row["category_id"],
                "category_code": row["category_code"],
                "title": row["title"],
                "overview": row["overview"],
                "index_status": row["index_status"],
                "revision": row["revision"],
                "keyword_score": k_score,
                "semantic_score": 0.0,
                "hybrid_score": round(rrf_k + k_score, 6),
                "matched_by": ["keyword"],
            }

        # 키워드 매칭이 있을 때만 의미 검색 후보 점수를 합산해 무관한 질의 결과 노출 방지
        has_keyword_hits = len(keyword_rows) > 0
        for rank, row in enumerate(semantic_rows, start=1):
            rid = int(row["report_id"])
            s_score = float(row["semantic_score"] or 0.0)
            rrf_s = 1.0 / (60.0 + rank) if has_keyword_hits else 0.0

            if rid in merged:
                # 기존 키워드 매칭 항목에 의미 검색 점수 누적 및 매칭 채널 추가
                merged[rid]["semantic_score"] = s_score
                merged[rid]["hybrid_score"] = round(
                    merged[rid]["hybrid_score"] + rrf_s + s_score, 6
                )
                if "semantic" not in merged[rid]["matched_by"]:
                    merged[rid]["matched_by"].append("semantic")
            elif has_keyword_hits:
                # 키워드 매칭이 존재할 경우 추가 의미 검색 후보 항목 등록
                merged[rid] = {
                    "report_id": rid,
                    "category_id": row["category_id"],
                    "category_code": row["category_code"],
                    "title": row["title"],
                    "overview": row["overview"],
                    "index_status": row["index_status"],
                    "revision": row["revision"],
                    "keyword_score": 0.0,
                    "semantic_score": s_score,
                    "hybrid_score": round(rrf_s + s_score, 6),
                    "matched_by": ["semantic"],
                }

        # 하이브리드 점수와 report_id 기준으로 내림차순 정렬
        ranked_results = sorted(
            merged.values(),
            key=lambda item: (item["hybrid_score"], item["report_id"]),
            reverse=True,
        )

        # 검색 조건 및 최종 결과 목록 반환
        return {
            "query": query,
            "category_code": category_code,
            "keyword_limit": keyword_limit,
            "semantic_limit": semantic_limit,
            "results": ranked_results,
            "total": len(ranked_results),
        }

    # 에이전트 질의 응답 생성 메서드
    # - 상위 검색 결과를 바탕으로 요약 답변 문자열과 출처 목록 구성
    def answer_report_query(
        self, query: str, category_code: str | None = None, top_k: int = 5
    ) -> dict[str, Any]:
        """질의에 대한 관련 보고서를 검색하여 요약 답변과 출처 정보를 반환하는 메서드"""
        # 하이브리드 검색 수행 후 상위 top_k 건 추출
        search_res = self.search_similar_reports(
            query=query,
            category_code=category_code,
            keyword_limit=max(top_k * 2, 10),
            semantic_limit=max(top_k * 2, 10),
        )
        top_items = search_res["results"][:top_k]

        # 검색 결과가 없는 경우 안내 문구와 빈 출처 목록 반환
        if not top_items:
            return {
                "query": query,
                "category_code": category_code,
                "top_k": top_k,
                "answer": f"'{query}'와(과) 관련된 보고서를 찾지 못했습니다.",
                "sources": [],
            }

        # 답변 본문 요약 라인과 출처 메타데이터 목록 생성
        summaries = [
            f"[{item['report_id']}] {item['title'] or item['overview']} (점수: {item['hybrid_score']})"
            for item in top_items
        ]
        sources = [
            {
                "report_id": item["report_id"],
                "title": item["title"],
                "overview": item["overview"],
                "category_id": item["category_id"],
                "category_code": item["category_code"],
                "revision": item["revision"],
                "score": item["hybrid_score"],
            }
            for item in top_items
        ]

        # 에이전트 질의 응답 딕셔너리 반환
        return {
            "query": query,
            "category_code": category_code,
            "top_k": top_k,
            "answer": "관련 보고서 검색 결과입니다:\n" + "\n".join(summaries),
            "sources": sources,
        }


"""
PostgreSQL 파라미터 타입 추론 모호성(AmbiguousParameter)을 해소하기 위해 바인딩 파라미터에 CAST를 명시하였다.
ORM 모델(app/models/report.py) 구조에 맞춰 reports, report_categories 및 6종 상세 테이블을 조인하도록 반영하였다.
"""
