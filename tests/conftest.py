from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from krtour_map.enums import FeatureKind
from krtour_map.ids import make_feature_id
from krtour_map.models import Address, Coordinate, Feature, RawDataRef


@pytest.fixture
def fixed_time() -> datetime:
    return datetime(2026, 5, 17, 9, 0, tzinfo=ZoneInfo("Asia/Seoul"))


@pytest.fixture
def sample_feature(fixed_time: datetime) -> Feature:
    feature_id = make_feature_id(
        provider="opinet",
        source_type="fuel_station",
        source_natural_key="A0010207",
        kind=FeatureKind.PRICE,
        category="fuel",
        bjd_code="1111010100",
        content_hash="abc123",
    )
    return Feature(
        feature_id=feature_id,
        kind=FeatureKind.PRICE,
        name="Sample Fuel Station",
        coord=Coordinate(longitude=127.0001, latitude=37.5001),
        address=Address(
            road_address="Seoul sample road 1",
            bjd_code="1111010100",
            sigungu_code="11110",
            sido_code="11",
        ),
        category="fuel",
        marker_icon="fuel",
        marker_color="P-04",
        raw_refs=[
            RawDataRef(
                provider="python-opinet-api",
                dataset_key="fuel_lowest_station",
                source_entity_id="A0010207",
                fetched_at=fixed_time,
                payload_hash="abc123",
            )
        ],
        created_at=fixed_time,
        updated_at=fixed_time,
    )
