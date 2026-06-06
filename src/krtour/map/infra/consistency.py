"""``krtour.map.infra.consistency`` — feature 정합성 검사 (ADR-033).

F1~F4 + Phase 2 케이스를 raw SQL(ADR-004)로 검사하고 결과를
``ops.feature_consistency_reports``에 1 배치 = 1 행으로 영속화한다. Dagster
게이트(``mv_refresh`` swap 차단)는 ``infra.batch_dag``가 ``severity_max``를 보고
처리한다.

검사 케이스
-----------
- **F1** orphan source_record — ``source_links``가 하나도 없는
  ``provider_sync.source_records`` (ETL transform 누수 → Feature 미생성).
  severity=ERROR.
- **F2** detail 누락 — detail-bearing kind(place/event/notice/route/area)인데
  ``features.detail`` JSONB가 비어 있음 (ADR-018 위배). severity=ERROR.
  (price/weather는 detail을 갖지 않음 — DETAIL_MODELS 제외.)
- **F3** CRS drift — ``coord``가 있는데 ``coord_5179`` ≠ ST_Transform(coord,5179)
  (ADR-012 STORED generated column 신뢰 손상). severity=ERROR.
- **F4** dedup 백로그 — ``ops.dedup_review_queue`` 미해소(pending) 수가
  ``DEDUP_PENDING_WARN_THRESHOLD``(baseline) 초과. severity=**WARN**(observe-only,
  적재 차단 안 함). F1~F3과 달리 행별 위반이 아니라 **임계 초과 집계** — 초과 시
  count=pending 수, 이하면 OK. (SPRINT-4 §2.3, Sprint 4b.)
- **F5** provider last_success SLA — active provider sync cursor의 마지막 성공 시각이
  SLA를 넘겼거나 아직 성공 기록이 없으면 severity=**WARN**. 기본 SLA는 24h이고,
  ``ops.provider_refresh_policies.system_interval_seconds``가 있으면 그 값을 우선한다.
- **F6** opening_hours 모순 — 같은 요일 안에서 ``open.time > close.time``인
  period. severity=ERROR. 다음 요일로 넘어가는 자정 통과 구간과 close 없는 24/7
  표현은 허용한다.
- **F7** cross-provider dedup score 회귀 — unresolved cross-provider 후보의 현재
  ``core.scoring`` 재계산 점수가 큐 저장 baseline보다 기본 10점 이상 낮아지면
  severity=**WARN**.
- **F8** file object orphan — 객체 저장소 스냅샷(``known_file_objects``)과
  ``feature.feature_files`` 메타데이터가 서로 어긋나면 severity=**WARN**.
  ``feature_files`` 테이블이 아직 없거나 스냅샷이 제공되지 않은 방향은 검사하지
  않고 OK로 둔다.

F1/F2/F3/F6은 ``CONSISTENCY_CASES``(행별 정적 SQL)로, F4/F5/F7/F8은
``run_consistency_checks``의 임계/정책/재계산/객체 스냅샷 분기로 추가된다.

ADR 참조: ADR-002(async) / ADR-004(raw SQL) / ADR-012 / ADR-018 / ADR-033.
"""

from __future__ import annotations

import json
from collections.abc import Iterable
from dataclasses import dataclass
from decimal import Decimal
from typing import TYPE_CHECKING, Any, Final
from uuid import uuid4

from sqlalchemy import text

from krtour.map.core.scoring import score_pair
from krtour.map.dto import Coordinate

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

__all__ = [
    "CaseSpec",
    "CaseResult",
    "ConsistencyReport",
    "FileObjectRef",
    "CONSISTENCY_CASES",
    "DEDUP_PENDING_WARN_THRESHOLD",
    "DEDUP_SCORE_REGRESSION_WARN_POINTS",
    "PROVIDER_LAST_SUCCESS_WARN_SECONDS",
    "build_report",
    "run_consistency_checks",
]

