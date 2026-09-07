"""``kortravelmap.infra.manual_provider_dedup_repo`` — M05 manual/provider dedup 후보 탐지.

수동 Feature와 같은 실체를 provider가 발행했을 때 그 쌍을 **후보로만** 올린다
(`T-VN-M05`, ADR-097, 설계 `t-vn-m05-manual-provider-dedup-design-2026-08-21.md`
§후보 탐지). **자동으로 병합하지 않는다** — 병합/유지/수동본 폐기는 admin이 고른다.

이 모듈이 존재하는 이유
-----------------------

계약·스키마·ACL·프로시저는 이미 배포돼 있었는데 **그것을 부르는 코드가 없었다**
(2026-09-07 실측: `feature.record_manual_provider_dedup_candidate`의 프로덕션 호출자
0건). 그래서 M05의 요지가 운영에서 한 번도 일어나지 않았다.

설계가 못 박은 것
-----------------

- **두 질의를 따로 읽는다.** manual origin Feature와 provider-linked Feature를 각각
  읽으며, **provider query의 INNER JOIN을 manual 쪽에 재사용하지 않는다.** 재사용하면
  manual Feature가 provider source를 가져야만 보이게 되어 대상이 조용히 비어 버린다.
- **점수는 순수하다.** ADR-016의 같은 가중치를 쓰되 `classify_decision()`·
  `select_master()`를 부르지 않는다. `THRESHOLD_MANUAL` 이상은 점수와 무관하게 전부
  `candidate`다 — 자동 병합 판정을 여기서 하지 않는다는 뜻이다.
- **대규모 provider scope는 먼저 block한다.** 공간 grid(manual 좌표 기준 bbox)로
  후보군을 좁히고, **complete set이 아니라는 사실과 detector input count를 case
  receipt(`detector_causation`)에 남긴다.**

권한
----

`feature.record_manual_provider_dedup_candidate`는 SECURITY DEFINER이고
`session_user = 'ktm_feature_dagster_runtime'` + `ktm_manual_provider_dedup_detector_executor`
멤버십을 요구하며, admin executor·reconciliation service executor를 겸하면 거부한다.
즉 이 경로는 **Dagster 런타임 전용**이다. detector relation에 대한 직접
INSERT/UPDATE 권한은 어디에도 주지 않는다 — 프로시저만이 쓴다.

**manual 쪽은 표를 직접 읽을 수 없다.** `feature.feature_creation_origins`와
`feature.manual_feature_identity_claims`는 `runtime_privileges.py`가
`ktm_feature_dagster_runtime`을 **이름으로** REVOKE한다(`_MANUAL_FEATURE_TABLE_ACL`).
그래서 manual 목록은 migration 304의 좁은 reader
`feature.list_manual_provider_dedup_detector_manuals`로만 연다. provider 쪽 네 표와
`feature.features`는 detector가 읽을 수 있으므로 그대로 SQL로 묻는다.

ADR 참조
--------
- ADR-002 async-only · ADR-004 raw SQL `text()` · ADR-016 Record Linkage 점수
- ADR-097 manual/provider dedup paired reconciliation
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Final

from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from kortravelmap.core.scoring import (
    THRESHOLD_MANUAL,
    category_similarity,
    name_similarity,
    score_pair,
    spatial_similarity,
)
from kortravelmap.dto.coordinate import Coordinate

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

__all__ = [
    "DEFAULT_BLOCK_RADIUS_METERS",
    "DEFAULT_PROVIDER_BLOCK_LIMIT",
    "CandidateFeature",
    "DetectionOutcome",
    "ManualProviderDedupError",
    "detect_manual_provider_candidates",
    "manual_origin_features",
    "provider_features_near",
    "record_manual_provider_candidate",
]


class ManualProviderDedupError(RuntimeError):
    """탐지 경로가 계약을 위반했다."""


#: 쌍 하나가 레이스로 거부되는 CONSTRAINT 집합.
#:
#: 이 셋은 **탐지기가 읽은 뒤 기록하기 전에 세상이 바뀌었다**는 뜻이지 탐지기의
#: 결함이 아니다(예: Feature가 그 사이 retire됐다, provider link가 둘이 됐다).
#: 그 쌍만 버리고 계속 간다 — 런을 죽이면 이미 기록한 후보까지 사라지고, Dagster
#: `RetryPolicy`가 같은 레이스로 재진입한다.
_RACED_CANDIDATE_CONSTRAINTS: Final[frozenset[str]] = frozenset(
    {
        "ck_m05_candidate_feature_proof",
        "ck_m05_candidate_manual_origin",
        "ck_m05_candidate_provider_source",
    }
)


def _constraint_name(error: BaseException) -> str | None:
    """`RAISE ... USING CONSTRAINT`가 실은 곳.

    SQLAlchemy가 asyncpg 예외를 번역하면서 `constraint_name`을 옮기지 않는다 —
    원본은 `__cause__`에 있다. 번역된 쪽만 보면 항상 `None`이라 **어떤 CONSTRAINT든
    통과하는** 판정이 된다.
    """

    seen: list[BaseException | None] = [error, getattr(error, "orig", None)]
    seen.append(getattr(seen[1], "__cause__", None) if seen[1] is not None else None)
    for candidate in seen:
        name = getattr(candidate, "constraint_name", None)
        if name:
            return str(name)
    return None


#: manual Feature 하나를 둘러싼 공간 block의 반경(m).
#:
#: 설계는 "행정구역/공간 grid로 먼저 block"만 정하고 값을 정하지 않았다. 공간
#: 반경을 고른 이유는 행정구역 코드가 manual Feature에 항상 있지는 않기 때문이다
#: (`manual_feature_v1` category는 bjd_code 없이 만들어진다). 반경은 좌표 정합이
#: 후보 판정에 실제로 기여하는 범위여야 하므로 `spatial_similarity`가 0이 되는
#: 거리보다 넉넉하지 않게 잡는다.
DEFAULT_BLOCK_RADIUS_METERS: Final[float] = 500.0

#: 한 manual Feature당 훑을 provider Feature 상한.
#:
#: 이 상한에 걸리면 그 block은 **complete set이 아니다.** 그 사실을 case receipt에
#: 남긴다 — 남기지 않으면 "후보가 없다"와 "다 보지 않았다"가 같아 보인다.
DEFAULT_PROVIDER_BLOCK_LIMIT: Final[int] = 200

#: 프로시저가 `scorer_id`를 이 값으로 **고정 삽입**한다(baseline schema.sql
#: 8205행). 여기서 다른 값을 쓰면 지문 입력과 저장된 scorer_id가 어긋난다.
_SCORER_ID: Final[str] = "manual-provider-v1"


@dataclass(frozen=True)
class CandidateFeature:
    """탐지에 필요한 최소 Feature 투영.

    `distance_meters`는 provider 쪽에만 있다 — **block 술어와 같은 질의가 낸 값**이다.
    Python에서 따로 haversine을 돌리면 block(EPSG:5179 평면)과 기록된 거리(구면)가
    서로 다른 의미가 되어, 반경 안이라고 뽑아 놓고 반경 밖 거리를 receipt에 싣는
    일이 생긴다.
    """

    feature_id: str
    name: str
    category: str | None
    lon: float
    lat: float
    distance_meters: float | None = None


@dataclass(frozen=True)
class DetectionOutcome:
    """한 번의 탐지 실행이 남긴 것."""

    manual_input_count: int
    provider_input_count: int
    scored_pair_count: int
    created_case_ids: tuple[str, ...]
    idempotent_case_ids: tuple[str, ...]
    suppressed_case_ids: tuple[str, ...] = ()
    incomplete_blocks: tuple[str, ...]
    manual_scan_truncated: bool = False
    raced_pair_count: int = 0

    @property
    def complete_set(self) -> bool:
        """훑은 범위가 완전했는가.

        block 상한에 한 번도 안 걸렸고 manual 스캔도 안 잘렸을 때만 참이다.
        둘 중 하나라도 걸리면 "후보가 이게 전부다"라고 말할 수 없다.
        """
        return (
            not self.incomplete_blocks
            and not self.manual_scan_truncated
            and self.raced_pair_count == 0
        )


# ─── SQL 상수 ──────────────────────────────────────────────────────────────

#: manual origin 대상. **표를 직접 읽지 않는다** — 두 증명 표는 detector 로그인에서
#: REVOKE돼 있고(모듈 docstring §권한), migration 304의 좁은 reader만이 그 판정을
#: 돌려준다. reader는 manual 한 건당 정확히 한 행을 돌려주므로 cursor가 항상
#: 전진한다(쌍을 돌려주면 이웃 없는 manual에서 페이지가 비어 그 뒤가 영원히
#: 스캔에서 빠진다 — 적대 리뷰가 잡은 결함).
_MANUAL_ORIGIN_SQL: Final[str] = """
SELECT feature_id, name, category, lon, lat
FROM feature.list_manual_provider_dedup_detector_manuals(
    CAST(:after AS text), CAST(:limit AS integer)
)
"""

#: provider-linked Feature. 프로시저가 요구하는 "현재 primary source 정확히 1건"을
#: 여기서도 강제해, 프로시저가 거부할 쌍을 애초에 점수 내지 않는다.
#:
#: 공간 block은 저장소 정본 형태 — **저장 컬럼 `coord_5179`를 그대로 두고 파라미터
#: 쪽만 `ST_Transform`한다**(ADR-012). 처음엔 `f.coord::geography`로 썼는데 그것은
#: 컬럼에 건 함수식이라 `idx_features_coord_5179_gist`도 `idx_features_coord_gist`도
#: 쓸 수 없고(geography 인덱스는 없다) manual 한 건마다 `feature.features` 전체
#: seq scan이 됐다 — 적대 리뷰가 잡았다.
#:
#: **정렬은 거리순이다.** `feature_id` 순으로 자르면 `limit`에 걸렸을 때 찾으려던
#: 최근접 후보를 정확히 버린다. 부분 인덱스의 WHERE(`active`/`published`/`valid`)를
#: 술어가 그대로 갖고 있어야 인덱스가 잡히므로 세 항을 지우면 안 된다.
_PROVIDER_NEAR_SQL: Final[str] = """
WITH input AS (
    SELECT x_extension.ST_Transform(
        x_extension.ST_SetSRID(
            x_extension.ST_MakePoint(
                CAST(:lon AS double precision),
                CAST(:lat AS double precision)
            ),
            4326
        ),
        5179
    ) AS pt
)
SELECT f.feature_id, f.name, f.category,
       x_extension.ST_X(f.coord) AS lon, x_extension.ST_Y(f.coord) AS lat,
       x_extension.ST_Distance(f.coord_5179, i.pt) AS distance_meters
