"""``kortravelmap.infra.price_repo`` -- price value 적재.

``PriceValue`` DTO를 ``feature.feature_price_values``에 멱등 upsert한다. PK는
결정적 ``price_value_key``(`make_price_value_key`)이며, commit은 호출자가 소유한다.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING, Any, Final, Literal, cast

from sqlalchemy import text
from sqlalchemy.engine import CursorResult

from kortravelmap.core.ids import make_price_value_key
from kortravelmap.core.retention import is_latest_only
from kortravelmap.dto._time import kst_now
from kortravelmap.infra.advisory_lock import advisory_lock_key
from kortravelmap.infra.canonical_feature_ids import resolve_canonical_feature_ids
from kortravelmap.infra.feature_repo import (
    DEFAULT_PRICE_STALE_HIDE_DAYS,
    FeatureLoadResult,
)

if TYPE_CHECKING:
    from sqlalchemy import RowMapping
    from sqlalchemy.ext.asyncio import AsyncSession

    from kortravelmap.dto import SourceRecord
    from kortravelmap.dto.price import PriceValue

__all__ = [
    "DEFAULT_PRICE_FRESHNESS_SECONDS",
    "DEFAULT_PRICE_STALE_HIDE_DAYS",
    "PriceCard",
    "PriceFeatureLoadResult",
    "PricePoint",
    "FeaturePriceDataset",
    "PriceSummaryMaterializeResult",
    "PriceValueLoadResult",
    "build_price_card",
    "build_price_snapshot",
    "latest_only_price_datasets_for_feature",
    "load_price_values",
    "materialize_current_price_summary",
    "prune_superseded_price_facts",
    "sort_current_points",
]

DEFAULT_PRICE_FRESHNESS_SECONDS: Final[int] = (
    DEFAULT_PRICE_STALE_HIDE_DAYS * 24 * 60 * 60
)
"""price card ``is_stale`` 기본 임계 — 현재가 표시 지평선과 동일 값에서 파생.

