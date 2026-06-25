"""``PriceValue`` — provider별 가격 시계열 값.

유가/식음료/통행료/입장료 등 시계열 price를 정규화. `feature.feature_price_
values` 테이블 row와 1:1. `feature_id`는 가격 표시용 `kind=price` anchor
feature를 가리킨다. `WeatherValue`와 동일 패턴이나 시간축 단순화
(forecast 없음 — 관측만).

고유성(`identity()`): (`feature_id`, `provider`, `price_domain`, `product_key`,
`observed_at`). product_key는 metric_key와 유사 — 'gasoline'/'diesel'/'lpg'
같은 product code.

ADR 참조
--------
- ADR-013 — bulk insert 30k 안전 마진 (opinet 가격은 시간 단위, BRIN 적재)
- ADR-014 — `BRIN(observed_at)` 시계열 인덱스
- ADR-018 — DTO ``extra="forbid"`` 강제
- ADR-019 — datetime aware (KST, ``Asia/Seoul``)
- ADR-024 — canonical provider name
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from ._enums import PriceDomain
from ._time import check_aware_datetime, kst_now

__all__ = ["PriceValue"]


class PriceValue(BaseModel):
    """provider별 가격 측정 한 건 — ``feature.feature_price_values`` row.

    예시:
        >>> from datetime import datetime, timezone, timedelta
        >>> KST = timezone(timedelta(hours=9))
        >>> p = PriceValue(
        ...     feature_id="f_1156010100_p_abc",
        ...     provider="python-opinet-api",
        ...     price_domain="opinet_gas_station",
        ...     product_key="gasoline",
        ...     product_name="휘발유",
        ...     value_number=Decimal("1820.0"),
        ...     unit="KRW/L",
        ...     observed_at=datetime(2026, 5, 28, 3, 0, tzinfo=KST),
        ... )
        >>> p.value_number
        Decimal('1820.0')
    """

    model_config = ConfigDict(extra="forbid")

    # ── 1) FK / 식별 ──────────────────────────────────────────────────────

    feature_id: str = Field(
        min_length=1,
        description="`make_feature_id(...)` 결과. price kind anchor feature를 참조.",
    )
    provider: str = Field(
        min_length=1,
        description=(
            "canonical provider name (ADR-024, 예: 'python-opinet-api', "
            "'python-krex-api')."
        ),
    )

    # ── 2) 가격 dataset 식별자 + product ─────────────────────────────────

    price_domain: PriceDomain = Field(
        description="provider별 가격 dataset 식별자.",
    )
    product_key: str = Field(
        min_length=1,
        description=(
            "표준 product code (예: 'gasoline'/'diesel'/'lpg'/'premium_gasoline'). "
            "WeatherValue의 metric_key와 같은 역할."
        ),
    )
    product_name: str | None = Field(
        default=None,
        description="표준 한글 이름 (예: '휘발유', '경유', 'LPG').",
    )
    source_product_key: str | None = Field(
        default=None,
        description="provider 원천 product code (예: opinet 'B027').",
    )
    source_product_name: str | None = Field(
        default=None,
        description="provider 원천 product 한글/영문 이름.",
    )

    # ── 3) 시간축 ─────────────────────────────────────────────────────────

    observed_at: datetime = Field(
        description="관측 시각 (aware datetime, KST aware).",
    )

    # ── 4) 값 ─────────────────────────────────────────────────────────────

    value_number: Decimal = Field(
        description="가격 값. `NUMERIC(14,4)` DDL과 정합.",
    )
    unit: str = Field(
        default="KRW",
        description="단위 (`KRW`/`KRW/L`/`KRW/회` 등). 기본 'KRW'.",
    )

    # ── 5) 메타 / 추적 ────────────────────────────────────────────────────

    normalization_version: str | None = Field(
        default=None,
        description="정규화 규약 버전 (예: 'opinet-v1.0').",
    )
    payload: dict[str, Any] = Field(
        default_factory=dict,
        description="provider raw payload (JSONB, canonical 직렬화 가능).",
    )
    collected_at: datetime = Field(
        default_factory=kst_now,
        description="본 라이브러리 적재 시각 (aware datetime).",
    )
    source_record_key: str | None = Field(
        default=None,
        description=(
            "`make_source_record_key(...)` 결과. provider raw → PriceValue 변환 "
            "시 SourceRecord에 연결. 운영상 권장."
        ),
    )

    # ── validators ────────────────────────────────────────────────────────

    @field_validator("observed_at", "collected_at")
    @classmethod
    def _check_aware(cls, value: datetime) -> datetime:
        """ADR-019 — naive datetime 입력은 ValidationError."""
        result = check_aware_datetime(value)
        assert result is not None
        return result

    @model_validator(mode="after")
    def _check_value_nonnegative(self) -> PriceValue:
        """가격은 0 이상. 음수 값은 데이터 오류."""
        if self.value_number < 0:
            raise ValueError(
                f"value_number는 0 이상이어야 함 (가격), got {self.value_number}."
            )
        return self

    # ── 편의 ──────────────────────────────────────────────────────────────

    def identity(self) -> tuple[str, str, str, str, datetime]:
        """unique key tuple — `feature_price_values` UNIQUE 제약과 정합."""
        return (
            self.feature_id,
            self.provider,
            self.price_domain.value,
            self.product_key,
            self.observed_at,
        )
