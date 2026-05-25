"""``test_dto_source_bundle`` — SourceRecord / SourceLink / FeatureBundle 검증.

PR#26 review report P0-4 — provider → load 전달 단위 DTO. Sprint 2 첫 provider
변환 함수가 본 DTO 묶음을 생성한다.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest
from pydantic import ValidationError

from krtour.map.core.ids import make_source_record_key
from krtour.map.dto import (
    KST,
    Coordinate,
    Feature,
    FeatureBundle,
    FeatureKind,
    PlaceDetail,
    SourceLink,
    SourceRecord,
    SourceRole,
    kst_now,
)

# -- SourceRecord ------------------------------------------------------


def _make_source_record(**overrides: object) -> SourceRecord:
    source_record_key = make_source_record_key(
        provider="python-visitkorea-api",
        dataset_key="festival",
        source_entity_type="festival_record",
        source_entity_id="E001234",
        raw_payload_hash="abc123",
    )
    base = {
        "provider": "python-visitkorea-api",
        "dataset_key": "festival",
        "source_entity_type": "festival_record",
        "source_entity_id": "E001234",
        "raw_payload_hash": "abc123",
        "raw_data": {"id": "E001234"},
        "fetched_at": datetime(2026, 1, 1, tzinfo=KST),
        "source_record_key": source_record_key,
    }
    base.update(overrides)  # type: ignore[arg-type]
    return SourceRecord(**base)  # type: ignore[arg-type]


@pytest.mark.unit
def test_source_record_minimal_creation() -> None:
    """DB에 바로 저장 가능한 필수 필드로 생성."""
    rec = _make_source_record()
    assert rec.provider == "python-visitkorea-api"
    assert rec.imported_at.tzinfo is not None  # kst_now default
    assert rec.source_record_key.startswith("sr_")
    assert rec.raw_data == {"id": "E001234"}


@pytest.mark.unit
def test_source_record_key_set_explicitly() -> None:
    """``source_record_key``는 호출자가 ``make_source_record_key(...)``로 계산 후 박는다.

    dto는 core를 import할 수 없으므로 (ADR-001/002), ``SourceRecord``는
    self-computing ``key()`` 메서드를 두지 않는다. 호출자가 명시적으로 설정.
    """
    key = make_source_record_key(
        provider="python-visitkorea-api",
        dataset_key="festival",
        source_entity_type="festival_record",
        source_entity_id="E001234",
        raw_payload_hash="abc123",
    )
    rec = _make_source_record(source_record_key=key)
    assert rec.source_record_key == key
    assert key.startswith("sr_")


@pytest.mark.unit
@pytest.mark.parametrize("field", ["fetched_at", "source_record_key"])
def test_source_record_db_required_fields(field: str) -> None:
    """DB NOT NULL 필드는 load DTO에서도 누락을 거부."""
    source_record_key = make_source_record_key(
        provider="python-visitkorea-api",
        dataset_key="festival",
        source_entity_type="festival_record",
        source_entity_id="E001234",
        raw_payload_hash="abc123",
    )
    data: dict[str, object] = {
        "provider": "python-visitkorea-api",
        "dataset_key": "festival",
        "source_entity_type": "festival_record",
        "source_entity_id": "E001234",
        "raw_payload_hash": "abc123",
        "fetched_at": datetime(2026, 1, 1, tzinfo=KST),
        "source_record_key": source_record_key,
    }
    del data[field]
    with pytest.raises(ValidationError, match=field):
        SourceRecord(**data)  # type: ignore[arg-type]


@pytest.mark.unit
def test_source_record_raw_data_defaults_to_empty_dict() -> None:
    """``raw_data``는 JSONB NOT NULL 기본값과 맞춰 빈 dict로 시작."""
    source_record_key = make_source_record_key(
        provider="python-visitkorea-api",
        dataset_key="festival",
        source_entity_type="festival_record",
        source_entity_id="E001234",
        raw_payload_hash="abc123",
    )
    rec = SourceRecord(
        provider="python-visitkorea-api",
        dataset_key="festival",
        source_entity_type="festival_record",
        source_entity_id="E001234",
        raw_payload_hash="abc123",
        fetched_at=datetime(2026, 1, 1, tzinfo=KST),
        source_record_key=source_record_key,
    )
    assert rec.raw_data == {}


@pytest.mark.unit
def test_source_record_naive_fetched_at_rejected() -> None:
    """ADR-019 — naive datetime은 ValidationError."""
    with pytest.raises(ValidationError, match="timezone-aware"):
        _make_source_record(fetched_at=datetime(2026, 1, 1))


@pytest.mark.unit
def test_source_record_aware_datetime_accepted() -> None:
    """KST/UTC aware datetime 모두 허용."""
    rec_kst = _make_source_record(fetched_at=datetime(2026, 1, 1, tzinfo=KST))
    rec_utc = _make_source_record(fetched_at=datetime(2026, 1, 1, tzinfo=UTC))
    assert rec_kst.fetched_at is not None
    assert rec_utc.fetched_at is not None


@pytest.mark.unit
def test_source_record_optional_raw_fields() -> None:
    """raw_* 필드는 모두 optional."""
    rec = _make_source_record(
        raw_name="제주올레",
        raw_address="제주시 OO",
        raw_longitude=Decimal("126.9"),
        raw_latitude=Decimal("33.5"),
        raw_data={"key": "value"},
    )
    assert rec.raw_name == "제주올레"
    assert rec.raw_longitude == Decimal("126.9")


@pytest.mark.unit
def test_source_record_extra_forbid() -> None:
    """``ConfigDict(extra='forbid')`` — 잘못된 필드 거부."""
    with pytest.raises(ValidationError, match="Extra inputs"):
        _make_source_record(unknown_field="value")  # type: ignore[arg-type]


# -- SourceLink --------------------------------------------------------


def _make_source_link(**overrides: object) -> SourceLink:
    source_record_key = make_source_record_key(
        provider="python-visitkorea-api",
        dataset_key="festival",
        source_entity_type="festival_record",
        source_entity_id="E001234",
        raw_payload_hash="abc123",
    )
    base = {
        "feature_id": "f_1100000000_e_abc",
        "source_record_key": source_record_key,
        "source_role": SourceRole.PRIMARY,
        "match_method": "natural_key",
        "confidence": 100,
        "is_primary_source": True,
    }
    base.update(overrides)  # type: ignore[arg-type]
    return SourceLink(**base)  # type: ignore[arg-type]


@pytest.mark.unit
def test_source_link_creation() -> None:
    """기본 생성 — 필수 6 필드."""
    link = _make_source_link()
    assert link.feature_id == "f_1100000000_e_abc"
    assert link.confidence == 100
    assert link.is_primary_source is True
    assert link.created_at.tzinfo is not None


@pytest.mark.unit
def test_source_link_confidence_bounds() -> None:
    """confidence 0~100 외는 ValidationError."""
    with pytest.raises(ValidationError, match="confidence"):
        _make_source_link(confidence=-1)
    with pytest.raises(ValidationError, match="confidence"):
        _make_source_link(confidence=101)


@pytest.mark.unit
def test_source_link_default_role() -> None:
    """기본 source_role은 ENRICHMENT (primary는 명시적 지정)."""
    source_record = _make_source_record()
    link = SourceLink(
        feature_id="f_1100000000_p_abc",
        source_record_key=source_record.source_record_key,
        match_method="natural_key",
        confidence=80,
    )
    assert link.source_role == SourceRole.ENRICHMENT
    assert link.is_primary_source is False


@pytest.mark.unit
def test_source_link_naive_created_at_rejected() -> None:
    """ADR-019 — naive datetime은 ValidationError."""
    with pytest.raises(ValidationError, match="timezone-aware"):
        _make_source_link(created_at=datetime(2026, 1, 1))


@pytest.mark.unit
def test_source_link_match_method_required() -> None:
    """``match_method``는 빈 문자열 거부 (min_length=1)."""
    with pytest.raises(ValidationError, match="match_method"):
        _make_source_link(match_method="")


# -- FeatureBundle -----------------------------------------------------


def _make_feature() -> Feature:
    return Feature(
        feature_id="f_1100000000_p_abc",
        kind=FeatureKind.PLACE,
        name="홍대 카페",
        coord=Coordinate(lon=Decimal("126.92"), lat=Decimal("37.55")),
        category="02020101",
        marker_icon="cafe",
        marker_color="P-03",
        detail=PlaceDetail(feature_id="f_1100000000_p_abc", place_kind="cafe"),
    )


@pytest.mark.unit
def test_feature_bundle_minimal_creation() -> None:
    """feature + source_record + source_link 3개 필수."""
    feature = _make_feature()
    source_record = _make_source_record()
    source_link = _make_source_link(
        feature_id=feature.feature_id,
        source_record_key=source_record.source_record_key,
    )
    bundle = FeatureBundle(
        feature=feature,
        source_record=source_record,
        source_link=source_link,
    )
    assert bundle.feature.feature_id == feature.feature_id
    assert bundle.source_record.provider == "python-visitkorea-api"
    assert bundle.source_link.source_role == SourceRole.PRIMARY


@pytest.mark.unit
def test_feature_bundle_detail_alias() -> None:
    """``bundle.detail``은 ``bundle.feature.detail`` alias."""
    feature = _make_feature()
    source_record = _make_source_record()
    bundle = FeatureBundle(
        feature=feature,
        source_record=source_record,
        source_link=_make_source_link(
            feature_id=feature.feature_id,
            source_record_key=source_record.source_record_key,
        ),
    )
    assert bundle.detail is feature.detail
    assert isinstance(bundle.detail, PlaceDetail)


@pytest.mark.unit
def test_feature_bundle_extra_forbid() -> None:
    """``ConfigDict(extra='forbid')`` — Sprint 2에서 추가될 필드 외 거부."""
    feature = _make_feature()
    source_record = _make_source_record()
    with pytest.raises(ValidationError, match="Extra inputs"):
        FeatureBundle(
            feature=feature,
            source_record=source_record,
            source_link=_make_source_link(
                feature_id=feature.feature_id,
                source_record_key=source_record.source_record_key,
            ),
            unknown=42,  # type: ignore[call-arg]
        )


@pytest.mark.unit
def test_feature_bundle_feature_id_matches_source_link() -> None:
    """``source_link.feature_id``는 ``feature.feature_id``와 일치해야 한다."""
    feature = _make_feature()
    source_record = _make_source_record()
    bundle = FeatureBundle(
        feature=feature,
        source_record=source_record,
        source_link=_make_source_link(
            feature_id=feature.feature_id,
            source_record_key=source_record.source_record_key,
        ),
    )
    assert bundle.source_link.feature_id == bundle.feature.feature_id


@pytest.mark.unit
def test_feature_bundle_rejects_feature_id_mismatch() -> None:
    """bundle 내부 feature/source_link feature_id 불일치 거부."""
    with pytest.raises(ValidationError, match="source_link.feature_id"):
        FeatureBundle(
            feature=_make_feature(),
            source_record=_make_source_record(),
            source_link=_make_source_link(feature_id="f_1100000000_p_other"),
        )


@pytest.mark.unit
def test_feature_bundle_rejects_source_record_key_mismatch() -> None:
    """bundle 내부 source_record/source_link key 불일치 거부."""
    feature = _make_feature()
    with pytest.raises(ValidationError, match="source_link.source_record_key"):
        FeatureBundle(
            feature=feature,
            source_record=_make_source_record(),
            source_link=_make_source_link(
                feature_id=feature.feature_id,
                source_record_key="sr_other",
            ),
        )


# -- end-to-end integration: 전체 flow ----------------------------------


@pytest.mark.unit
def test_provider_to_bundle_flow() -> None:
    """provider 변환 함수 출력 예시 — Sprint 2 첫 PR의 패턴 미리보기.

    1. raw payload → payload_hash 계산
    2. source_record_key 결정
    3. feature_id 결정
    4. FeatureBundle 묶음
    """
    from krtour.map.core.ids import (
        make_feature_id,
        make_payload_hash,
        make_source_record_key,
    )

    raw_payload = {"id": "E001234", "title": "올레 축제", "loc": [126.5, 33.4]}

    # 1. payload hash
    payload_hash = make_payload_hash(raw_payload)
    assert len(payload_hash) == 32

    # 2. source_record_key
    src_key = make_source_record_key(
        provider="python-visitkorea-api",
        dataset_key="festival",
        source_entity_type="festival_record",
        source_entity_id="E001234",
        raw_payload_hash=payload_hash,
    )
    assert src_key.startswith("sr_")

    # 3. feature_id
    fid = make_feature_id(
        bjd_code="5000000000",
        kind="event",
        category="01020101",
        source_type="visitkorea_festival",
        source_natural_key="E001234",
    )
    assert fid.startswith("f_5000000000_e_")

    # 4. bundle
    feature = Feature(
        feature_id=fid,
        kind=FeatureKind.EVENT,
        name="올레 축제",
        coord=Coordinate(lon=Decimal("126.5"), lat=Decimal("33.4")),
        category="01020101",
        marker_icon="festival",
        marker_color="P-05",
    )
    source_record = SourceRecord(
        provider="python-visitkorea-api",
        dataset_key="festival",
        source_entity_type="festival_record",
        source_entity_id="E001234",
        raw_payload_hash=payload_hash,
        raw_data=raw_payload,
        fetched_at=kst_now(),
        source_record_key=src_key,
    )
    source_link = SourceLink(
        feature_id=fid,
        source_record_key=src_key,
        source_role=SourceRole.PRIMARY,
        match_method="natural_key",
        confidence=100,
        is_primary_source=True,
    )
    bundle = FeatureBundle(
        feature=feature,
        source_record=source_record,
        source_link=source_link,
    )

    # 결정성 — 같은 raw payload 재호출 시 같은 hash/key
    assert make_payload_hash(raw_payload) == payload_hash
    assert source_record.source_record_key == src_key
    assert bundle.source_link.feature_id == bundle.feature.feature_id
