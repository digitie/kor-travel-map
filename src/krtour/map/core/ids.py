"""``krtour.map.core.ids`` — 결정적 ID 생성 함수 모음 (ADR-009).

같은 source 데이터가 여러 번 적재되거나 여러 provider가 같은 자연키로 올라올
때 ``feature``가 중복 생성되지 않도록, 모든 ID는 결정적(SHA1/SHA256 기반)으로
생성한다. ``raw string concat`` 금지 — 모든 ID는 본 모듈을 통과해야 한다.

제공 함수:
- ``make_feature_id`` — Feature ID (ADR-009, ``f_{bjd}_{kind[0]}_{sha1[:16]}``)
- ``make_source_record_key`` — source_record 자연키 (``sr_{sha1[:20]}``)
- ``make_payload_hash`` — canonical JSON → SHA256 hexdigest prefix
  (``docs/data-model.md §11``)

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
import json
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Final

__all__ = [
    "make_feature_id",
    "make_source_record_key",
    "make_payload_hash",
    "FEATURE_ID_HASH_LENGTH",
    "SOURCE_RECORD_KEY_HASH_LENGTH",
    "PAYLOAD_HASH_DEFAULT_LENGTH",
]


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


SOURCE_RECORD_KEY_HASH_LENGTH: Final[int] = 20
"""``source_record_key``의 SHA1 hex digest prefix 길이 (20 hex chars = 80 bits).
``feature_id``(16)보다 길게 잡는 이유: source_record는 raw payload 단위로
훨씬 다양 (한 feature당 여러 source).
"""


def make_source_record_key(
    *,
    provider: str,
    dataset_key: str,
    source_entity_type: str,
    source_entity_id: str,
    raw_payload_hash: str,
) -> str:
    """``source_records`` PK인 ``source_record_key``를 결정적으로 계산.

    ``docs/data-model.md §11`` 명세: ``sr_{sha1(input)[:20]}``.

    Parameters
    ----------
    provider
        canonical provider name (예: ``"python-visitkorea-api"``).
    dataset_key
        provider 내 dataset 식별자 (예: ``"festival"``).
    source_entity_type
        provider 내 entity type (예: ``"festival_record"``).
    source_entity_id
        provider 원천 entity id (예: ``"E001234"``).
    raw_payload_hash
        ``make_payload_hash``의 결과. 같은 entity_id라도 payload 변경 시 새
        source_record (이력 보존).

    Returns
    -------
    str
        ``sr_{sha1(input)[:20]}``.

    Raises
    ------
    ValueError
        구성요소 중 빈 문자열 또는 ``|`` 구분자 포함.

    Examples
    --------
    >>> make_source_record_key(
    ...     provider="python-visitkorea-api",
    ...     dataset_key="festival",
    ...     source_entity_type="festival_record",
    ...     source_entity_id="E001234",
    ...     raw_payload_hash="abc123def456",
    ... )  # doctest: +SKIP
    'sr_<20 hex chars>'

    Notes
    -----
    같은 입력 → 같은 key. 다른 PR (예: source_repo)에서 upsert 시 idempotent.
    """
    _validate_component("provider", provider)
    _validate_component("dataset_key", dataset_key)
    _validate_component("source_entity_type", source_entity_type)
    _validate_component("source_entity_id", source_entity_id)
    _validate_component("raw_payload_hash", raw_payload_hash)

    raw = (
        f"{provider}|{dataset_key}|{source_entity_type}|"
        f"{source_entity_id}|{raw_payload_hash}"
    )
    digest = hashlib.sha1(raw.encode("utf-8"), usedforsecurity=False).hexdigest()
    return f"sr_{digest[:SOURCE_RECORD_KEY_HASH_LENGTH]}"


PAYLOAD_HASH_DEFAULT_LENGTH: Final[int] = 32
"""``make_payload_hash``의 default prefix 길이 (32 hex chars = 128 bits).
충돌 확률은 2^128에서 1로 영구 안전. 길이는 호출자가 줄여서 사용 가능
(예: 16 chars로 줄여도 64 bits — feature_id와 동등)."""


def make_payload_hash(data: Any, *, length: int = PAYLOAD_HASH_DEFAULT_LENGTH) -> str:
    """canonical JSON 직렬화 결과의 SHA256 hex digest prefix.

    같은 raw payload (provider 응답)는 항상 같은 hash → ``source_records``의
    중복 적재 차단 + payload 변경 시 새 row (이력 보존).

    Parameters
    ----------
    data
        JSON 직렬화 가능한 객체 (``dict`` / ``list`` / ``str`` / ``int`` 등).
        ``datetime``/``date``/``Decimal``은 canonical JSON 값으로 정규화한다.
        Pydantic 모델 등은 호출자가 ``.model_dump()``로 변환해 전달.
    length
        반환 hex digest의 prefix 길이. 기본 32 (128 bits). 1~64 hex chars.

    Returns
    -------
    str
        SHA256 hex digest의 앞 ``length`` 문자.

    Raises
    ------
    ValueError
        ``length``가 1 미만 또는 64 초과.
    TypeError
        ``data``가 canonical JSON 값으로 정규화 불가.

    Examples
    --------
    >>> make_payload_hash({"a": 1, "b": 2}) == make_payload_hash({"b": 2, "a": 1})
    True
    >>> len(make_payload_hash({"a": 1}))
    32
    >>> len(make_payload_hash({"a": 1}, length=16))
    16

    Notes
    -----
    **Canonical 직렬화 규칙** (``json.dumps`` 옵션):

    - ``sort_keys=True`` — 키 순서 무관, 같은 dict는 같은 hash.
    - ``separators=(",", ":")`` — 공백 제거 (whitespace로 hash 깨짐 방지).
    - ``ensure_ascii=False`` — 한글 보존 (UTF-8 인코딩).
    - ``datetime``/``date``는 ISO 8601 문자열, ``Decimal``은 ``str()``로 변환.
    - ``set``/``bytes``/임의 객체는 거부한다. Pydantic 모델은 호출자가 사전에
      ``.model_dump(mode='json')``로 변환한다.

    이 규칙은 ``docs/data-model.md §11``과 일치. 변경 시 기존 source_records의
    hash 전부 재계산 필요 → **변경 금지** (영구 약속).
    """
    if not 1 <= length <= 64:
        raise ValueError(
            f"length는 1~64 범위여야 함 (SHA256 hexdigest 길이), got {length}."
        )
    normalized = _normalize_payload_value(data)
    canonical = json.dumps(
        normalized,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )
    digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    return digest[:length]


def _normalize_payload_value(value: Any) -> Any:
    """Hash 입력을 JSONB에 보존 가능한 canonical JSON 값으로 제한한다."""
    if value is None or isinstance(value, str | int | float | bool):
        return value
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, dict):
        normalized: dict[str, Any] = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise TypeError(
                    "payload dict key는 str이어야 함 "
                    f"(got {type(key).__name__}: {key!r})."
                )
            normalized[key] = _normalize_payload_value(item)
        return normalized
    if isinstance(value, list | tuple):
        return [_normalize_payload_value(item) for item in value]
    raise TypeError(
        "payload 값은 JSON primitive/list/dict 또는 datetime/date/Decimal만 "
        f"허용됨 (got {type(value).__name__}: {value!r})."
    )
