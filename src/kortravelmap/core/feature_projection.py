"""정본 Place DTO projection을 직렬화하기 전 깊이·노드·byte를 검사한다.

외부 모델의 serializer나 apply 권한을 승인하지 않는 내부 순수 도우미다.
"""

from __future__ import annotations

import json
import math
import sys
from collections.abc import Mapping
from datetime import date, datetime
from decimal import Decimal
from enum import Enum
from uuid import UUID

from pydantic import BaseModel

from kortravelmap.dto import (
    Address,
    Coordinate,
    Feature,
    FeatureBundle,
    FeatureUrls,
    PlaceDetail,
    SourceLink,
    SourceRecord,
)
from kortravelmap.dto.provider_field_presence import ProviderFieldPresence

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


def within_place_projection_budget(values: tuple[object, ...]) -> bool:
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
