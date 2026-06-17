"""``Coordinate`` — WGS84 좌표 + 한국 경계 검증.

ADR 참조
--------
- ADR-012 — 공간 쿼리 입력 좌표 1회 변환, 반경은 ``coord_5179`` (meter)
- SKILL.md DO NOT #5 — 외부 인터페이스는 모두 ``(lon, lat)`` 순서
"""

from __future__ import annotations

from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field, model_validator

__all__ = ["Coordinate"]

# 한국 본토 + 제주 + 부속 도서 (대마도 제외).
# `docs/architecture/feature-model.md §4.1 검증 룰` + v1 spec 정합.
_KOREA_LON_MIN: float = 124.0
_KOREA_LON_MAX: float = 132.0
_KOREA_LAT_MIN: float = 33.0
_KOREA_LAT_MAX: float = 39.5


class Coordinate(BaseModel):
    """WGS84 좌표 (lon, lat).

    저장/API 직렬화는 ``(lon, lat)`` 순서 (SKILL.md DO NOT #5). 본 모델은
    field alias 없이 명시 키 ``lon``/``lat`` 사용. 한국 경계 내인지 자동
    검증 — 범위를 벗어나면 ``ValidationError``.

    예시:
        >>> Coordinate(lon=127.0, lat=37.5)
        Coordinate(lon=Decimal('127.0'), lat=Decimal('37.5'))
        >>> Coordinate(lon=200.0, lat=37.5)  # 한국 경계 밖
        Traceback (most recent call last):
        ...
        pydantic_core._pydantic_core.ValidationError: ...
    """

    model_config = ConfigDict(frozen=True)

    lon: Decimal = Field(description="경도 (longitude, WGS84). 한국 본토 범위 [124.0, 132.0].")
    lat: Decimal = Field(description="위도 (latitude, WGS84). 한국 본토 범위 [33.0, 39.5].")

    @model_validator(mode="after")
    def _check_korea_bounds(self) -> Coordinate:
        lon_f = float(self.lon)
        lat_f = float(self.lat)
        if not (_KOREA_LON_MIN <= lon_f <= _KOREA_LON_MAX):
            raise ValueError(
                f"lon {lon_f} 한국 경계 밖 (허용 범위 [{_KOREA_LON_MIN}, {_KOREA_LON_MAX}])."
            )
        if not (_KOREA_LAT_MIN <= lat_f <= _KOREA_LAT_MAX):
            raise ValueError(
                f"lat {lat_f} 한국 경계 밖 (허용 범위 [{_KOREA_LAT_MIN}, {_KOREA_LAT_MAX}])."
            )
        return self
