"""두 고정 snapshot profile의 exact-type 선검사·wire 스캔만 공유한다.

Rest 값은 실험 후보이며 운영 등록 권위가 아니다. Airport의 기존 한도는 유지한다.
caller 소유 가변 입력을 검사하는 동안 임의 serializer/hook/IO를 호출하지 않는다.
"""

from __future__ import annotations

import math
import re
import sys
from datetime import datetime, timezone
from decimal import Decimal
from enum import Enum
from typing import Any, Never
from zoneinfo import ZoneInfo

from kortravelmap.dto import (
    Address,
    Coordinate,
    Feature,
    FeatureBundle,
    FeatureKind,
    FeatureLifecycleState,
    FeaturePublicationState,
    FeatureQualityState,
    FeatureUrls,
    PlaceDetail,
    SourceLink,
    SourceRecord,
    SourceRole,
)
from kortravelmap.dto.geo_dataset import DatasetRef, GeoApplied, GeoLoadContext
from kortravelmap.dto.provider_field_presence import ProviderFieldPresence

_MAX_BYTES = 1_048_576
_MAX_DEPTH = 64
# 겹치지 않는 span을 possessive로 소비해 escape 수에 비례하는 역추적 상태를 만들지 않는다.
# JSON 객체는 한도 검사 뒤에 만든다.
_QUOTED_STRING = re.compile(r'"[^"\\]*+(?:\\.[^"\\]*+)*+"', re.DOTALL)
_ASCII_ESCAPES = re.compile(r'["\\\x00-\x1f]')


class CodecProfile(Enum):
    """동적 domain/사용자 상한을 받지 않는 두 내부 profile."""

    AIRPORT = "airport"
    REST_AREA = "rest_area"


def _limits(profile: CodecProfile) -> tuple[int, int, int]:
    if profile is CodecProfile.AIRPORT:
        return 8192, 1_048_576, 8192
    if profile is CodecProfile.REST_AREA:
        return 65_536, 2_097_152, 131_072
    return _reject()


def _reject() -> Never:
    raise ValueError("unsupported bounded typed snapshot")


_MODELS = {
    cls.__name__: cls
    for cls in (
        Address,
        Coordinate,
        Feature,
        FeatureBundle,
        FeatureUrls,
        PlaceDetail,
        SourceLink,
        SourceRecord,
        ProviderFieldPresence,
        DatasetRef,
        GeoApplied,
    )
}
_ENUMS = {
    cls.__name__: cls
    for cls in (
        FeatureKind,
        FeatureLifecycleState,
        FeaturePublicationState,
        FeatureQualityState,
        SourceRole,
    )
}


