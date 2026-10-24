"""국가유산 저장 typed projection의 재정규화와 이름 갱신 적격성 진단.

provider HTTP facade가 아니다. validator는 정본 public HeritageDetail.model_validate를
호출자가 직접 전달한다. DB/collector/정책을 변경하거나 apply 권한을 발급하지 않는다.
"""

from __future__ import annotations

import json
import math
import re
import sys
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from enum import Enum
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel

from kortravelmap.core.ids import make_payload_hash, make_source_record_key
from kortravelmap.dto import (
    Address,
    Coordinate,
    Feature,
    FeatureBundle,
    FeatureKind,
    FeatureUrls,
    PlaceDetail,
    SourceLink,
    SourceRecord,
    SourceRole,
)
from kortravelmap.dto.provider_field_presence import ProviderFieldPresence
from kortravelmap.providers.krheritage import (
    DATASET_KEY_HERITAGE,
    HERITAGE_NAME_NORMALIZER_REVISION,
    PROVIDER_NAME,
    KrHeritageItem,
    heritage_items_to_bundles,
)

HeritageProjectionValidator = Callable[[dict[str, object]], KrHeritageItem]
_RAW_KEYS = frozenset(
    {
        "ccba_kdcd",
        "ccba_asno",
        "ccba_ctcd",
        "name_ko",
        "category",
        "region",
        "sigungu",
        "longitude",
        "latitude",
        "location_text",
        "designated_at",
        "manager",
        "image_url",
    }
)
_DIGEST = re.compile(r"[0-9a-f]{64}")
# 이 한정 진단에서 실제 사용하는 정본 DTO class identity만 허용한다.
# 임의 BaseModel의 computed field/serializer는 사전 순회 이후 출력 크기를 바꿀 수 있다.
_CANONICAL_MODELS = frozenset(
    {
        Address,
        Coordinate,
        Feature,
        FeatureBundle,
        FeatureUrls,
        PlaceDetail,
        SourceLink,
        SourceRecord,
        ProviderFieldPresence,
    }
)


@dataclass(frozen=True)
class HeritageGeoEvidence:
    """별도 조회자가 확보해야 하는 Geo 비교 증거. 이 값 자체는 DB 권한 증명이 아니다.

    resolved는 old/new의 동일 token·주소·stamp 지문을 모두 요구한다. not_requested는
    실제 해당 경로가 Geo를 요청하지 않았다는 명시 입력이며 누락 증거의 대체값이 아니다.
    """

    mode: Literal["not_requested", "resolved"]
    data_token: str | None = None
    address: Address | None = None
    stamp_digest: str | None = None

    def __post_init__(self) -> None:
        if self.mode == "not_requested":
            valid = self.data_token is None and self.address is None and self.stamp_digest is None
        elif self.mode == "resolved":
            valid = (
                isinstance(self.data_token, str)
                and 0 < len(self.data_token) <= 256
                and self.data_token == self.data_token.strip()
                and isinstance(self.address, Address)
                and isinstance(self.stamp_digest, str)
                and _DIGEST.fullmatch(self.stamp_digest) is not None
            )
        else:
            valid = False
        if not valid:
            raise ValueError("incomplete heritage Geo comparison evidence")


@dataclass(frozen=True)
class HeritageNameEligibility:
    """pure 비교 진단이다. canonical claim/membership/epoch는 적용 TX에서 다시 검증해야 한다."""

    eligible: bool
    reason: str
    changed_paths: tuple[str, ...] = ()

    @property
    def requires_database_verification(self) -> bool:
        return True

    @property
    def collector_ready(self) -> bool:
        return False


def _projection_input(raw: Mapping[str, Any]) -> dict[str, object]:
    # Map이 저장한 flat typed projection만 받는다. 외부 envelope/확장 raw는 해석하지 않는다.
    if len(raw) != len(_RAW_KEYS) or set(raw) != _RAW_KEYS:
        raise ValueError("unknown or missing heritage projection field")
    total = 0
    for value in raw.values():
        if value is not None and not isinstance(value, str):
            raise ValueError("heritage projection must contain bounded scalar text")
        if isinstance(value, str):
            if len(value) > 1_048_576:
                raise ValueError("heritage projection exceeds byte budget")
            total += len(value.encode("utf-8"))
            if total > 1_048_576:
                raise ValueError("heritage projection exceeds byte budget")
    keys = {name: raw[name] for name in ("ccba_kdcd", "ccba_asno", "ccba_ctcd")}
    if any(
        not isinstance(v, str) or not v.isascii() or not v.isdigit() or len(v) > 32
        for v in keys.values()
    ):
        raise ValueError("complete heritage composite key required")
    if (raw["longitude"] is None) != (raw["latitude"] is None):
        raise ValueError("incomplete heritage coordinate pair")
    for key, bound in (("longitude", 180), ("latitude", 90)):
        value = raw[key]
        if value is not None:
            try:
                number = Decimal(value)
            except InvalidOperation:
                raise ValueError("invalid heritage projected coordinate") from None
            if not number.is_finite() or abs(number) > bound:
                raise ValueError("invalid heritage projected coordinate")
    return {
        "key": keys,
        **{key: value for key, value in raw.items() if key not in {*keys, "manager"}},
        "owner": raw["manager"],
    }