과거엔 18h(일 1회 ETL 가정)였지만, OpiNet 시군 윈도 로테이션(전국 ≈4일 1주기)
아래에서는 정상 갱신 중인 주유소도 최장 ~4일 관측 공백이 생긴다 — 18h 기준이면
대부분이 항상 stale로 표시된다(사용자 가시 증상). 이제 ``is_stale``은 "현재가
지평선(``KOR_TRAVEL_MAP_PRICE_STALE_HIDE_DAYS``, 기본 4일) 안에 관측이 없다"를
뜻하며, 지평선이 ``current``를 비우는 조건과 일치한다(단일 노브, drift 없음).
호출별 ``freshness_seconds`` override는 그대로 유지."""

_PRICE_CURRENT_SUMMARY_LOCK_ID: Final[int] = advisory_lock_key(
    "projection:current-price-summary"
)
"""price current projection 전체를 직렬화하는 transaction advisory lock."""


@dataclass(frozen=True)
class PricePoint:
    """feature price card의 provider/domain/product series 관측 1건."""

    provider_dataset_id: int
    dataset_key: str
    dataset_display_name: str
    provider: str
    price_domain: str
    product_key: str
    product_name: str | None
    source_product_key: str | None
    source_product_name: str | None
    value_number: Decimal
    unit: str
    observed_at: datetime
    known_at: datetime


@dataclass(frozen=True)
class PriceCard:
    """feature 1건의 price card — series별 최신 가격 + 최근 이력."""

    feature_id: str
    current: list[PricePoint]
    history: list[PricePoint]
    latest_at: datetime | None
    is_stale: bool
    snapshot_observed_at: datetime | None = None
    snapshot_known_at: datetime | None = None


@dataclass(frozen=True)
class PriceValueLoadResult:
    """한 raw response의 price fact 적재 결과.

    ``pruned``는 latest-only dataset(ADR-114)에서 같은 transaction이 지운 superseded fact 수다.
    다른 dataset은 항상 0이다.
    """

    inserted: int
    pruned: int = 0


@dataclass(frozen=True)
class PriceFeatureLoadResult:
    """price anchor feature + ``PriceValue`` 적재 결과."""

    features: FeatureLoadResult
    price_values: int
    price_values_pruned: int = 0

    def as_metadata(self) -> dict[str, object]:
        return {
            "price_features_total": self.features.bundles_total,
            "price_features_inserted": self.features.features_inserted,
            "price_features_updated": self.features.features_updated,
            "price_source_records_inserted": self.features.source_records_inserted,
            "price_source_links_inserted": self.features.source_links_inserted,
            "price_source_links_updated": self.features.source_links_updated,
            "price_values_upserted": self.price_values,
            "price_values_pruned": self.price_values_pruned,
            "retention_records_pruned": self.features.retention_records_pruned,
            "retention_entities_pruned": self.features.retention_entities_pruned,
            "retention_held": self.features.retention_held,
        }


@dataclass(frozen=True)
class FeaturePriceDataset:
    """feature의 현재 price series가 속한 dataset과 그 dataset의 자연키(identity claim)."""

    provider_dataset_id: int
    provider: str
    dataset_key: str
    display_name: str
    natural_key: str | None


@dataclass(frozen=True)
class _PriceValueWriteContext:
    """하나의 raw provider response가 소유하는 immutable price fact write 경계."""

    provider_dataset_id: int
    source_entity_key: str
    source_record_key: str
    known_at: datetime


@dataclass(frozen=True)
class PriceSummaryMaterializeResult:
    """price current summary 재구성 receipt와 변경 건수."""

    summary_run_id: int
    input_count: int
    inserted_count: int
    updated_count: int
    deleted_count: int


_IMMUTABLE_INSERT_SQL: Final[str] = """
INSERT INTO feature.feature_price_values (
    price_value_key, feature_id, provider_dataset_id, price_domain, product_key,
    product_name, source_product_key, source_product_name, observed_at, known_at,
    value_number, unit, normalization_version, payload, source_entity_key,
    source_record_key
) VALUES (
    :price_value_key, CAST(:feature_id AS uuid), :provider_dataset_id,
    :price_domain, :product_key,
    :product_name, :source_product_key, :source_product_name, :observed_at, :known_at,
    :value_number, :unit, :normalization_version, CAST(:payload AS jsonb),
    :source_entity_key, :source_record_key
)
ON CONFLICT (feature_id, provider_dataset_id, price_domain, product_key,
             observed_at, source_record_key) DO NOTHING
"""

_PRODUCT_ORDER: Final[dict[str, int]] = {
    "gasoline": 10,
    "diesel": 20,
    "premium_gasoline": 30,
    "lpg": 40,
}

_PRICE_SUMMARY_DESIRED_SQL: Final[str] = """
WITH ranked AS (
    SELECT
        fact.price_value_key,
        fact.feature_id,
        fact.provider_dataset_id,
        fact.price_domain,
        fact.product_key,
        row_number() OVER (
            PARTITION BY
                fact.feature_id, fact.provider_dataset_id, fact.price_domain, fact.product_key
            ORDER BY
                fact.observed_at DESC,
                fact.known_at DESC,
                fact.price_value_key DESC
        ) AS rank
    FROM feature.feature_price_values AS fact
    JOIN provider_sync.provider_datasets AS dataset
      ON dataset.provider_dataset_id = fact.provider_dataset_id
     AND dataset.is_active
)
SELECT
    price_value_key,
    feature_id,
    provider_dataset_id,
    price_domain,
    product_key
FROM ranked
WHERE rank = 1
ORDER BY feature_id, provider_dataset_id, price_domain, product_key
"""

_PRICE_SUMMARY_INPUT_COUNT_SQL: Final[str] = """
SELECT count(*)
FROM feature.feature_price_values AS fact
JOIN provider_sync.provider_datasets AS dataset
  ON dataset.provider_dataset_id = fact.provider_dataset_id
 AND dataset.is_active