# severity 순위 — severity_max 계산용.
_SEVERITY_ORDER: Final[dict[str, int]] = {"OK": 0, "WARN": 1, "ERROR": 2}

# 케이스별 sample id 기본 상한 (리포트 비대화 방지).
_SAMPLE_LIMIT: Final[int] = 20

# F4 baseline (ADR-033 §2.3) — dedup_review_queue 미해소(pending) 백로그가 이 수를
# 초과하면 severity=WARN(observe-only, Phase 1은 게이트 없음). **provisional** — MOIS
# Step A bulk가 큐를 채운 뒤 첫 적재 후보 수 기준으로 재조정한다(SPRINT-4 §2.3
# "후반에 baseline 조정"). 운영 시 호출자가 ``dedup_pending_threshold`` 인자로 덮어쓸
# 수 있다.
DEDUP_PENDING_WARN_THRESHOLD: Final[int] = 1000

# F5 기본 SLA — provider별 refresh policy가 없으면 active sync cursor가 24h 넘게
# 성공하지 못한 상태를 WARN으로 본다(ADR-033 Phase 2 observe-only).
PROVIDER_LAST_SUCCESS_WARN_SECONDS: Final[int] = 24 * 60 * 60

# F7 기본 허용 회귀폭 — dedup_review_queue에 저장된 baseline total_score(0~100) 대비
# 현재 core.scoring 재계산 점수가 이 점수 이상 낮아지면 WARN으로 본다.
DEDUP_SCORE_REGRESSION_WARN_POINTS: Final[float] = 10.0

# detail-bearing kind (DETAIL_MODELS 매핑 — price/weather 제외, ADR-018).
_DETAIL_KINDS_SQL: Final[str] = "'place','event','notice','route','area'"
_FileObjectKey = tuple[str, str, str]


@dataclass(frozen=True)
class FileObjectRef:
    """F8 비교에 사용하는 객체 저장소 스냅샷 항목."""

    storage_backend: str
    bucket: str
    object_key: str

    @property
    def key(self) -> _FileObjectKey:
        return (self.storage_backend, self.bucket, self.object_key)

    def sample_id(self) -> str:
        return f"{self.storage_backend}:{self.bucket}:{self.object_key}"


@dataclass(frozen=True)
class CaseSpec:
    """정합성 케이스 정의. ``sql``은 위반 row의 식별자를 ``id``로 SELECT한다."""

    code: str
    severity: str
    description: str
    sql: str