async def rebuild_heritage_projection(
    record: SourceRecord,
    *,
    validate: HeritageProjectionValidator,
    geo: HeritageGeoEvidence,
) -> FeatureBundle:
    """저장 projection을 public DTO로 복원한 뒤 기존 converter로 다시 변환한다.

    validator는 provider parser의 대체 구현이 아니다. flatten된 저장 key와 manager를
    public DTO 입력으로 되돌리는 Map 전용 seam이며 재직렬화 raw/hash 일치도 요구한다.
    반환값의 감사 시각은 원 record의 시각으로 고정한다. Feature 감사 시각 비교는 별도다.
    """
    if (
        record.provider != PROVIDER_NAME
        or record.dataset_key != DATASET_KEY_HERITAGE
        or record.source_entity_type != "heritage"
        or record.expires_at is not None
    ):
        raise ValueError("unsupported heritage record identity")
    payload = _projection_input(record.raw_data)
    if record.raw_payload_hash != make_payload_hash(
        record.raw_data, length=len(record.raw_payload_hash)
    ):
        raise ValueError("heritage source hash mismatch")
    expected = make_source_record_key(
        provider=record.provider,
        dataset_key=record.dataset_key,
        source_entity_type=record.source_entity_type,
        source_entity_id=record.source_entity_id,
        raw_payload_hash=record.raw_payload_hash,
    )
    if record.source_record_key != expected:
        raise ValueError("heritage source key mismatch")
    try:
        item = validate(payload)
    except (ValueError, TypeError, KeyError):
        raise ValueError("invalid stored heritage public DTO projection") from None

    async def reverse(_coordinate: object) -> Address | None:
        return geo.address

    bundles = await heritage_items_to_bundles(
        [item],
        fetched_at=record.fetched_at,
        reverse_geocoder=reverse if geo.mode == "resolved" else None,
    )
    if len(bundles) != 1:
        raise ValueError("heritage projection does not reconstruct one item")
    bundle = bundles[0]
    if (
        bundle.source_record.raw_data != record.raw_data
        or bundle.source_record.source_entity_id != record.source_entity_id
        or bundle.source_record.raw_payload_hash != record.raw_payload_hash
        or bundle.source_record.source_record_key != record.source_record_key
    ):
        raise ValueError("heritage projection roundtrip changed source evidence")
    return bundle.model_copy(update={"source_record": record})


def _meaning(bundle: FeatureBundle, *, name_changes: bool, aliases: bool) -> dict[str, Any]:
    """전체 필드를 비교하며 감사 시각과 명시한 파생 alias/name만 분리한다."""
    result = bundle.model_dump(mode="json")
    feature = result.pop("feature")
    # provider 값이 아닌 DTO 생성 감사 시각이다. source 시각은 원 artifact에 별도 보존한다.
    feature.pop("created_at")
    feature.pop("updated_at")
    if name_changes:
        feature.pop("name")
    if aliases:
        feature.pop("feature_id")
        feature["detail"].pop("feature_id", None)
    record = result.pop("source_record")
    # raw/key/hash는 rebuild에서 별도 검증했다. 새 관측 시각 차이는 필드 의미 차이가 아니다.
    for key in ("raw_data", "raw_payload_hash", "source_record_key", "fetched_at", "imported_at"):
        record.pop(key)
    link = result.pop("source_link")
    link.pop("created_at")
    link.pop("source_record_key")
    if aliases:
        link.pop("feature_id")
    return {
        **{f"feature.{k}": v for k, v in feature.items()},
        **{f"source_record.{k}": v for k, v in record.items()},
        **{f"source_link.{k}": v for k, v in link.items()},
        **{f"bundle.{k}": v for k, v in result.items()},
    }


