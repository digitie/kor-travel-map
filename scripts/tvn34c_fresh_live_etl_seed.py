#!/usr/bin/env python3
"""T-VN-34C n150 fresh-live 전용 Dagster runtime 적재 fixture.

외부 provider 자격증명이나 운영 row를 빌리지 않는다. 이 파일은 격리 compose의
``ktm_feature_dagster_runtime`` 로그인으로만 실행되어, 실제 provider 적재 경로가
새 3축 state·subtype·source lineage를 통과하는지 확인한다.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
import sys
from datetime import UTC, datetime
from decimal import Decimal
from typing import Final

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from kortravelmap.client import AsyncKorTravelMapClient
from kortravelmap.core.ids import make_payload_hash, make_source_record_key
from kortravelmap.dto import (
    Coordinate,
    Feature,
    FeatureBundle,
    PlaceDetail,
    SourceLink,
    SourceRecord,
)
from kortravelmap.dto._enums import FeatureKind, SourceRole
from kortravelmap.dto.price import PriceValue
from kortravelmap.dto.weather import WeatherValue
from kortravelmap.infra import price_repo, weather_repo
from kortravelmap.infra.db import (
    assert_runtime_db_privilege_boundary,
    make_async_engine,
)
from kortravelmap.settings import KorTravelMapSettings

_RUN_ID_PATTERN: Final[re.Pattern[str]] = re.compile(r"^[a-z0-9][a-z0-9-]{15,79}$")
# Fresh 0097 databases own only the canonical provider-dataset catalog from
# 0089.  Use the active KHOA beach dataset rather than creating a fixture-only
# catalog row under the restricted Dagster runtime login: this exercises the
# same provider-dataset authority path as a real beach ingestion.
_PROVIDER: Final[str] = "python-khoa-api"
_DATASET_KEY: Final[str] = "khoa_beaches"
_BEACH_CATEGORY: Final[str] = "01050100"
_BEACH_MARKER_COLOR: Final[str] = "P-07"
_FIXTURE_CATEGORY: Final[str] = "00000000"


def _bundle(
    *,
    run_id: str,
    feature_id: str,
    kind: FeatureKind,
    name: str,
    lon: float,
    marker_icon: str,
    marker_color: str,
    fetched_at: datetime,
    category: str,
    publication_state: str = "published",
) -> FeatureBundle:
    """제한 Dagster runtime의 canonical provider 적재 경로를 그대로 탄다."""
    source_entity_id = f"fresh-live::{run_id}::{kind.value}"
    raw_data = {
        "fixture": "tvn34c-fresh-live",
        "provider": _PROVIDER,
        "dataset_key": _DATASET_KEY,
        "kind": kind.value,
        "run_id": run_id,
        "source_entity_id": source_entity_id,
    }
    payload_hash = make_payload_hash(raw_data)
    source_record_key = make_source_record_key(
        provider=_PROVIDER,
        dataset_key=_DATASET_KEY,
        source_entity_type=kind.value,
        source_entity_id=source_entity_id,
        raw_payload_hash=payload_hash,
    )
    return FeatureBundle(
        feature=Feature(
            feature_id=feature_id,
            kind=kind,
            name=name,
            coord=Coordinate(lon=lon, lat=36.5),
            category=category,
            marker_icon=marker_icon,
            marker_color=marker_color,
            publication_state=publication_state,
            created_at=fetched_at,
            updated_at=fetched_at,
        ),
        source_record=SourceRecord(
            provider=_PROVIDER,
            dataset_key=_DATASET_KEY,
            source_entity_type=kind.value,
            source_entity_id=source_entity_id,
            raw_payload_hash=payload_hash,
            raw_data=raw_data,
            fetched_at=fetched_at,
            imported_at=fetched_at,
            source_record_key=source_record_key,
        ),
        source_link=SourceLink(
            feature_id=feature_id,
            source_record_key=source_record_key,
            source_role=SourceRole.PRIMARY,
            match_method="fresh_live_fixture",
            confidence=100,
            created_at=fetched_at,
        ),
    )


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id", required=True)
    return parser.parse_args()


async def _run(run_id: str) -> dict[str, object]:
    if not _RUN_ID_PATTERN.fullmatch(run_id):
        raise ValueError("run_id 형식이 올바르지 않습니다")

    settings = KorTravelMapSettings()
    if settings.pg_dsn is None:
        raise RuntimeError("KOR_TRAVEL_MAP_PG_DSN이 필요합니다")
    engine = make_async_engine(settings.pg_dsn)
    try:
        await assert_runtime_db_privilege_boundary(
            engine,
            expected_login="ktm_feature_dagster_runtime",
        )
        fetched_at = datetime.now(UTC)
        feature_id = f"tvn34c::fresh-live::{run_id}::beach"
        beach_bundle = _bundle(
            run_id=run_id,
            feature_id=feature_id,
            kind=FeatureKind.PLACE,
            name=f"T-VN-34C fresh beach {run_id}",
            lon=127.5,
            marker_icon="beach",
            marker_color=_BEACH_MARKER_COLOR,
            fetched_at=fetched_at,
            category=_BEACH_CATEGORY,
        )
        beach_bundle = beach_bundle.model_copy(
            update={
                "feature": beach_bundle.feature.model_copy(
                    update={
                        "detail": PlaceDetail(
                            feature_id=feature_id,
                            place_kind="beach",
                        )
                    }
                )
            }
        )
        weather_feature_id = f"e2e_live_acceptance::{run_id}::weather"
        price_feature_id = f"e2e_live_acceptance::{run_id}::price"
        weather_bundle = _bundle(
            run_id=run_id,
            feature_id=weather_feature_id,
            kind=FeatureKind.WEATHER,
            name=f"E2E suppressed weather {run_id}",
            lon=127.502,
            marker_icon="weather",
            marker_color="P-03",
            fetched_at=fetched_at,
            category=_FIXTURE_CATEGORY,
            publication_state="suppressed",
        )
        price_bundle = _bundle(
            run_id=run_id,
            feature_id=price_feature_id,
            kind=FeatureKind.PRICE,
            name=f"E2E suppressed price {run_id}",
            lon=127.498,
            marker_icon="fuel",
            marker_color="P-04",
            fetched_at=fetched_at,
            category=_FIXTURE_CATEGORY,
            publication_state="suppressed",
        )
        async with AsyncKorTravelMapClient(engine) as client:
            receipt = await client.load_feature_bundles(
                [beach_bundle, weather_bundle, price_bundle]
            )
        if receipt.features_inserted != 3 or receipt.source_links_inserted != 3:
            raise RuntimeError("fresh ETL fixture 적재 receipt가 예상과 다릅니다")
        async with AsyncSession(engine) as session, session.begin():
            dataset_id = await session.scalar(
                text(
                    """
                    SELECT provider_dataset_id
                    FROM provider_sync.provider_datasets
                    WHERE provider = :provider
                      AND dataset_key = :dataset_key
                      AND is_active
                    """
                ),
                {"provider": _PROVIDER, "dataset_key": _DATASET_KEY},
            )
            if dataset_id is None:
                raise RuntimeError("canonical fresh ETL dataset을 찾을 수 없습니다")
            weather_values_inserted = await weather_repo.load_weather_values(
                session,
                [
                    WeatherValue(
                        feature_id=weather_feature_id,
                        provider="e2e-live-acceptance",
                        weather_domain="kma_short_forecast",
                        forecast_style="short",
                        timeline_bucket="short",
                        metric_key="TMP",
                        metric_name="인수 기온",
                        value_number=Decimal("21.5"),
                        unit="deg_c",
                        issued_at=fetched_at,
                        valid_at=fetched_at,
                        normalization_version="tvn34c-fresh-live",
                        payload={"fixture": "tvn34c-fresh-live"},
                    )
                ],
                provider_dataset_id=int(dataset_id),
                source_record=weather_bundle.source_record,
                selected_at=fetched_at,
            )
            price_values_inserted = await price_repo.load_price_values(
                session,
                [
                    PriceValue(
                        feature_id=price_feature_id,
                        provider="e2e-live-acceptance",
                        price_domain="opinet_gas_station",
                        product_key="gasoline",
                        product_name="인수 휘발유",
                        value_number=Decimal("1711"),
                        unit="KRW/L",
                        observed_at=fetched_at,
                        normalization_version="tvn34c-fresh-live",
                        payload={"fixture": "tvn34c-fresh-live"},
                    )
                ],
                provider_dataset_id=int(dataset_id),
                source_record=price_bundle.source_record,
            )
        if weather_values_inserted != 1 or price_values_inserted != 1:
            raise RuntimeError("fresh weather/price fixture 적재 receipt가 예상과 다릅니다")
        return {
            "feature_id": feature_id,
            "features_inserted": receipt.features_inserted,
            "source_links_inserted": receipt.source_links_inserted,
            "weather_values_inserted": weather_values_inserted,
            "price_values_inserted": price_values_inserted,
        }
    finally:
        await engine.dispose()


def main() -> None:
    args = _parse_args()
    result = asyncio.run(_run(args.run_id))
    json.dump(result, sys.stdout, ensure_ascii=False, sort_keys=True)
    sys.stdout.write("\n")


if __name__ == "__main__":
    main()
