"""``test_dto_file`` — FeatureFileSource DTO + FeatureBundle.file_sources 검증."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from pydantic import ValidationError

from kortravelmap.dto import (
    Address,
    Coordinate,
    Feature,
    FeatureBundle,
    FeatureFileSource,
    FeatureKind,
    PlaceDetail,
    SourceLink,
    SourceRecord,
    SourceRole,
)

pytestmark = pytest.mark.unit

_KST = timezone(timedelta(hours=9))
_FID = "f_global_p_0123456789abcdef0123"
_SRK = "sr_test_key_0001"


def _source_record() -> SourceRecord:
    return SourceRecord(
        provider="python-krheritage-api",
        dataset_key="krheritage_heritage_features",
        source_entity_type="heritage",
        source_entity_id="11-1-11",
        raw_payload_hash="h" * 16,
        raw_data={},
        fetched_at=datetime(2026, 5, 28, tzinfo=_KST),
        source_record_key=_SRK,
    )


def _feature() -> Feature:
    return Feature(
        feature_id=_FID,
        kind=FeatureKind.PLACE,
        name="통도사 대웅전",
        coord=Coordinate(lon=128.99, lat=35.49),
        address=Address(),
        category="01070100",
        marker_icon="monument",
        marker_color="P-07",
        detail=PlaceDetail(feature_id=_FID, place_kind="temple"),
    )


def _link() -> SourceLink:
    return SourceLink(
        feature_id=_FID,
        source_record_key=_SRK,
        source_role=SourceRole.PRIMARY,
        match_method="natural_key",
        confidence=100,
        is_primary_source=True,
    )


def test_file_source_defaults() -> None:
    fs = FeatureFileSource(feature_id=_FID, source_url="https://x/a.jpg")
    assert fs.role == "gallery"
    assert fs.display_order == 0
    assert fs.file_type == "image"
    assert fs.payload == {}


def test_file_source_rejects_extra() -> None:
    with pytest.raises(ValidationError):
        FeatureFileSource(feature_id=_FID, source_url="https://x/a.jpg", bogus=1)  # type: ignore[call-arg]


def test_file_source_rejects_negative_display_order() -> None:
    with pytest.raises(ValidationError):
        FeatureFileSource(feature_id=_FID, source_url="https://x/a.jpg", display_order=-1)


def test_bundle_accepts_matching_file_sources() -> None:
    bundle = FeatureBundle(
        feature=_feature(),
        source_record=_source_record(),
        source_link=_link(),
        file_sources=[
            FeatureFileSource(
                feature_id=_FID,
                source_url="https://x/a.jpg",
                role="primary",
                source_record_key=_SRK,
            )
        ],
    )
    assert len(bundle.file_sources) == 1
    # 기본 bundle은 file_sources 빈 list.
    empty = FeatureBundle(
        feature=_feature(), source_record=_source_record(), source_link=_link()
    )
    assert empty.file_sources == []


def test_bundle_rejects_file_source_feature_id_mismatch() -> None:
    with pytest.raises(ValidationError, match="file_sources"):
        FeatureBundle(
            feature=_feature(),
            source_record=_source_record(),
            source_link=_link(),
            file_sources=[
                FeatureFileSource(
                    feature_id="f_global_p_DIFFERENT00000000000000",
                    source_url="https://x/a.jpg",
                )
            ],
        )
