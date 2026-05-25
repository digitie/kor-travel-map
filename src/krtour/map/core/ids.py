"""``krtour.map.core.ids`` — 결정적 ID 생성 함수 모음 (ADR-009).

같은 source 데이터가 여러 번 적재되거나 여러 provider가 같은 자연키로 올라올
때 ``feature``가 중복 생성되지 않도록, 모든 ID는 결정적(SHA1 기반)으로
생성한다. ``raw string concat`` 금지 — 모든 ID는 본 모듈을 통과해야 한다.

현재 제공:
- ``make_feature_id`` — Feature ID (ADR-009)

추후 추가 (별도 PR):
- ``make_source_record_key`` — source_record 자연키 (``sr_{sha1[:20]}``)
- ``make_payload_hash`` — canonical JSON → sha256 (``docs/data-model.md §11``)

ADR 참조
--------
- ADR-009 — ``feature_id`` 결정적 생성 (SPEC V8 D-2)
- ADR-022 — Import path는 ``from krtour.map.core import make_feature_id``

포맷
----
``f_{bjd_code or 'global'}_{kind[0]}_{sha1(input)[:16]}``

input 구성 (``|`` 구분, 마지막 ``content_hash``는 ``None`` 시 빈 문자열):

    {bjd_code or 'global'}|{kind}|{category}|{source_type}
    |{source_natural_key}|{content_hash or ''}

예시 (``docs/data-model.md §11``)
- ``bjd_code='1168010100'``, ``kind='place'``, ``category='PLACE_RESTAURANT'``,
  ``source_type='krex_rest_area'``, ``source_natural_key='RA00012'``
  → ``f_1168010100_p_a1b2c3d4e5f60718``
- ``bjd_code=None``, ``kind='event'``, ...
  → ``f_global_e_...``

설계 노트
---------
- ``kind`` 파라미터는 ``str``로 타입 annotation. dto의 ``FeatureKind``는
  ``StrEnum`` 서브클래스이므로 ``FeatureKind.PLACE``를 그대로 넘기면 자동으로
  ``str``로 동작한다. 본 모듈은 dto를 import하지 않는다 (ADR-001 의존 방향
  유지 — core가 dto에 의존하지만 본 함수만큼은 dto 없이도 동작 가능하도록
  의도적으로 약결합).
- ``bjd_code``가 변경되면 (행정구역 개편) ``feature_id``도 바뀐다 — 이는 의도된
  동작. 옛 feature는 soft-delete + 새 feature 생성.
- ``content_hash``가 다르면 다른 feature로 취급 (옵션 — 기본 ``None``).
"""

from __future__ import annotations

import hashlib
from typing import Final

__all__ = ["make_feature_id", "FEATURE_ID_HASH_LENGTH"]


FEATURE_ID_HASH_LENGTH: Final[int] = 16
"""SHA1 hex digest의 prefix 길이 (16 hex chars = 64 bits). 충돌 확률은
2^64에서 1로 충분히 안전 (Feature 수가 10^9에 도달해도 충돌 확률 ~3e-11)."""

_BJD_FALLBACK: Final[str] = "global"
"""``bjd_code``가 미상일 때 사용하는 placeholder. 행정구역 외 (해상/공해 등)
또는 매핑 실패 시."""


def make_feature_id(
    *,
    bjd_code: str | None,
    kind: str,
    category: str,
    source_type: str,
    source_natural_key: str,
    content_hash: str | None = None,
) -> str:
    """결정적으로 ``feature_id``를 계산한다 (ADR-009 SPEC V8 D-2).

    Parameters
    ----------
    bjd_code
        법정동 코드 (10자리). 미상 시 ``None`` → ``'global'``로 대체.
    kind
        ``FeatureKind.value`` 또는 동등 문자열 (``'place'``/``'event'``/
        ``'notice'``/``'price'``/``'weather'``/``'route'``/``'area'``).
        prefix 1자만 ID에 박힘 (``'p'``/``'e'``/``'n'``/...).
    category
        카테고리 enum value (예: ``'PLACE_RESTAURANT'``,
        ``'WEATHER_TEMPERATURE'``, ``'EVENT_FESTIVAL'``).
    source_type
        provider 또는 dataset 타입 (예: ``'krex_rest_area'``,
        ``'kma_weather_ultra_short'``).
    source_natural_key
        source 시스템 내 자연키 (예: rest area code ``'RA00012'``).
    content_hash
        선택. payload 변경을 ID에 반영하고 싶을 때 사용 (기본 ``None``).
        ``None``이면 같은 자연키는 항상 같은 ID.

    Returns
    -------
    str
        ``f_{bjd_code or 'global'}_{kind[0]}_{sha1(input)[:16]}``.

    Raises
    ------
    ValueError
        ``kind``/``category``/``source_type``/``source_natural_key`` 중 하나라도
        빈 문자열이거나 ``|`` 구분자가 포함된 경우.

    Examples
    --------
    >>> make_feature_id(
    ...     bjd_code="1168010100",
    ...     kind="place",
    ...     category="PLACE_RESTAURANT",
    ...     source_type="krex_rest_area",
    ...     source_natural_key="RA00012",
    ... )
    'f_1168010100_p_3c0c2820e96d28d3'

    >>> # 같은 입력 → 같은 ID (idempotent)
    >>> a = make_feature_id(bjd_code=None, kind="event", category="EVENT_FESTIVAL",
    ...                     source_type="tour_api", source_natural_key="EVT001")
    >>> b = make_feature_id(bjd_code=None, kind="event", category="EVENT_FESTIVAL",
    ...                     source_type="tour_api", source_natural_key="EVT001")
    >>> a == b
    True
    >>> a.startswith("f_global_e_")
    True
    """
    _validate_component("kind", kind)
    _validate_component("category", category)
    _validate_component("source_type", source_type)
    _validate_component("source_natural_key", source_natural_key)

    bjd_part = bjd_code if bjd_code else _BJD_FALLBACK
    kind_str = str(kind)  # FeatureKind StrEnum도 그대로 처리
    kind_prefix = kind_str[0]

    raw = (
        f"{bjd_part}|{kind_str}|{category}|{source_type}|{source_natural_key}|"
        f"{content_hash or ''}"
    )
    digest = hashlib.sha1(raw.encode("utf-8"), usedforsecurity=False).hexdigest()
    return f"f_{bjd_part}_{kind_prefix}_{digest[:FEATURE_ID_HASH_LENGTH]}"


def _validate_component(name: str, value: str) -> None:
    """단일 구성요소 검증. 빈 값 또는 ``|`` 포함은 ID 충돌 위험."""
    if not value:
        raise ValueError(f"{name!r}은 비어 있을 수 없음 (ADR-009).")
    if "|" in str(value):
        raise ValueError(
            f"{name!r}에 '|' 문자가 포함됨 — 구분자 충돌로 결정성 깨짐 (ADR-009). "
            f"value={value!r}"
        )
