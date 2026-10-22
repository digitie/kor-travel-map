"""``kortravelmap.dto.transport_state`` — Valkey에 담는 transport 현재 상태의 값 모델 (ADR-114).

Map Dagster의 ``transport_state_*`` job이 이 모델의 JSON을 Valkey 세대 키에 쓰고, Map API의
``/v1/service/transport/*``가 같은 모델로 읽어 그대로 응답한다. 값의 모양은 여기 한 곳이 정본이다
(ADR-114 "구현 설계 — 1단계" D2). 모양을 바꾸면 Valkey 키 접두사의 스키마 버전
(``infra.valkey_state.STATE_KEY_PREFIX``)도 함께 올린다 — 옛 세대 값을 새 모델로 읽지 않는다.

- ``feature_id``는 ``core.make_feature_id``(``bjd_code=None``)로 만든 legacy 형식 문자열이다
  (ADR-114 D1). PG feature의 UUID와 다른 네임스페이스다.
- 시각은 timezone이 있는 값만 받는다(ADR-019). 원천이 준 timezone을 그대로 둔다.
- 행정 코드(``bjd_code``)는 transport export가 VWorld 블록을 실을 때(ADR-114 결정 6) 채운다.
  1단계에서는 비어 있다 — Map은 이 데이터에 geo를 부르지 않는다.
"""

from __future__ import annotations

from typing import Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field

__all__ = [
    "AirportState",
    "FuelPriceState",
    "FuelStationState",
    "HighwayIncidentState",
    "RestAreaFuelPriceState",
    "RestAreaState",
    "StateAddress",
    "StateCoordinate",
]


class _StateModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class StateCoordinate(_StateModel):
    """WGS84 경위도."""

    lon: float = Field(ge=-180.0, le=180.0)
    lat: float = Field(ge=-90.0, le=90.0)


class StateAddress(_StateModel):
    """원천이 준 주소 문자열과(있으면) 행정 코드."""

    road: str | None = None
    jibun: str | None = None
    bjd_code: str | None = Field(
        default=None,
        description=(
            "법정동 코드 10자리. transport VWorld 블록이 실릴 때만 채워진다"
            "(ADR-114 결정 6)."
        ),
    )


class FuelPriceState(_StateModel):
    """주유소 유종 하나의 최신 가격."""

    product_key: str = Field(
        description="표준 유종 키(gasoline·diesel·premium_gasoline·kerosene·lpg)."
    )
    product_code: str = Field(description="오피넷 유종 코드(B027·D047·B034·C004·K015).")
    product_name: str | None = None
    price: float | None = Field(description="원/L. null이면 지금 판매하지 않는다.")
    unit: Literal["KRW/L"] = "KRW/L"
    provider_updated_at: AwareDatetime | None = Field(
        default=None, description="오피넷이 그 유종 가격을 마지막으로 바꾼 시각."
    )
    collected_at: AwareDatetime = Field(
        description="transport가 이 가격을 현재가로 마지막으로 확인한 수집 시각."
    )


class FuelStationState(_StateModel):
    """오피넷 주유소 1곳 + 유종별 최신가."""

    feature_id: str
    kind: Literal["place"] = "place"
    category: str
    marker_icon: str
    marker_color: str
    name: str
    natural_key: str = Field(description="오피넷 주유소 ID(uni_id).")
    coord: StateCoordinate | None
    address: StateAddress
    phone: str | None = None
    brand_code: str | None = None
    brand_name: str | None = None
    is_self: bool | None = None
    is_24h: bool | None = None
    has_carwash: bool | None = None
    has_maintenance: bool | None = None
    has_cvs: bool | None = None
    lpg_available: bool | None = None
    prices: list[FuelPriceState]
    source_last_seen_at: AwareDatetime = Field(
        description="transport가 이 주유소를 원천에서 마지막으로 본 시각."
    )


class RestAreaState(_StateModel):
    """고속도로 휴게소 1곳."""

    feature_id: str
    kind: Literal["place"] = "place"
    category: str
    marker_icon: str
    marker_color: str
    name: str
    natural_key: str = Field(description="``name::route_name::direction``(strip→lower).")
    route_name: str | None = None
    direction: str | None = None
    coord: StateCoordinate | None
    address: StateAddress
    phone: str | None = None
    has_gas_station: bool | None = None
    has_lpg_station: bool | None = None
    has_ev_charger: bool | None = None


class RestAreaFuelPriceState(_StateModel):
    """휴게소 주유소 1곳의 최신 유가(휴게소에 읽을 때 붙인다)."""

    feature_id: str
    kind: Literal["price"] = "price"
    service_area_code: str
    service_area_name: str | None = None
    match_key: str | None = Field(
        description="휴게소 ``natural_key``와 같은 규칙으로 정규화한 매칭 키. 이름이 없으면 null."
    )
    route_name: str | None = None
    direction: str | None = None
    oil_company: str | None = None
    phone: str | None = None
    address: str | None = None
    gasoline_price: int | None = None
    diesel_price: int | None = None
    lpg_price: int | None = None
    unit: Literal["KRW/L"] = "KRW/L"
    observed_at: AwareDatetime


class HighwayIncidentState(_StateModel):
    """고속도로 활성 돌발 1건."""

    feature_id: str
    kind: Literal["notice"] = "notice"
    category: str
    marker_icon: str
    marker_color: str
    title: str
    notice_type: str
    natural_key: str
    occurred_at: AwareDatetime | None = Field(
        default=None, description="원천 발생 일자·시각(KST). 읽을 수 없으면 null."
    )
    incident_type: str | None = None
    incident_type_code: str | None = None
    process_status: str | None = None
    process_status_code: str | None = None
    route_no: str | None = None
    route_name: str | None = None
    direction: str | None = None
    point_name: str | None = None
    message: str | None = None
    congestion_length: float | None = None
    coord: StateCoordinate | None


class AirportState(_StateModel):
    """국내 운영 공항 1곳."""

    feature_id: str
    kind: Literal["place"] = "place"
    category: str
    marker_icon: str
    marker_color: str
    name: str
    name_english: str
    iata_code: str
    icao_code: str | None = None
    municipality: str | None = None
    coord: StateCoordinate | None
    address: StateAddress
