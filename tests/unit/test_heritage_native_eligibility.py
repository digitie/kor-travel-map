"""국가유산의 실제 converter 출력으로 이름과 파생/지원 외 변화를 구분한다."""

from dataclasses import replace
from datetime import timedelta

import pytest

from kortravelmap.core.ids import make_payload_hash, make_source_record_key
from kortravelmap.dto import Address
from kortravelmap.providers.krheritage import (
    HERITAGE_NAME_NORMALIZER_REVISION,
    heritage_items_to_bundles,
)
from kortravelmap.providers.krheritage_native import (
    HeritageGeoEvidence,
    assess_heritage_name_refresh,
    rebuild_heritage_projection,
)
from tests.unit.test_providers_krheritage import _FETCHED, _Item, _item, _Key

_ADDRESS = Address(legal="서울특별시 영등포구 여의도동 8", bjd_code="1156011000")
_GEO = HeritageGeoEvidence("resolved", "geo-v1", _ADDRESS, "a" * 64)


def _validate(payload):
    # public DTO 입력 seam의 단위 대역이다. 실제 SDK 검증은 별도 계약 시험에서 실행한다.
    data = dict(payload)
    return _Item(key=_Key(**data.pop("key")), **data)


async def _bundle(item, *, later=False):
    async def reverse(_):
        return _ADDRESS

    return (
        await heritage_items_to_bundles(
            [item],
            fetched_at=_FETCHED + timedelta(seconds=int(later)),
            reverse_geocoder=reverse,
        )
    )[0]


def _base():
    return _item(
        kdcd="11",
        asno="990001",
        ctcd="11",
        name_ko="기준 유산",
        category="문화유산",
        longitude=126.9239,
        latitude=37.5263,
        location_text=_ADDRESS.legal,
        owner="관리기관",
    )


async def _assess(before, after, **kwargs):
    return await assess_heritage_name_refresh(
        before.source_record,
        after,
        validate=_validate,
        previous_normalizer_revision=kwargs.pop("revision", HERITAGE_NAME_NORMALIZER_REVISION),
        previous_geo=kwargs.pop("old_geo", _GEO),
        current_geo=kwargs.pop("new_geo", _GEO),
        **kwargs,
    )


async def test_stable_composite_identity_name_presence_and_original_clocks():
    before = await _bundle(_base())
    after = await _bundle(replace(_base(), name_ko="새 유산"), later=True)
    assert before.source_record.source_entity_id == after.source_record.source_entity_id
    assert before.feature.provider_natural_key == after.feature.provider_natural_key
    assert after.provider_field_presence.supplied_fields == frozenset({"core.name"})
    result = await _assess(before, after)
    assert result.eligible
    assert result.reason == "name_only"
    assert result.requires_database_verification
    assert not result.collector_ready
    rebuilt = await rebuild_heritage_projection(before.source_record, validate=_validate, geo=_GEO)
    assert rebuilt.source_record == before.source_record
    assert rebuilt.feature.name == before.feature.name
    assert rebuilt.feature.address == before.feature.address
    assert (await _assess(before, await _bundle(_base(), later=True))).reason == "unchanged"


@pytest.mark.parametrize(
    "changes",
    [
        {"name_ko": "왕릉 유산"},
        {"longitude": 126.94},
        {"owner": "다른 관리자"},
        {"category": "전통사찰"},
        {"location_text": "다른 주소"},
        {"image_url": "https://example.invalid/image.jpg"},
    ],
)
async def test_actual_converter_derived_and_unsupported_changes_are_not_name_only(changes):
    before = await _bundle(_base())
    after = await _bundle(replace(_base(), **changes), later=True)
    result = await _assess(before, after)
    assert not result.eligible
    if "name_ko" in changes:
        assert before.source_record.source_entity_id == after.source_record.source_entity_id
        assert before.feature.feature_id != after.feature.feature_id
        assert "feature.category" in result.changed_paths
        assert "feature.marker_icon" in result.changed_paths


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("marker_color", "P-01"),
        ("category", "01070200"),
        ("provider_natural_key", "different-key"),
        ("parent_feature_id", "different-parent"),
        ("feature_id", "different-alias"),
        ("name", "not-the-source-name"),
    ],
)
async def test_current_dto_must_match_reconstruction_including_derived_alias(field, value):
    before = await _bundle(_base())
    current = await _bundle(replace(_base(), name_ko="새 유산"), later=True)
    tampered = current.model_copy(
        update={"feature": current.feature.model_copy(update={field: value})}
    )
    expected = (
        "invalid_current_lineage" if field == "feature_id" else "current_bundle_not_canonical"
    )
    assert (await _assess(before, tampered)).reason == expected


