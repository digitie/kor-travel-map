"""``kortravelmap.core.ids`` — 결정적 ID 생성 함수 모음 (ADR-009).

같은 source 데이터가 여러 번 적재되거나 여러 provider가 같은 자연키로 올라올
때 ``feature``가 중복 생성되지 않도록, 모든 ID는 결정적(SHA1/SHA256 기반)으로
생성한다. ``raw string concat`` 금지 — 모든 ID는 본 모듈을 통과해야 한다.

제공 함수:
- ``make_feature_id`` — Feature ID (ADR-009, ``f_{bjd}_{kind[0]}_{sha1[:16]}``)
- ``make_source_record_key`` — source_record 자연키 (``sr_{sha1[:20]}``)
- ``make_integrity_finding_key`` — 주소 검증 finding 안정키
  (``av2_{sha256}``)
- ``make_payload_hash`` — canonical JSON → SHA256 hexdigest prefix
  (``docs/architecture/data-model.md §11``)

ADR 참조
--------
- ADR-009 — ``feature_id`` 결정적 생성 (SPEC V8 D-2)
- ADR-022 — Import path는 ``from kortravelmap.core import make_feature_id``

포맷
----
``f_{bjd_code or 'global'}_{kind[0]}_{sha1(input)[:16]}``

input 구성 (``|`` 구분, 마지막 ``content_hash``는 ``None`` 시 빈 문자열):

    {bjd_code or 'global'}|{kind}|{category}|{source_type}
    |{source_natural_key}|{content_hash or ''}

예시 (``docs/architecture/data-model.md §11``)
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
import os
import time
import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Final

__all__ = [
    "make_feature_id",
    "make_feature_uuid",
    "make_source_record_key",
    "make_integrity_finding_key",
    "make_payload_hash",
    "make_weather_value_key",
    "make_price_value_key",
    "feature_uuid_from_legacy",
    "FEATURE_ID_HASH_LENGTH",
    "FEATURE_UUID_NAMESPACE",
    "SOURCE_RECORD_KEY_HASH_LENGTH",
    "INTEGRITY_FINDING_KEY_HASH_LENGTH",
    "PAYLOAD_HASH_DEFAULT_LENGTH",
    "WEATHER_VALUE_KEY_HASH_LENGTH",
    "PRICE_VALUE_KEY_HASH_LENGTH",
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


# ── feature_uuid_from_legacy (T-VN-32A, ADR-068) ───────────────────────────


FEATURE_UUID_NAMESPACE: Final[uuid.UUID] = uuid.uuid5(
    uuid.NAMESPACE_URL, "kor-travel-map:feature-uuid:v1"
)
"""legacy ``f_*`` feature_id → shadow ``feature_uuid`` 파생용 고정 namespace.

파생 근거: ``uuid5(NAMESPACE_URL, 'kor-travel-map:feature-uuid:v1')``
= ``75d60e13-2779-5b06-a920-6b1b892a7c84``. RFC 4122 표준 namespace에서
저장소 식별 문자열로 한 번 더 파생해 다른 시스템의 uuid5 공간과 충돌하지
않는다. **변경 금지** — 값이 바뀌면 backfill된 전 UUID가 갈라진다 (영구 약속,
alembic ``0080_feature_uuid_shadow``의 SQL mirror
``feature.feature_uuid_from_legacy``와 반드시 일치해야 한다).

