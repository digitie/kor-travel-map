# OpiNet 장소/가격 ETL

OpiNet 주유소/충전소 데이터는 장소 정보와 가격 시계열을 분리해서 저장한다. 이 라이브러리는
provider 호출 wrapper를 만들지 않고, `python-opinet-api`의 안정된 `StationDetail` 또는
`NormalizedFuelStationDetail` typed model을 직접 받아 feature DB 계약으로 변환한다.

## 문서 정보

| 항목 | 값 |
| --- | --- |
| provider | `python-opinet-api` |
| `dataset_key` | `opinet_fuel_station_details` |
| `Feature.kind` | `place`와 `PricePoint`/`PriceValue` |
| `source_entity_type` | `fuel_station` |
| 상세 테이블 | `feature_place_details`, `price_points`, `price_values` |
| 코드 entrypoint | `krtour_map.opinet` |

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

주소는 도로명주소(`address_road`)와 지번주소(`address_jibun`)를 `kraddr.base.Address`의
road/jibun DTO에 보존한다. OpiNet `sigun_code`는 OpiNet provider 지역 코드이므로 법정동코드로
저장하지 않는다. TripMate가 `reverse_geocoder` callable을 넘기면 좌표에서 법정동코드를
확정하고 `AddressMatchReport`로 매칭 수준을 반환한다.

영업시간을 provider typed model이 `business_hours` 또는 `opening_hours`로 구조화해 제공하면
`PlaceDetail.business_hours: FeatureOpeningHours`로 저장한다. 단순 원문 문자열이나
provider별 보조 정보는 `PlaceDetail.payload`에 남긴다.

## DB 적재

`load_opinet_station_detail(session, detail, collected_at=..., reverse_geocoder=...)`는 열린
feature DB session에 staged write한다. Transaction commit/rollback은 TripMate가 담당한다.

```python
from krtour_map.opinet import load_opinet_station_detail

with feature_context.session_factory() as session:
    detail = opinet_client.get_station_detail("A0010207")
    result = load_opinet_station_detail(
        session,
        detail,
        reverse_geocoder=tripmate_reverse_geocoder,
    )
    session.commit()
```

OpiNet의 지역 코드 조회, 주변 검색, 최저가 조회 pagination이나 endpoint 보강이 필요하면 TripMate
또는 이 라이브러리에 임시 facade를 만들지 말고 `python-opinet-api`에서 public client와 typed
model을 먼저 안정화한다.
