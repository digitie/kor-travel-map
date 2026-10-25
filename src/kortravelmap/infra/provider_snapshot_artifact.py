"""공항 최종 DTO의 한정된 순수 codec. 파일/DB/수집·apply 권한은 소유하지 않는다.

호출자는 encode 동안 원본 가변 객체를 독점 소유한다. decode는 독립된 snapshot을
만들며 기존 live observed set의 alias는 복원하지 않는다. 8192는 이 codec의 JSON
노드 한도이며 kernel manifest dependency 한도와 관계없다.
"""

from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta, timezone, tzinfo
from decimal import Decimal, DecimalException
from typing import Any, Never
from zoneinfo import ZoneInfo

from kortravelmap.core.feature_projection import within_place_projection_budget
from kortravelmap.dto import (
    FeatureBundle,
    FeatureKind,
    PlaceDetail,
)
from kortravelmap.dto._time import KST
from kortravelmap.dto.geo_dataset import DatasetRef, GeoApplied, GeoLoadContext
from kortravelmap.dto.provider_field_presence import ProviderFieldPresence
from kortravelmap.infra._snapshot_artifact_codec import (
    _ENUMS,
    _MODELS,
    CodecProfile,
)
from kortravelmap.infra._snapshot_artifact_codec import (
    guard_wire as _typed_guard_wire,
)
from kortravelmap.infra._snapshot_artifact_codec import (
    preflight as _typed_preflight,
)
from kortravelmap.infra.exclusive_provider_refresh import (
    ExclusiveProviderSnapshotOptions,
    bounded_full_snapshot,
)
from kortravelmap.infra.scoped_provider_refresh import _artifact_digest

_MAX_BYTES = 1_048_576
_MAX_ITEMS = 2730
_MAX_NODES = 8192
_MAX_DEPTH = 64
_DOMAIN = "airport-prepared-typed-v1"
_NATIVE_DOMAIN = "native-full-refresh-v1"

_RAW_KEYS = frozenset(
    {"code", "name_korean", "name_english", "icao_code", "municipality", "latitude", "longitude"}
)


class UnsupportedSnapshotArtifact(ValueError):
    """DML 전에 중단하는 명시적 미지원/무결성 거부. EX 실행 권위는 아니다."""


@dataclass(frozen=True)
class SnapshotArtifactPins:
    """호출자가 검증한 고정값. 이 객체 자체는 코드/SDK의 출처 증명이 아니다."""

    code_revision: str
    sdk_inventory_sha256: str
    provider: str
    dataset_key: str
    source_entity_type: str
    normalizer_revision: str
    geo_domain: str
    clock_domain: str
    native_domain: str = _NATIVE_DOMAIN


@dataclass(frozen=True)
class DecodedSnapshotArtifact:
    """독립 복원값. 내부 DTO는 가변이므로 이후 await 동안 caller가 독점 소유한다."""

    bundles: tuple[FeatureBundle, ...]
    geo: GeoLoadContext | None
    native_input_digest: str


def _reject() -> Never:
    raise UnsupportedSnapshotArtifact("unsupported or inconsistent airport snapshot artifact")


def _pins(pins: SnapshotArtifactPins) -> dict[str, str]:
    if type(pins) is not SnapshotArtifactPins:
        _reject()
    values = {key: getattr(pins, key) for key in SnapshotArtifactPins.__dataclass_fields__}
    if any(type(v) is not str or not 0 < len(v) <= 128 or v != v.strip() for v in values.values()):
        _reject()
    if not re.fullmatch("[0-9a-f]{40}", pins.code_revision):
        _reject()
    if not re.fullmatch("[0-9a-f]{64}", pins.sdk_inventory_sha256):
        _reject()
    if pins.native_domain != _NATIVE_DOMAIN:
        _reject()
    return values


def _preflight(values: tuple[object, ...]) -> None:
    """기존 Airport exact-type 순서와 한도를 유지하는 wrapper."""
    try:
        _typed_preflight(values, profile=CodecProfile.AIRPORT)
    except ValueError:
        _reject()


def _json_bytes(value: Any) -> bytes:
    result = bytearray()
    encoder = json.JSONEncoder(
        ensure_ascii=False, allow_nan=False, sort_keys=True, separators=(",", ":")
    )
    for chunk in encoder.iterencode(value):
        encoded = chunk.encode("utf-8", errors="strict")
        if len(result) + len(encoded) > _MAX_BYTES:
            _reject()
        result.extend(encoded)
    return bytes(result)