@pytest.mark.parametrize(
    "kwargs",
    [
        {"revision": None},
        {"revision": "unknown-version"},
        {"old_geo": None},
        {"new_geo": HeritageGeoEvidence("resolved", "geo-v2", _ADDRESS, "a" * 64)},
        {"new_geo": HeritageGeoEvidence("resolved", "geo-v1", _ADDRESS, "b" * 64)},
        {"new_geo": HeritageGeoEvidence("resolved", "geo-v1", Address(legal="다른 답"), "a" * 64)},
    ],
)
async def test_unknown_revision_or_geo_evidence_fails_closed(kwargs):
    before = await _bundle(_base())
    assert not (await _assess(before, await _bundle(_base()), **kwargs)).eligible


def _replace_raw(record, raw):
    digest = make_payload_hash(raw)
    key = make_source_record_key(
        provider=record.provider,
        dataset_key=record.dataset_key,
        source_entity_type=record.source_entity_type,
        source_entity_id=record.source_entity_id,
        raw_payload_hash=digest,
    )
    return record.model_copy(
        update={"raw_data": raw, "raw_payload_hash": digest, "source_record_key": key}
    )


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("unknown", "extra"),
        ("name_ko", {"deep": ["input"]}),
        ("manager", True),
        ("name_ko", "x" * 1_048_577),
        ("longitude", "NaN"),
        ("latitude", "Infinity"),
        ("longitude", "181"),
        ("ccba_asno", "missing-numeric-key"),
    ],
)
async def test_invalid_stored_projection_and_unknown_fields_do_not_reach_validator(field, value):
    before = await _bundle(_base())
    bad = _replace_raw(before.source_record, before.source_record.raw_data | {field: value})
    called = False

    def forbidden(_):
        nonlocal called
        called = True
        pytest.fail("invalid projection reached public validator")

    with pytest.raises(ValueError, match="heritage|source"):
        await rebuild_heritage_projection(bad, validate=forbidden, geo=_GEO)
    assert not called


@pytest.mark.parametrize(
    "change",
    [
        {"source_record_key": "different"},
        {"raw_payload_hash": "bad-hash"},
        {"source_entity_id": "wrong-key"},
        {"provider": "wrong-provider"},
        {"dataset_key": "wrong-dataset"},
        {"expires_at": _FETCHED},
    ],
)
async def test_source_evidence_mismatch_is_rejected(change):
    bundle = await _bundle(_base())
    bad = bundle.source_record.model_copy(update=change)
    with pytest.raises(ValueError, match="heritage|source"):
        await rebuild_heritage_projection(bad, validate=_validate, geo=_GEO)


@pytest.mark.parametrize(
    "evidence",
    [
        ("resolved", None, None, None),
        ("not_requested", "unexpected", None, None),
        ("resolved", "geo", _ADDRESS, "NaN"),
        ("resolved", " ", _ADDRESS, "a" * 64),
    ],
)
def test_incomplete_geo_evidence_is_rejected(evidence):
    with pytest.raises(ValueError, match="heritage|source"):
        HeritageGeoEvidence(*evidence)


async def test_omitted_presence_and_actual_bundle_obligations_are_rejected():
    before = await _bundle(_base())
    assert (
        await _assess(before, before.model_copy(update={"provider_field_presence": None}))
    ).reason == "unproven_presence"
    # model_copy는 이미 검증된 DTO를 바꾼 반례를 만든다. truthy dict도 무시해서는 안 된다.
    for field in ("geo_attempt", "admin_evidence"):
        result = await _assess(before, before.model_copy(update={field: {"unexpected": True}}))
        assert result.reason == "unsupported_bundle_obligation"
    changed_role = before.source_link.model_copy(update={"confidence": 99})
    assert (
        await _assess(before, before.model_copy(update={"source_link": changed_role}))
    ).reason == "current_bundle_not_canonical"


async def test_current_link_record_key_must_match_the_actual_record():
    before = await _bundle(_base())
    current = await _bundle(replace(_base(), name_ko="새 유산"), later=True)
    for key in (before.source_record.source_record_key, "unrelated-record"):
        bad_link = current.source_link.model_copy(update={"source_record_key": key})
        bad = current.model_copy(update={"source_link": bad_link})
        result = await _assess(before, bad)
        assert not result.eligible
        assert result.reason == "invalid_current_lineage"


@pytest.mark.parametrize("shape", ["deep", "nodes", "bytes"])
async def test_current_bundle_budget_rejects_before_model_dump(shape, monkeypatch):
    before = await _bundle(_base())
    payload = "x" * 1_048_577 if shape == "bytes" else list(range(9000))
    if shape == "deep":
        payload = "leaf"
        for _ in range(65):
            payload = {"child": payload}
    detail = before.feature.detail.model_copy(update={"payload": {"unsupported": payload}})
    current = before.model_copy(
        update={"feature": before.feature.model_copy(update={"detail": detail})}
    )
    original = type(current).model_dump

    def forbidden_copy(self, *args, **kwargs):
        if self is current:
            pytest.fail("unsafe current bundle reached model_dump before budget rejection")
        return original(self, *args, **kwargs)

    monkeypatch.setattr(type(current), "model_dump", forbidden_copy)
    result = await _assess(before, current)
    assert not result.eligible
    assert result.reason == "invalid_bundle_budget"