"""

_INSERT_CURRENT_PRICE_SUMMARY_RUN_SQL: Final[str] = """
INSERT INTO ops.current_summary_runs (projection_kind, run_kind, status, scope)
VALUES ('price', :run_kind, 'running', CAST(:scope AS jsonb))
RETURNING summary_run_id
"""

_COMPLETE_CURRENT_PRICE_SUMMARY_RUN_SQL: Final[str] = """
UPDATE ops.current_summary_runs
SET status = 'succeeded',
    finished_at = clock_timestamp(),
    input_count = :input_count,
    inserted_count = :inserted_count,
    updated_count = :updated_count,
    deleted_count = :deleted_count,
    detail = CAST(:detail AS jsonb)
WHERE summary_run_id = :summary_run_id
  AND projection_kind = 'price'
  AND status = 'running'
"""

_UPSERT_CURRENT_PRICE_SUMMARY_SQL: Final[str] = """
INSERT INTO feature.current_price_summary (
    feature_id, provider_dataset_id, price_domain, product_key,
    price_value_key, summary_run_id
) VALUES (
    :feature_id, :provider_dataset_id, :price_domain, :product_key,
    :price_value_key, :summary_run_id
)
ON CONFLICT (feature_id, provider_dataset_id, price_domain, product_key)
DO UPDATE SET
    price_value_key = EXCLUDED.price_value_key,
    summary_run_id = EXCLUDED.summary_run_id
"""

_DELETE_STALE_PRICE_SUMMARIES_SQL: Final[str] = """
DELETE FROM feature.current_price_summary AS summary
WHERE NOT EXISTS (
    SELECT 1
    FROM feature.feature_price_values AS fact
    JOIN provider_sync.provider_datasets AS dataset
      ON dataset.provider_dataset_id = fact.provider_dataset_id
     AND dataset.is_active
    WHERE fact.feature_id = summary.feature_id
      AND fact.provider_dataset_id = summary.provider_dataset_id
      AND fact.price_domain = summary.price_domain
      AND fact.product_key = summary.product_key
)
"""

_ACQUIRE_PRICE_CURRENT_SUMMARY_LOCK_SQL: Final[str] = """
SELECT pg_advisory_xact_lock(CAST(:lock_id AS bigint))
"""

#: ADR-114: latest-only dataset의 superseded fact를 지운다 — summary가 가리키지 않는 것만. 삭제는
#: SECURITY DEFINER 함수(migration 410)가 한다: runtime에는 fact DELETE 권한이 없고, 함수가 dataset이 활성
#: kor-travel-transport인지 먼저 본다. 트리거(``reject_price_value_mutation``)가 같은 조건을 행마다 다시 본다.
_PRUNE_SUPERSEDED_PRICE_FACTS_SQL: Final[str] = """
SELECT feature.prune_transport_price_facts(CAST(:provider_dataset_id AS bigint))
"""

_PRICE_DATASET_IDENTITY_SQL: Final[str] = """
SELECT provider, dataset_key
FROM provider_sync.provider_datasets
WHERE provider_dataset_id = :provider_dataset_id
"""

#: price card가 원천 서비스에서 추이를 읽어야 하는지 판정할 재료 — feature의 summary series가 속한
#: dataset과 그 dataset 안의 identity claim 자연키(ADR-114 결정 6).
_FEATURE_PRICE_DATASETS_SQL: Final[str] = """
SELECT DISTINCT
    dataset.provider_dataset_id,
    dataset.provider,
    dataset.dataset_key,
    dataset.display_name,
    claim.natural_key
FROM feature.current_price_summary AS summary
JOIN provider_sync.provider_datasets AS dataset
  ON dataset.provider_dataset_id = summary.provider_dataset_id
 AND dataset.is_active
LEFT JOIN provider_sync.provider_feature_identities AS claim
  ON claim.feature_id = summary.feature_id
 AND claim.provider_dataset_id = summary.provider_dataset_id
 AND claim.feature_kind = 'price'
