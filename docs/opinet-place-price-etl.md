# OpiNet place and price ETL

OpiNet 주유소/충전소 데이터는 장소 정보와 가격 시계열을 분리해서 저장한다. 이 라이브러리는
provider 호출 wrapper를 만들지 않고, `python-opinet-api`의 안정된 `StationDetail` 또는
`NormalizedFuelStationDetail` typed model을 직접 받아 feature DB 계약으로 변환한다.

## 변환 계약

`opinet_station_detail_to_feature_bundle(detail, collected_at=...)`는 아래 묶음을 만든다.

- `Feature(kind="place")`: 주유소/충전소의 지도 지점
- `PlaceDetail`: 전화번호, 편의시설, 상표, 업종, KATEC 원본 좌표 보조 정보
- `PricePoint`: 가격 시계열이 붙는 지점 선언
- `PriceValue`: 제품별 유가 시계열
- `SourceRecord`: OpiNet 원천 row와 payload hash
- `SourceLink`: feature와 source record의 primary link

좌표는 `python-opinet-api`가 제공하는 `kraddr.base.PlaceCoordinate(lat, lon)`를 그대로 사용한다.
가격 관측 시각은 provider price row의 `trade_datetime()` 또는 `trade_date + trade_time`을 사용한다.

## DB 적재

`load_opinet_station_detail(session, detail, collected_at=...)`는 열린 feature DB session에 staged
write한다. Transaction commit/rollback은 TripMate가 담당한다.

```python
from krtour_map.opinet import load_opinet_station_detail

with feature_context.session_factory() as session:
    detail = opinet_client.get_station_detail("A0010207")
    result = load_opinet_station_detail(session, detail)
    session.commit()
```

OpiNet의 지역 코드 조회, 주변 검색, 최저가 조회 pagination이나 endpoint 보강이 필요하면 TripMate
또는 이 라이브러리에 임시 facade를 만들지 말고 `python-opinet-api`에서 public client와 typed
model을 먼저 안정화한다.
