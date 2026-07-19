#!/usr/bin/env python3
"""#741 production live 인수용 weather/price owned fixture 관리.

이 helper는 API container 안에서 stdin으로 실행한다. 운영 기존 row를 빌리지 않고
실행별 exact ID 두 건만 transaction으로 seed/cleanup/audit한다. host runner가 mutation
전에 root-owned BLOCKED/journal을 기록하는 것이 선행조건이다.
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


async def _seed(session: AsyncSession, run_id: str) -> dict[str, int]:
    feature_ids = _feature_ids(run_id)
    before = await _counts(session, feature_ids)
    if before != {"features": 0, "weather_values": 0, "price_values": 0}:
        raise RuntimeError("owned fixture ID가 이미 존재합니다; recovery를 먼저 실행하세요")

    weather_id, price_id = feature_ids
    await session.execute(
        text(
            """
            INSERT INTO feature.features (
                feature_id, kind, name, category, coord, status,
                marker_icon, marker_color, data_origin, data_version,
                updated_at
            ) VALUES
              (
                :weather_id, 'weather', :weather_name, '00000000',
                x_extension.ST_SetSRID(
                  x_extension.ST_MakePoint(:weather_lon, :lat), 4326
                ),
                'hidden', 'weather', 'P-03', 'user_request', 1, now()
              ),
              (
                :price_id, 'price', :price_name, '00000000',
                x_extension.ST_SetSRID(
                  x_extension.ST_MakePoint(:price_lon, :lat), 4326
                ),
                'hidden', 'fuel', 'P-04', 'user_request', 1, now()
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
    observed = await _counts(session, feature_ids)
    if observed != {"features": 2, "weather_values": 1, "price_values": 1}:
        raise RuntimeError("owned weather/price fixture cardinality가 예상과 다릅니다")
    return observed


async def _cleanup(session: AsyncSession, run_id: str) -> dict[str, int]:
    feature_ids = _feature_ids(run_id)
    await session.execute(
        text(
            "DELETE FROM feature.features "
            "WHERE feature_id = ANY(CAST(:feature_ids AS text[]))"
        ),
        {"feature_ids": list(feature_ids)},
    )
    observed = await _counts(session, feature_ids)
    if observed != {"features": 0, "weather_values": 0, "price_values": 0}:
        raise RuntimeError("owned weather/price fixture cleanup이 완결되지 않았습니다")
    return observed


async def _run(action: str, run_id: str) -> dict[str, object]:
    settings = KorTravelMapSettings()
    engine = create_async_engine(settings.pg_dsn.get_secret_value())
    try:
        async with AsyncSession(engine) as session, session.begin():
            if action == "seed":
                counts = await _seed(session, run_id)
            elif action == "cleanup":
                counts = await _cleanup(session, run_id)
            else:
                counts = await _counts(session, _feature_ids(run_id))
    finally:
        await engine.dispose()
    return {"action": action, "counts": counts, "version": 1}


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