def preflight(values: tuple[object, ...], *, profile: CodecProfile) -> None:
    """외부 hook을 호출하지 않는 exact-type 선검사. pack/hash/복사보다 먼저다."""
    stack: list[tuple[Any, int]] = [(value, 0) for value in values]
    nodes, remaining, _ = _limits(profile)
    while stack:
        value, depth = stack.pop()
        nodes -= 1
        remaining -= 8
        if nodes < 0 or remaining < 0 or depth > _MAX_DEPTH:
            _reject()
        kind = type(value)
        children: Any = ()
        scalar = kind is str or value is None or kind is bool
        if not scalar and any(kind is cls for cls in _MODELS.values()):
            data = value.__dict__
            fields = value.model_fields_set
            if type(data) is not dict or type(fields) is not set:
                _reject()
            if (
                len(data) != len(kind.model_fields)
                or any(type(key) is not str for key in data)
                or any(type(key) is not str for key in fields)
                or any(key not in kind.model_fields for key in data)
                or any(key not in kind.model_fields for key in fields)
                or value.__pydantic_extra__ is not None
            ):
                _reject()
            if len(stack) + 1 > nodes:
                _reject()
            stack.append((fields, depth + 1))
            children = data.items()
        elif kind is GeoLoadContext:
            data = value.__dict__
            if (
                type(data) is not dict
                or len(data) != 3
                or any(type(key) is not str for key in data)
                or any(
                    key not in ("geo_applied", "current_dataset", "observed_data_tokens")
                    for key in data
                )
            ):
                _reject()
            children = data.items()
        elif kind is dict:
            # exact dict만: Mapping.items/__iter__ 등의 임의 구현을 호출하지 않는다.
            children = dict.items(value)
        elif kind is list or kind is tuple or kind is set or kind is frozenset:
            for child in value:
                if len(stack) + 1 > nodes:
                    _reject()
                stack.append((child, depth + 1))
        elif not scalar and any(kind is cls for cls in _ENUMS.values()):
            stack.append((value.value, depth + 1))
        elif kind is str:
            # 거대한 escape/UTF8 복사 없이 전체 encoded 문자열 비용을 선누적한다.
            if len(value) > remaining:
                _reject()
            if value.isascii():
                remaining -= len(value) + 2
                for match in _ASCII_ESCAPES.finditer(value):
                    remaining -= 1 if match[0] in '\"\\\b\f\n\r\t' else 5
                if remaining < 0:
                    _reject()
                continue
            remaining -= 2
            for char in value:
                code = ord(char)
                if 0xD800 <= code <= 0xDFFF:
                    _reject()
                if char in ('"', "\\") or char in "\b\f\n\r\t":
                    remaining -= 2
                elif code < 32:
                    remaining -= 6
                else:
                    remaining -= 1 if code < 128 else 2 if code < 2048 else 3 if code < 65536 else 4
                if remaining < 0:
                    _reject()
        elif value is None or kind is bool:
            pass
        elif kind is int:
            if value.bit_length() > 4096:
                _reject()
            remaining -= len(str(value))
        elif kind is float:
            if not math.isfinite(value):
                _reject()
            remaining -= len(repr(value))
        elif kind is Decimal:
            if not value.is_finite() or sys.getsizeof(value) > 1024:
                _reject()
            remaining -= len(str(value))
        elif kind is datetime:
            zone = value.tzinfo
            if type(zone) is timezone:
                # builtin timezone도 임의 길이/str subclass의 name을 그대로 보관한다.
                name = zone.tzname(None)
                if type(name) is not str or len(name) > 128 or len(stack) + 1 > nodes:
                    _reject()
                stack.append((name, depth + 1))
            elif type(zone) is ZoneInfo:
                if type(zone.key) is not str or zone.key != "Asia/Seoul":
                    _reject()
            else:
                _reject()
            remaining -= 128
        else:
            _reject()
        for key, child in children:
            if type(key) is not str or len(stack) + 2 > nodes:
                _reject()
            stack.append((key, depth + 1))
            stack.append((child, depth + 1))
        if remaining < 0:
            _reject()


def guard_wire(raw: bytes, *, profile: CodecProfile) -> str:
    """JSON 객체를 만들기 전에 bytes/UTF8/컨테이너 깊이와 토큰 노드를 제한한다."""
    _, _, max_wire_nodes = _limits(profile)
    if type(raw) is not bytes or not raw or len(raw) > _MAX_BYTES:
        _reject()
    value = raw.decode("utf-8", errors="strict")
    depth = nodes = 0
    token = False
    index = 0
    while index < len(value):
        char = value[index]
        index += 1
        if char == '"':
            nodes += 1
            token = False
            if depth > _MAX_DEPTH or nodes > max_wire_nodes:
                _reject()
            matched = _QUOTED_STRING.match(value, index - 1)
            # 닫히지 않은 문자열은 이전 scanner와 같이 나머지를 추가 토큰으로 세지 않는다.
            # 실제 JSON 구문 거부는 호출자의 json.loads가 그대로 수행한다.
            if matched is None:
                break
            index = matched.end()
        elif char in "[{":
            depth += 1
            nodes += 1
            token = False
        elif char in "]}":
            depth -= 1
            token = False
        elif char in ",: \t\r\n":
            token = False
        elif not token:
            nodes += 1
            token = True
        if depth > _MAX_DEPTH or nodes > max_wire_nodes:
            _reject()
    return value