버전 suffix ``:v1``은 파생 규칙 자체를 재정의해야 할 때(그럴 일이 없어야
한다) 새 namespace임을 명시적으로 드러내기 위한 것이다.
"""


def feature_uuid_from_legacy(feature_id: str) -> uuid.UUID:
    """legacy 문자열 ``feature_id`` → 결정적 shadow ``feature_uuid`` (ADR-068).

    같은 legacy id는 언제 어디서 계산해도 같은 UUID다 — 같은 snapshot에서
    재실행해도, 두 저장소(KTM/PinVi)가 독립 계산해도 동일하다 (T-VN-32C
    checksum 대조의 전제). 입력은 legacy id 문자열 **하나뿐**이며 bjd/category
    등 수정 가능한 속성은 어떤 것도 입력이 아니다 (ADR-068 결정 2의 정신).

    Parameters
    ----------
    feature_id
        legacy feature id (``make_feature_id`` 결과 또는 과거 임의 문자열 id).

    Returns
    -------
    uuid.UUID
        ``uuid5(FEATURE_UUID_NAMESPACE, feature_id)`` — RFC 4122 version 5.

    Raises
    ------
    ValueError
        ``feature_id``가 빈 문자열인 경우.

    Examples
    --------
    >>> str(feature_uuid_from_legacy("f_1168010100_p_3c0c2820e96d28d3"))
    '4232803d-a8a7-57c2-b80b-e13ca8fa1a2a'
    >>> feature_uuid_from_legacy("f_global_e_x") == feature_uuid_from_legacy("f_global_e_x")
    True

    Notes
    -----
    - DB mirror: alembic ``0079``가 만드는 IMMUTABLE SQL 함수
      ``feature.feature_uuid_from_legacy(text)`` (pgcrypto SHA-1 기반 수동
      uuid5 구성)와 결과가 동일하다. 통합 테스트가 고정 벡터로 양쪽을 대조한다.
    - 신규 행의 UUID generator는 본 함수가 **아니다** — T-VN-32C(alembic
      ``0083``)가 비파생 UUIDv7(:func:`make_feature_uuid`)로 결정했다. 본 함수는
      0080 backfill 세대(기존 731,600행)의 값 재현·검증 참조로 존속한다.
    """
    if not feature_id:
        raise ValueError("feature_id는 비어 있을 수 없음 (ADR-068 alias 파생).")
    return uuid.uuid5(FEATURE_UUID_NAMESPACE, feature_id)


def make_feature_uuid(*, _now_ms: int | None = None) -> uuid.UUID:
    """신규 feature의 **비파생** 정본 UUID를 생성한다 (RFC 9562 UUIDv7).

    T-VN-32C 값 전환(0083)부터 신규 행의 ``feature_uuid``는 legacy id 파생
    (:func:`feature_uuid_from_legacy`)이 아니라 본 함수 산출이다 — ADR-068
    결정 1("애플리케이션이 생성하는 UUID surrogate", UUIDv7 채택 시 생성기
    고정)의 그 생성기다.

    설계 고정:

    - **버전 v7**: 상위 48bit = Unix epoch milliseconds, 이후 version(7)·
      variant(0b10) 비트, 나머지 74bit 난수. 시간 정렬성은 **내부 인덱스
      지역성 용도로만** 쓰며 API 계약으로 노출하지 않는다(UUID는 opaque
      string — ADR-068 결정 3).
    - DB mirror: alembic ``0083``의 ``feature.uuid_generate_v7()``(raw SQL
      경로 fill 트리거용 안전망)과 같은 v7 레이아웃 — 통합 테스트가 version/
      variant 비트 동일성을 대조한다.
    - 기존 행의 파생 uuid는 영구 보존된다(0082 identity fence) — 본 함수는
      신규 행 전용이고 :func:`feature_uuid_from_legacy`는 backfill/검증
      참조용으로 존속한다.

    Parameters
    ----------
    _now_ms
        테스트 전용 밀리초 타임스탬프 주입 (기본: 현재 시각).
    """
    now_ms = int(time.time() * 1000) if _now_ms is None else _now_ms
    if now_ms < 0 or now_ms >= 1 << 48:
        raise ValueError("UUIDv7 timestamp가 48bit 범위를 벗어남")
    rand = int.from_bytes(os.urandom(10), "big")  # 80bit 난수 확보
    rand_a = (rand >> 68) & 0x0FFF  # 12bit
    rand_b = rand & ((1 << 62) - 1)  # 62bit
    value = (
        (now_ms << 80)
        | (0x7 << 76)  # version 7
        | (rand_a << 64)
        | (0b10 << 62)  # variant RFC 4122/9562
        | rand_b
    )
    return uuid.UUID(int=value)


SOURCE_RECORD_KEY_HASH_LENGTH: Final[int] = 20
"""``source_record_key``의 SHA1 hex digest prefix 길이 (20 hex chars = 80 bits).
``feature_id``(16)보다 길게 잡는 이유: source_record는 raw payload 단위로
훨씬 다양 (한 feature당 여러 source).
"""

INTEGRITY_FINDING_KEY_HASH_LENGTH: Final[int] = 64
"""주소 검증 finding key의 SHA256 hex 길이.

