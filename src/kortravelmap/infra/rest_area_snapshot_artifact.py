"""휴게소 전용 실험 profile의 순수 최종입력 codec. DB/수집/등록 권위는 없다.

호출자는 encode 동안 원본 DTO를 독점 소유한다. durable wire는 기존1MiB이며
Rest 후보의256행/typed65536/source2MiB/wire131072는 Airport에 적용하지 않는다.
"""

from __future__ import annotations

import json
import re
from decimal import DecimalException
from typing import Any, Never

from kortravelmap.core.feature_projection import within_place_projection_budget
from kortravelmap.dto import FeatureBundle, FeatureKind, PlaceDetail
from kortravelmap.dto.geo_dataset import DatasetRef, GeoApplied, GeoLoadContext
from kortravelmap.dto.provider_field_presence import ProviderFieldPresence
from kortravelmap.infra._snapshot_artifact_codec import CodecProfile, guard_wire, preflight
from kortravelmap.infra.exclusive_provider_refresh import (
    ExclusiveProviderSnapshotOptions,
    bounded_full_snapshot,
)
from kortravelmap.infra.provider_snapshot_artifact import (
    DecodedSnapshotArtifact,
    SnapshotArtifactPins,
    UnsupportedSnapshotArtifact,
    _json_bytes,
    _pack,
    _pins,
    _unique,
    _unpack,
)
from kortravelmap.infra.scoped_provider_refresh import _artifact_digest

REST_AREA_SNAPSHOT_DOMAIN = "rest-area-prepared-typed-v1"
_MAX_ITEMS = 256
_RAW_KEYS = frozenset(
    {"natural_key", "name", "route_name", "direction", "lon", "lat", "phone_number"}
)
_PIN_SCOPE = {
    "provider": "kor-travel-transport",
    "dataset_key": "transport_rest_areas",
    "source_entity_type": "rest_area",
    "normalizer_revision": "transport-rest-area-name-phones-v1",
    "geo_domain": "transport-rest-area-geo-v1",
    "clock_domain": "aware-clock-preserved-v1",
    "native_domain": "native-full-refresh-v1",
}


class UnsupportedRestAreaSnapshotArtifact(UnsupportedSnapshotArtifact):
    """휴게소 profile 미지원/입력 무결성 거부. EX/등록 실행을 허용하지 않는다."""


def _reject() -> Never:
    raise UnsupportedRestAreaSnapshotArtifact("unsupported or inconsistent rest-area snapshot")


def _rest_pins(pins: SnapshotArtifactPins) -> dict[str, str]:
    values = _pins(pins)
    if any(values[key] != value for key, value in _PIN_SCOPE.items()):
        _reject()
    return values


def _snapshot(bundles: Any, geo: Any, pins: SnapshotArtifactPins) -> str:
    if type(bundles) is not tuple or not 0 < len(bundles) <= _MAX_ITEMS:
        _reject()
    # 전체 exact-type 순회가 외부 Mapping/serializer/tzinfo hook보다 먼저다.
    preflight((bundles, geo), profile=CodecProfile.REST_AREA)
    geo_values: tuple[object, ...] = ()
    if geo is not None:
        if (
            type(geo) is not GeoLoadContext
            or type(geo.geo_applied) is not GeoApplied
            or (geo.current_dataset is not None and type(geo.current_dataset) is not DatasetRef)
            or (
                geo.observed_data_tokens is not None
                and type(geo.observed_data_tokens) not in (set, frozenset)
            )
        ):
            _reject()
        ref = geo.current_dataset
        geo_values = (
            geo.geo_applied.reverse,
            geo.geo_applied.geocode,
            None
            if ref is None
            else (ref.version_token, ref.data_token, ref.activated_at, ref.reference_months),
            geo.observed_data_tokens,
        )
    # whole budget은 Rest 후보로 고정하며 각 행의 기존 Place whitelist/1MiB도 유지한다.
    if not within_place_projection_budget(geo_values) or any(
        not within_place_projection_budget((bundle,)) for bundle in bundles
    ):
        _reject()
    _pack(bundles)
    if geo is not None:
        _pack(geo.geo_applied)
        _pack(geo.current_dataset)
        _pack(geo.observed_data_tokens)
    for bundle in bundles:
        if (
            type(bundle) is not FeatureBundle
            or type(bundle.feature.detail) is not PlaceDetail
            or bundle.feature.kind != FeatureKind.PLACE
            or bundle.feature.detail.place_kind != "rest_area"
            or bundle.file_sources
            or bundle.admin_evidence is not None
            or bundle.geo_attempt is not None
            or bundle.feature.raw_refs
            or bundle.feature.detail.reviews_link
            or bundle.feature.detail.business_hours is not None
            or bundle.feature.detail.license_date is not None
        ):
            _reject()
        presence = bundle.provider_field_presence
        raw = bundle.source_record.raw_data
        identity = bundle.feature.provider_natural_key
        if (
            type(presence) is not ProviderFieldPresence
            or presence.normalizer_revision != pins.normalizer_revision
            or presence.supplied_fields != frozenset({"core.name", "place.phones"})
            or set(raw) != _RAW_KEYS
            or any(v is not None and type(v) is not str for v in raw.values())
            or type(identity) is not str
            or not 0 < len(identity) <= 256
            or len(identity.encode("utf-8")) > 256
            or raw["natural_key"] != identity
            or bundle.source_record.source_entity_id != identity
            or type(raw["name"]) is not str
            or not raw["name"].strip()
            or re.fullmatch("[0-9a-f]{32}", bundle.source_record.raw_payload_hash) is None
            or bundle.source_link.feature_id != bundle.feature.feature_id
            or bundle.feature.detail.feature_id != bundle.feature.feature_id
        ):
            _reject()
    # 기존 canonical hash/key/primary/unexpired/duplicate 검사와 native digest를 재사용한다.
    bounded_full_snapshot(
        bundles,
        options=ExclusiveProviderSnapshotOptions(
            pins.provider, pins.dataset_key, pins.source_entity_type
        ),
        geo=geo,
        retire_geometryless_areas=True,
    )
    return _artifact_digest(
        [
            pins.native_domain,
            pins.provider,
            pins.dataset_key,
            pins.source_entity_type,
            list(bundles),
            None
            if geo is None
            else [geo.geo_applied, geo.current_dataset, geo.observed_data_tokens],
            True,
        ]
    )