def _time(value: datetime) -> list[Any]:
    if value.tzinfo is UTC:
        zone: Any = "UTC"
    elif type(value.tzinfo) is ZoneInfo and value.tzinfo.key == "Asia/Seoul":
        zone = "Asia/Seoul"
    elif type(value.tzinfo) is timezone:
        offset = value.utcoffset()
        if offset is None:
            _reject()
        zone = [int(offset.total_seconds()), value.tzname()]
    else:
        _reject()
    return ["datetime", value.isoformat(), zone, value.fold]


def _pack(value: Any) -> Any:
    if type(value) in _ENUMS.values():
        return ["enum", type(value).__name__, value.value]
    if value is None or type(value) in (str, bool, int):
        return value
    if type(value) is float and math.isfinite(value):
        return value
    if type(value) is Decimal and value.is_finite():
        return ["decimal", str(value)]
    if type(value) is datetime:
        return _time(value)
    if type(value) in _MODELS.values():
        cls = type(value)
        if set(value.__dict__) != set(cls.model_fields) or value.__pydantic_extra__:
            _reject()
        if type(value.model_fields_set) is not set or not value.model_fields_set <= set(
            cls.model_fields
        ):
            _reject()
        return [
            "model",
            cls.__name__,
            sorted(value.model_fields_set),
            {key: _pack(value.__dict__[key]) for key in cls.model_fields},
        ]
    if type(value) is dict:
        if any(type(key) is not str for key in value):
            _reject()
        return ["dict", [[key, _pack(value[key])] for key in sorted(value)]]
    if type(value) in (list, tuple):
        return ["list" if type(value) is list else "tuple", [_pack(v) for v in value]]
    if type(value) in (set, frozenset):
        if any(type(v) is not str for v in value):
            _reject()
        return ["set" if type(value) is set else "frozenset", sorted(value)]
    _reject()


def _unpack(value: Any) -> Any:
    if value is None or type(value) in (str, bool, int, float):
        return value
    if type(value) is not list or not value or type(value[0]) is not str:
        _reject()
    tag = value[0]
    if tag in ("dict", "list", "tuple", "set", "frozenset") and len(value) == 2:
        children = value[1]
        if type(children) is not list:
            _reject()
        if tag == "dict":
            result = {}
            for pair in children:
                if (
                    type(pair) is not list
                    or len(pair) != 2
                    or type(pair[0]) is not str
                    or pair[0] in result
                ):
                    _reject()
                result[pair[0]] = _unpack(pair[1])
            return result
        if tag in ("set", "frozenset"):
            if any(type(v) is not str for v in children) or len(set(children)) != len(children):
                _reject()
            return set(children) if tag == "set" else frozenset(children)
        decoded = [_unpack(v) for v in children]
        return decoded if tag == "list" else tuple(decoded)
    if tag == "decimal" and len(value) == 2 and type(value[1]) is str:
        number = Decimal(value[1])
        if not number.is_finite():
            _reject()
        return number
    if tag == "enum" and len(value) == 3 and value[1] in _ENUMS:
        return _ENUMS[value[1]](value[2])
    if tag == "datetime" and len(value) == 4:
        parsed = datetime.fromisoformat(value[1])
        if type(value[3]) is not int or value[3] not in (0, 1) or parsed.utcoffset() is None:
            _reject()
        zone = value[2]
        tz: tzinfo
        if zone == "UTC":
            tz = UTC
        elif zone == "Asia/Seoul":
            tz = KST
        elif (
            type(zone) is list
            and len(zone) == 2
            and type(zone[0]) is int
            and type(zone[1]) is str
            and len(zone[1]) <= 128
        ):
            tz = timezone(timedelta(seconds=zone[0]), zone[1])
        else:
            _reject()
        return parsed.replace(tzinfo=tz, fold=value[3])
    if tag == "model" and len(value) == 4 and value[1] in _MODELS:
        cls = _MODELS[value[1]]
        fields_set, data = value[2:]
        if (
            type(fields_set) is not list
            or any(type(v) is not str for v in fields_set)
            or len(set(fields_set)) != len(fields_set)
            or type(data) is not dict
            or set(data) != set(cls.model_fields)
            or not set(fields_set) <= set(data)
        ):
            _reject()
        model = cls.model_validate(
            {key: _unpack(child) for key, child in data.items()}, strict=True
        )
        # 모든 default 값도 명시 전달했으므로 시각/default factory 재생성은 없다.
        object.__setattr__(model, "__pydantic_fields_set__", set(fields_set))
        return model
    _reject()


