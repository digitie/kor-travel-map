"""``kortravelmap.infra.consistency`` — feature 정합성 검사 (ADR-033).

F1~F4 + Phase 2 케이스를 raw SQL(ADR-004)로 검사하고 결과를
``ops.feature_consistency_reports``에 1 배치 = 1 행으로 영속화한다. Dagster
게이트(``mv_refresh`` swap 차단)는 ``infra.batch_dag``가 ``severity_max``를 보고
처리한다.

검사 케이스
-----------
- **F1** orphan source entity — ``source_links``가 하나도 없는
  ``provider_sync.source_entities`` (ETL transform 누수 → Feature 미생성).
  severity=ERROR.
- **F2** detail 누락 — detail-bearing kind(place/event/notice/route/area)인데
  ``features.detail`` JSONB가 비어 있음 (ADR-018 위배). severity=ERROR.
  (price/weather는 detail을 갖지 않음 — DETAIL_MODELS 제외.)
- **F3** CRS drift — ``coord``가 있는데 ``coord_5179`` ≠ ST_Transform(coord,5179)
  (ADR-012 STORED generated column 신뢰 손상). severity=ERROR.
- **F4** dedup 백로그 — ``ops.dedup_review_queue`` 미해소(pending) 수가
  ``DEDUP_PENDING_WARN_THRESHOLD``(baseline) 초과. severity=**WARN**(observe-only,
  적재 차단 안 함). F1~F3과 달리 행별 위반이 아니라 **임계 초과 집계** — 초과 시
  count=1, 실제 pending 수는 ``metadata.pending_count``에 둔다. 이하면 OK.
  (SPRINT-4 §2.3, Sprint 4b.)
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
- **F9** backup last_success staleness — ``backup_root``에 있는 **완결된** backup
  artifact 중 가장 새 것이 SLA(기본 ``backup_last_success_warn_hours``)보다 낡았거나
  아예 하나도 없으면 severity=**WARN**(observe-only). F5와 같은 "최근 성공이
  있는가" 축이고, 근거는 DB job 행이 아니라 **디스크의 산출물**이다.

  왜 그 축인가 — 2026-09-16에 geo 예약 백업이 **5일간 425회 연속 실패**하는 동안
  아무것도 울리지 않았다. "실패가 있는가"로 묻는 검사는 *시도 자체가 멈춘* 경로를
  영원히 놓치고(실패 행이 0건이다), 결과는 같다. 그리고 그때 retention GC는 정상
  동작해 09-07 artifact를 TTL로 지웠다 — 즉 **보유 개수는 멀쩡했고 보유분만
  낡아갔다.** 그래서 F9의 판정축은 최신 성공의 나이 하나뿐이고, GC가 만드는
  모양(보유 개수·보유 시간 폭)은 ``metadata``에만 둔다. 개수를 판정에 넣었다면 그날
  "artifact 3건, 정상"이라고 답했을 것이다.

F1/F2/F3/F6은 ``CONSISTENCY_CASES``(행별 정적 SQL)로, F4/F5/F7/F8/F9는
``run_consistency_checks``의 임계/정책/재계산/객체 스냅샷/백업 산출물 분기로
추가된다.

ADR 참조: ADR-002(async) / ADR-004(raw SQL) / ADR-012 / ADR-018 / ADR-033.
"""

from __future__ import annotations

import json
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from typing import TYPE_CHECKING, Any, Final
from uuid import uuid4

from sqlalchemy import text

from kortravelmap.core.scoring import score_pair
from kortravelmap.dto import Coordinate
from kortravelmap.infra.backup import BackupArtifactError, list_backup_artifacts
from kortravelmap.settings import BACKUP_LAST_SUCCESS_WARN_HOURS_DEFAULT

if TYPE_CHECKING:
    from pathlib import Path

    from sqlalchemy.ext.asyncio import AsyncSession

    from kortravelmap.infra.backup import BackupArtifact

