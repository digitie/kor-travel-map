"""``WeatherValue`` — provider별 날씨 raw 측정/예보 값 (ADR-010).

`docs/etl/weather-feature-normalization.md §4` 명세.

`forecast_style`(원천값 성격) + `timeline_bucket`(KMA식 조회 축) 두 축이
직교. `timeline_bucket`은 분류 결과라 unique key 제외 — `identity()` 메서드
참고.

ADR 참조
--------
- ADR-010 — `forecast_style` vs `timeline_bucket` 두 축 분리
- ADR-018 — DTO ``extra="forbid"`` 강제
- ADR-019 — datetime aware (KST, ``Asia/Seoul``)
- ADR-024 — canonical provider name
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from ._enums import ForecastStyle, TimelineBucket, WeatherDomain
from ._time import check_aware_datetime, kst_now

__all__ = ["WeatherValue"]


class WeatherValue(BaseModel):
    """provider별 측정/예보 값 한 건 — `feature.feature_weather_values` row.

    고유성(`identity()`): (`feature_id`, `provider`, `weather_domain`,
    `forecast_style`, `metric_key`, `issued_at`, `valid_at`, `observed_at`).
    `timeline_bucket`은 제외 — 분류 결과.

    예시:
        >>> from datetime import datetime, timezone, timedelta
        >>> KST = timezone(timedelta(hours=9))
        >>> v = WeatherValue(
        ...     feature_id="f_global_w_abc",
        ...     provider="python-kma-api",
        ...     weather_domain="kma_short_forecast",
        ...     forecast_style="short",
        ...     timeline_bucket="short",
        ...     metric_key="TMP",
        ...     metric_name="기온",
        ...     value_number=Decimal("23.5"),
        ...     unit="deg_c",
        ...     issued_at=datetime(2026, 5, 27, 23, 0, tzinfo=KST),
        ...     valid_at=datetime(2026, 5, 28, 9, 0, tzinfo=KST),
        ... )
    """

    model_config = ConfigDict(extra="forbid")

    # ── 1) FK / 식별 ──────────────────────────────────────────────────────

    feature_id: str = Field(
        min_length=1,
        description="`make_feature_id(...)` 결과. weather kind feature를 참조.",
    )
    provider: str = Field(
        min_length=1,
        description=(
            "canonical provider name (ADR-024, 예: 'python-kma-api', "
            "'python-airkorea-api'). `normalize_provider_name` 결과."
        ),
    )

    # ── 2) ADR-010 두 축 + metric ─────────────────────────────────────────

    weather_domain: WeatherDomain = Field(
        description="provider별 dataset 식별자 (`docs/etl/weather-feature-normalization.md §3`).",
    )
    forecast_style: ForecastStyle = Field(
        description="원천값 성격 — nowcast/ultra_short/short/mid/observed/index/advisory.",
    )
    timeline_bucket: TimelineBucket | None = Field(
        default=None,
        description=(
            "조회 축 — ultra_short/short/mid. `None` 허용 (지수/특보 등 시간축 "
            "모호한 경우). **unique key에 포함되지 않음** (ADR-010)."
        ),
    )

    metric_key: str = Field(
        min_length=1,
        description=(
            "표준 metric_key (T1H/TMP/REH/WSD/VEC/RN1/PTY/SKY/POP/PCP/SNO/WAV/"
            "TMN/TMX/FIRE_RISK/PM10/PM2_5/CAI/WATER_TEMP 등). "
            "`docs/etl/weather-feature-normalization.md §2` 표."
        ),
    )

    # ── 3) 시간축 ─────────────────────────────────────────────────────────

    issued_at: datetime | None = Field(
        default=None,
        description="예보 발표 시각 (aware datetime, KST).",
    )
    valid_at: datetime | None = Field(
        default=None,
        description="예보 유효 시점 (단일 시각, aware).",
    )
    valid_from: datetime | None = Field(
        default=None,
        description="예보 유효 시작 (구간형, aware).",
    )
    valid_until: datetime | None = Field(
        default=None,
        description="예보 유효 종료 (구간형, aware).",
    )
    observed_at: datetime | None = Field(
        default=None,
        description="관측 시각 (aware datetime, KST).",
    )

    # ── 4) provider 원문 보존 ─────────────────────────────────────────────

    source_metric_key: str | None = Field(
        default=None,
        description="provider 원천 metric key (예: KMA의 'T1H'를 그대로 유지).",
    )
    source_metric_name: str | None = Field(
        default=None,
        description="provider 원천 metric 한글/영문 이름.",
    )
    metric_name: str | None = Field(
        default=None,
        description="표준 한글 이름 (예: '현재 기온', '강수확률').",
    )

    # ── 5) 값 ─────────────────────────────────────────────────────────────

    value_number: Decimal | None = Field(
        default=None,
        description="숫자 값. `NUMERIC(14,4)` DDL과 정합.",
    )
    value_text: str | None = Field(
        default=None,
        description="텍스트 값 (예: '맑음', 'PM10 등급=좋음').",
    )
    unit: str | None = Field(
        default=None,
        description="단위 (`deg_c`/`%`/`m/s`/`mm`/`cm`/`code`/`score`/`ppm`/`μg/m³` 등).",
    )
    severity: str | None = Field(
        default=None,
        description="특보/지수 등급 (예: '주의보', '경보', '관심', '심각').",
    )

    # ── 6) 메타 / 추적 ────────────────────────────────────────────────────

    normalization_version: str | None = Field(
        default=None,
        description="정규화 규약 버전 (예: 'kma-v1.4', 'airkorea-v2.0').",
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
            "`make_source_record_key(...)` 결과. provider raw → WeatherValue "
            "변환 시 소속 SourceRecord에 연결. 누락 시 트레이싱 불가하므로 "
            "운영상 권장."
        ),
    )

    # ── validators ────────────────────────────────────────────────────────

    @field_validator(
        "issued_at",
        "valid_at",
        "valid_from",
        "valid_until",
        "observed_at",
        "collected_at",
    )
    @classmethod
    def _check_aware(cls, value: datetime | None) -> datetime | None:
        """ADR-019 — naive datetime 입력은 ValidationError."""
        return check_aware_datetime(value)

    @model_validator(mode="after")
    def _check_value_present(self) -> WeatherValue:
        """`value_number` 또는 `value_text` 중 하나는 반드시."""
        if self.value_number is None and self.value_text is None:
            raise ValueError(
                "WeatherValue는 value_number 또는 value_text 중 최소 하나는 "
                f"있어야 함 (metric_key={self.metric_key!r})."
            )
        return self

    @model_validator(mode="after")
    def _check_valid_range_order(self) -> WeatherValue:
        """`valid_from`/`valid_until` 둘 다 있으면 from <= until."""
        if (
            self.valid_from is not None
            and self.valid_until is not None
            and self.valid_until < self.valid_from
        ):
            raise ValueError(
                f"valid_until ({self.valid_until}) >= valid_from "
                f"({self.valid_from})이어야 함."
            )
        return self

    # ── 편의 ──────────────────────────────────────────────────────────────

    def identity(
        self,
    ) -> tuple[
        str,
        str,
        str,
        str,
        str,
        datetime | None,
        datetime | None,
        datetime | None,
    ]:
        """unique key tuple — `feature_weather_values` UNIQUE 제약과 정합.

        `timeline_bucket`은 제외 (ADR-010 분류 결과 — 재계산 가능).
        """
        return (
            self.feature_id,
            self.provider,
            self.weather_domain.value,
            self.forecast_style.value,
            self.metric_key,
            self.issued_at,
            self.valid_at,
            self.observed_at,
        )
