# Address geocoding and match report

`python-krtour-map`은 feature 주소와 좌표를 `python-kraddr-base` DTO로 정리한다. 실제
reverse geocoding provider 실행은 TripMate/Dagster resource가 담당하고, 이 라이브러리는
주입받은 callable 결과를 `Address`로 병합한다.

## 원칙

- 좌표 DTO는 `kraddr.base.PlaceCoordinate(lat, lon)`를 사용한다.
- 주소 DTO는 `kraddr.base.Address`, `AddressRegion`, `AddressCodeSet`을 사용한다.
- 지오코딩 provider별 wrapper/adapter/gateway를 만들지 않는다.
- `reverse_geocoder: Callable[[PlaceCoordinate], Address | Mapping | object | None]`는
  TripMate resource에서 넘긴다.
- provider 원문 주소와 provider별 지역 코드는 `SourceRecord.raw_data`와 kind별 `payload`에
  보존한다.
- feature row에 저장하는 `legal_dong_code`는 `kraddr.base`로 검증/정규화된 값만 사용한다.

## 코드 변환 기준

`AddressCodeSet.from_mapping()`으로 인식되는 주소 코드는 import 시점에 `Address`에 반영한다.

| 원천 코드 | 저장 기준 |
| --- | --- |
| `legal_dong_code`, `admCd` | 10자리 법정동코드로 저장 |
| `roadAddrMgtNo` 또는 `admCd + rnMgtSn + buld*` | 도로명주소관리번호에서 법정동코드와 도로명코드를 파생해 저장 |
| `sggCd`, 5자리 `sigungu_code` | 시군구 레벨 법정동 표현(`1111000000` 형태)으로 저장하고 match level은 `sigungu_code_only` |
| VisitKorea `areaCode`/`sigunguCode`, OpiNet `sigun_code` | provider별 코드이므로 raw/payload에만 보존. 좌표 reverse geocoding으로 법정동코드를 확정한 경우에만 feature 주소에 저장 |

주소 문자열만으로 법정동코드를 추정하지 않는다. 주소 문자열은 행정구역명 parsing과 매칭 검토에만
사용하고, 코드 확정은 provider 코드 또는 좌표 reverse geocoding 결과를 사용한다.

## 매칭 수준

`enrich_address_from_coordinate()`는 `AddressEnrichment`을 반환한다.

- `address`: feature에 저장할 `Address`
- `geocoded_address`: reverse geocoder가 반환한 주소
- `report`: `AddressMatchReport`

`AddressMatchReport.match_level` 기준:

| match level | 의미 |
| --- | --- |
| `legal_dong_exact` | 원천 법정동코드와 좌표 reverse geocoding 법정동코드가 일치 |
| `coordinate_legal_dong` | 원천에는 법정동코드가 없고 좌표 reverse geocoding으로 채움 |
| `legal_dong_conflict` | 원천 법정동코드와 좌표 reverse geocoding 결과가 충돌 |
| `source_legal_dong` | 원천의 법정동코드를 그대로 사용 |
| `provider_code_converted` | 도로명주소관리번호 등으로 법정동코드를 파생 |
| `sigungu_code_only` | 시군구 코드만 있어 시군구 레벨 법정동 표현으로 저장 |
| `address_text_match` | 코드 없이 주소 문자열만 일치 |
| `address_text_review` | 코드 없이 주소 문자열 검토 필요 |
| `address_text_only` | 좌표/geocoder 없이 주소 문자열만 있음 |
| `coordinate_only` | 주소 문자열 없이 좌표 reverse geocoding 결과만 있음 |
| `not_geocoded` | 좌표는 있지만 reverse geocoder resource가 없음 |
| `no_address` | 주소와 좌표 모두 없음 |

TripMate 운영 리포트는 `AddressMatchReport`를 모아 DOCX/스프레드시트로 만들 수 있다.
`legal_dong_conflict`, `address_text_review`, `sigungu_code_only`, `not_geocoded`는 운영 검토
대상으로 본다.

## ETL 적용

VisitKorea 축제 ETL과 OpiNet 주유소 ETL은 `reverse_geocoder`를 선택적으로 받는다.

```python
result = collect_visitkorea_festival_events(
    visitkorea_client,
    event_start_date="2026-01-01",
    reverse_geocoder=tripmate_reverse_geocoder,
)

bundle = opinet_station_detail_to_feature_bundle(
    station_detail,
    reverse_geocoder=tripmate_reverse_geocoder,
)
```

TripMate Dagster resource는 `reverse_geocoder` 속성이나 mapping key를 제공하면 된다. 이 callable
내부에서는 `python-kraddr-geo`, `python-vworld-api` 같은 안정된 public client를 직접 사용한다.

## 영업시간/운영시간

운영시간은 provider 문자열을 feature 본문에 임의 key로 넣지 않고 DTO에 맞춰 넣는다.

- 장소: `PlaceDetail.business_hours: FeatureOpeningHours`
- 행사: `EventDetail.opening_hours: FeatureOpeningHours`
- 정규 구간: `OpeningPeriod`
- 날짜별 예외: `SpecialOpeningDay`

provider가 구조화된 dict/model을 제공하면 `FeatureOpeningHours`로 검증한 뒤 detail DTO에 저장하고,
원문 문자열이나 provider별 보조 필드는 detail `payload`에 남긴다.
