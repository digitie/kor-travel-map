"""``krtour.map.providers.opinet`` — OpiNet 유가 → ``PriceValue``.

본 모듈은 `python-opinet-api` provider 라이브러리의 typed model을 본 라이브러리
``PriceValue`` DTO로 정규화한다. 주유소 자체(`Feature`)는 별도 PR 예정 —
본 PR(#42)은 **시계열 가격 변환만**.

OpiNet은 한국석유공사 운영. 주유소 ID(uni_id) + 제품코드(prodcd) + 관측시각이
unique. 본 lib는 `feature_id`를 호출자가 미리 결정한 후 전달받는다 (격자→
feature 매핑 같은 책임은 본 모듈 X).

OpiNet product code(KMA `category` 위치):

| OpiNet `prodcd` | 본 lib `product_key` | 한글 |
|----------------|---------------------|------|
| `B027` | `gasoline` | 휘발유 |
| `D047` | `diesel` | 경유 |
| `B034` | `premium_gasoline` | 고급휘발유 |
| `K015` | `kerosene` | 등유 |
| `C004` | `lpg` | LPG |

ADR 참조
--------
- ADR-006 — provider wrapper 금지
- ADR-009 — `make_price_value_key`
- ADR-013/014 — bulk insert + BRIN(observed_at) 시계열
- ADR-019 — datetime aware
- ADR-024 — canonical provider name `python-opinet-api`
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime
from decimal import Decimal
from typing import Any, Final, Protocol, runtime_checkable

from krtour.map.core.providers import normalize_provider_name
from krtour.map.dto import PriceDomain, PriceValue

__all__ = [
    "OpinetPriceItem",
    "prices_to_values",
    # 메타
    "OPINET_PROVIDER_NAME",
    "OPINET_PRODUCT_KEY_MAP",
    "OPINET_PRODUCT_NAME_KO",
]


# -- 상수 -----------------------------------------------------------------

OPINET_PROVIDER_NAME: Final[str] = "python-opinet-api"
"""canonical provider name (ADR-024)."""


# OpiNet 원천 product code → 본 lib 표준 product_key 매핑.
OPINET_PRODUCT_KEY_MAP: Final[dict[str, str]] = {
    "B027": "gasoline",
    "D047": "diesel",
    "B034": "premium_gasoline",
    "K015": "kerosene",
    "C004": "lpg",
}

# 표준 product_key → 한글 이름.
OPINET_PRODUCT_NAME_KO: Final[dict[str, str]] = {
    "gasoline": "휘발유",
    "diesel": "경유",
    "premium_gasoline": "고급휘발유",
    "kerosene": "등유",
    "lpg": "LPG",
}


# -- 입력 Protocol --------------------------------------------------------


@runtime_checkable
class OpinetPriceItem(Protocol):
    """OpiNet 주유소 가격 시계열 row 1건의 입력 shape.

    `python-opinet-api`의 typed model이 본 Protocol을 만족해야 한다. OpiNet
    원천 컬럼명을 영문 snake_case로 정규화된 형태 가정.
    """

    uni_id: str
    """OpiNet 주유소 자연키 (provider 내 unique). source_entity_id로 매핑."""

    prodcd: str
    """제품 코드 (B027/D047/B034/K015/C004). source_product_key로 보존."""

    price: str | Decimal | int | float
    """판매가 (KRW/L). 원천 string일 수도 있으나 numeric 변환 후 적재."""

    trade_dt: datetime
    """관측 시각 (KST aware). observed_at에 매핑."""


# -- 헬퍼 ---------------------------------------------------------------


def _parse_price_value(raw: str | Decimal | int | float) -> Decimal:
    """가격을 `Decimal`로 변환. ``"1,820"`` (천 단위 구분자) 흡수."""
    if isinstance(raw, Decimal):
        return raw
    if isinstance(raw, int | float):
        return Decimal(str(raw))
    # str — 천 단위 구분자 / 공백 흡수.
    cleaned = str(raw).replace(",", "").strip()
    return Decimal(cleaned)


# -- 단일 row → PriceValue -----------------------------------------------


def _item_to_price_value(
    item: OpinetPriceItem,
    *,
    feature_id: str,
    source_record_key: str | None,
) -> PriceValue:
    """OpiNet 가격 row 한 건 → ``PriceValue``."""
    product_key = OPINET_PRODUCT_KEY_MAP.get(item.prodcd, item.prodcd.lower())
    product_name = OPINET_PRODUCT_NAME_KO.get(product_key)
    value = _parse_price_value(item.price)

    payload: dict[str, Any] = {
        "uni_id": item.uni_id,
        "prodcd": item.prodcd,
        "price": str(item.price),
        "trade_dt": item.trade_dt.isoformat(),
    }

    return PriceValue(
        feature_id=feature_id,
        provider=normalize_provider_name(OPINET_PROVIDER_NAME),
        price_domain=PriceDomain.OPINET_GAS_STATION,
        product_key=product_key,
        product_name=product_name,
        source_product_key=item.prodcd,
        observed_at=item.trade_dt,
        value_number=value,
        unit="KRW/L",
        normalization_version="opinet-v1.0",
        payload=payload,
        source_record_key=source_record_key,
    )


# -- 공개 API -----------------------------------------------------------


def prices_to_values(
    items: Iterable[OpinetPriceItem],
    *,
    feature_id: str,
    source_record_key: str | None = None,
) -> list[PriceValue]:
    """OpiNet 가격 items → ``list[PriceValue]``.

    Parameters
    ----------
    items
        `python-opinet-api`의 가격 시계열 typed model iterable. 본 Protocol을
        만족해야 한다.
    feature_id
        주유소 ``Feature``의 ID (`make_feature_id` 결과, kind=place). 호출자가
        OpiNet uni_id → feature_id 매핑을 사전 결정해서 명시 전달.
    source_record_key
        provider raw payload 추적용. 운영상 권장 — 누락 시 trace 불가.

    Returns
    -------
    list[PriceValue]
        입력 순서 유지. `price_domain=opinet_gas_station`,
        `unit="KRW/L"`, `observed_at=trade_dt`.

    Raises
    ------
    pydantic.ValidationError
        observed_at naive 또는 value_number 음수 (ADR-019 / PriceValue
        validator).

    Examples
    --------
    호출자 측 사용 예시 (TripMate Dagster asset):

    >>> # client = AsyncOpiNetClient(...)
    >>> # async for page in client.aiter_prices(area="11", ...):
    >>> #     values = prices_to_values(
    >>> #         page.items,
    >>> #         feature_id=station_feature_id,
    >>> #         source_record_key=sr_key,
    >>> #     )
    >>> #     await krtour_client.load_price_values(values)

    Notes
    -----
    - OpiNet uni_id → feature_id 매핑은 별도 catalog (`OpinetStationCatalog`
      등) 책임. 본 함수는 매핑 X.
    - 가격 시계열은 시간 단위로 들어옴 — BRIN(observed_at) 인덱스 적재 권장
      (ADR-014). 호출자가 bulk insert 시 안전 마진 30k (ADR-013).
    - PR#43+: gas station feature (`stations_to_bundles`) — `Feature(kind=
      place, category="06020000" TRANSPORT_FUEL)` + SourceRecord + SourceLink.
    """
    return [
        _item_to_price_value(
            item,
            feature_id=feature_id,
            source_record_key=source_record_key,
        )
        for item in items
    ]