WHERE summary.feature_id = CAST(:feature_id AS uuid)
ORDER BY dataset.provider_dataset_id
"""

_CURRENT_SQL: Final[str] = """
SELECT
    fact.provider_dataset_id,
    dataset.dataset_key,
    dataset.display_name AS dataset_display_name,
    dataset.provider,
    fact.price_domain,
    fact.product_key,
    fact.product_name,
    fact.source_product_key,
    fact.source_product_name,
    fact.value_number,
    fact.unit,
    fact.observed_at,
    fact.known_at
FROM feature.current_price_summary AS summary
JOIN feature.feature_price_values AS fact
  ON fact.price_value_key = summary.price_value_key
JOIN provider_sync.provider_datasets AS dataset
  ON dataset.provider_dataset_id = fact.provider_dataset_id
 AND dataset.is_active
WHERE summary.feature_id = :feature_id
  AND (
    CAST(:stale_hide_days AS integer) IS NULL
    OR fact.observed_at >= now() - make_interval(days => CAST(:stale_hide_days AS integer))
  )
ORDER BY
    CASE fact.product_key
      WHEN 'gasoline' THEN 10
      WHEN 'diesel' THEN 20
      WHEN 'premium_gasoline' THEN 30
      WHEN 'lpg' THEN 40
      ELSE 100
    END,
    fact.product_name NULLS LAST,
    fact.product_key,
    dataset.provider,
    fact.price_domain
"""

_HISTORICAL_CURRENT_SQL: Final[str] = """
WITH ranked AS (
    SELECT
        fact.provider_dataset_id,
        dataset.dataset_key,
        dataset.display_name AS dataset_display_name,
        dataset.provider,
        fact.price_domain,
        fact.product_key,
        fact.product_name,
        fact.source_product_key,
        fact.source_product_name,
        fact.value_number,
        fact.unit,
        fact.observed_at,
        fact.known_at,
        row_number() OVER (
            PARTITION BY fact.provider_dataset_id, fact.price_domain, fact.product_key
            ORDER BY fact.observed_at DESC, fact.known_at DESC, fact.price_value_key DESC
        ) AS rank
    FROM feature.feature_price_values AS fact
    JOIN provider_sync.provider_datasets AS dataset
      ON dataset.provider_dataset_id = fact.provider_dataset_id
     AND dataset.is_active
    WHERE fact.feature_id = :feature_id
      AND fact.observed_at <= CAST(:observed_at AS timestamptz)
      AND fact.known_at <= CAST(:known_at AS timestamptz)
)
SELECT *
FROM ranked
WHERE rank = 1
ORDER BY
    CASE product_key
      WHEN 'gasoline' THEN 10
      WHEN 'diesel' THEN 20
      WHEN 'premium_gasoline' THEN 30
      WHEN 'lpg' THEN 40
      ELSE 100
    END,
    product_name NULLS LAST,
    product_key,
    provider,
    price_domain
"""

_HISTORY_SQL: Final[str] = """
SELECT
    fact.provider_dataset_id,
    dataset.dataset_key,
    dataset.display_name AS dataset_display_name,
    dataset.provider,
    fact.price_domain,
    fact.product_key,
    fact.product_name,
    fact.source_product_key,
    fact.source_product_name,
    fact.value_number,
    fact.unit,
    fact.observed_at,
    fact.known_at
FROM feature.feature_price_values AS fact
JOIN provider_sync.provider_datasets AS dataset
  ON dataset.provider_dataset_id = fact.provider_dataset_id
 AND dataset.is_active
WHERE fact.feature_id = :feature_id
  AND (
    CAST(:observed_at AS timestamptz) IS NULL
    OR (
        fact.observed_at <= CAST(:observed_at AS timestamptz)
        AND fact.known_at <= CAST(:known_at AS timestamptz)
    )
  )
