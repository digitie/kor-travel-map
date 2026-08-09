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
from typing import Final

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
from kortravelmap.infra.db import (
    assert_runtime_db_privilege_boundary,
    make_async_engine,
)
from kortravelmap.settings import KorTravelMapSettings

_RUN_ID_PATTERN: Final[re.Pattern[str]] = re.compile(r"^[a-z0-9][a-z0-9-]{15,79}$")
_PROVIDER: Final[str] = "tvn34c-fresh-live"


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
        feature_id = f"tvn34c::fresh-live::{run_id}::beach"
        source_entity_id = f"fresh-live::{run_id}::beach"
        fetched_at = datetime.now(UTC)
        raw_data = {
            "fixture": "tvn34c-fresh-live",
            "kind": "beach",
            "run_id": run_id,
            "source_entity_id": source_entity_id,
        }
        payload_hash = make_payload_hash(raw_data)
        source_record_key = make_source_record_key(
            provider=_PROVIDER,
            dataset_key="fresh-live-beaches",
            source_entity_type="beach",
            source_entity_id=source_entity_id,
            raw_payload_hash=payload_hash,
        )
        bundle = FeatureBundle(
            feature=Feature(
                feature_id=feature_id,
                kind=FeatureKind.PLACE,
                name=f"T-VN-34C fresh beach {run_id}",
                coord=Coordinate(lon=127.5, lat=36.5),
                category="01070300",
                marker_icon="beach",
                marker_color="P-06",
                detail=PlaceDetail(feature_id=feature_id, place_kind="beach"),
                created_at=fetched_at,
                updated_at=fetched_at,
            ),
            source_record=SourceRecord(
                provider=_PROVIDER,
                dataset_key="fresh-live-beaches",
                source_entity_type="beach",
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
        async with AsyncKorTravelMapClient(engine) as client:
            receipt = await client.load_feature_bundles([bundle])
        if receipt.features_inserted != 1 or receipt.source_links_inserted != 1:
            raise RuntimeError("fresh ETL fixture 적재 receipt가 예상과 다릅니다")
        return {
            "feature_id": feature_id,
            "features_inserted": receipt.features_inserted,
            "source_links_inserted": receipt.source_links_inserted,
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
