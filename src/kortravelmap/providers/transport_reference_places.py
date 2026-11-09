"""``kortravelmap.providers.transport_reference_places`` — transport 철도역·항구 → place.

원천: kor-travel-transport 저변동 기준정보 export(ADR-120)

- ``/v1/service/exports/rail-stations`` — KRIC dataset 1294 전국 도시·광역철도 역사정보.
  운영기관·노선마다 한 행이다.
- ``/v1/service/exports/ferry-ports`` — 공공데이터포털 국내선박운항정보의 여객선 항구.

``providers.kor_travel_transport``가 응답을 엄격히 읽어 :class:`TransportRailStation`·
:class:`TransportFerryPort`로 바꾸고, 이 모듈이 place Feature로 바꾼다. HTTP는 Dagster fetcher가
한다(ADR-006은 공개 provider client 규칙이고, 이 모듈은 wrapper가 아니다).

**철도역은 같은 역을 하나로 묶는다.** 원천은 노선마다 한 행이라(서울역 = 1·4호선·공항철도·
경의중앙선 …) 그대로 적재하면 "서울역" 검색에 같은 역이 네 번 나온다. 묶는 규칙은 이렇다.

1. 좌표가 없는 행은 Feature를 만들지 않는다(지도·근처·동선에 쓸 수 없다 — #1459 §4).
2. 이름 비교 키(공백 제거, 끝의 "역" 제거)가 같고, 묶음의 **어느 구성원**에서든
   :data:`RAIL_STATION_CLUSTER_RADIUS_M` 안이면 같은 역이다. 행은 transport 자연키 순으로 본다 —
   입력 순서와 무관하게 같은 결과다.
3. Feature 자연키는 묶음 anchor의 transport 자연키다(``|``는 ``::``로 바꾼다 — ADR-009가 ``|``를
   id 구분자로 예약했다). anchor는 **이미 적재된 Feature의 자연키인 구성원**이 있으면 그것(여럿이면
   가장 작은 것), 없으면 자연키가 가장 작은 구성원이다. 그래서 환승역에 노선이 새로 생겨 더 작은
   자연키가 들어와도 역 Feature가 다시 주조되지 않는다. anchor 행 자체가 원천에서 빠질 때만 새
   자연키로 다시 주조되고 옛 Feature는 완전 snapshot reconcile이 퇴역시킨다.
4. 이름이 같아도 반경 밖이면 다른 역이다(예: 2호선 신촌과 경의중앙선 신촌은 약 700 m 떨어진
   별개 역이다).

분류: 묶음의 어느 행이든 운영기관이 국가철도 운영사(:data:`NATIONAL_RAIL_OPERATOR_MARKERS`)면
기차역(``06030300``), 아니면 지하철역(``06030200``). 둘 다 검색 그룹 1이다.

표시 이름: 역은 끝에 "역"이 없으면 붙인다("중앙" → "중앙역"). 항구는 이름이 이미 항구·터미널을
말하지 않으면 " 여객선터미널"을 붙인다("백령도" → "백령도 여객선터미널"). 원천 이름은 raw에
그대로 남는다.

ADR 참조: ADR-009 / ADR-012 / ADR-098 / ADR-106 / ADR-114 결정 6 / ADR-120
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Any, Final

from kortravelmap.category import PlaceCategoryCode, mapbox_maki_icon_or_none
from kortravelmap.core.address import extract_sido_code, extract_sigungu_code
from kortravelmap.core.ids import make_feature_id, make_payload_hash, make_source_record_key
from kortravelmap.core.providers import normalize_provider_name
from kortravelmap.dto import (
    Address,
    Coordinate,
    Feature,
    FeatureBundle,
    FeatureKind,
    PlaceDetail,
    SourceLink,
    SourceRecord,
    SourceRole,
)
from kortravelmap.geocoding import ReverseGeocoder, cached_reverse_geocoder
from kortravelmap.providers.kor_travel_transport import (
    DATASET_KEY_FERRY_PORTS,
    DATASET_KEY_RAIL_STATIONS,
    KOR_TRAVEL_TRANSPORT_PROVIDER_NAME,
    TransportFerryPort,
    TransportRailStation,
)

__all__ = [
    "FERRY_PORT_CATEGORY",
    "FERRY_PORT_DISPLAY_SUFFIX",
    "NATIONAL_RAIL_OPERATOR_MARKERS",
    "RAIL_STATION_CLUSTER_RADIUS_M",
    "RAIL_STATION_TRAIN_CATEGORY",
    "RAIL_STATION_SUBWAY_CATEGORY",
    "ferry_port_display_name",
    "ferry_ports_to_bundles",
    "rail_station_display_name",
    "rail_station_name_key",
    "rail_stations_to_bundles",
]

RAIL_STATION_TRAIN_CATEGORY: Final[str] = PlaceCategoryCode.TRANSPORT_STOP_TRAIN.value
"""기차역 06030300."""
RAIL_STATION_SUBWAY_CATEGORY: Final[str] = PlaceCategoryCode.TRANSPORT_STOP_SUBWAY.value
"""지하철역 06030200."""
FERRY_PORT_CATEGORY: Final[str] = PlaceCategoryCode.TRANSPORT_FERRY_TERMINAL.value
"""여객선터미널 06060000(ADR-120)."""

RAIL_STATION_CLUSTER_RADIUS_M: Final[float] = 500.0
"""같은 이름의 행을 같은 역으로 보는 반경(anchor 기준). 환승역의 노선별 좌표 차이(대개 수백 m
안)는 묶고, 같은 이름의 별개 역(2호선 신촌 ↔ 경의중앙선 신촌 약 700 m)은 가른다."""

NATIONAL_RAIL_OPERATOR_MARKERS: Final[tuple[str, ...]] = ("한국철도공사", "코레일", "에스알")
"""운영기관 이름에 이것이 들어 있으면 국가철도 운영사다 — 그 역은 기차역으로 분류한다."""

FERRY_PORT_DISPLAY_SUFFIX: Final[str] = "여객선터미널"
"""항구 표시 이름에 덧붙이는 말."""

_FERRY_NAME_MARKERS: Final[tuple[str, ...]] = ("항", "터미널", "선착장", "포구", "부두", "나루")
"""이름 끝이 이것이면 이미 항구·터미널을 말한다 — 표시 이름에 덧붙이지 않는다."""

_RAIL_ENTITY_TYPE: Final[str] = "rail_station"
_FERRY_ENTITY_TYPE: Final[str] = "ferry_port"
_RAIL_PLACE_KIND: Final[str] = "rail_station"
_FERRY_PLACE_KIND: Final[str] = "ferry_terminal"
_RAIL_MARKER_COLOR: Final[str] = "P-10"
_FERRY_MARKER_COLOR: Final[str] = "P-10"
_STATION_SUFFIX: Final[str] = "역"
_EARTH_RADIUS_M: Final[float] = 6_371_008.8


def _compact(value: str) -> str:
    return "".join(value.split())


def rail_station_name_key(name: str) -> str:
    """같은 역 판정의 이름 키 — 공백을 지우고 끝의 "역"을 뗀다("서울역"·"서울" → "서울").

    "역" 한 글자뿐인 이름은 그대로 둔다(빈 키를 만들지 않는다).
    """
    compact = _compact(name)
    if compact.endswith(_STATION_SUFFIX) and len(compact) > len(_STATION_SUFFIX):
        return compact[: -len(_STATION_SUFFIX)]
    return compact


def rail_station_display_name(name: str) -> str:
    """역 표시 이름 — 끝에 "역"이 없으면 붙인다. 두 번 적용해도 같다."""
    stripped = name.strip()
    if not stripped or stripped.endswith(_STATION_SUFFIX):
        return stripped
    return f"{stripped}{_STATION_SUFFIX}"


def ferry_port_display_name(name: str) -> str:
    """항구 표시 이름 — 이름이 항구·터미널을 말하지 않으면 " 여객선터미널"을 붙인다."""
    stripped = name.strip()
    if not stripped or stripped.endswith(_FERRY_NAME_MARKERS):
        return stripped
    return f"{stripped} {FERRY_PORT_DISPLAY_SUFFIX}"


def _map_natural_key(transport_key: str) -> str:
    """transport 자연키를 Map 자연키로 — ``|``(ADR-009 예약)를 ``::``로 바꾼다."""
    return "::".join(part.strip() for part in transport_key.split("|"))


def _coordinate(lat: float | None, lon: float | None) -> Coordinate | None:
    if lat is None or lon is None or not (math.isfinite(lat) and math.isfinite(lon)):
        return None
    try:
        return Coordinate(lon=Decimal(str(lon)), lat=Decimal(str(lat)))
    except ValueError:
        # Coordinate가 국내 범위 밖 좌표를 거부한다 — 그 행은 좌표 없는 행과 같다.
        return None


def _distance_m(a: Coordinate, b: Coordinate) -> float:
    """두 좌표 사이 대권 거리(m, haversine). 같은 역 판정만 쓴다 — DB 공간 술어가 아니다."""
    lat1, lon1 = math.radians(float(a.lat)), math.radians(float(a.lon))
    lat2, lon2 = math.radians(float(b.lat)), math.radians(float(b.lon))
    h = (
        math.sin((lat2 - lat1) / 2) ** 2
        + math.cos(lat1) * math.cos(lat2) * math.sin((lon2 - lon1) / 2) ** 2
    )
    return 2 * _EARTH_RADIUS_M * math.asin(min(1.0, math.sqrt(h)))


@dataclass
class _RailCluster:
    name_key: str
    members: list[tuple[TransportRailStation, Coordinate]] = field(default_factory=list)

    def near(self, coord: Coordinate) -> bool:
        return any(
            _distance_m(member_coord, coord) <= RAIL_STATION_CLUSTER_RADIUS_M
            for _, member_coord in self.members
        )

    def anchor(self, existing: frozenset[str]) -> tuple[TransportRailStation, Coordinate]:
        """이미 적재된 자연키인 구성원 → 없으면 자연키가 가장 작은 구성원(members는 자연키 순)."""
        for member, coord in self.members:
            if _map_natural_key(member.natural_key) in existing:
                return member, coord
        return self.members[0]


def _is_national_rail(operator_name: str | None) -> bool:
    return operator_name is not None and any(
        marker in operator_name for marker in NATIONAL_RAIL_OPERATOR_MARKERS
    )


def _cluster_rail_stations(items: Iterable[TransportRailStation]) -> list[_RailCluster]:
    """좌표 있는 행을 같은 역끼리 묶는다(모듈 docstring 규칙). 결과는 anchor 자연키 순이다."""
    rows: dict[str, TransportRailStation] = {}
    for item in items:
        if item.natural_key in rows:
            # transport가 같은 identity를 두 번 냈다 — 어느 쪽을 쓸지 정할 근거가 없다.
            raise ValueError(f"철도역 자연키 중복: {item.natural_key!r}")
        rows[item.natural_key] = item
    clusters: list[_RailCluster] = []
    by_name: dict[str, list[_RailCluster]] = {}
    for natural_key in sorted(rows):
        item = rows[natural_key]
        coord = _coordinate(item.lat, item.lon)
        name_key = rail_station_name_key(item.name)
        if coord is None or not name_key:
            continue
        for cluster in by_name.get(name_key, ()):
            if cluster.near(coord):
                cluster.members.append((item, coord))
                break
        else:
            cluster = _RailCluster(name_key=name_key, members=[(item, coord)])
            clusters.append(cluster)
            by_name.setdefault(name_key, []).append(cluster)
    return clusters


async def _reverse(
    coord: Coordinate, geocoder: ReverseGeocoder | None
) -> Address | None:
    if geocoder is None:
        return None
    return await geocoder(coord)


def _address(geo: Address | None) -> Address:
    bjd_code = geo.bjd_code if geo is not None else None
    return Address(
        admin=geo.admin if geo is not None else None,
        bjd_code=bjd_code,
        admin_dong_code=geo.admin_dong_code if geo is not None else None,
        sigungu_code=(geo.sigungu_code if geo is not None else None)
        or extract_sigungu_code(bjd_code),
        sido_code=(geo.sido_code if geo is not None else None) or extract_sido_code(bjd_code),
        zipcode=geo.zipcode if geo is not None else None,
        sido_name=geo.sido_name if geo is not None else None,
        sigungu_name=geo.sigungu_name if geo is not None else None,
    )


def _bundle(
    *,
    dataset_key: str,
    entity_type: str,
    natural_key: str,
    name: str,
    category: str,
    coord: Coordinate,
    address: Address,
    place_kind: str,
    marker_color: str,
    facility_info: dict[str, Any],
    raw_data: dict[str, Any],
    fetched_at: datetime,
) -> FeatureBundle:
    payload_hash = make_payload_hash(raw_data)
    source_record_key = make_source_record_key(
        provider=KOR_TRAVEL_TRANSPORT_PROVIDER_NAME,
        dataset_key=dataset_key,
        source_entity_type=entity_type,
        source_entity_id=natural_key,
        raw_payload_hash=payload_hash,
    )
    feature_id = make_feature_id(
        bjd_code=address.bjd_code,
        kind=FeatureKind.PLACE.value,
        category=category,
        source_type=f"{KOR_TRAVEL_TRANSPORT_PROVIDER_NAME}:{dataset_key}",
        source_natural_key=natural_key,
    )
    feature = Feature(
        feature_id=feature_id,
        provider_natural_key=natural_key,
        kind=FeatureKind.PLACE,
        name=name,
        coord=coord,
        address=address,
        category=category,
        marker_icon=mapbox_maki_icon_or_none(category),
        marker_color=marker_color,
        detail=PlaceDetail(
            feature_id=feature_id,
            place_kind=place_kind,
            facility_info=facility_info,
        ),
    )
    source_record = SourceRecord(
        provider=normalize_provider_name(KOR_TRAVEL_TRANSPORT_PROVIDER_NAME),
        dataset_key=dataset_key,
        source_entity_type=entity_type,
        source_entity_id=natural_key,
        raw_payload_hash=payload_hash,
        raw_data=raw_data,
        fetched_at=fetched_at,
        source_record_key=source_record_key,
    )
    source_link = SourceLink(
        feature_id=feature_id,
        source_record_key=source_record_key,
        source_role=SourceRole.PRIMARY,
        match_method="natural_key",
        confidence=100,
    )
    return FeatureBundle(feature=feature, source_record=source_record, source_link=source_link)


def _rail_line(item: TransportRailStation) -> dict[str, Any]:
    return {
        key: value
        for key, value in {
            "natural_key": item.natural_key,
            "name": item.name,
            "operator_name": item.operator_name,
            "line_name": item.line_name,
            "station_number": item.station_number,
            "operator_code": item.operator_code,
            "line_code": item.line_code,
            "station_code": item.station_code,
            "latitude": str(item.lat) if item.lat is not None else None,
            "longitude": str(item.lon) if item.lon is not None else None,
        }.items()
        if value is not None
    }


async def rail_stations_to_bundles(
    items: Sequence[TransportRailStation],
    *,
    fetched_at: datetime,
    reverse_geocoder: ReverseGeocoder | None = None,
    existing_natural_keys: Iterable[str] = (),
) -> list[FeatureBundle]:
    """transport 철도역 행 → 역마다 place ``FeatureBundle`` 하나(모듈 docstring의 묶음 규칙).

    ``existing_natural_keys``는 이 dataset에 이미 적재된(active) Feature의 자연키다 — anchor를
    고정해 역 Feature가 노선 추가로 다시 주조되지 않게 한다. 좌표는 anchor의 좌표이고, 행정구역은
    그 좌표를 Map geo로 역지오코딩해 채운다. 노선별 원천 행은 ``facility_info.lines``와 raw에
    남는다.
    """
    geocoder = cached_reverse_geocoder(reverse_geocoder) if reverse_geocoder is not None else None
    existing = frozenset(existing_natural_keys)
    bundles: list[FeatureBundle] = []
    for cluster in _cluster_rail_stations(items):
        anchor, anchor_coord = cluster.anchor(existing)
        members = [member for member, _ in cluster.members]
        national = any(_is_national_rail(member.operator_name) for member in members)
        category = RAIL_STATION_TRAIN_CATEGORY if national else RAIL_STATION_SUBWAY_CATEGORY
        lines = [_rail_line(member) for member in members]
        operators = sorted({m.operator_name for m in members if m.operator_name})
        line_names = sorted({m.line_name for m in members if m.line_name})
        display_name = rail_station_display_name(anchor.name)
        geo = await _reverse(anchor_coord, geocoder)
        bundles.append(
            _bundle(
                dataset_key=DATASET_KEY_RAIL_STATIONS,
                entity_type=_RAIL_ENTITY_TYPE,
                natural_key=_map_natural_key(anchor.natural_key),
                name=display_name,
                category=category,
                coord=anchor_coord,
                address=_address(geo),
                place_kind=_RAIL_PLACE_KIND,
                marker_color=_RAIL_MARKER_COLOR,
                facility_info={
                    "operators": operators,
                    "lines": line_names,
                    "line_count": len(members),
                },
                raw_data={
                    "anchor_natural_key": anchor.natural_key,
                    "display_name": display_name,
                    "category": category,
                    "lines": lines,
                },
                fetched_at=fetched_at,
            )
        )
    return bundles


async def ferry_ports_to_bundles(
    items: Sequence[TransportFerryPort],
    *,
    fetched_at: datetime,
    reverse_geocoder: ReverseGeocoder | None = None,
) -> list[FeatureBundle]:
    """transport 항구 행 → 항구마다 place ``FeatureBundle`` 하나(category 06060000).

    좌표가 없는 항구(transport가 항만가이드라인 한 점이나 범위 밖 좌표를 null로 낸다)는 Feature를
    만들지 않는다. 자연키는 transport 자연키(``{source}:{port_id}``) 그대로다.
    """
    geocoder = cached_reverse_geocoder(reverse_geocoder) if reverse_geocoder is not None else None
    seen: set[str] = set()
    bundles: list[FeatureBundle] = []
    for item in sorted(items, key=lambda port: port.natural_key):
        if item.natural_key in seen:
            raise ValueError(f"항구 자연키 중복: {item.natural_key!r}")
        seen.add(item.natural_key)
        coord = _coordinate(item.lat, item.lon)
        if coord is None:
            continue
        display_name = ferry_port_display_name(item.name)
        geo = await _reverse(coord, geocoder)
        bundles.append(
            _bundle(
                dataset_key=DATASET_KEY_FERRY_PORTS,
                entity_type=_FERRY_ENTITY_TYPE,
                natural_key=_map_natural_key(item.natural_key),
                name=display_name,
                category=FERRY_PORT_CATEGORY,
                coord=coord,
                address=_address(geo),
                place_kind=_FERRY_PLACE_KIND,
                marker_color=_FERRY_MARKER_COLOR,
                facility_info={
                    k: v
                    for k, v in {
                        "port_id": item.port_id,
                        "location_source": item.location_source,
                    }.items()
                    if v is not None
                },
                raw_data={
                    "natural_key": item.natural_key,
                    "source": item.source,
                    "port_id": item.port_id,
                    "name": item.name,
                    "display_name": display_name,
                    "latitude": str(coord.lat),
                    "longitude": str(coord.lon),
                    "location_source": item.location_source,
                },
                fetched_at=fetched_at,
            )
        )
    return bundles
