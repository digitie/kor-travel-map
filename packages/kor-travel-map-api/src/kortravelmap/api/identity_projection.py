"""응답 identity 치환 — feature_id 값의 UUID 정본 전환 (T-VN-32C PR-2, ADR-068).

read 응답의 ``feature_id`` 필드 값은 legacy ``f_*`` 표기가 아니라 UUID 정본
문자열을 담는다. 치환은 **응답 조립 경계에서만** 일어난다:

- projection은 정본 키를 ``feature_uuid`` **이름으로** 함께 내보낸다. T-VN-39
  재키 전에는 그것이 shadow 컬럼이었고, 재키 후에는 같은 이름의 출력 별칭이
  ``CAST(feature_id AS text)``에서 온다 — 나가는 이름은 바뀌지 않았고 원천만 바뀌었다.
- cursor/keyset encode·내부 join 키는 치환 **전** row의 값을 쓴다. 재키 후 그 축은
  더 이상 legacy가 아니라 정본 키(uuid) 자신이다.
- echo 예외(요청 표기 보존): batch found/missing 키·item ``feature_id``,
  weather-batch target echo, path-param echo. 이들은 치환 대상이 아니다 — 요청이
  legacy ``f_*``로 물었으면 응답의 그 자리는 물어본 표기를 되돌려준다.

projection에 ``feature_uuid``가 빠졌거나 NULL이면 fail-close(ValueError). 재키 후
그 이름은 컬럼이 아니라 출력 별칭이므로, 결측은 **repo가 별칭을 빠뜨렸다**는 뜻이고
여전히 projection 누락 버그다.

이 모듈은 재키 후 사실상 항등 치환이다(``feature_id``가 이미 정본 키다). 걷어내는
것은 8개 라우터 ~30개 호출부가 걸린 독립 정리 항목이라 T-VN-39 범위에 넣지 않았다 —
``docs/reports/t-vn-39-routine-open-defects.md`` "남은 것"에 기록돼 있다.
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