FROM feature.features AS f, input AS i
WHERE f.lifecycle_state = 'active'
  AND f.publication_state = 'published'
  AND f.quality_state = 'valid'
  AND f.coord IS NOT NULL
  AND f.coord_5179 IS NOT NULL
  AND f.feature_id <> :manual_feature_id
  AND x_extension.ST_DWithin(
        f.coord_5179, i.pt, CAST(:radius_meters AS double precision)
      )
  AND (
    SELECT count(*)
    FROM provider_sync.source_links AS link
    JOIN provider_sync.source_entities AS entity
      ON entity.source_entity_key = link.source_entity_key
    JOIN provider_sync.source_entity_heads AS head
      ON head.source_entity_key = entity.source_entity_key
    JOIN provider_sync.source_records AS source
      ON source.source_entity_key = head.source_entity_key
     AND source.source_record_key = head.current_source_record_key
    WHERE link.feature_id = f.feature_id
      AND link.source_role = 'primary'
  ) = 1
ORDER BY f.coord_5179 OPERATOR(x_extension.<->) i.pt, f.feature_id
LIMIT :limit
"""

_RECORD_CANDIDATE_SQL: Final[str] = """
CALL feature.record_manual_provider_dedup_candidate(
    :manual_feature_id, :provider_feature_id,
    CAST(:scores AS jsonb), CAST(:detector_causation AS jsonb),
    NULL, NULL
)
"""


def _row_to_feature(row: Any) -> CandidateFeature:
    distance = getattr(row, "distance_meters", None)
    return CandidateFeature(
        feature_id=row.feature_id,
        name=row.name,
        category=row.category,
        lon=float(row.lon),
        lat=float(row.lat),
        distance_meters=None if distance is None else float(distance),
    )


async def manual_origin_features(
    session: AsyncSession, *, after: str | None = None, limit: int = 1000
) -> tuple[CandidateFeature, ...]:
    """manual origin이 증명된 active/published/valid Feature 한 페이지.

    `after`는 **직전 페이지의 마지막 `feature_id`**다. reader가 manual 한 건당
    한 행을 돌려주므로 이 cursor는 이웃 유무와 무관하게 전진한다.
    """

    result = await session.execute(
        text(_MANUAL_ORIGIN_SQL), {"after": after, "limit": limit}
    )
    return tuple(_row_to_feature(row) for row in result)


async def provider_features_near(
    session: AsyncSession,
    *,
    manual: CandidateFeature,
    radius_meters: float = DEFAULT_BLOCK_RADIUS_METERS,
    limit: int = DEFAULT_PROVIDER_BLOCK_LIMIT,
) -> tuple[CandidateFeature, ...]:
    """manual Feature 주변 block의 provider-linked Feature."""

    result = await session.execute(
        text(_PROVIDER_NEAR_SQL),
        {
            "manual_feature_id": manual.feature_id,
            "lon": manual.lon,
            "lat": manual.lat,
            "radius_meters": radius_meters,
            "limit": limit,
        },
    )
    return tuple(_row_to_feature(row) for row in result)


def _scorer_input_sha256(manual: CandidateFeature, provider: CandidateFeature) -> str:
    """점수를 만든 **입력**의 지문.

    프로시저가 `^[0-9a-f]{64}$`를 강제한다. 지문의 목적은 "같은 입력이면 같은
    점수"를 사후에 확인할 수 있게 하는 것이므로, 점수 자체가 아니라 점수의
    입력만 canonical JSON으로 직렬화해 해싱한다.
    """

    payload = {
        "manual": {
            "feature_id": manual.feature_id,
            "name": manual.name,
            "category": manual.category,
            "lon": manual.lon,
            "lat": manual.lat,
        },
        "provider": {
            "feature_id": provider.feature_id,
            "name": provider.name,
            "category": provider.category,
            "lon": provider.lon,
            "lat": provider.lat,
        },
        "scorer_id": _SCORER_ID,
    }
    canonical = json.dumps(payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def score_manual_provider_pair(
    manual: CandidateFeature, provider: CandidateFeature
) -> dict[str, Any]:
    """ADR-016 가중치로 점수를 낸다 — **판정은 하지 않는다.**

    `classify_decision()`·`select_master()`를 부르지 않는다. 이 함수가 내는 것은
    프로시저가 요구하는 canonical score 봉투 그대로다.
    """

    coord_a = Coordinate(lon=manual.lon, lat=manual.lat)
    coord_b = Coordinate(lon=provider.lon, lat=provider.lat)
    # 단일 category를 집합으로 감싸는 것은 `core.dedup`의 기존 호출 규약과 같다.
    cat_a = {manual.category} if manual.category else None
    cat_b = {provider.category} if provider.category else None
    return {
        "name_score": round(name_similarity(manual.name, provider.name), 6),
        "spatial_score": round(spatial_similarity(coord_a, coord_b), 6),
        "category_score": round(category_similarity(cat_a, cat_b), 6),
        "total_score": round(
            score_pair(
                name_a=manual.name,
                name_b=provider.name,
                coord_a=coord_a,
                coord_b=coord_b,
                cat_a=cat_a,
                cat_b=cat_b,
            ),
            6,
        ),
        # block 술어가 낸 값을 그대로 싣는다 — 두 번 재지 않는다.
        "distance_meters": round(provider.distance_meters or 0.0, 3),
        "scorer_input_sha256": _scorer_input_sha256(manual, provider),
    }


async def record_manual_provider_candidate(
    session: AsyncSession,
    *,
    manual_feature_id: str,
    provider_feature_id: str,
    scores: dict[str, Any],
    detector_causation: dict[str, Any],
) -> tuple[str, str]:
    """후보 하나를 evidence로 남긴다. ``(case_id, outcome)``을 돌려준다.

    ``outcome``은 셋 중 하나다:

    - ``created`` — 새 case
    - ``idempotent`` — 같은 evidence 지문의 **미해결** case가 이미 있다
    - ``suppressed`` — admin이 이미 판정한 쌍이고 판정을 좌우하는 증거가 그대로다
      (migration 305). 이것을 세지 않으면 "후보가 없다"와 "이미 판정됐다"가 같아 보인다.
    """

    row = (
        await session.execute(
            text(_RECORD_CANDIDATE_SQL),
            {
                "detector_causation": json.dumps(detector_causation, ensure_ascii=False),
                "manual_feature_id": manual_feature_id,
                "provider_feature_id": provider_feature_id,
                "scores": json.dumps(scores, ensure_ascii=False),
            },
        )
    ).one()
    outcome = row.o_outcome
    case_id = row.o_case_id
    if outcome not in {"created", "idempotent", "suppressed"} or case_id is None:
        raise ManualProviderDedupError(
            "manual/provider dedup candidate receipt is not canonical"
        )
    return str(case_id), str(outcome)


async def detect_manual_provider_candidates(
    session: AsyncSession,
    *,
    run_id: str,
    manual_page_size: int = 1000,
    max_manual_pages: int = 100,
    radius_meters: float = DEFAULT_BLOCK_RADIUS_METERS,
    block_limit: int = DEFAULT_PROVIDER_BLOCK_LIMIT,
) -> DetectionOutcome:
    """manual origin Feature 전부에 대해 block을 훑어 후보를 남긴다.

    **`THRESHOLD_MANUAL` 이상은 점수와 무관하게 전부 후보다.** 자동 병합 판정을
    여기서 하지 않는 것이 이 task의 요지다 — `classify_decision()`·`select_master()`를
    부르지 않는다.

    각 case의 `detector_causation`에는 그 쌍이 **어떤 범위를 본 결과인지**를
    남긴다 — block 반경·상한, 그 block에서 실제로 본 provider 수, 그리고 상한에
    걸려 **complete set이 아닌지**.

    **집계는 case와 무관하게 돌려준다.** 후보가 한 건도 안 나와도
    `DetectionOutcome`은 훑은 manual 수·provider 수·점수 낸 쌍 수를 싣는다.
    case에만 실으면 "후보가 없다"와 "아무것도 안 훑었다"가 같아 보이는데, 그게
    정확히 이 저장소가 반복해 겪은 실패 양상이다. 호출자(Dagster asset)가 이
    값을 materialization metadata로 남긴다.

    `max_manual_pages`에 걸려 스캔이 잘리면 `manual_scan_truncated`가 참이 된다 —
    조용히 자르지 않는다.
    """

    created: list[str] = []
    idempotent: list[str] = []
    suppressed: list[str] = []
    incomplete: list[str] = []
    manual_total = 0
    provider_total = 0
    scored = 0
    raced = 0
    after: str | None = None
    truncated = True

    for _page in range(max_manual_pages):
        manuals = await manual_origin_features(
            session, after=after, limit=manual_page_size
        )
        if not manuals:
            truncated = False
            break
        manual_total += len(manuals)
        after = manuals[-1].feature_id

        for manual in manuals:
            providers = await provider_features_near(
                session, manual=manual, radius_meters=radius_meters, limit=block_limit
            )
            provider_total += len(providers)
            block_complete = len(providers) < block_limit
            if not block_complete:
                incomplete.append(manual.feature_id)
            for provider in providers:
                scores = score_manual_provider_pair(manual, provider)
                scored += 1
                if scores["total_score"] < THRESHOLD_MANUAL:
                    continue
                causation = {
                    "detector_id": _SCORER_ID,
                    "run_id": run_id,
                    "block": {
                        "kind": "spatial_radius",
                        "radius_meters": radius_meters,
                        "limit": block_limit,
                        "observed_provider_count": len(providers),
                        "complete_set": block_complete,
                    },
                    "detector_input_count": {
                        "manual_page": len(manuals),
                        "provider_in_block": len(providers),
                    },
                    "threshold_manual": THRESHOLD_MANUAL,
                }
                try:
                    case_id, outcome = await record_manual_provider_candidate(
                        session,
                        manual_feature_id=manual.feature_id,
                        provider_feature_id=provider.feature_id,
                        scores=scores,
                        detector_causation=causation,
                    )
                except DBAPIError as error:
                    if _constraint_name(error) not in _RACED_CANDIDATE_CONSTRAINTS:
                        raise
                    # 이 쌍만 버린다. 롤백 없이 다음으로 가면 PostgreSQL이
                    # "current transaction is aborted"로 이후 전부를 거부한다.
                    await session.rollback()
                    raced += 1
                    continue
                # **case 하나만큼만 fence를 쥔다.** 프로시저는 호출마다
                # `pg_advisory_xact_lock('feature-curation-m05')`을 잡는데 그것은
                # xact-scoped라, 런 전체를 한 트랜잭션으로 묶으면 첫 후보에서 잡은
                # fence가 런 끝까지 유지돼 admin의 resolve 경로가 그동안 막힌다
                # (두 Feature 행의 FOR UPDATE도 같이 쌓인다). 형제 job
                # `file_registry_scan`의 "단위별 독립 커밋"과 같은 규약이다.
                await session.commit()
                if outcome == "created":
                    created.append(case_id)
                elif outcome == "suppressed":
                    suppressed.append(case_id)
                else:
                    idempotent.append(case_id)

        if len(manuals) < manual_page_size:
            truncated = False
            break

    return DetectionOutcome(
        manual_input_count=manual_total,
        provider_input_count=provider_total,
        scored_pair_count=scored,
        created_case_ids=tuple(created),
        idempotent_case_ids=tuple(idempotent),
        suppressed_case_ids=tuple(suppressed),
        incomplete_blocks=tuple(incomplete),
        manual_scan_truncated=truncated,
        raced_pair_count=raced,
    )