원천 entity id를 그대로 B-tree expression index에 싣지 않고 전체 digest를 사용한다.
입력 길이와 무관하게 ``av2_`` prefix를 포함한 key가 항상 68 bytes로 고정된다.
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

    ``docs/architecture/data-model.md §11`` 명세: ``sr_{sha1(input)[:20]}``.

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


def make_integrity_finding_key(
    *,
    provider: str,
    dataset_key: str,
    source_entity_type: str,
    source_entity_id: str,
    violation_type: str,
) -> str:
    """주소 검증 finding의 원천 정체성과 규칙을 고정 길이 key로 계산한다.

    동일 provider dataset 안에서도 서로 다른 entity type이 같은 id를 재사용할 수 있으므로
    ``source_entity_type``을 생략하지 않는다. ``source_record_key``는 payload hash에 따라
    바뀌므로 입력으로 쓰지 않는다.
    """
    components = {
        "provider": provider,
        "dataset_key": dataset_key,
        "source_entity_type": source_entity_type,
        "source_entity_id": source_entity_id,
        "violation_type": violation_type,
    }
    for name, value in components.items():
        _validate_component(name, value)
    raw = "|".join(components.values())
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()
    return f"av2_{digest}"


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

    이 규칙은 ``docs/architecture/data-model.md §11``과 일치. 변경 시 기존 source_records의
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


# ── make_weather_value_key (PR#38, ADR-010) ────────────────────────────────


WEATHER_VALUE_KEY_HASH_LENGTH: Final[int] = 20
"""SHA1 hex digest의 prefix 길이 (20 hex chars = 80 bits). source_record_key
와 동등 — weather 시계열 row 수가 수억 단위로 늘어도 충돌 안전."""


def make_weather_value_key(
    *,
    feature_id: str,
    provider_dataset_id: int,
    weather_domain: str,
    forecast_style: str,
    metric_key: str,
    target_at: datetime,
    source_record_key: str,
) -> str:
    """``WeatherValue.weather_value_key`` PK를 결정적으로 계산.

    ADR-089 immutable fact identity와 동일 input이다.

    Parameters
    ----------
    feature_id
        weather kind ``Feature``의 ID (`make_feature_id` 결과).
    provider_dataset_id
        canonical provider dataset surrogate key.
    weather_domain
        ``WeatherDomain.value`` 또는 동등 문자열 (예: ``"kma_short_forecast"``).
    forecast_style
        ``ForecastStyle.value`` (예: ``"short"``).
    metric_key
        표준 metric_key (예: ``"TMP"``, ``"PM10"``).
    target_at / source_record_key
        business-time와 immutable raw response revision.

    Returns
    -------
    str
        ``wv_{sha1[:20]}``.

    Raises
    ------
    ValueError
        구성요소 중 빈 문자열 또는 ``|`` 구분자 포함.

    Examples
    --------
    >>> from datetime import datetime, timezone, timedelta
    >>> KST = timezone(timedelta(hours=9))
    >>> key = make_weather_value_key(
    ...     feature_id="f_global_w_abc",
    ...     provider_dataset_id=42,
    ...     weather_domain="kma_short_forecast",
    ...     forecast_style="short",
    ...     metric_key="TMP",
    ...     target_at=datetime(2026, 5, 28, 9, 0, tzinfo=KST),
    ...     source_record_key="sr_example",
    ... )
    >>> key.startswith("wv_")
    True
    >>> len(key)
    23

    Notes
    -----
    같은 입력 → 같은 key다. correction은 다른 response record key를 가져 새 fact가 된다.
    """
    _validate_component("feature_id", feature_id)
    if provider_dataset_id <= 0:
        raise ValueError("provider_dataset_id must be positive")
    _validate_component("weather_domain", weather_domain)
    _validate_component("forecast_style", forecast_style)
    _validate_component("metric_key", metric_key)

    raw = (
        f"{feature_id}|{provider_dataset_id}|{weather_domain}|{forecast_style}|"
        f"{metric_key}|{target_at.isoformat()}|{source_record_key}"
    )
    digest = hashlib.sha1(raw.encode("utf-8"), usedforsecurity=False).hexdigest()
    return f"wv_{digest[:WEATHER_VALUE_KEY_HASH_LENGTH]}"


