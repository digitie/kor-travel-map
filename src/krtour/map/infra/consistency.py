"""``krtour.map.infra.consistency`` — feature 정합성 검사 (ADR-033 Phase 1).

F1~F3 critical 케이스를 raw SQL(ADR-004)로 검사하고 결과를
``ops.feature_consistency_reports``에 1 배치 = 1 행으로 영속화한다. Dagster
게이트(``mv_refresh`` swap 차단)는 Phase 2(Sprint 5, ADR-033) — 본 모듈은
**관측만** 한다 (검사 결과를 보이게 만들 뿐, 적재를 차단하지 않음).

검사 케이스 (Phase 1)
---------------------
- **F1** orphan source_record — ``source_links``가 하나도 없는
  ``provider_sync.source_records`` (ETL transform 누수 → Feature 미생성).
  severity=ERROR.
- **F2** detail 누락 — detail-bearing kind(place/event/notice/route/area)인데
  ``features.detail`` JSONB가 비어 있음 (ADR-018 위배). severity=ERROR.
  (price/weather는 detail을 갖지 않음 — DETAIL_MODELS 제외.)
- **F3** CRS drift — ``coord``가 있는데 ``coord_5179`` ≠ ST_Transform(coord,5179)
  (ADR-012 STORED generated column 신뢰 손상). severity=ERROR.

F4~F8 + Dagster 게이트는 Phase 2(ADR-033). 본 모듈은 케이스를
``CONSISTENCY_CASES``로 선언만 추가하면 확장된다.

ADR 참조: ADR-002(async) / ADR-004(raw SQL) / ADR-012 / ADR-018 / ADR-033.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Final
from uuid import uuid4

from sqlalchemy import text

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

__all__ = [
    "CaseSpec",
    "CaseResult",
    "ConsistencyReport",
    "CONSISTENCY_CASES",
    "build_report",
    "run_consistency_checks",
]

# severity 순위 — severity_max 계산용.
_SEVERITY_ORDER: Final[dict[str, int]] = {"OK": 0, "WARN": 1, "ERROR": 2}

# 케이스별 sample id 기본 상한 (리포트 비대화 방지).
_SAMPLE_LIMIT: Final[int] = 20

# detail-bearing kind (DETAIL_MODELS 매핑 — price/weather 제외, ADR-018).
_DETAIL_KINDS_SQL: Final[str] = "'place','event','notice','route','area'"


@dataclass(frozen=True)
class CaseSpec:
    """정합성 케이스 정의. ``sql``은 위반 row의 식별자를 ``id``로 SELECT한다."""

    code: str
    severity: str
    description: str
    sql: str


# F1~F3 (ADR-033 Phase 1). 각 SQL은 위반 식별자를 ``AS id``로 반환.
CONSISTENCY_CASES: Final[tuple[CaseSpec, ...]] = (
    CaseSpec(
        code="F1",
        severity="ERROR",
        description="orphan source_record (source_links 없음 — ETL transform 누수)",
        sql=(
            "SELECT sr.source_record_key AS id "
            "FROM provider_sync.source_records sr "
            "LEFT JOIN provider_sync.source_links sl "
            "  ON sl.source_record_key = sr.source_record_key "
            "WHERE sl.source_record_key IS NULL"
        ),
    ),
    CaseSpec(
        code="F2",
        severity="ERROR",
        description="detail 누락 (detail-bearing kind인데 detail JSONB 비어있음, ADR-018)",
        sql=(
            "SELECT f.feature_id AS id "
            "FROM feature.features f "
            "WHERE f.deleted_at IS NULL "
            f"  AND f.kind IN ({_DETAIL_KINDS_SQL}) "
            "  AND (f.detail IS NULL OR f.detail = '{}'::jsonb)"
        ),
    ),
    CaseSpec(
        code="F3",
        severity="ERROR",
        description="CRS drift (coord_5179 ≠ ST_Transform(coord,5179), ADR-012)",
        sql=(
            "SELECT f.feature_id AS id "
            "FROM feature.features f "
            "WHERE f.coord IS NOT NULL "
            "  AND (f.coord_5179 IS NULL "
            "       OR ST_SRID(f.coord_5179) <> 5179 "
            "       OR NOT ST_DWithin(f.coord_5179, ST_Transform(f.coord, 5179), 0.01))"
        ),
    ),
)


@dataclass(frozen=True)
class CaseResult:
    """1 케이스 검사 결과 (count + sample)."""

    code: str
    severity: str
    description: str
    count: int
    sample_ids: list[str]

    @property
    def ok(self) -> bool:
        return self.count == 0

    def to_dict(self) -> dict[str, Any]:
        # 위반 0건이면 effective severity는 OK.
        return {
            "code": self.code,
            "severity": self.severity if self.count else "OK",
            "description": self.description,
            "count": self.count,
            "sample_ids": self.sample_ids,
        }


@dataclass(frozen=True)
class ConsistencyReport:
    """배치 1회 정합성 리포트 — ``ops.feature_consistency_reports`` 1 행."""

    batch_id: str
    severity_max: str
    cases: list[CaseResult]
    summary: dict[str, Any]

    def cases_json(self) -> list[dict[str, Any]]:
        return [c.to_dict() for c in self.cases]


def build_report(batch_id: str, cases: list[CaseResult]) -> ConsistencyReport:
    """케이스 결과를 집계해 ``ConsistencyReport`` 생성 (순수 함수, DB 무관).

    ``severity_max``는 위반(count>0)이 있는 케이스의 최고 severity, 없으면 ``OK``.
    """
    violated = [c.severity for c in cases if c.count > 0]
    severity_max = (
        max(violated, key=_SEVERITY_ORDER.__getitem__) if violated else "OK"
    )
    total = sum(c.count for c in cases)
    summary: dict[str, Any] = {
        "total_violations": total,
        "cases_evaluated": len(cases),
        "by_severity": {
            "ERROR": sum(c.count for c in cases if c.severity == "ERROR"),
            "WARN": sum(c.count for c in cases if c.severity == "WARN"),
        },
        "by_code": {c.code: c.count for c in cases},
    }
    return ConsistencyReport(
        batch_id=batch_id,
        severity_max=severity_max,
        cases=cases,
        summary=summary,
    )


async def run_consistency_checks(
    session: AsyncSession,
    *,
    batch_id: str | None = None,
    persist: bool = True,
    sample_limit: int = _SAMPLE_LIMIT,
) -> ConsistencyReport:
    """F1~F3 정합성 검사 실행 + (옵션) ``ops.feature_consistency_reports`` 적재.

    Parameters
    ----------
    session:
        async DB 세션. search_path에 ``x_extension`` 포함 필요 (ST_* 호출, ADR-008).
    batch_id:
        배치 식별자. 미지정 시 새 UUID 생성.
    persist:
        True면 리포트를 ``ops.feature_consistency_reports``에 INSERT (commit은
        호출자 책임 — Phase 1은 게이트 없이 관측만).
    sample_limit:
        케이스별 ``sample_ids`` 상한.

    Returns
    -------
    ConsistencyReport
        ``severity_max`` / ``cases`` / ``summary``.
    """
    bid = batch_id or str(uuid4())
    cases: list[CaseResult] = []
    for spec in CONSISTENCY_CASES:
        count = int(
            (
                await session.execute(
                    text(f"SELECT count(*) FROM ({spec.sql}) AS v")  # noqa: S608
                )
            ).scalar_one()
        )
        sample_ids: list[str] = []
        if count:
            rows = (
                await session.execute(
                    text(f"SELECT id FROM ({spec.sql}) AS v LIMIT :lim"),  # noqa: S608
                    {"lim": sample_limit},
                )
            ).scalars().all()
            sample_ids = [str(r) for r in rows]
        cases.append(
            CaseResult(
                code=spec.code,
                severity=spec.severity,
                description=spec.description,
                count=count,
                sample_ids=sample_ids,
            )
        )

    report = build_report(bid, cases)
    if persist:
        await session.execute(
            text(
                "INSERT INTO ops.feature_consistency_reports "
                "(batch_id, started_at, finished_at, severity_max, cases, summary) "
                "VALUES (:batch_id, now(), now(), :severity_max, "
                "CAST(:cases AS jsonb), CAST(:summary AS jsonb))"
            ),
            {
                "batch_id": bid,
                "severity_max": report.severity_max,
                "cases": json.dumps(report.cases_json(), ensure_ascii=False),
                "summary": json.dumps(report.summary, ensure_ascii=False),
            },
        )
    return report
