#!/usr/bin/env python3
"""#741 production live 인수용 weather/price owned fixture 관리.

이 helper는 exact API image의 standalone container에 read-only bind mount해 실행한다.
운영 기존 row를 빌리지 않고 실행별 exact ID 두 건만 transaction으로
seed/cleanup/audit한다. host runner가 mutation 전에 root-owned BLOCKED/journal을 기록하는
것이 선행조건이다.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import math
import re
from collections import Counter
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Final, NamedTuple

from sqlalchemy import text
from sqlalchemy.engine import RowMapping
from sqlalchemy.ext.asyncio import AsyncSession

from kortravelmap.core.ids import make_payload_hash, make_source_record_key
from kortravelmap.dto import SourceRecord
from kortravelmap.dto._time import kst_now
from kortravelmap.dto.price import PriceValue
from kortravelmap.dto.weather import WeatherValue
from kortravelmap.infra import price_repo, weather_repo
from kortravelmap.infra.db import make_async_engine
from kortravelmap.infra.provider_refresh_policy_repo import (
    get_provider_refresh_policy,
    upsert_provider_refresh_policy,
)
from kortravelmap.settings import KorTravelMapSettings

_RUN_ID_RE: Final[re.Pattern[str]] = re.compile(r"^[a-z0-9][a-z0-9-]{15,79}$")
_LON: Final[float] = 127.5
_LAT: Final[float] = 36.5
_E2E_PROVIDER: Final[str] = "e2e-live-acceptance"


def _dataset_key(run_id: str, kind: str) -> str:
    return f"admin-live-{run_id}-{kind}"


async def _ensure_dataset(session: AsyncSession, *, run_id: str, kind: str) -> int:
    dataset_key = _dataset_key(run_id, kind)
    value = await session.scalar(
        text(
            """
            INSERT INTO provider_sync.provider_datasets (
                provider, dataset_key, display_name, source_kind
            ) VALUES (:provider, :dataset_key, :display_name, 'manual')
            ON CONFLICT (provider, dataset_key) DO UPDATE
            SET is_active = true
            RETURNING provider_dataset_id
            """
        ),
        {
            "provider": _E2E_PROVIDER,
            "dataset_key": dataset_key,
            "display_name": f"E2E admin {kind} {run_id}",
        },
    )
    assert value is not None
    dataset_id = int(value)
    if kind == "weather":
        policy = await get_provider_refresh_policy(
            session, provider_dataset_id=dataset_id
        )
        await upsert_provider_refresh_policy(
            session,
            provider_dataset_id=dataset_id,
            source_kind="manual",
            expected_revision=(policy.revision if policy is not None else None),
            stale_after_minutes=24 * 60,
        )
    return dataset_id


def _response_record(
    *, run_id: str, kind: str, fetched_at: datetime
) -> SourceRecord:
    dataset_key = _dataset_key(run_id, kind)
    raw_data = {"fixture": "admin-feature-live-acceptance", "run_id": run_id, "kind": kind}
    payload_hash = make_payload_hash(raw_data)
    source_entity_id = f"run:{run_id}:{kind}"
    return SourceRecord(
        provider=_E2E_PROVIDER,
        dataset_key=dataset_key,
        source_entity_type=f"{kind}_response",
        source_entity_id=source_entity_id,
        raw_payload_hash=payload_hash,
        raw_data=raw_data,
        fetched_at=fetched_at,
        source_record_key=make_source_record_key(
            provider=_E2E_PROVIDER,
            dataset_key=dataset_key,
            source_entity_type=f"{kind}_response",
            source_entity_id=source_entity_id,
            raw_payload_hash=payload_hash,
        ),
    )


def _feature_ids(run_id: str) -> tuple[str, str]:
    prefix = f"e2e_live_acceptance::{run_id}"
    return f"{prefix}::weather", f"{prefix}::price"


def _api_feature_fingerprints(
    run_id: str,
) -> dict[str, tuple[float, float, frozenset[str]]]:
    prefix = f"e2e_live_acceptance::{run_id}"
    jitter = hashlib.sha256(f"acceptance-coord:{run_id}".encode()).digest()

    def coord_jitter(offset: int) -> float:
        return (
            int.from_bytes(jitter[offset : offset + 4], "big") / 0xFFFFFFFF * 2 - 1
        ) * 0.25

    marker_lon = _LON + coord_jitter(0)
    marker_lat = _LAT + coord_jitter(4)
    expected: dict[str, tuple[float, float, frozenset[str]]] = {}
    for index, status in enumerate(("draft", "inactive", "hidden")):
        expected[f"{prefix}::marker::{status}"] = (
            marker_lon + index * 0.001,
            marker_lat + index * 0.001,
            frozenset({f"E2E {status} marker {run_id}"}),
        )
    expected[f"{prefix}::correction"] = (
        _LON,
        _LAT - 0.002,
        frozenset(
            {
                f"E2E correction baseline {run_id}",
                f"E2E approved competing update {run_id}",
            }
        ),
    )
    search_token = hashlib.sha256(
        f"acceptance-search:{run_id}".encode()
    ).hexdigest()[:32]
    for index, suffix in enumerate(("alpha", "beta")):
        expected[f"{prefix}::search::{suffix}"] = (
            _LON + 0.004 + index * 0.001,
            _LAT + 0.004 + index * 0.001,
            frozenset({f"e2esrch {search_token} {suffix}"}),
        )
    return expected


async def _counts(session: AsyncSession, feature_ids: tuple[str, str]) -> dict[str, int]:
    weather_id, price_id = feature_ids
    row = (
        await session.execute(
            text(
                """
                SELECT
                  (SELECT count(*) FROM feature.features
                   WHERE feature_id = ANY(CAST(:feature_ids AS text[]))) AS features,
                  (SELECT count(*) FROM feature.feature_weather_values
                   WHERE feature_id = :weather_id) AS weather_values,
                  (SELECT count(*) FROM feature.feature_price_values
                   WHERE feature_id = :price_id) AS price_values
                """
            ),
            {
                "feature_ids": list(feature_ids),
                "weather_id": weather_id,
                "price_id": price_id,
            },
        )
    ).mappings().one()
    return {key: int(row[key]) for key in ("features", "weather_values", "price_values")}


async def _assert_owned_or_absent(
    session: AsyncSession,
    run_id: str,
    feature_ids: tuple[str, str],
    *,
    lock: bool = False,
) -> set[str]:
    lock_clause = " FOR UPDATE" if lock else ""
    rows = (
        await session.execute(
            text(
                """
                SELECT
                  feature_id, kind, name, category, status,
                  marker_icon, marker_color, data_origin, coord_precision_digits,
                  x_extension.ST_X(coord) AS lon,
                  x_extension.ST_Y(coord) AS lat
                FROM feature.features
                WHERE feature_id = ANY(CAST(:feature_ids AS text[]))
                ORDER BY feature_id
                """
                + lock_clause
            ),
            {"feature_ids": list(feature_ids)},
        )
    ).mappings()
    expected = {
        feature_ids[0]: {
            "category": "00000000",
            "coord_precision_digits": 6,
            "data_origin": "user_request",
            "kind": "weather",
            "lat": _LAT,
            "lon": _LON + 0.002,
            "marker_color": "P-03",
            "marker_icon": "weather",
            "name": f"E2E hidden weather {run_id}",
            "status": "hidden",
        },
        feature_ids[1]: {
            "category": "00000000",
            "coord_precision_digits": 6,
            "data_origin": "user_request",
            "kind": "price",
            "lat": _LAT,
            "lon": _LON - 0.002,
            "marker_color": "P-04",
            "marker_icon": "fuel",
            "name": f"E2E hidden price {run_id}",
            "status": "hidden",
        },
    }
    present: set[str] = set()
    for row in rows:
        feature_id = str(row["feature_id"])
        present.add(feature_id)
        fingerprint = {
            "category": str(row["category"]),
            "coord_precision_digits": int(row["coord_precision_digits"]),
            "data_origin": str(row["data_origin"]),
            "kind": str(row["kind"]),
            "lat": float(row["lat"]),
            "lon": float(row["lon"]),
            "marker_color": str(row["marker_color"]),
            "marker_icon": str(row["marker_icon"]),
            "name": str(row["name"]),
            "status": str(row["status"]),
        }
        if expected.get(feature_id) != fingerprint:
            raise RuntimeError("owned fixture ID의 소유권 fingerprint가 다릅니다")
    return present


def _quote_identifier(value: str) -> str:
    return '"' + value.replace('"', '""') + '"'


async def _foreign_key_reference_counts(
    session: AsyncSession,
    feature_ids: tuple[str, ...],
) -> dict[str, int]:
    constraints = (
        await session.execute(
            text(
                """
                SELECT
                  constraint_row.conname,
                  local_schema.nspname AS schema_name,
                  local_table.relname AS table_name,
                  local_column.attname AS column_name,
                  target_column.attname AS target_column_name
                FROM pg_catalog.pg_constraint AS constraint_row
                JOIN pg_catalog.pg_class AS local_table
                  ON local_table.oid = constraint_row.conrelid
                JOIN pg_catalog.pg_namespace AS local_schema
                  ON local_schema.oid = local_table.relnamespace
                JOIN pg_catalog.pg_attribute AS local_column
                  ON local_column.attrelid = constraint_row.conrelid
                 AND local_column.attnum = constraint_row.conkey[1]
                JOIN pg_catalog.pg_attribute AS target_column
                  ON target_column.attrelid = constraint_row.confrelid
                 AND target_column.attnum = constraint_row.confkey[1]
                WHERE constraint_row.contype = 'f'
                  AND constraint_row.confrelid = 'feature.features'::regclass
                  -- subtype/alias identity fence처럼 feature_id에 다른 정본 열을 붙이는
                  -- composite FK는 이 fixture가 가진 feature_id만으로 reference를 셀 수
                  -- 없다. 이 ownership 검사는 단일 feature_id FK의 cascade 잔여만
                  -- 정확히 계수한다.
                  AND cardinality(constraint_row.conkey) = 1
                  AND cardinality(constraint_row.confkey) = 1
                ORDER BY local_schema.nspname, local_table.relname,
                         local_column.attname, constraint_row.conname
                """
            )
        )
    ).mappings()
    counts: dict[str, int] = {}
    for constraint in constraints:
        if str(constraint["target_column_name"]) != "feature_id":
            raise RuntimeError("feature FK topology가 단일 feature_id 계약과 다릅니다")
        schema_name = str(constraint["schema_name"])
        table_name = str(constraint["table_name"])
        column_name = str(constraint["column_name"])
        key = f"{schema_name}.{table_name}.{column_name}"
        if key in counts:
            raise RuntimeError("같은 feature FK column에 중복 constraint가 있습니다")
        statement = text(
            "SELECT count(*) FROM "
            f"{_quote_identifier(schema_name)}.{_quote_identifier(table_name)} "
            f"WHERE {_quote_identifier(column_name)} = ANY(CAST(:feature_ids AS text[]))"
        )
        counts[key] = int(
            (await session.execute(statement, {"feature_ids": list(feature_ids)}))
            .scalars()
            .one()
        )
    required = {
        "feature.feature_price_values.feature_id",
        "feature.feature_weather_values.feature_id",
    }
    if not required.issubset(counts):
        raise RuntimeError("weather/price feature FK constraint가 누락되었습니다")
    return counts


async def _assert_owned_values(
    session: AsyncSession,
    run_id: str,
    feature_ids: tuple[str, str],
    present: set[str],
    *,
    lock: bool = False,
) -> None:
    lock_clause = " FOR UPDATE" if lock else ""
    weather_rows = (
        await session.execute(
            text(
                """
                SELECT
                  dataset.provider, dataset.dataset_key,
                  weather_domain, forecast_style, timeline_bucket,
                  metric_key, metric_name, value_number, unit,
                  normalization_version, payload
                FROM feature.feature_weather_values AS fact
                JOIN provider_sync.provider_datasets AS dataset
                  ON dataset.provider_dataset_id = fact.provider_dataset_id
                WHERE feature_id = :feature_id
                """
                + lock_clause
            ),
            {"feature_id": feature_ids[0]},
        )
    ).mappings().all()
    price_rows = (
        await session.execute(
            text(
                """
                SELECT
                  dataset.provider, dataset.dataset_key,
                  price_domain, product_key, product_name,
                  value_number, unit, normalization_version, payload
                FROM feature.feature_price_values AS fact
                JOIN provider_sync.provider_datasets AS dataset
                  ON dataset.provider_dataset_id = fact.provider_dataset_id
                WHERE feature_id = :feature_id
                """
                + lock_clause
            ),
            {"feature_id": feature_ids[1]},
        )
    ).mappings().all()
    expected_weather = []
    if feature_ids[0] in present:
        expected_weather.append(
            {
                "forecast_style": "short",
                "metric_key": "TMP",
                "metric_name": "인수 기온",
                "normalization_version": "e2e-v1",
                "payload": {"fixture": "admin-feature-live-acceptance"},
                "provider": _E2E_PROVIDER,
                "dataset_key": _dataset_key(run_id, "weather"),
                "timeline_bucket": "short",
                "unit": "deg_c",
                "value_number": Decimal("21.5"),
                "weather_domain": "kma_short_forecast",
            }
        )
    expected_price = []
    if feature_ids[1] in present:
        expected_price.append(
            {
                "normalization_version": "e2e-v1",
                "payload": {"fixture": "admin-feature-live-acceptance"},
                "price_domain": "opinet_gas_station",
                "product_key": "gasoline",
                "product_name": "인수 휘발유",
                "provider": _E2E_PROVIDER,
                "dataset_key": _dataset_key(run_id, "price"),
                "unit": "KRW/L",
                "value_number": Decimal("1711"),
            }
        )
    if [dict(row) for row in weather_rows] != expected_weather:
        raise RuntimeError("owned weather value fingerprint가 다릅니다")
    if [dict(row) for row in price_rows] != expected_price:
        raise RuntimeError("owned price value fingerprint가 다릅니다")


async def _assert_owned_state(
    session: AsyncSession,
    run_id: str,
    feature_ids: tuple[str, str],
    *,
    lock: bool = False,
) -> tuple[dict[str, int], dict[str, int]]:
    present = await _assert_owned_or_absent(
        session,
        run_id,
        feature_ids,
        lock=lock,
    )
    counts = await _counts(session, feature_ids)
    if counts["features"] != len(present):
        raise RuntimeError("owned fixture cardinality와 fingerprint가 다릅니다")
    await _assert_owned_values(session, run_id, feature_ids, present, lock=lock)
    foreign_keys = await _foreign_key_reference_counts(session, feature_ids)
    expected_references: dict[str, int] = {}
    if present:
        # feature INSERT trigger가 canonical alias를 함께 만든다. alias는 direct
        # feature_id FK이므로 fixture cleanup의 cascade evidence에 포함한다.
        expected_references["feature.feature_aliases.feature_id"] = len(present)
    if feature_ids[0] in present:
        expected_references["feature.feature_weather_values.feature_id"] = 1
        expected_references["feature.current_weather_summary.feature_id"] = 1
    if feature_ids[1] in present:
        expected_references["feature.feature_price_values.feature_id"] = 1
        expected_references["feature.current_price_summary.feature_id"] = 1
    observed_references = {key: value for key, value in foreign_keys.items() if value}
    if observed_references != expected_references:
        raise RuntimeError("owned fixture에 예상하지 않은 FK reference가 있습니다")
    return counts, foreign_keys


async def _seed(
    session: AsyncSession,
    run_id: str,
) -> tuple[dict[str, int], dict[str, int]]:
    feature_ids = _feature_ids(run_id)
    before = await _counts(session, feature_ids)
    if before != {"features": 0, "weather_values": 0, "price_values": 0}:
        raise RuntimeError("owned fixture ID가 이미 존재합니다; recovery를 먼저 실행하세요")

    weather_id, price_id = feature_ids
    await session.execute(
        text(
            """
            INSERT INTO feature.features (
                feature_id, kind, name, category, coord, coord_precision_digits, status,
                marker_icon, marker_color, data_origin, data_version,
                updated_at
            ) VALUES
              (
                :weather_id, 'weather', :weather_name, '00000000',
                x_extension.ST_SetSRID(
                  x_extension.ST_MakePoint(:weather_lon, :lat), 4326
                ),
                6, 'hidden', 'weather', 'P-03', 'user_request', 1, now()
              ),
              (
                :price_id, 'price', :price_name, '00000000',
                x_extension.ST_SetSRID(
                  x_extension.ST_MakePoint(:price_lon, :lat), 4326
                ),
                6, 'hidden', 'fuel', 'P-04', 'user_request', 1, now()
              )
            """
        ),
        {
            "weather_id": weather_id,
            "weather_name": f"E2E hidden weather {run_id}",
            "weather_lon": _LON + 0.002,
            "price_id": price_id,
            "price_name": f"E2E hidden price {run_id}",
            "price_lon": _LON - 0.002,
            "lat": _LAT,
        },
    )
    now = kst_now().replace(microsecond=0)
    weather_dataset_id = await _ensure_dataset(session, run_id=run_id, kind="weather")
    price_dataset_id = await _ensure_dataset(session, run_id=run_id, kind="price")
    await weather_repo.load_weather_values(
        session,
        [
            WeatherValue(
                feature_id=weather_id,
                provider="e2e-live-acceptance",
                weather_domain="kma_short_forecast",
                forecast_style="short",
                timeline_bucket="short",
                metric_key="TMP",
                metric_name="인수 기온",
                value_number=Decimal("21.5"),
                unit="deg_c",
                issued_at=now - timedelta(hours=1),
                valid_at=now,
                normalization_version="e2e-v1",
                payload={"fixture": "admin-feature-live-acceptance"},
            )
        ],
        provider_dataset_id=weather_dataset_id,
        source_record=_response_record(run_id=run_id, kind="weather", fetched_at=now),
        selected_at=now,
    )
    await price_repo.load_price_values(
        session,
        [
            PriceValue(
                feature_id=price_id,
                provider="e2e-live-acceptance",
                price_domain="opinet_gas_station",
                product_key="gasoline",
                product_name="인수 휘발유",
                value_number=Decimal("1711"),
                unit="KRW/L",
                observed_at=now,
                normalization_version="e2e-v1",
                payload={"fixture": "admin-feature-live-acceptance"},
            )
        ],
        provider_dataset_id=price_dataset_id,
        source_record=_response_record(run_id=run_id, kind="price", fetched_at=now),
    )
    observed, foreign_keys = await _assert_owned_state(session, run_id, feature_ids)
    if observed != {"features": 2, "weather_values": 1, "price_values": 1}:
        raise RuntimeError("owned weather/price fixture cardinality가 예상과 다릅니다")
    return observed, foreign_keys


async def _cleanup(
    session: AsyncSession,
    run_id: str,
) -> tuple[dict[str, int], dict[str, int]]:
    feature_ids = _feature_ids(run_id)
    # Parent FOR UPDATE는 concurrent FK insert의 KEY SHARE와 충돌한다. 기존 child도
    # FOR UPDATE한 같은 transaction 안에서 fingerprint/FK audit/delete를 끝낸다.
    await _assert_owned_state(session, run_id, feature_ids, lock=True)
    await session.execute(
        text(
            """
            DELETE FROM feature.features
            WHERE (feature_id = :weather_id AND kind = 'weather')
               OR (feature_id = :price_id AND kind = 'price')
            """
        ),
        {"weather_id": feature_ids[0], "price_id": feature_ids[1]},
    )
    observed, foreign_keys = await _assert_owned_state(session, run_id, feature_ids)
    if observed != {"features": 0, "weather_values": 0, "price_values": 0}:
        raise RuntimeError("owned weather/price fixture cleanup이 완결되지 않았습니다")
    await _delete_owned_datasets(session, run_id)
    return observed, foreign_keys


async def _delete_owned_datasets(session: AsyncSession, run_id: str) -> None:
    """fixture response lineage와 dataset/policy를 feature 삭제 뒤 완전히 지운다."""

    dataset_keys = [_dataset_key(run_id, kind) for kind in ("weather", "price")]
    params = {"provider": _E2E_PROVIDER, "dataset_keys": dataset_keys}
    # 0091의 entity-head 완결성 trigger 때문에 head → record → entity 순서가
    # 필수다. dataset은 모든 raw 계보와 policy가 사라진 뒤에만 지운다.
    for statement in (
        """
        DELETE FROM provider_sync.source_entity_heads AS head
        USING provider_sync.source_entities AS entity,
              provider_sync.provider_datasets AS dataset
        WHERE head.source_entity_key = entity.source_entity_key
          AND entity.provider_dataset_id = dataset.provider_dataset_id
          AND dataset.provider = :provider
          AND dataset.dataset_key = ANY(CAST(:dataset_keys AS text[]))
        """,
        """
        DELETE FROM provider_sync.source_records AS record
        USING provider_sync.source_entities AS entity,
              provider_sync.provider_datasets AS dataset
        WHERE record.source_entity_key = entity.source_entity_key
          AND entity.provider_dataset_id = dataset.provider_dataset_id
          AND dataset.provider = :provider
          AND dataset.dataset_key = ANY(CAST(:dataset_keys AS text[]))
        """,
        """
        DELETE FROM provider_sync.source_entities AS entity
        USING provider_sync.provider_datasets AS dataset
        WHERE entity.provider_dataset_id = dataset.provider_dataset_id
          AND dataset.provider = :provider
          AND dataset.dataset_key = ANY(CAST(:dataset_keys AS text[]))
        """,
        """
        DELETE FROM ops.provider_refresh_policies AS policy
        USING provider_sync.provider_datasets AS dataset
        WHERE policy.provider_dataset_id = dataset.provider_dataset_id
          AND dataset.provider = :provider
          AND dataset.dataset_key = ANY(CAST(:dataset_keys AS text[]))
        """,
        """
        DELETE FROM provider_sync.provider_datasets
        WHERE provider = :provider
          AND dataset_key = ANY(CAST(:dataset_keys AS text[]))
        """,
    ):
        await session.execute(text(statement), params)
    remaining = int(
        (
            await session.execute(
                text(
                    """
                    SELECT count(*)
                    FROM provider_sync.provider_datasets
                    WHERE provider = :provider
                      AND dataset_key = ANY(CAST(:dataset_keys AS text[]))
                    """
                ),
                params,
            )
        )
        .scalars()
        .one()
    )
    if remaining:
        raise RuntimeError("owned fixture provider dataset cleanup이 완결되지 않았습니다")


class _ApiOwnedInspection(NamedTuple):
    feature_ids: tuple[str, ...]
    features: int
    requests: int
    request_fingerprints: Counter[tuple[str, str, str]]
    versions: int
    foreign_keys: dict[str, int]


async def _inspect_api_owned(
    session: AsyncSession,
    run_id: str,
) -> _ApiOwnedInspection:
    expected = _api_feature_fingerprints(run_id)
    feature_ids = tuple(expected)
    rows = (
        await session.execute(
            text(
                """
                SELECT
                  feature_id, kind, name, category, status,
                  marker_icon, marker_color, data_origin,
                  x_extension.ST_X(coord) AS lon,
                  x_extension.ST_Y(coord) AS lat
                FROM feature.features
                WHERE feature_id LIKE :prefix ESCAPE '\\'
                ORDER BY feature_id
                FOR UPDATE
                """
            ),
            {"prefix": f"e2e_live_acceptance::{run_id}::%"},
        )
    ).mappings().all()
    for row in rows:
        feature_id = str(row["feature_id"])
        fingerprint = expected.get(feature_id)
        if fingerprint is None:
            raise RuntimeError("API-owned prefix에 예상하지 않은 Feature가 있습니다")
        expected_lon, expected_lat, expected_names = fingerprint
        if (
            row["kind"] != "place"
            or row["category"] != "01070300"
            or row["status"] != "deleted"
            or row["marker_icon"] != "marker"
            or row["marker_color"] != "P-02"
            or row["data_origin"] != "user_request"
            or row["name"] not in expected_names
            or not math.isclose(
                float(row["lon"]),
                expected_lon,
                rel_tol=0,
                abs_tol=1e-9,
            )
            or not math.isclose(
                float(row["lat"]),
                expected_lat,
                rel_tol=0,
                abs_tol=1e-9,
            )
        ):
            raise RuntimeError("API-owned Feature fingerprint가 다릅니다")

    request_rows = (
        await session.execute(
            text(
                """
                SELECT
                  request_id, feature_id, action, state, review_mode, reason,
                  requested_by, reviewed_by
                FROM ops.feature_change_requests
                WHERE feature_id = ANY(CAST(:feature_ids AS text[]))
                ORDER BY created_at, request_id
                FOR UPDATE
                """
            ),
            {"feature_ids": list(feature_ids)},
        )
    ).mappings().all()
    reason_prefix = f"admin feature live acceptance {run_id} "
    allowed_reasons = {
        f"{reason_prefix}create active",
        f"{reason_prefix}create draft",
        f"{reason_prefix}create hidden",
        f"{reason_prefix}create inactive",
        f"{reason_prefix}competing update",
        f"{reason_prefix}reject reapply fixture",
        f"{reason_prefix}cleanup delete",
    }
    requests_by_id: dict[str, tuple[str, str, str]] = {}
    request_fingerprints: Counter[tuple[str, str, str]] = Counter()
    for request in request_rows:
        if (
            request["feature_id"] not in expected
            or request["action"] not in {"add", "update", "delete"}
            or request["state"] not in {"applied", "rejected"}
            or request["review_mode"] != "require_review"
            or request["reason"] not in allowed_reasons
            or request["requested_by"] != "admin"
            or request["reviewed_by"] != "admin"
        ):
            raise RuntimeError("API-owned change request fingerprint가 다릅니다")
        request_id = str(request["request_id"])
        if request_id in requests_by_id:
            raise RuntimeError("API-owned change request ID가 중복됩니다")
        requests_by_id[request_id] = (
            str(request["feature_id"]),
            str(request["action"]),
            str(request["state"]),
        )
        request_fingerprints[
            (
                str(request["action"]),
                str(request["state"]),
                str(request["reason"]),
            )
        ] += 1

    version_rows = (
        await session.execute(
            text(
                """
                SELECT
                  feature_id, version, origin, change_kind, payload,
                  request_id, created_by
                FROM feature.feature_versions
                WHERE feature_id = ANY(CAST(:feature_ids AS text[]))
                ORDER BY feature_id, version
                FOR UPDATE
                """
            ),
            {"feature_ids": list(feature_ids)},
        )
    ).mappings().all()
    changes_by_feature: dict[str, list[str]] = {}
    for version_row in version_rows:
        feature_id = str(version_row["feature_id"])
        fingerprint = expected.get(feature_id)
        payload = version_row["payload"]
        version = int(version_row["version"])
        change_kind = str(version_row["change_kind"])
        linked_request = requests_by_id.get(str(version_row["request_id"]))
        if (
            fingerprint is None
            or not isinstance(payload, dict)
            or version < 1
            or version_row["origin"] != "user_request"
            or change_kind not in {"add", "update", "delete"}
            or version_row["created_by"] != "admin"
            or linked_request != (feature_id, change_kind, "applied")
        ):
            raise RuntimeError("API-owned Feature version 소유권이 다릅니다")
        expected_lon, expected_lat, expected_names = fingerprint
        expected_status = "active"
        if change_kind == "delete":
            expected_status = "deleted"
        elif change_kind == "add":
            for marker_status in ("draft", "inactive", "hidden"):
                if feature_id.endswith(f"::marker::{marker_status}"):
                    expected_status = marker_status
                    break
        if (
            payload.get("feature_id") != feature_id
            or payload.get("kind") != "place"
            or payload.get("category") != "01070300"
            or payload.get("data_origin") != "user_request"
            or payload.get("marker_icon") != "marker"
            or payload.get("marker_color") != "P-02"
            or payload.get("coord_precision_digits") != 6
            or payload.get("data_version") != version
            or payload.get("user_change_kind") != change_kind
            or payload.get("user_change_status") != "applied"
            or payload.get("name") not in expected_names
            or payload.get("status") != expected_status
            or not isinstance(payload.get("lon"), (int, float))
            or not isinstance(payload.get("lat"), (int, float))
            or not math.isclose(
                float(payload["lon"]), expected_lon, rel_tol=0, abs_tol=1e-9
            )
            or not math.isclose(
                float(payload["lat"]), expected_lat, rel_tol=0, abs_tol=1e-9
            )
        ):
            raise RuntimeError("API-owned Feature version payload가 다릅니다")
        changes_by_feature.setdefault(feature_id, []).append(change_kind)

    for feature_id, changes in changes_by_feature.items():
        expected_sequence = ["add", "delete"]
        if feature_id.endswith("::correction") and "update" in changes:
            expected_sequence = ["add", "update", "delete"]
        versions = [
            int(row["version"])
            for row in version_rows
            if str(row["feature_id"]) == feature_id
        ]
        if changes != expected_sequence or versions != list(
            range(1, len(changes) + 1)
        ):
            raise RuntimeError("API-owned Feature version 이력이 예상과 다릅니다")
    if set(changes_by_feature) != {str(row["feature_id"]) for row in rows}:
        raise RuntimeError("API-owned Feature와 version 이력이 일치하지 않습니다")

    foreign_keys = await _foreign_key_reference_counts(session, feature_ids)
    expected_references = {
        "feature.feature_aliases.feature_id": len(rows),
        "feature.feature_versions.feature_id": len(version_rows),
    }
    observed_references = {
        key: value
        for key, value in foreign_keys.items()
        if value
    }
    if observed_references != expected_references:
        raise RuntimeError(
            "API-owned Feature FK reference 감사가 다릅니다: "
            f"expected={expected_references!r}, observed={observed_references!r}"
        )
    return _ApiOwnedInspection(
        feature_ids=feature_ids,
        features=len(rows),
        requests=len(request_rows),
        request_fingerprints=request_fingerprints,
        versions=len(version_rows),
        foreign_keys=foreign_keys,
    )


async def _purge_api_owned(
    session: AsyncSession,
    run_id: str,
) -> tuple[dict[str, int], dict[str, int], dict[str, int]]:
    inspection = await _inspect_api_owned(session, run_id)
    await session.execute(
        text(
            """
            DELETE FROM ops.feature_change_requests
            WHERE feature_id = ANY(CAST(:feature_ids AS text[]))
            """
        ),
        {"feature_ids": list(inspection.feature_ids)},
    )
    await session.execute(
        text(
            """
            DELETE FROM feature.features
            WHERE feature_id = ANY(CAST(:feature_ids AS text[]))
            """
        ),
        {"feature_ids": list(inspection.feature_ids)},
    )
    remaining_features = int(
        (
            await session.execute(
                text(
                    """
                    SELECT count(*) FROM feature.features
                    WHERE feature_id = ANY(CAST(:feature_ids AS text[]))
                    """
                ),
                {"feature_ids": list(inspection.feature_ids)},
            )
        )
        .scalars()
        .one()
    )
    remaining_requests = int(
        (
            await session.execute(
                text(
                    """
                    SELECT count(*) FROM ops.feature_change_requests
                    WHERE feature_id = ANY(CAST(:feature_ids AS text[]))
                    """
                ),
                {"feature_ids": list(inspection.feature_ids)},
            )
        )
        .scalars()
        .one()
    )
    if remaining_features or remaining_requests:
        raise RuntimeError("API-owned purge가 완결되지 않았습니다")
    remaining_foreign_keys = await _foreign_key_reference_counts(
        session,
        inspection.feature_ids,
    )
    if any(remaining_foreign_keys.values()):
        raise RuntimeError("API-owned purge 뒤 FK reference가 남았습니다")
    return (
        {"features": 0, "price_values": 0, "weather_values": 0},
        remaining_foreign_keys,
        {
            "change_requests": inspection.requests,
            "feature_versions": inspection.versions,
            "features": inspection.features,
        },
    )


async def _audit_complete_api_owned(
    session: AsyncSession,
    run_id: str,
) -> tuple[dict[str, int], dict[str, int]]:
    inspection = await _inspect_api_owned(session, run_id)
    reason_prefix = f"admin feature live acceptance {run_id} "
    expected_requests = Counter(
        {
            ("add", "applied", f"{reason_prefix}create active"): 3,
            ("add", "applied", f"{reason_prefix}create draft"): 1,
            ("add", "applied", f"{reason_prefix}create hidden"): 1,
            ("add", "applied", f"{reason_prefix}create inactive"): 1,
            ("delete", "applied", f"{reason_prefix}cleanup delete"): 6,
            ("update", "applied", f"{reason_prefix}competing update"): 1,
            (
                "update",
                "rejected",
                f"{reason_prefix}reject reapply fixture",
            ): 1,
        }
    )
    if (
        inspection.features != 6
        or inspection.requests != 14
        or inspection.versions != 13
        or inspection.request_fingerprints != expected_requests
    ):
        raise RuntimeError("완료 API-owned 행 집합이 예상과 다릅니다")
    return (
        {
            "change_requests": inspection.requests,
            "feature_versions": inspection.versions,
            "features": inspection.features,
        },
        inspection.foreign_keys,
    )


def _auth_request_ids(run_id: str) -> dict[str, str]:
    prefix = f"e2e_live_acceptance::{run_id}::auth"
    return {
        "main": f"{prefix}::main",
        "recovery": f"{prefix}::recovery",
    }


async def _inspect_auth_audit(
    session: AsyncSession,
    run_id: str,
) -> tuple[list[RowMapping], dict[str, int]]:
    request_ids = _auth_request_ids(run_id)
    auth_rows = (
        await session.execute(
            text(
                """
                SELECT
                  auth_event_id, event_type, outcome, attempted_username,
                  actor, reason, next_path, client_ip, user_agent, request_id
                FROM ops.admin_auth_events
                WHERE request_id = ANY(CAST(:request_ids AS text[]))
                ORDER BY created_at, auth_event_id
                FOR UPDATE
                """
            ),
            {"request_ids": list(request_ids.values())},
        )
    ).mappings().all()
    counts = {"main": 0, "recovery": 0}
    for row in auth_rows:
        if (
            row["event_type"] != "login"
            or row["outcome"] != "succeeded"
            or row["attempted_username"] != "admin"
            or row["actor"] != "ui-auth"
            or row["reason"] != "authenticated"
            or row["next_path"] != "/"
            or row["client_ip"] is not None
            or row["request_id"] not in request_ids.values()
            or not isinstance(row["user_agent"], str)
            or not row["user_agent"].startswith("Mozilla/5.0 ")
        ):
            raise RuntimeError("run-bound admin 인증 감사행 소유권이 다릅니다")
        phase = "main" if row["request_id"] == request_ids["main"] else "recovery"
        counts[phase] += 1
    return list(auth_rows), counts


async def _reset_auth_audit(session: AsyncSession, run_id: str) -> dict[str, int]:
    auth_rows, counts = await _inspect_auth_audit(session, run_id)
    if auth_rows:
        await session.execute(
            text(
                """
                DELETE FROM ops.admin_auth_events
                WHERE auth_event_id = ANY(CAST(:auth_event_ids AS uuid[]))
                """
            ),
            {"auth_event_ids": [str(row["auth_event_id"]) for row in auth_rows]},
        )
    remaining = int(
        (
            await session.execute(
                text(
                    """
                    SELECT count(*)
                    FROM ops.admin_auth_events
                    WHERE request_id = ANY(CAST(:request_ids AS text[]))
                    """
                ),
                {"request_ids": list(_auth_request_ids(run_id).values())},
            )
        )
        .scalars()
        .one()
    )
    if remaining:
        raise RuntimeError("run-bound admin 인증 감사행 reset이 완결되지 않았습니다")
    return counts


async def _verify_auth_audit(
    session: AsyncSession,
    run_id: str,
) -> dict[str, int]:
    _auth_rows, counts = await _inspect_auth_audit(session, run_id)
    if counts != {"main": 1, "recovery": 1}:
        raise RuntimeError("run-bound admin 인증 감사행 수가 예상과 다릅니다")
    return counts


async def _run(
    action: str,
    run_id: str,
) -> dict[str, object]:
    settings = KorTravelMapSettings()
    # make_async_engine은 normalize_async_dsn으로 plain `postgresql://` DSN도
    # asyncpg dialect로 정규화한다. raw create_async_engine을 쓰면 배포 env가
    # plain scheme일 때 컨테이너 안에서 sync psycopg2 dialect를 로드하려다
    # 실패한다 (Codex PR #792 사후 적대 리뷰 R792-3).
    engine = make_async_engine(settings.pg_dsn)
    try:
        async with AsyncSession(engine) as session, session.begin():
            if action == "seed":
                counts, foreign_keys = await _seed(session, run_id)
            elif action == "cleanup":
                counts, foreign_keys = await _cleanup(session, run_id)
            elif action == "purge":
                counts, foreign_keys, purged = await _purge_api_owned(
                    session,
                    run_id,
                )
            elif action == "api-audit":
                counts, foreign_keys = await _audit_complete_api_owned(
                    session,
                    run_id,
                )
            elif action == "auth-reset":
                auth_counts = await _reset_auth_audit(session, run_id)
            elif action == "auth-verify":
                auth_counts = await _verify_auth_audit(session, run_id)
            else:
                counts, foreign_keys = await _assert_owned_state(
                    session,
                    run_id,
                    _feature_ids(run_id),
                )
    finally:
        await engine.dispose()
    if action in {"auth-reset", "auth-verify"}:
        return {
            "action": action,
            "counts": auth_counts,
            "version": 1,
        }
    result: dict[str, object] = {
        "action": action,
        "counts": counts,
        "foreign_key_constraints_checked": len(foreign_keys),
        "foreign_key_references": sum(foreign_keys.values()),
        "version": 1,
    }
    if action == "purge":
        result["purged"] = purged
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "action",
        choices=(
            "seed",
            "cleanup",
            "audit",
            "purge",
            "api-audit",
            "auth-reset",
            "auth-verify",
        ),
    )
    parser.add_argument("--run-id", required=True)
    args = parser.parse_args()
    if _RUN_ID_RE.fullmatch(args.run_id) is None:
        raise SystemExit("run-id 형식이 올바르지 않습니다")
    print(
        json.dumps(
            asyncio.run(_run(args.action, args.run_id)),
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