__all__ = [
    "CaseSpec",
    "CaseResult",
    "ConsistencyReport",
    "FileObjectRef",
    "BACKUP_LAST_SUCCESS_WARN_SECONDS",
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

# F9 기본 SLA — 숫자 자체는 ``settings.backup_last_success_warn_hours``가 갖는다(그
# description이 "왜 48h인가"의 정본). 여기서 숫자를 다시 적지 않는 이유는 env 기본값과
# 코드 기본값이 갈라질 수 있기 때문이다 — 갈라지면 더 느슨한 쪽이 조용히 이긴다.
BACKUP_LAST_SUCCESS_WARN_SECONDS: Final[int] = BACKUP_LAST_SUCCESS_WARN_HOURS_DEFAULT * 3600

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
        description="orphan source_entity (source_links 없음 — ETL transform 누수)",
        sql=(
            "SELECT se.source_entity_key AS id "
            "FROM provider_sync.source_entities se "
            "LEFT JOIN provider_sync.source_links sl "
            "  ON sl.source_entity_key = se.source_entity_key "
            "WHERE sl.source_entity_key IS NULL"
        ),
    ),
    CaseSpec(
        code="F2",
        severity="ERROR",
        description=(
            "subtype 행 결측 (subtype-bearing kind인데 typed subtype 행이 없음, "
            "ADR-086)"
        ),
        # T-VN-35: 종전 축("detail JSONB가 비어 있음")은 core detail이 사라져
        # 성립하지 않는다. 조립 뷰는 subtype 행이 없어도 NULL 필드로 채운
        # 객체를 내므로 '{}' 술어는 영원히 0건이 된다 — 탐지 능력을 잃는
        # 대신, 같은 결함의 **정확한 축**인 subtype 결측을 본다(배타 arc가
        # 구조적으로 막지만 replica-mode 우회가 남는다 — 0083 identity 4축과
        # 같은 성격의 보상 관측).
        sql=(
            "SELECT f.feature_id AS id "
            "FROM feature.features f "
            "LEFT JOIN ("
            "  SELECT feature_id FROM feature.feature_places "
            "  UNION ALL SELECT feature_id FROM feature.feature_events "
            "  UNION ALL SELECT feature_id FROM feature.feature_notices "
            "  UNION ALL SELECT feature_id FROM feature.feature_routes "
            "  UNION ALL SELECT feature_id FROM feature.feature_areas "
            ") AS s ON s.feature_id = f.feature_id "
            # `deleted_at IS NULL`의 3축 등가물. 이 술어가 빠지면 retired feature가
            # subtype row 없다는 이유로 일관성 위반으로 올라온다 — retire는 위반이
            # 아니라 정상 종료다.
            "WHERE f.lifecycle_state = 'active' "
            f"  AND f.kind IN ({_DETAIL_KINDS_SQL}) "
            "  AND s.feature_id IS NULL"
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
            "       OR x_extension.ST_SRID(f.coord_5179) <> 5179 "
            "       OR NOT x_extension.ST_DWithin("
            "         f.coord_5179, x_extension.ST_Transform(f.coord, 5179), 0.01"
            "       ))"
        ),
    ),
    CaseSpec(
        code="F6",
        severity="ERROR",
        description=("opening_hours 모순 (같은 요일 period에서 open.time > close.time, ADR-019)"),
        sql=(
            # T-VN-35: opening_hours 보유 kind는 place(business_hours)와
            # event(opening_hours) 둘뿐이다 — 각 subtype 컬럼을 직접 읽어
            # ``idx_feature_places_opening_hours`` partial index가 후보를
            # 좁히게 한다(종전 core detail 표현식 인덱스의 대체).
            "WITH candidate_features AS ("
            "  SELECT p.feature_id, "
            "         jsonb_build_object('business_hours', p.business_hours) AS hours "
            "  FROM feature.feature_places p "
            "  JOIN feature.features f ON f.feature_id = p.feature_id "
            "  WHERE f.lifecycle_state = 'active' AND p.business_hours IS NOT NULL "
            "  UNION ALL "
            "  SELECT e.feature_id, "
            "         jsonb_build_object('opening_hours', e.opening_hours) AS hours "
            "  FROM feature.feature_events e "
            "  JOIN feature.features f ON f.feature_id = e.feature_id "
            "  WHERE f.lifecycle_state = 'active' AND e.opening_hours IS NOT NULL"
            "), opening_periods AS ("
            "  SELECT c.feature_id, periods.period "
            "  FROM candidate_features c "
            "  CROSS JOIN LATERAL ("
            "    SELECT period "
            "    FROM jsonb_path_query("
            "      c.hours, '$.business_hours.periods[*] ? (@.close != null)'"
            "    ) AS period "
            "    UNION ALL "
            "    SELECT period "
            "    FROM jsonb_path_query("
            "      c.hours, '$.opening_hours.periods[*] ? (@.close != null)'"
            "    ) AS period "
            "    UNION ALL "
            "    SELECT period "
            "    FROM jsonb_path_query("
            "      c.hours, '$.business_hours.special_days[*].periods[*] ? (@.close != null)'"
            "    ) AS period "
            "    UNION ALL "
            "    SELECT period "
            "    FROM jsonb_path_query("
            "      c.hours, '$.opening_hours.special_days[*].periods[*] ? (@.close != null)'"
            "    ) AS period "
            "  ) AS periods "
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
    """1 케이스 검사 결과 (count + sample + optional metadata)."""

    code: str
    severity: str
    description: str
    count: int
    sample_ids: list[str]
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return self.count == 0

    def to_dict(self) -> dict[str, Any]:
        # 위반 0건이면 effective severity는 OK.
        payload: dict[str, Any] = {
            "code": self.code,
            "severity": self.severity if self.count else "OK",
            "description": self.description,
            "count": self.count,
            "sample_ids": self.sample_ids,
        }
        if self.metadata:
            payload["metadata"] = self.metadata
        return payload


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
    case_metadata = {c.code: c.metadata for c in cases if c.metadata}
    if case_metadata:
        summary["case_metadata"] = case_metadata
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
    "SELECT review_id FROM ops.dedup_review_queue WHERE status = 'pending' "
    "ORDER BY total_score DESC, review_id DESC LIMIT :lim"
)

_F5_PROVIDER_LAST_SUCCESS_COUNT_SQL: Final[str] = (
    "WITH stale_provider_sync AS ("
    "  SELECT s.provider_dataset_id, s.sync_scope "
    "  FROM provider_sync.provider_sync_state s "
    "  LEFT JOIN ops.provider_refresh_policies p "
    "    ON p.provider_dataset_id = s.provider_dataset_id "
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
    # ``pk_provider_sync_state``가 triple이므로 id도 triple이라야 한다. pair로
    # 합성하면 operation만 다른 두 stale 상태가 같은 id로 중복 표시돼 운영자가
    # 어느 쪽을 봐야 하는지 가릴 수 없다.
    "    s.provider_dataset_id::text || ':' || s.sync_scope "
    "      || ':' || s.operation_key AS id, "
    "    s.provider_dataset_id, dataset.provider, dataset.dataset_key, "
    "    s.sync_scope, s.operation_key "
    "  FROM provider_sync.provider_sync_state s "
    "  JOIN provider_sync.provider_datasets dataset "
    "    ON dataset.provider_dataset_id = s.provider_dataset_id "
    "  LEFT JOIN ops.provider_refresh_policies p "
    "    ON p.provider_dataset_id = s.provider_dataset_id "
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
    "ORDER BY provider_dataset_id, sync_scope, operation_key "
    "LIMIT :lim"
)

_F7_DEDUP_SCORE_ROWS_SQL: Final[str] = """
WITH pending_dedup AS MATERIALIZED (
  SELECT
    review_id,
    feature_id_a,
    feature_id_b,
    total_score
  FROM ops.dedup_review_queue
  WHERE status = 'pending'
  ORDER BY total_score DESC, review_id DESC
),
primary_sources AS (
  SELECT feature_id, provider, dataset_key
  FROM (
    SELECT
      sl.feature_id,
      pd.provider,
      pd.dataset_key,
      row_number() OVER (
        PARTITION BY sl.feature_id
        ORDER BY sr.imported_at DESC NULLS LAST, sr.source_record_key
      ) AS rn
    FROM provider_sync.source_links AS sl
    JOIN provider_sync.source_entities AS se
      ON se.source_entity_key = sl.source_entity_key
    JOIN provider_sync.provider_datasets AS pd
      ON pd.provider_dataset_id = se.provider_dataset_id
    -- 정렬축(``sr.imported_at``)은 **현재** record의 것이다. head가 그 포인터를
    -- 들고 있으므로 head → source_records로 도달한다.
    JOIN provider_sync.source_entity_heads AS head
      ON head.source_entity_key = se.source_entity_key
    JOIN provider_sync.source_records AS sr
      ON sr.source_record_key = head.current_source_record_key
    WHERE sl.source_role = 'primary'
  ) AS ranked
  WHERE rn = 1
)
SELECT
  dq.review_id,
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
FROM pending_dedup AS dq
JOIN feature.features AS fa
  ON fa.feature_id = dq.feature_id_a
JOIN feature.features AS fb
  ON fb.feature_id = dq.feature_id_b
JOIN primary_sources AS psa
  ON psa.feature_id = dq.feature_id_a
JOIN primary_sources AS psb
  ON psb.feature_id = dq.feature_id_b
WHERE psa.provider <> psb.provider
ORDER BY dq.total_score DESC, dq.review_id DESC
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
  -- retired feature는 "없는 것"으로 본다(legacy `deleted_at IS NOT NULL`의 3축 등가물).
  -- 이 축이 빠지면 retire된 feature의 첨부가 고아 파일로 보고되지 않는다.
  (f.feature_id IS NULL OR f.lifecycle_state <> 'active') AS feature_missing
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
        # F4는 행별 위반이 아니라 임계 초과 이벤트다. pending 규모는 metadata에 둔다.
        count=1 if over else 0,
        sample_ids=sample_ids,
        metadata={
            "pending_count": pending,
            "threshold": threshold,
            "over_threshold": over,
        },
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
                    f"{row['review_id']}:{row['feature_id_a']}:{row['feature_id_b']}:"
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
    metadata_file_issue_ids: set[str] = set()
    object_missing_metadata_count = 0
    sample_ids: list[str] = []

    for row in rows:
        key = (str(row["storage_backend"]), str(row["bucket"]), str(row["object_key"]))
        metadata_keys.add(key)
        key_sample = ":".join(key)
        file_id = str(row["file_id"])
        row_has_issue = False
        if row["feature_missing"]:
            row_has_issue = True
            _append_limited_sample(
                sample_ids,
                f"metadata_without_active_feature:{key_sample}:{file_id}:"
                f"{row['feature_id']}",
                sample_limit=sample_limit,
            )
        if known_keys is not None and key not in known_keys:
            row_has_issue = True
            _append_limited_sample(
                sample_ids,
                f"metadata_missing_object:{key_sample}:{file_id}:"
                f"{row['feature_id']}",
                sample_limit=sample_limit,
            )
        if row_has_issue:
            metadata_file_issue_ids.add(file_id)

    if known_keys is not None:
        for key in sorted(known_keys - metadata_keys):
            object_missing_metadata_count += 1
            _append_limited_sample(
                sample_ids,
                "object_missing_metadata:" + ":".join(key),
                sample_limit=sample_limit,
            )
    count = len(metadata_file_issue_ids) + object_missing_metadata_count

    return CaseResult(
        code="F8",
        severity="WARN",
        description=(
            "file object orphan (feature_files metadata ↔ 객체 저장소 스냅샷 불일치, "
            "distinct metadata/object row 기준, ADR-033 F8)"
        ),
        count=count,
        sample_ids=sample_ids,
        metadata={
            "metadata_file_issue_count": len(metadata_file_issue_ids),
            "object_missing_metadata_count": object_missing_metadata_count,
        },
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


def _is_successful_backup_artifact(artifact: BackupArtifact) -> bool:
    """artifact 하나가 **성공한 백업**으로 셀 자격이 있는가.

    ``scripts/docker-backup.sh``는 디렉터리를 먼저 만들고 dump → ``meta/manifest.json``
    → **마지막에** ``meta/SHA256SUMS``를 쓴다(그 스크립트가 직접 "``SHA256SUMS``가
    유일한 신뢰 뿌리"라고 적어 둔 그 파일이다). 그러므로 checksum 0건은 "아직 쓰는
    중이거나 도중에 죽었다"와 같은 말이다 — manifest까지만 쓰고 끊긴 디렉터리는
    ``manifest_status == "ok"``라서, manifest만 보는 판정에는 **성공으로 통과한다.**
    2026-09-16 사고에서 23분간 남아 있던 geo의 ``.part``가 디렉터리 모양으로
    나타나면 정확히 이 상태다.

    ``created_at_utc``가 ``None``인 경우(manifest 부재/파싱 실패/시각 필드 파싱 실패)는
    따로 셀 것도 없다 — **언제 찍힌 것인지를 모르면** 최근성의 근거가 될 수 없다.

    세 축 중 ``manifest_status``는 지금은 시각 축에 가려져 있다(manifest가 없거나 깨지면
    ``infra.backup``이 ``created_at_utc``도 ``None``으로 준다). 그래도 남긴다 — 그 가림은
    ``infra.backup``의 현재 구현에만 의존하고, 언젠가 디렉터리 mtime 등으로 시각을
    보충하면 manifest 축이 유일한 방어가 된다.
    """
    return (
        artifact.manifest_status == "ok"
        and artifact.created_at_utc is not None
        and artifact.checksum_count > 0
    )


def _build_f9_backup_staleness_result(
    artifacts: Iterable[BackupArtifact],
    *,
    backup_root: Path | None,
    sla_seconds: int,
    now: datetime,
    sample_limit: int,
    scan_error: str | None = None,
) -> CaseResult:
    """F9 — backup artifact 목록에서 "최근 성공이 있는가"를 판정한다(순수 함수)."""
    if scan_error is not None:
        # 스캔이 실패하면 **최신 성공을 증명할 수 없다.** 증명 실패를 OK로 두면
        # 읽기 권한 하나가 이 검사를 조용히 끄는 길이 된다.
        return CaseResult(
            code="F9",
            severity="WARN",
            count=1,
            description=(
                f"backup_root를 읽지 못해 최근 성공을 확인할 수 없다: {scan_error}"
            ),
            metadata={
                "observed": False,
                "scan_error": scan_error,
                "backup_root": str(backup_root) if backup_root is not None else None,
            },
            sample_ids=(),
        )
    if backup_root is None:
        # 미관측과 정상을 구분해서 적는다. Dagster 쪽 배치 경로는 ``backup_root``
        # 볼륨이 아예 없고(api 컨테이너만 마운트한다), 거기서 WARN을 내면 매 배치마다
        # 울려 곧 무시된다. 대신 ``observed=False``를 남겨 count 0이 "백업이 멀쩡하다"로
        # 읽히지 않게 한다.
        return CaseResult(
            code="F9",
            severity="WARN",
            description=(
                "backup artifact 최근 성공 SLA — **미관측**(backup_root 미제공, "
                "ADR-033 F9). count 0은 정상이라는 뜻이 아니다."
            ),
            count=0,
            sample_ids=[],
            metadata={"observed": False, "reason": "backup_root_not_provided"},
        )

    materialized = list(artifacts)
    # ``created_at_utc is not None``을 다시 적는 것은 mypy 때문이다 — 술어 함수 안의
    # 검사는 호출부의 타입을 좁혀 주지 않는다.
    dated: list[tuple[datetime, BackupArtifact]] = [
        (artifact.created_at_utc, artifact)
        for artifact in materialized
        if _is_successful_backup_artifact(artifact) and artifact.created_at_utc is not None
    ]
    newest = max(dated, key=lambda item: item[0]) if dated else None
    oldest = min(dated, key=lambda item: item[0]) if dated else None
    newest_age = (now - newest[0]).total_seconds() if newest is not None else None
    oldest_age = (now - oldest[0]).total_seconds() if oldest is not None else None

    # 판정축은 **최신 성공의 나이** 하나다. 성공 기록이 하나도 없는 경우를 같은 결론에
    # 넣는 것이 핵심이다(F5가 ``last_success_at IS NULL``을 stale에 넣는 것과 같은 모양)
    # — 시도조차 멈춘 경로는 실패 행을 한 건도 만들지 않으므로, 빈 디렉터리를 조용히 OK로
    # 두면 가장 나쁜 상태가 가장 조용해진다.
    # **미래 날짜도 stale이다.** `newest_age > sla`만 보면 시계가 한 번 앞으로 튄
    # 동안 만들어진 artifact가 **영원히 최신**이 되어 이 검사가 다시는 울리지 않는다
    # (2026-09-16 적대 리뷰 실증: incident fixture + 2027년 artifact 하나 → age
    # -2580h → 조용). 조용해지지 않는 것이 이 검사의 존재 이유이므로, 설명할 수 없는
    # 시각은 안심이 아니라 경보다.
    stale = newest_age is None or not (0.0 <= newest_age <= float(sla_seconds))

    sample_ids: list[str] = []
    if stale:
        _append_limited_sample(
            sample_ids,
            (
                f"no_successful_backup_artifact:{backup_root}"
                if newest is None
                else f"stale_newest_success:{newest[1].backup_id}:{newest[0].isoformat()}"
            ),
            sample_limit=sample_limit,
        )
    age_text = f"{newest_age / 3600:.1f}h" if newest_age is not None else "성공 기록 없음"
    return CaseResult(
        code="F9",
        severity="WARN",
        description=(
            f"backup artifact 최근 성공 SLA 초과 (기준 {sla_seconds}s, 최신 성공 "
            f"{age_text}, ADR-033 F9 — observe-only)"
        ),
        # F4와 같은 임계 초과 이벤트다 — root 하나에 백업 경로는 하나뿐이라 "몇 행이
        # 위반인가"라는 물음 자체가 성립하지 않는다.
        count=1 if stale else 0,
        sample_ids=sample_ids,
        metadata={
            "observed": True,
            "backup_root": str(backup_root),
            "sla_seconds": sla_seconds,
            "stale": stale,
            "newest_success_backup_id": newest[1].backup_id if newest is not None else None,
            "newest_success_at_utc": newest[0].isoformat() if newest is not None else None,
            "newest_success_age_seconds": (
                int(newest_age) if newest_age is not None else None
            ),
            # ── 아래 넷은 판정에 **쓰이지 않는다.** 이쪽은 retention GC가 만드는 모양
            # (보유 개수와 그 보유분이 덮는 시간 폭)이고 백업이 도는지와는 다른 축이다.
            # 2026-09-16이 정확히 그 분리였다: artifact 3건이 멀쩡히 있었고 GC는 09-07을
            # TTL로 지우며 정상 동작 중이었는데 최신 성공은 5일 전이었다. 보유 폭이 TTL을
            # 넘어 계속 자라면 그때는 반대로 GC 쪽이 멈춘 것이다 — 두 축을 한 숫자로
            # 합치지 않았기 때문에 그 구분이 리포트에서 읽힌다.
            "artifact_count": len(materialized),
            "success_count": len(dated),
            "incomplete_count": len(materialized) - len(dated),
            "oldest_success_age_seconds": (
                int(oldest_age) if oldest_age is not None else None
            ),
            "held_set_span_seconds": (
                int(oldest_age - newest_age)
                if oldest_age is not None and newest_age is not None
                else None
            ),
        },
    )


def _check_f9_backup_staleness(
    backup_root: Path | None,
    *,
    sla_seconds: int,
    sample_limit: int,
    now: datetime | None = None,
) -> CaseResult:
    """F9 — ``backup_root``를 훑어 최신 **성공** artifact의 나이를 잰다.

    근거를 DB job 행이 아니라 디스크에서 읽는다. "시작했다"고 적힌 행은 이번 사고에서
    425번 적혔고 그중 성공은 0건이었다 — 산출물만이 성공의 증거다. 파일시스템 I/O를
    async 함수 안에서 동기로 도는 것은 ``infra.file_registry_scan.scan_backup_root``와
    같은 선택이다(artifact 수십 개 규모).
    """
    artifacts: Iterable[BackupArtifact] = ()
    scan_error: str | None = None
    if backup_root is not None:
        try:
            artifacts = list_backup_artifacts(backup_root)
        except (OSError, UnicodeDecodeError, BackupArtifactError) as exc:
            # **artifact 하나가 리포트 전체를 죽이면 안 된다.** `list_backup_artifacts`는
            # `BackupArtifactError`만 잡고 `OSError`·`UnicodeDecodeError`는 흘려보내는데,
            # 이 호출부가 F1~F8과 같은 `cases` 목록에 들어 있어 **그 예외 하나가
            # 일관성 리포트를 통째로 못 만들게 한다**(2026-09-16 적대 리뷰가
            # `SHA256SUMS`에 비-UTF-8 바이트를 넣어 실증했다).
            #
            # 덧붙여 이 경로는 **본질적으로 경합한다** — retention GC가 스캔 중에
            # artifact를 지우면 `FileNotFoundError`가 난다. 그것은 고장이 아니라 정상
            # 동작이고, 그때 리포트 전체를 잃는 것이 훨씬 나쁘다.
            #
            # 읽지 못한 것을 **OK로 두지 않는다** — 읽을 수 없으면 최신 성공을 증명할
            # 수 없고, 증명할 수 없는 것은 이 검사에서 경보다.
            artifacts = ()
            scan_error = f"{type(exc).__name__}: {exc}"
    return _build_f9_backup_staleness_result(
        artifacts,
        scan_error=scan_error,
        backup_root=backup_root,
        sla_seconds=sla_seconds,
        now=now if now is not None else datetime.now(UTC),
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
    backup_root: Path | None = None,
    backup_last_success_sla_seconds: int = BACKUP_LAST_SUCCESS_WARN_SECONDS,
) -> ConsistencyReport:
    """F1~F9 정합성 검사 실행 + (옵션) ``ops.feature_consistency_reports`` 적재.

    Parameters
    ----------
    session:
        async DB 세션. PostGIS 함수는 ``x_extension.``으로 schema-qualified 호출한다
        (ADR-008).
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
    backup_root:
        F9 backup artifact 루트(``settings.backup_root``). 이 process가 그 볼륨을 보는
        경우에만 호출자가 넘긴다 — 미제공이면 F9는 count 0 + ``metadata.observed=False``
        (**정상이라는 뜻이 아니라 안 봤다는 뜻**)로 남는다.
    backup_last_success_sla_seconds:
        F9 SLA. 기본값은 ``settings.backup_last_success_warn_hours``(48h)를 초 환산한
        것이고, env로 주기를 바꿨다면 호출자가 그 값을 넘긴다.

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

    # F4/F5/F7/F8/F9 — 정적 SQL이 아닌 임계/정책/source join/object snapshot/
    # 백업 산출물 케이스.
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
    # F9만 session을 쓰지 않는다 — 백업의 성공 여부는 DB가 아니라 디스크에 있다.
    cases.append(
        _check_f9_backup_staleness(
            backup_root,
            sla_seconds=backup_last_success_sla_seconds,
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
