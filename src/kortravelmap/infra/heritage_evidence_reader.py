"""Heritage 증거 reader의 제한된 입력 계약. collector/SH apply 권한은 발급하지 않는다."""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass
from enum import StrEnum
from typing import Final

_MAX_TARGETS: Final[int] = 2730
_MAX_INPUT_BYTES: Final[int] = 262_144
_ENTITY: Final[re.Pattern[str]] = re.compile(r"se_[0-9a-f]{64}")


class HeritageEvidenceIneligibility(StrEnum):
    """SQL이 명시적으로 반환할 수 있는 전체 요청의 알려진 부적격 사유."""

    SCOPE_UNSUPPORTED = "scope_unsupported"
    MISSING_SOURCE = "missing_source"
    UNSUPPORTED_MEMBERSHIP = "unsupported_membership"
    INACTIVE_FEATURE = "inactive_feature"
    POLICY_UNSUPPORTED = "policy_unsupported"
    LINEAGE_INCOMPLETE = "lineage_incomplete"
    MIXED_BASE_LINEAGE = "mixed_base_lineage"
    STORAGE_UNSUPPORTED = "storage_unsupported"
    SHAPE_UNSUPPORTED = "shape_unsupported"
    BUDGET_EXCEEDED = "budget_exceeded"
    RETIRE_REQUIRED = "retire_required"


@dataclass(frozen=True)
class HeritageEvidenceRequest:
    """사전 검증된 읽기 요청. 결과의 완결성은 SH 적격성/쓰기 권한과 다르다."""

    dataset_id: int
    entity_keys: tuple[str, ...]


def validate_heritage_evidence_request(
    dataset_id: int, entity_keys: Iterable[str]
) -> HeritageEvidenceRequest:
    """MAX+1까지만 소비하고 정본 key/중복/배열 전송 예산을 SQL 호출 전에 확인한다.

    Python은 caller가 이미 만든 객체나 PG wire 전체의 메모리를 제한하지 않는다.
    서버도 배열 datum 크기를 unnest/cardinality/문자열 처리 전에 별도로 확인해야 한다.
    """
    if type(dataset_id) is not int or not 1 <= dataset_id <= 9_223_372_036_854_775_807:
        raise ValueError("dataset id must be a positive PostgreSQL bigint")
    if isinstance(entity_keys, (str, bytes, bytearray)):
        raise ValueError("entity keys must be an iterable of canonical keys")
    collected: list[str] = []
    seen: set[str] = set()
    # 배열 header/차원과 원소별 datum header/정렬 여유를 보수적으로 포함한다.
    reserved_bytes = 64
    for key in entity_keys:
        if len(collected) >= _MAX_TARGETS:
            raise ValueError("heritage evidence request exceeds 2730 targets")
        if type(key) is not str or len(key) != 67 or _ENTITY.fullmatch(key) is None:
            raise ValueError("invalid canonical source entity key")
        if key in seen:
            raise ValueError("duplicate source entity key")
        reserved_bytes += 8 + len(key)
        if reserved_bytes > _MAX_INPUT_BYTES:
            raise ValueError("heritage evidence request exceeds input byte budget")
        collected.append(key)
        seen.add(key)
    if not collected:
        raise ValueError("heritage evidence request cannot be empty")
    return HeritageEvidenceRequest(dataset_id, tuple(collected))
