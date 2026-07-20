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
import json
import re
from datetime import timedelta
from decimal import Decimal
from typing import Final

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from kortravelmap.dto._time import kst_now
from kortravelmap.dto.price import PriceValue
from kortravelmap.dto.weather import WeatherValue
from kortravelmap.infra import price_repo, weather_repo
from kortravelmap.settings import KorTravelMapSettings

_RUN_ID_RE: Final[re.Pattern[str]] = re.compile(r"^[a-z0-9][a-z0-9-]{15,79}$")
_LON: Final[float] = 127.5
_LAT: Final[float] = 36.5


def _feature_ids(run_id: str) -> tuple[str, str]:
    prefix = f"e2e_live_acceptance::{run_id}"
    return f"{prefix}::weather", f"{prefix}::price"


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
    feature_ids: tuple[str, str],
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
                  target_column.attname AS target_column_name,
                  cardinality(constraint_row.conkey) AS local_column_count,
                  cardinality(constraint_row.confkey) AS target_column_count
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
                ORDER BY local_schema.nspname, local_table.relname,
                         local_column.attname, constraint_row.conname
                """
            )
        )
    ).mappings()
    counts: dict[str, int] = {}
    for constraint in constraints:
        if (
            int(constraint["local_column_count"]) != 1
            or int(constraint["target_column_count"]) != 1
            or str(constraint["target_column_name"]) != "feature_id"
        ):
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
                  provider, weather_domain, forecast_style, timeline_bucket,
                  metric_key, metric_name, value_number, unit,
                  normalization_version, payload
                FROM feature.feature_weather_values
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
                  provider, price_domain, product_key, product_name,
                  value_number, unit, normalization_version, payload
                FROM feature.feature_price_values
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
                "provider": "e2e-live-acceptance",
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
                "provider": "e2e-live-acceptance",
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
    await _assert_owned_values(session, feature_ids, present, lock=lock)
    foreign_keys = await _foreign_key_reference_counts(session, feature_ids)
    expected_references: dict[str, int] = {}
    if feature_ids[0] in present:
        expected_references["feature.feature_weather_values.feature_id"] = 1
    if feature_ids[1] in present:
        expected_references["feature.feature_price_values.feature_id"] = 1
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
                collected_at=now,
            )
        ],
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
                collected_at=now,
            )
        ],
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
    return observed, foreign_keys


async def _run(action: str, run_id: str) -> dict[str, object]:
    settings = KorTravelMapSettings()
    engine = create_async_engine(settings.pg_dsn.get_secret_value())
    try:
        async with AsyncSession(engine) as session, session.begin():
            if action == "seed":
                counts, foreign_keys = await _seed(session, run_id)
            elif action == "cleanup":
                counts, foreign_keys = await _cleanup(session, run_id)
            else:
                counts, foreign_keys = await _assert_owned_state(
                    session,
                    run_id,
                    _feature_ids(run_id),
                )
    finally:
        await engine.dispose()
    return {
        "action": action,
        "counts": counts,
        "foreign_key_constraints_checked": len(foreign_keys),
        "foreign_key_references": sum(foreign_keys.values()),
        "version": 1,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=("seed", "cleanup", "audit"))
    parser.add_argument("--run-id", required=True)
    args = parser.parse_args()
    if _RUN_ID_RE.fullmatch(args.run_id) is None:
        raise SystemExit("run-id 형식이 올바르지 않습니다")
    print(json.dumps(asyncio.run(_run(args.action, args.run_id)), sort_keys=True))


if __name__ == "__main__":
    main()