# F1/F2/F3/F6. 각 SQL은 위반 식별자를 ``AS id``로 반환.
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
    CaseSpec(
        code="F6",
        severity="ERROR",
        description=("opening_hours 모순 (같은 요일 period에서 open.time > close.time, ADR-019)"),
        sql=(
            "WITH opening_periods AS ("
            "  SELECT f.feature_id, period "
            "  FROM feature.features f "
            "  CROSS JOIN LATERAL jsonb_path_query("
            "    f.detail, '$.business_hours.periods[*] ? (@.close != null)'"
            "  ) AS period "
            "  WHERE f.deleted_at IS NULL "
            "  UNION ALL "
            "  SELECT f.feature_id, period "
            "  FROM feature.features f "
            "  CROSS JOIN LATERAL jsonb_path_query("
            "    f.detail, '$.opening_hours.periods[*] ? (@.close != null)'"
            "  ) AS period "
            "  WHERE f.deleted_at IS NULL "
            "  UNION ALL "
            "  SELECT f.feature_id, period "
            "  FROM feature.features f "
            "  CROSS JOIN LATERAL jsonb_path_query("
            "    f.detail, '$.business_hours.special_days[*].periods[*] ? (@.close != null)'"
            "  ) AS period "
            "  WHERE f.deleted_at IS NULL "
            "  UNION ALL "
            "  SELECT f.feature_id, period "
            "  FROM feature.features f "
            "  CROSS JOIN LATERAL jsonb_path_query("
            "    f.detail, '$.opening_hours.special_days[*].periods[*] ? (@.close != null)'"
            "  ) AS period "
            "  WHERE f.deleted_at IS NULL "
            ") "
            "SELECT DISTINCT feature_id AS id "
            "FROM opening_periods "
            "WHERE COALESCE(period->'open'->>'day', '') ~ '^[0-6]$' "
            "  AND COALESCE(period->'close'->>'day', '') ~ '^[0-6]$' "
            "  AND COALESCE(period->'open'->>'time', '') ~ '^([01][0-9]|2[0-3])[0-5][0-9]$' "
            "  AND COALESCE(period->'close'->>'time', '') ~ '^([01][0-9]|2[0-3])[0-5][0-9]$' "
            "  AND (period->'open'->>'day')::int = (period->'close'->>'day')::int "
            "  AND (period->'open'->>'time') > (period->'close'->>'time')"
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
    severity_max = max(violated, key=_SEVERITY_ORDER.__getitem__) if violated else "OK"
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


_F4_PENDING_COUNT_SQL: Final[str] = (
    "SELECT count(*) FROM ops.dedup_review_queue WHERE status = 'pending'"
)
_F4_PENDING_SAMPLE_SQL: Final[str] = (
    "SELECT review_key FROM ops.dedup_review_queue WHERE status = 'pending' "
    "ORDER BY total_score DESC LIMIT :lim"
)

_F5_PROVIDER_LAST_SUCCESS_COUNT_SQL: Final[str] = (
    "WITH stale_provider_sync AS ("
    "  SELECT s.provider, s.dataset_key, s.sync_scope "
    "  FROM provider_sync.provider_sync_state s "
    "  LEFT JOIN ops.provider_refresh_policies p "
    "    ON p.provider = s.provider AND p.dataset_key = s.dataset_key "
    "  WHERE s.status = 'active' "
    "    AND COALESCE(p.enabled, true) "
    "    AND ("
    "      s.last_success_at IS NULL "
    "      OR s.last_success_at < now() - ("
    "        COALESCE(p.system_interval_seconds, :sla_seconds)::double precision "
    "        * interval '1 second'"
    "      )"
    "    )"
    ") "
    "SELECT count(*) FROM stale_provider_sync"
)
_F5_PROVIDER_LAST_SUCCESS_SAMPLE_SQL: Final[str] = (
    "WITH stale_provider_sync AS ("
    "  SELECT "
    "    s.provider || ':' || s.dataset_key || ':' || s.sync_scope AS id, "
    "    s.provider, s.dataset_key, s.sync_scope "
    "  FROM provider_sync.provider_sync_state s "
    "  LEFT JOIN ops.provider_refresh_policies p "
    "    ON p.provider = s.provider AND p.dataset_key = s.dataset_key "
    "  WHERE s.status = 'active' "
    "    AND COALESCE(p.enabled, true) "
    "    AND ("
    "      s.last_success_at IS NULL "
    "      OR s.last_success_at < now() - ("
    "        COALESCE(p.system_interval_seconds, :sla_seconds)::double precision "
    "        * interval '1 second'"
    "      )"
    "    )"
    ") "
    "SELECT id FROM stale_provider_sync "
    "ORDER BY provider, dataset_key, sync_scope "
    "LIMIT :lim"
)

_F7_DEDUP_SCORE_ROWS_SQL: Final[str] = """
WITH primary_sources AS (
  SELECT feature_id, provider, dataset_key
  FROM (
    SELECT
      sl.feature_id,
      sr.provider,
      sr.dataset_key,
      row_number() OVER (
        PARTITION BY sl.feature_id
        ORDER BY sr.imported_at DESC NULLS LAST, sr.source_record_key
      ) AS rn
    FROM provider_sync.source_links AS sl
    JOIN provider_sync.source_records AS sr
      ON sr.source_record_key = sl.source_record_key
    WHERE sl.is_primary_source
  ) AS ranked
  WHERE rn = 1
)
SELECT
  dq.review_key,
  dq.feature_id_a,
  dq.feature_id_b,
  dq.total_score::float AS baseline_score,
  fa.name AS name_a,
  fb.name AS name_b,
  fa.category AS category_a,
  fb.category AS category_b,
  x_extension.ST_X(fa.coord) AS lon_a,
  x_extension.ST_Y(fa.coord) AS lat_a,
  x_extension.ST_X(fb.coord) AS lon_b,
  x_extension.ST_Y(fb.coord) AS lat_b
FROM ops.dedup_review_queue AS dq
JOIN feature.features AS fa
  ON fa.feature_id = dq.feature_id_a
JOIN feature.features AS fb
  ON fb.feature_id = dq.feature_id_b
JOIN primary_sources AS psa
  ON psa.feature_id = dq.feature_id_a
JOIN primary_sources AS psb
  ON psb.feature_id = dq.feature_id_b
WHERE dq.status = 'pending'
  AND psa.provider <> psb.provider
ORDER BY dq.total_score DESC, dq.review_key
"""

_F8_FEATURE_FILES_TABLE_EXISTS_SQL: Final[str] = (
    "SELECT to_regclass('feature.feature_files') IS NOT NULL"
)
_F8_FEATURE_FILE_METADATA_ROWS_SQL: Final[str] = """
SELECT
  ff.file_id,
  ff.feature_id,
  ff.storage_backend,
  ff.bucket,
  ff.object_key,
  (f.feature_id IS NULL OR f.deleted_at IS NOT NULL) AS feature_missing
FROM feature.feature_files AS ff
LEFT JOIN feature.features AS f
  ON f.feature_id = ff.feature_id
ORDER BY ff.storage_backend, ff.bucket, ff.object_key, ff.file_id
"""


async def _check_f4_dedup_backlog(
    session: AsyncSession, *, threshold: int, sample_limit: int
) -> CaseResult:
    """F4 — pending dedup 백로그가 baseline 초과 시 WARN (임계 집계 케이스)."""
    pending = int((await session.execute(text(_F4_PENDING_COUNT_SQL))).scalar_one())
    over = pending > threshold
    sample_ids: list[str] = []
    if over:
        rows = (
            (await session.execute(text(_F4_PENDING_SAMPLE_SQL), {"lim": sample_limit}))
            .scalars()
            .all()
        )
        sample_ids = [str(r) for r in rows]
    return CaseResult(
        code="F4",
        severity="WARN",
        description=(
            f"dedup_review_queue 미해소(pending) 백로그 baseline {threshold} 초과 "
            f"(현재 {pending}, ADR-033 F4 — observe-only)"
        ),
        # 초과 시에만 위반(count>0) — 이하면 OK. count는 현재 pending 수.
        count=pending if over else 0,
        sample_ids=sample_ids,
    )


async def _check_f5_provider_last_success_sla(
    session: AsyncSession, *, sla_seconds: int, sample_limit: int
) -> CaseResult:
    """F5 — active provider cursor가 SLA 안에 성공하지 못하면 WARN."""
    params = {"sla_seconds": sla_seconds}
    count = int(
        (await session.execute(text(_F5_PROVIDER_LAST_SUCCESS_COUNT_SQL), params)).scalar_one()
    )
    sample_ids: list[str] = []
    if count:
        rows = (
            (
                await session.execute(
                    text(_F5_PROVIDER_LAST_SUCCESS_SAMPLE_SQL),
                    {"sla_seconds": sla_seconds, "lim": sample_limit},
                )
            )
            .scalars()
            .all()
        )
        sample_ids = [str(r) for r in rows]
    return CaseResult(
        code="F5",
        severity="WARN",
        description=(
            "provider_sync_state active cursor last_success SLA 초과 "
            f"(기본 {sla_seconds}s, provider policy interval 우선, ADR-033 F5)"
        ),
        count=count,
        sample_ids=sample_ids,
    )


def _coord_from_row(row: Any, lon_key: str, lat_key: str) -> Coordinate | None:
    lon = row[lon_key]
    lat = row[lat_key]
    if lon is None or lat is None:
        return None
    return Coordinate(lon=Decimal(str(lon)), lat=Decimal(str(lat)))


def _build_f7_dedup_score_result(
    rows: Iterable[Any], *, regression_points: float, sample_limit: int
) -> CaseResult:
    """F7 SQL row를 현재 scoring 결과와 비교해 ``CaseResult``로 집계한다."""
    sample_ids: list[str] = []
    count = 0
    for row in rows:
        current_score = round(
            score_pair(
                name_a=str(row["name_a"]),
                name_b=str(row["name_b"]),
                coord_a=_coord_from_row(row, "lon_a", "lat_a"),
                coord_b=_coord_from_row(row, "lon_b", "lat_b"),
                cat_a={str(row["category_a"])},
                cat_b={str(row["category_b"])},
            )
            * 100,
            2,
        )
        baseline_score = float(row["baseline_score"])
        drop = round(baseline_score - current_score, 2)
        if drop >= regression_points:
            count += 1
            if len(sample_ids) < sample_limit:
                sample_ids.append(
                    f"{row['review_key']}:{row['feature_id_a']}:{row['feature_id_b']}:"
                    f"{baseline_score:.2f}->{current_score:.2f}"
                )
    return CaseResult(
        code="F7",
        severity="WARN",
        description=(
            "cross-provider dedup score baseline 대비 현재 score 회귀 "
            f"({regression_points:g}점 이상 하락, ADR-033 F7)"
        ),
        count=count,
        sample_ids=sample_ids,
    )


async def _check_f7_dedup_score_regression(
    session: AsyncSession, *, regression_points: float, sample_limit: int
) -> CaseResult:
    """F7 — unresolved cross-provider dedup 후보의 score baseline 회귀 WARN."""
    rows = (await session.execute(text(_F7_DEDUP_SCORE_ROWS_SQL))).mappings().all()
    return _build_f7_dedup_score_result(
        rows, regression_points=regression_points, sample_limit=sample_limit
    )


def _append_limited_sample(samples: list[str], sample: str, *, sample_limit: int) -> None:
    if len(samples) < sample_limit:
        samples.append(sample)


def _normalize_file_object_refs(
    known_file_objects: Iterable[FileObjectRef] | None,
) -> set[_FileObjectKey] | None:
    if known_file_objects is None:
        return None
    return {obj.key for obj in known_file_objects}


def _build_f8_file_object_orphan_result(
    rows: Iterable[Any],
    *,
    known_file_objects: Iterable[FileObjectRef] | None,
    sample_limit: int,
) -> CaseResult:
    """F8 metadata row와 객체 저장소 스냅샷을 비교해 orphan을 집계한다."""
    known_keys = _normalize_file_object_refs(known_file_objects)
    metadata_keys: set[_FileObjectKey] = set()
    count = 0
    sample_ids: list[str] = []

    for row in rows:
        key = (str(row["storage_backend"]), str(row["bucket"]), str(row["object_key"]))
        metadata_keys.add(key)
        key_sample = ":".join(key)
        if row["feature_missing"]:
            count += 1
            _append_limited_sample(
                sample_ids,
                f"metadata_without_active_feature:{key_sample}:{row['file_id']}:"
                f"{row['feature_id']}",
                sample_limit=sample_limit,
            )
        if known_keys is not None and key not in known_keys:
            count += 1
            _append_limited_sample(
                sample_ids,
                f"metadata_missing_object:{key_sample}:{row['file_id']}:"
                f"{row['feature_id']}",
                sample_limit=sample_limit,
            )

    if known_keys is not None:
        for key in sorted(known_keys - metadata_keys):
            count += 1
            _append_limited_sample(
                sample_ids,
                "object_missing_metadata:" + ":".join(key),
                sample_limit=sample_limit,
            )

    return CaseResult(
        code="F8",
        severity="WARN",
        description=(
            "file object orphan (feature_files metadata ↔ 객체 저장소 스냅샷 불일치, "
            "ADR-033 F8)"
        ),
        count=count,
        sample_ids=sample_ids,
    )


async def _check_f8_file_object_orphans(
    session: AsyncSession,
    *,
    known_file_objects: Iterable[FileObjectRef] | None,
    sample_limit: int,
) -> CaseResult:
    """F8 — feature_files metadata와 객체 저장소 스냅샷 불일치 WARN."""
    table_exists = bool(
        (await session.execute(text(_F8_FEATURE_FILES_TABLE_EXISTS_SQL))).scalar_one()
    )
    rows: Iterable[Any] = []
    if table_exists:
        rows = (
            (await session.execute(text(_F8_FEATURE_FILE_METADATA_ROWS_SQL)))
            .mappings()
            .all()
        )
    return _build_f8_file_object_orphan_result(
        rows,
        known_file_objects=known_file_objects,
        sample_limit=sample_limit,
    )


async def run_consistency_checks(
    session: AsyncSession,
    *,
    batch_id: str | None = None,
    persist: bool = True,
    sample_limit: int = _SAMPLE_LIMIT,
    dedup_pending_threshold: int = DEDUP_PENDING_WARN_THRESHOLD,
    provider_last_success_sla_seconds: int = PROVIDER_LAST_SUCCESS_WARN_SECONDS,
    dedup_score_regression_warn_points: float = DEDUP_SCORE_REGRESSION_WARN_POINTS,
    known_file_objects: Iterable[FileObjectRef] | None = None,
) -> ConsistencyReport:
    """F1~F8 정합성 검사 실행 + (옵션) ``ops.feature_consistency_reports`` 적재.

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
    dedup_pending_threshold:
        F4 baseline — pending dedup 백로그가 이 수를 초과하면 WARN. 기본
        ``DEDUP_PENDING_WARN_THRESHOLD``(provisional).
    provider_last_success_sla_seconds:
        F5 기본 SLA. ``ops.provider_refresh_policies.system_interval_seconds``가 있는
        provider/dataset은 policy 값을 우선 사용한다.
    dedup_score_regression_warn_points:
        F7 기본 허용 회귀폭. ``ops.dedup_review_queue.total_score`` baseline 대비 현재
        ``core.scoring`` 재계산 점수가 이 점수 이상 낮아지면 WARN으로 본다.
    known_file_objects:
        F8 객체 저장소 스냅샷. 제공되면 ``feature.feature_files`` metadata와 양방향
        비교한다. 미제공 시 DB metadata가 참조하는 feature 활성 여부만 검사한다.

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
                (
                    await session.execute(
                        text(f"SELECT id FROM ({spec.sql}) AS v LIMIT :lim"),  # noqa: S608
                        {"lim": sample_limit},
                    )
                )
                .scalars()
                .all()
            )
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

    # F4/F5/F7/F8 — 정적 SQL이 아닌 임계/정책/source join/object snapshot 케이스.
    cases.append(
        await _check_f4_dedup_backlog(
            session, threshold=dedup_pending_threshold, sample_limit=sample_limit
        )
    )
    cases.append(
        await _check_f5_provider_last_success_sla(
            session,
            sla_seconds=provider_last_success_sla_seconds,
            sample_limit=sample_limit,
        )
    )
    cases.append(
        await _check_f7_dedup_score_regression(
            session,
            regression_points=dedup_score_regression_warn_points,
            sample_limit=sample_limit,
        )
    )
    cases.append(
        await _check_f8_file_object_orphans(
            session,
            known_file_objects=known_file_objects,
            sample_limit=sample_limit,
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