def _envelope(
    bundles: tuple[FeatureBundle, ...], geo: GeoLoadContext | None, pins: SnapshotArtifactPins
) -> dict[str, Any]:
    values = _rest_pins(pins)
    digest = _snapshot(bundles, geo, pins)
    return _canonical_envelope(bundles, geo, values, digest)


def _canonical_envelope(
    bundles: tuple[FeatureBundle, ...],
    geo: GeoLoadContext | None,
    values: dict[str, str],
    digest: str,
) -> dict[str, Any]:
    """같은 호출에서 검증한 값만 고정 envelope로 조립한다. 별도 입력 권위가 아니다."""
    return {
        "version": 1,
        "domain": REST_AREA_SNAPSHOT_DOMAIN,
        "pins": values,
        "native_input_digest": digest,
        "bundles": _pack(bundles),
        "geo": None
        if geo is None
        else [_pack(geo.geo_applied), _pack(geo.current_dataset), _pack(geo.observed_data_tokens)],
    }


def encode_rest_area_snapshot_artifact(
    bundles: tuple[FeatureBundle, ...], geo: GeoLoadContext | None, *, pins: SnapshotArtifactPins
) -> bytes:
    """모든 휴게소 입력을 lossless 검사한 뒤 canonical bytes만 반환한다."""
    try:
        raw = _json_bytes(_envelope(bundles, geo, pins))
        decode_rest_area_snapshot_artifact(raw, expected_pins=pins)
        return raw
    except (
        ValueError,
        TypeError,
        KeyError,
        OverflowError,
        UnicodeError,
        DecimalException,
        AttributeError,
    ) as exc:
        raise UnsupportedRestAreaSnapshotArtifact(
            "unsupported rest-area snapshot artifact"
        ) from exc


def decode_rest_area_snapshot_artifact(
    raw: bytes, *, expected_pins: SnapshotArtifactPins
) -> DecodedSnapshotArtifact:
    """고정 Rest pins/domain·원본 fieldset/시각/typed 의미와 canonical bytes를 검증한다."""
    try:
        expected = _rest_pins(expected_pins)
        data = json.loads(
            guard_wire(raw, profile=CodecProfile.REST_AREA),
            object_pairs_hook=_unique,
            parse_constant=lambda _: _reject(),
        )
        if (
            type(data) is not dict
            or set(data) != {"version", "domain", "pins", "native_input_digest", "bundles", "geo"}
            or type(data["version"]) is not int
            or data["version"] != 1
            or data["domain"] != REST_AREA_SNAPSHOT_DOMAIN
            or data["pins"] != expected
        ):
            _reject()
        bundles = _unpack(data["bundles"])
        geo_data = data["geo"]
        if geo_data is None:
            geo = None
        elif type(geo_data) is list and len(geo_data) == 3:
            geo = GeoLoadContext(*(_unpack(v) for v in geo_data))
        else:
            _reject()
        digest = _snapshot(bundles, geo, expected_pins)
        if (
            digest != data["native_input_digest"]
            or _json_bytes(_canonical_envelope(bundles, geo, expected, digest)) != raw
        ):
            _reject()
        return DecodedSnapshotArtifact(bundles, geo, digest)
    except (
        ValueError,
        TypeError,
        KeyError,
        OverflowError,
        UnicodeError,
        DecimalException,
        AttributeError,
    ) as exc:
        raise UnsupportedRestAreaSnapshotArtifact("invalid rest-area snapshot artifact") from exc