ORDER BY fact.observed_at DESC, dataset.provider, fact.price_domain, fact.product_key
LIMIT :limit
"""


def _enum_value(value: Any) -> str:
    return str(getattr(value, "value", value))


def _price_value_params(
    value: PriceValue,
    *,
    context: _PriceValueWriteContext,
    canonical_feature_ids: Mapping[str, str],
) -> dict[str, Any]:
    price_domain = _enum_value(value.price_domain)
    key = make_price_value_key(
        feature_id=value.feature_id,
        provider_dataset_id=context.provider_dataset_id,
        price_domain=price_domain,
        product_key=value.product_key,
        observed_at=value.observed_at,
        source_record_key=context.source_record_key,
    )
    return {
        "price_value_key": key,
        # T-VN-39: 컬럼은 uuid다. 값 키(`key`)는 provider가 준 참조로 이미
        # 만들어졌고 그것을 흔들면 기존 행 전체가 중복이 된다 — 바꾸는 것은
        # 컬럼에 들어가는 값뿐이다(`infra/canonical_feature_ids.py`).
        "feature_id": canonical_feature_ids[value.feature_id],
        "provider_dataset_id": context.provider_dataset_id,
        "price_domain": price_domain,
        "product_key": value.product_key,
        "product_name": value.product_name,
        "source_product_key": value.source_product_key,
        "source_product_name": value.source_product_name,
        "observed_at": value.observed_at,
        "value_number": value.value_number,
        "unit": value.unit,
        "normalization_version": value.normalization_version,
        "payload": json.dumps(value.payload, ensure_ascii=False, default=str),
        "source_entity_key": context.source_entity_key,
        "source_record_key": context.source_record_key,
        "known_at": context.known_at,
    }


async def load_price_values(
    session: AsyncSession,
    values: Iterable[PriceValue],
    *,
    provider_dataset_id: int,
    source_record: SourceRecord,
) -> PriceValueLoadResult:
    """한 raw response의 price facts를 append-only로 적재한다.

    ``provider_dataset_id``는 exact operation membership이 전달한 canonical id이고,
    ``source_record``는 같은 response의 immutable 원문이다. source record 생성,
    fact append, current summary receipt/upsert를 같은 session transaction에서 묶어
    source-less price write와 current/history drift를 없앤다.

    dataset이 latest-only(ADR-114, ``core.retention``)면 summary 물화 직후 **같은 transaction·같은
    advisory lock** 안에서 superseded fact를 지운다 — commit 경계마다 "summary가 가리키는 fact만
    남는다"가 참이다.
    """
    if provider_dataset_id <= 0:
        raise ValueError("provider_dataset_id must be positive")
    from kortravelmap.infra.feature_repo import upsert_source_record

    await upsert_source_record(session, source_record)
    lineage = (
        await session.execute(
            text(
                """
                SELECT record.source_entity_key, record.fetched_at
                FROM provider_sync.source_records AS record
                JOIN provider_sync.source_entities AS entity
                  ON entity.source_entity_key = record.source_entity_key
                WHERE record.source_record_key = :source_record_key
                  AND entity.provider_dataset_id = :provider_dataset_id
                """
            ),
            {
                "source_record_key": source_record.source_record_key,
                "provider_dataset_id": provider_dataset_id,
            },
        )
    ).mappings().one_or_none()
    if lineage is None:
        raise ValueError(
            "price source response does not belong to the operation provider dataset"
        )
    context = _PriceValueWriteContext(
        provider_dataset_id=provider_dataset_id,
        source_entity_key=str(lineage["source_entity_key"]),
        source_record_key=source_record.source_record_key,
        known_at=lineage["fetched_at"],
    )
    materialized = list(values)
    canonical_feature_ids = await resolve_canonical_feature_ids(
        session, (v.feature_id for v in materialized)
    )
    params = [
        _price_value_params(
            v, context=context, canonical_feature_ids=canonical_feature_ids
        )
        for v in materialized
    ]
    if not params:
        return PriceValueLoadResult(inserted=0)
    await session.execute(text(_IMMUTABLE_INSERT_SQL), params)
    await materialize_current_price_summary(session, run_kind="ingest")
    pruned = 0
    if await _is_latest_only_dataset(session, provider_dataset_id):
        pruned = await prune_superseded_price_facts(
            session, provider_dataset_ids=[provider_dataset_id]
        )
    return PriceValueLoadResult(inserted=len(params), pruned=pruned)


async def _is_latest_only_dataset(session: AsyncSession, provider_dataset_id: int) -> bool:
    row = (
        await session.execute(
            text(_PRICE_DATASET_IDENTITY_SQL),
            {"provider_dataset_id": provider_dataset_id},
        )
    ).mappings().one_or_none()
    return row is not None and is_latest_only(str(row["provider"]), str(row["dataset_key"]))


async def prune_superseded_price_facts(
    session: AsyncSession,
    *,
    provider_dataset_ids: Sequence[int],
) -> int:
    """latest-only dataset의 superseded price fact를 지운다(ADR-114 결정 2).

    ``feature.current_price_summary``가 가리키지 않는 fact만 지운다. summary를 바꾸는 writer와
    겹치지 않도록 ``projection:current-price-summary`` transaction advisory lock을 잡는다 — 같은
    transaction에서 이미 쥐었으면(물화 직후) 즉시 돌아온다. 호출자는 이 transaction에서 summary가
    최신인 상태로 불러야 한다(적재 경로는 물화 직후, maintenance는 물화한 뒤).

    정책 판정은 하지 않는다 — 어떤 dataset을 넘길지는 호출자가 ``core.retention``으로 정한다. DB
    함수·트리거(migration 410)는 활성 kor-travel-transport dataset 밖이면 어떤 경우에도 거부한다.

    잠금 순서(ADR-111 §2): 적재 경로는 이미 ``feature-curation-write``를 쥔 뒤 여기 온다. maintenance도
    같은 순서로 부른다(gate → summary lock).
    """
    ids = sorted({int(value) for value in provider_dataset_ids})
    if not ids:
        return 0
    await session.execute(
        text(_ACQUIRE_PRICE_CURRENT_SUMMARY_LOCK_SQL),
        {"lock_id": _PRICE_CURRENT_SUMMARY_LOCK_ID},
    )
    pruned = 0
    for provider_dataset_id in ids:
        pruned += int(
            await session.scalar(
                text(_PRUNE_SUPERSEDED_PRICE_FACTS_SQL),
                {"provider_dataset_id": provider_dataset_id},
            )
            or 0
        )
    return pruned


async def latest_only_price_datasets_for_feature(
    session: AsyncSession,
    *,
    feature_id: str,
) -> list[FeaturePriceDataset]:
    """feature의 summary series 중 latest-only dataset(ADR-114)에 속한 것.

    이 dataset들의 이력은 Map DB에 없다 — 추이는 원천 서비스(transport)에서 읽는다.
    """
    rows = (
        await session.execute(text(_FEATURE_PRICE_DATASETS_SQL), {"feature_id": feature_id})
    ).mappings().all()
    return [
        FeaturePriceDataset(
            provider_dataset_id=int(row["provider_dataset_id"]),
            provider=str(row["provider"]),
            dataset_key=str(row["dataset_key"]),
            display_name=str(row["display_name"]),
            natural_key=None if row["natural_key"] is None else str(row["natural_key"]),
        )
        for row in rows
        if is_latest_only(str(row["provider"]), str(row["dataset_key"]))
    ]


async def materialize_current_price_summary(
    session: AsyncSession,
    *,
    run_kind: Literal["ingest", "reconcile", "backfill", "restore"] = "reconcile",
) -> PriceSummaryMaterializeResult:
    """active price dataset 전체의 current projection을 재구성한다.

    price winner의 business rank는 ``observed_at DESC, known_at DESC,
    price_value_key DESC`` 뿐이다. 실행 receipt의 시각·종류는 이 순위에 전혀
    관여하지 않는다. 동일 winner인 reconcile은 summary pointer를 다시 쓰지 않고
    audit receipt만 남긴다.
    """
    if run_kind not in {"ingest", "reconcile", "backfill", "restore"}:
        raise ValueError("unsupported price summary run_kind")

    # summary는 전역 projection이다. desired 집합을 계산한 오래된 transaction이
    # 더 새 writer의 series를 stale-delete 또는 pointer rollback하지 않도록
    # transaction advisory lock으로 직렬화한다.
    await session.execute(
        text(_ACQUIRE_PRICE_CURRENT_SUMMARY_LOCK_SQL),
        {"lock_id": _PRICE_CURRENT_SUMMARY_LOCK_ID},
    )

    summary_run_id = await session.scalar(
        text(_INSERT_CURRENT_PRICE_SUMMARY_RUN_SQL),
        {
            "run_kind": run_kind,
            "scope": json.dumps({"provider_dataset_scope": "all_active"}),
        },
    )
    if summary_run_id is None:
        raise AssertionError("price current-summary receipt write disappeared")

    desired = (await session.execute(text(_PRICE_SUMMARY_DESIRED_SQL))).mappings().all()
    input_count = await session.scalar(text(_PRICE_SUMMARY_INPUT_COUNT_SQL))
    existing_rows = (
        await session.execute(
            text(
                """
                SELECT feature_id, provider_dataset_id, price_domain, product_key,
                       price_value_key
                FROM feature.current_price_summary
                """
            )
        )
    ).mappings().all()
    existing = {
        (
            str(row["feature_id"]),
            int(row["provider_dataset_id"]),
            str(row["price_domain"]),
            str(row["product_key"]),
        ): str(row["price_value_key"])
        for row in existing_rows
    }
    desired_by_key = {
        (
            str(row["feature_id"]),
            int(row["provider_dataset_id"]),
            str(row["price_domain"]),
            str(row["product_key"]),
        ): row
        for row in desired
    }
    inserted_count = sum(key not in existing for key in desired_by_key)
    updated_count = sum(
        key in existing and existing[key] != str(row["price_value_key"])
        for key, row in desired_by_key.items()
    )
    deleted_count = sum(key not in desired_by_key for key in existing)
    changed = [
        row
        for key, row in desired_by_key.items()
        if key not in existing or existing[key] != str(row["price_value_key"])
    ]

    completed = await session.execute(
        text(_COMPLETE_CURRENT_PRICE_SUMMARY_RUN_SQL),
        {
            "summary_run_id": summary_run_id,
            "input_count": int(input_count or 0),
            "inserted_count": inserted_count,
            "updated_count": updated_count,
            "deleted_count": deleted_count,
            "detail": json.dumps({"selection": "price-v1"}),
        },
    )
    if cast(CursorResult[Any], completed).rowcount != 1:
        raise AssertionError("price current-summary receipt could not become succeeded")
    if changed:
        await session.execute(
            text(_UPSERT_CURRENT_PRICE_SUMMARY_SQL),
            [{**dict(row), "summary_run_id": summary_run_id} for row in changed],
        )
    await session.execute(text(_DELETE_STALE_PRICE_SUMMARIES_SQL))
    return PriceSummaryMaterializeResult(
        summary_run_id=int(summary_run_id),
        input_count=int(input_count or 0),
        inserted_count=inserted_count,
        updated_count=updated_count,
        deleted_count=deleted_count,
    )


def _price_point(row: RowMapping) -> PricePoint:
    return PricePoint(
        provider_dataset_id=int(row["provider_dataset_id"]),
        dataset_key=str(row["dataset_key"]),
        dataset_display_name=str(row["dataset_display_name"]),
        provider=str(row["provider"]),
        price_domain=str(row["price_domain"]),
        product_key=str(row["product_key"]),
        product_name=row["product_name"],
        source_product_key=row["source_product_key"],
        source_product_name=row["source_product_name"],
        value_number=row["value_number"],
        unit=str(row["unit"]),
        observed_at=row["observed_at"],
        known_at=row["known_at"],
    )


def sort_current_points(points: list[PricePoint]) -> list[PricePoint]:
    """price card current의 표시 순서(유종 고정 순서 → 이름 → 키 → dataset → domain)."""
    return sorted(
        points,
        key=lambda point: (
            _PRODUCT_ORDER.get(point.product_key, 100),
            point.product_name or "",
            point.product_key,
            point.provider_dataset_id,
            point.price_domain,
        ),
    )


async def _build_price_card(
    session: AsyncSession,
    *,
    feature_id: str,
    observed_at: datetime | None,
    known_at: datetime | None,
    history_limit: int = 100,
    freshness_seconds: int = DEFAULT_PRICE_FRESHNESS_SECONDS,
    stale_hide_days: int | None = DEFAULT_PRICE_STALE_HIDE_DAYS,
) -> PriceCard:
    """feature의 price card — series별 최신값과 최근 이력.

    각 ``provider + price_domain + product_key`` series에서 ``observed_at`` 최신
    1건을 현재 가격으로 고르고, history는 최신 관측순으로 제한한다. card 자체는
    feature 존재 여부를 판정하지 않는다. 호출 라우터가 필요하면 feature 상세
    조회와 조합한다.

    ``stale_hide_days``보다 오래된 관측은 **current에서 제외**한다(이력은 유지) —
    로테이션 주기 밖으로 밀린 주유소가 옛 가격을 현재가처럼 보이지 않게 한다.
    snapshot에서는 observed/known time이 함께 필요하고 신선도 지평선을 적용하지
    않는다. current read에서는 둘 다 ``None``이다.
    """

    limit = min(max(history_limit, 1), 500)
    params: dict[str, Any] = {
        "feature_id": feature_id,
        "observed_at": observed_at,
        "known_at": known_at,
        "stale_hide_days": stale_hide_days,
    }
    if (observed_at is None) != (known_at is None):
        raise ValueError("price snapshot requires observed_at and known_at together")
    current_sql = _CURRENT_SQL if observed_at is None else _HISTORICAL_CURRENT_SQL
    current_rows = (await session.execute(text(current_sql), params)).mappings().all()
    history_rows = (
        await session.execute(
            text(_HISTORY_SQL),
            {
                "feature_id": feature_id,
                "observed_at": observed_at,
                "known_at": known_at,
                "limit": limit,
            },
        )
    ).mappings().all()

    current = sort_current_points([_price_point(row) for row in current_rows])
    history = [_price_point(row) for row in history_rows]
    latest_at = max((point.observed_at for point in history), default=None)
    reference = observed_at if observed_at is not None else kst_now()
    is_stale = (
        latest_at is None
        or (reference - latest_at).total_seconds() > freshness_seconds
    )
    return PriceCard(
        feature_id=feature_id,
        current=current,
        history=history,
        latest_at=latest_at,
        is_stale=is_stale,
        snapshot_observed_at=observed_at,
        snapshot_known_at=known_at,
    )


async def build_price_card(
    session: AsyncSession,
    *,
    feature_id: str,
    history_limit: int = 100,
    freshness_seconds: int = DEFAULT_PRICE_FRESHNESS_SECONDS,
    stale_hide_days: int | None = DEFAULT_PRICE_STALE_HIDE_DAYS,
) -> PriceCard:
    """receipt-backed current summary에서 price card를 만든다."""

    return await _build_price_card(
        session,
        feature_id=feature_id,
        observed_at=None,
        known_at=None,
        history_limit=history_limit,
        freshness_seconds=freshness_seconds,
        stale_hide_days=stale_hide_days,
    )


async def build_price_snapshot(
    session: AsyncSession,
    *,
    feature_id: str,
    observed_at: datetime,
    known_at: datetime,
    history_limit: int = 100,
    freshness_seconds: int = DEFAULT_PRICE_FRESHNESS_SECONDS,
) -> PriceCard:
    """명시된 observed/knowledge time의 immutable price fact를 재현한다."""

    if observed_at.tzinfo is None or observed_at.utcoffset() is None:
        raise ValueError("price snapshot observed_at must be timezone-aware")
    if known_at.tzinfo is None or known_at.utcoffset() is None:
        raise ValueError("price snapshot known_at must be timezone-aware")
    return await _build_price_card(
        session,
        feature_id=feature_id,
        observed_at=observed_at,
        known_at=known_at,
        history_limit=history_limit,
        freshness_seconds=freshness_seconds,
        stale_hide_days=None,
    )
