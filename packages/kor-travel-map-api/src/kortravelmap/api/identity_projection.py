"""응답 identity 치환 — feature_id 값의 UUID 정본 전환 (T-VN-32C PR-2, ADR-068).

read 응답의 ``feature_id`` 필드 값은 legacy ``f_*`` 표기가 아니라 UUID 정본
문자열을 담는다. 치환은 **응답 조립 경계에서만** 일어난다:

- projection은 legacy ``feature_id``와 ``feature_uuid``를 병행 select한다.
- cursor/keyset encode·내부 join 키·batch echo 키는 치환 **전** row의 legacy
  값을 그대로 쓴다 — keyset 술어(``feature_id > :cursor``)는 legacy 축이다.
- echo 예외(요청 표기 보존): batch found/missing 키·item ``feature_id``,
  weather-batch target echo, path-param echo. 이들은 치환 대상이 아니다.

projection에 ``feature_uuid``가 빠졌거나 NULL이면 fail-close(ValueError) —
DB 컬럼이 NOT NULL(0080 backfill 100%)이므로 결측은 projection 누락 버그다.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

__all__ = ["response_feature_id", "uuid_substituted_row"]


def response_feature_id(row: Mapping[str, Any] | Any) -> str:
    """row(dict 또는 attribute-row)에서 응답용 feature_id 값(UUID 정본)을 뽑는다."""
    if isinstance(row, Mapping):
        uuid_text = row.get("feature_uuid")
    else:
        uuid_text = getattr(row, "feature_uuid", None)
    if not uuid_text:
        raise ValueError(
            "row에 feature_uuid가 없습니다 — read projection 누락 (T-VN-32C PR-2)"
        )
    return str(uuid_text)


def uuid_substituted_row(row: Mapping[str, Any]) -> dict[str, Any]:
    """``feature_id`` 값을 UUID 정본으로 치환한 얕은 사본을 돌려준다.

    dict-splat 조립 사이트(``Model(**row)``)용. cursor 등 legacy 값이 필요한
    로직은 반드시 이 호출 **전의** 원본 row에서 값을 뽑아야 한다.
    """
    substituted = dict(row)
    substituted["feature_id"] = response_feature_id(row)
    return substituted