def _within_comparison_budget(values: tuple[object, ...]) -> bool:
    """model_dump 전 lazy 순회. 전체 입력을 복사하지 않고 깊이/노드/byte를 제한한다."""
    stack = [(value, 0) for value in values]
    nodes = 8192
    remaining = 1_048_576
    while stack:
        value, depth = stack.pop()
        nodes -= 1
        remaining -= 8  # JSON 구분자/상수 표기의 보수적 여유.
        if nodes < 0 or remaining < 0 or depth > 64:
            return False
        if isinstance(value, Enum):
            # plain Enum.value도 임의 크기/형태를 가질 수 있으므로 정수처럼 취급하지 않는다.
            if len(stack) + 1 > nodes:
                return False
            stack.append((value.value, depth + 1))
        elif isinstance(value, BaseModel):
            if type(value) not in _CANONICAL_MODELS:
                return False
            # 공식 iterator를 직접 소비한다. model_copy의 미선언 __dict__ 필드도 복사 전에 거부한다.
            for key, child in value:
                if key not in type(value).model_fields or len(stack) + 2 > nodes:
                    return False
                stack.append((key, depth + 1))
                stack.append((child, depth + 1))
        elif isinstance(value, Mapping):
            for key, child in value.items():
                if len(stack) + 2 > nodes:
                    return False
                stack.append((key, depth + 1))
                stack.append((child, depth + 1))
        elif isinstance(value, (list, tuple, set, frozenset)):
            for child in value:
                if len(stack) + 1 > nodes:
                    return False
                stack.append((child, depth + 1))
        elif isinstance(value, str):
            if len(value) > remaining:
                return False
            try:
                remaining -= len(json.dumps(value, ensure_ascii=False).encode("utf-8"))
            except UnicodeError:
                return False
        elif value is None or isinstance(value, bool):
            pass
        elif isinstance(value, int):
            if value.bit_length() > 4096:
                return False
            remaining -= len(str(value))
        elif isinstance(value, float):
            if not math.isfinite(value):
                return False
            remaining -= len(repr(value))
        elif isinstance(value, Decimal):
            if not value.is_finite() or sys.getsizeof(value) > 1024:
                return False
            remaining -= len(str(value))
        elif isinstance(value, (datetime, date, UUID)):
            remaining -= 128
        else:
            return False
        if remaining < 0:
            return False
    return True


async def assess_heritage_name_refresh(
    previous: SourceRecord,
    current: FeatureBundle,
    *,
    previous_normalizer_revision: str | None,
    previous_geo: HeritageGeoEvidence | None,
    current_geo: HeritageGeoEvidence | None,
    validate: HeritageProjectionValidator,
) -> HeritageNameEligibility:
    """기존 primary place의 name만 변했는지 진단한다. DB apply 승인이 아니다."""
    if previous_normalizer_revision != HERITAGE_NAME_NORMALIZER_REVISION:
        return HeritageNameEligibility(False, "unknown_previous_normalizer")
    if (
        not isinstance(previous_geo, HeritageGeoEvidence)
        or not isinstance(current_geo, HeritageGeoEvidence)
        or previous_geo != current_geo
    ):
        return HeritageNameEligibility(False, "unknown_or_changed_geo_evidence")
    if not _within_comparison_budget(
        (previous, current, previous_geo.address, current_geo.address)
    ):
        return HeritageNameEligibility(False, "invalid_bundle_budget")
    if (
        current.source_link.source_record_key != current.source_record.source_record_key
        or current.source_link.feature_id != current.feature.feature_id
    ):
        return HeritageNameEligibility(False, "invalid_current_lineage")
    presence = current.provider_field_presence
    if (
        presence is None
        or presence.normalizer_revision != HERITAGE_NAME_NORMALIZER_REVISION
        or presence.supplied_fields != frozenset({"core.name"})
    ):
        return HeritageNameEligibility(False, "unproven_presence")
    if (
        current.feature.kind != FeatureKind.PLACE
        or current.source_link.source_role != SourceRole.PRIMARY
        or current.file_sources
        or current.geo_attempt is not None
        or current.admin_evidence is not None
    ):
        return HeritageNameEligibility(False, "unsupported_bundle_obligation")
    try:
        before = await rebuild_heritage_projection(previous, validate=validate, geo=previous_geo)
        rebuilt = await rebuild_heritage_projection(
            current.source_record, validate=validate, geo=current_geo
        )
    except (ValueError, TypeError, KeyError):
        return HeritageNameEligibility(False, "invalid_typed_projection")
    if before.feature.kind != FeatureKind.PLACE or before.file_sources:
        return HeritageNameEligibility(False, "unsupported_previous_bundle")
    if _meaning(rebuilt, name_changes=False, aliases=False) != _meaning(
        current, name_changes=False, aliases=False
    ):
        return HeritageNameEligibility(False, "current_bundle_not_canonical")
    left = _meaning(before, name_changes=True, aliases=True)
    right = _meaning(current, name_changes=True, aliases=True)
    # 같은 Geo 답에 가려진 원천 주소 변경도 미지원이다. 이름 외 저장 projection은 그대로여야 한다.
    left.update(
        {f"source_projection.{k}": v for k, v in previous.raw_data.items() if k != "name_ko"}
    )
    right.update(
        {
            f"source_projection.{k}": v
            for k, v in current.source_record.raw_data.items()
            if k != "name_ko"
        }
    )
    changed = tuple(sorted(k for k in left.keys() | right.keys() if left.get(k) != right.get(k)))
    reason = "unchanged" if before.feature.name == current.feature.name else "name_only"
    return HeritageNameEligibility(
        not changed, "unsupported_meaning_change" if changed else reason, changed
    )