def _guard_wire(raw: bytes) -> str:
    """기존 Airport wire 한도를 유지하는 wrapper."""
    try:
        return _typed_guard_wire(raw, profile=CodecProfile.AIRPORT)
    except UnicodeError:
        raise
    except ValueError:
        _reject()


def _unique(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            _reject()
        result[key] = value
    return result


def _snapshot(bundles: Any, geo: Any, pins: SnapshotArtifactPins) -> str:
    if type(bundles) is not tuple or not 0 < len(bundles) <= _MAX_ITEMS:
        _reject()
    _preflight((bundles, geo))
    # 외부 serializer/model_dump/정본 raw hash보다 먼저 원천 예산을 검사한다.
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
        # Geo는 공통 Place whitelist 밖이다. 고정 필드만 원천 검사한다.
        ref = geo.current_dataset
        geo_values = (
            geo.geo_applied.reverse,
            geo.geo_applied.geocode,
            None
            if ref is None
            else (ref.version_token, ref.data_token, ref.activated_at, ref.reference_months),
            geo.observed_data_tokens,
        )
    if not within_place_projection_budget((*bundles, *geo_values)):
        _reject()
    _pack(bundles)  # foreign timezone/type은 정본 digest 호출보다 먼저 거부한다.
    if geo is not None:
        _pack(geo.geo_applied)
        _pack(geo.current_dataset)
        _pack(geo.observed_data_tokens)
    for bundle in bundles:
        if (
            type(bundle) is not FeatureBundle
            or type(bundle.feature.detail) is not PlaceDetail
            or bundle.feature.kind != FeatureKind.PLACE
            or bundle.feature.detail.place_kind != "airport"
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
        if (
            type(presence) is not ProviderFieldPresence
            or presence.normalizer_revision != pins.normalizer_revision
            or presence.supplied_fields != frozenset({"core.name"})
            or set(raw) != _RAW_KEYS
            or any(v is not None and type(v) is not str for v in raw.values())
        ):
            _reject()
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
    pin_values = _pins(pins)
    digest = _snapshot(bundles, geo, pins)
    return {
        "version": 1,
        "domain": _DOMAIN,
        "pins": pin_values,
        "native_input_digest": digest,
        "bundles": _pack(bundles),
        "geo": None
        if geo is None
        else [_pack(geo.geo_applied), _pack(geo.current_dataset), _pack(geo.observed_data_tokens)],
    }


def encode_provider_snapshot_artifact(
    bundles: tuple[FeatureBundle, ...],
    geo: GeoLoadContext | None,
    *,
    pins: SnapshotArtifactPins,
) -> bytes:
    """전체 최종 공항 snapshot을 encode. 미지원 타입은 호출자가 preDML 거부한다."""
    try:
        envelope = _envelope(bundles, geo, pins)
        raw = _json_bytes(envelope)
        # encode도 정본 validator와 fieldset 복원 왕복을 증명한 입력만 반환한다.
        decode_provider_snapshot_artifact(raw, expected_pins=pins)
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
        raise UnsupportedSnapshotArtifact("unsupported airport snapshot artifact") from exc


def decode_provider_snapshot_artifact(
    raw: bytes,
    *,
    expected_pins: SnapshotArtifactPins,
) -> DecodedSnapshotArtifact:
    """정확 pins+canonical bytes+정본 typed 의미를 확인하고 독립 DTO를 복원한다."""
    try:
        expected = _pins(expected_pins)
        data = json.loads(
            _guard_wire(raw), object_pairs_hook=_unique, parse_constant=lambda _: _reject()
        )
        if (
            type(data) is not dict
            or set(data) != {"version", "domain", "pins", "native_input_digest", "bundles", "geo"}
            or type(data["version"]) is not int
            or data["version"] != 1
            or data["domain"] != _DOMAIN
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
            or _json_bytes(_envelope(bundles, geo, expected_pins)) != raw
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
        raise UnsupportedSnapshotArtifact("invalid airport snapshot artifact") from exc