# ── make_price_value_key (PR#42) ──────────────────────────────────────────


PRICE_VALUE_KEY_HASH_LENGTH: Final[int] = 20
"""SHA1 hex digest의 prefix 길이 — weather_value_key와 동등."""


def make_price_value_key(
    *,
    feature_id: str,
    provider_dataset_id: int,
    price_domain: str,
    product_key: str,
    observed_at: datetime,
    source_record_key: str,
) -> str:
    """``PriceValue.price_value_key`` PK를 결정적으로 계산.

    immutable fact의 logical identity 전체를 입력으로 받는다. 시간 필드는
    ``observed_at`` 하나이며, correction은 새 ``source_record_key``로 append한다.

    Parameters
    ----------
    feature_id
        ``place`` kind ``Feature``의 ID (`make_feature_id` 결과).
    provider_dataset_id
        exact operation membership이 넘긴 canonical provider dataset 대리 키.
    price_domain
        ``PriceDomain.value`` 또는 동등 문자열 (예: ``"opinet_gas_station"``).
    product_key
        표준 product code (예: ``"gasoline"``).
    observed_at
        관측 시각 (aware datetime, KST). ISO 8601 직렬화 + tz 포함 hash.
    source_record_key
        이 fact를 만든 immutable provider response revision key.

    Returns
    -------
    str
        ``pv_{sha1[:20]}``.

    Raises
    ------
    ValueError
        구성요소 중 빈 문자열 또는 ``|`` 구분자 포함.

    Examples
    --------
    >>> from datetime import datetime, timezone, timedelta
    >>> KST = timezone(timedelta(hours=9))
    >>> key = make_price_value_key(
    ...     feature_id="f_1156010100_p_abc",
    ...     provider_dataset_id=42,
    ...     price_domain="opinet_gas_station",
    ...     product_key="gasoline",
    ...     observed_at=datetime(2026, 5, 28, 3, 0, tzinfo=KST),
    ...     source_record_key="sr_0123456789abcdef",
    ... )
    >>> key.startswith("pv_")
    True
    >>> len(key)
    23

    Notes
    -----
    같은 입력 → 같은 key (append idempotent). datetime은 ISO 8601 직렬화 +
    tz 포함 → 호출자는 aware datetime을 KST로 정규화해서 넘긴다 (ADR-019).
    """
    _validate_component("feature_id", feature_id)
    if provider_dataset_id <= 0:
        raise ValueError("provider_dataset_id must be positive")
    _validate_component("price_domain", price_domain)
    _validate_component("product_key", product_key)
    _validate_component("source_record_key", source_record_key)

    raw = (
        f"{feature_id}|{provider_dataset_id}|{price_domain}|{product_key}|"
        f"{observed_at.isoformat()}|{source_record_key}"
    )
    digest = hashlib.sha1(raw.encode("utf-8"), usedforsecurity=False).hexdigest()
    return f"pv_{digest[:PRICE_VALUE_KEY_HASH_LENGTH]}"
