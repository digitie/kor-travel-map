# python-kraddr-base 자료형 사용 기준

`python-krtour-map`은 주소, 좌표, 장소 category 체계를 직접 재정의하지 않는다. 공통 자료형은 `python-kraddr-base`의 안정된 public API를 직접 사용한다.

## 코드 기준

- `krtour_map.Address`는 `kraddr.base.Address`를 그대로 노출한다.
- `krtour_map.Coordinate`는 `kraddr.base.PlaceCoordinate`를 그대로 노출한다.
- 행정구역은 `kraddr.base.AddressRegion`을 사용한다.
- 주소 코드 정규화는 `kraddr.base.AddressCodeSet`, `LegalDongCode`, `SigunguCode`,
  `RoadNameAddressCode`, `RoadNameCode`를 사용한다.
- 장소 category code는 `kraddr.base.PlaceCategoryCode`와 `category_label`, `category_path`, `get_category`, `is_known_category_code`, `mapbox_maki_icon_for_category`를 사용한다.
- `Feature`는 `PlaceCoordinate`를 받은 뒤 `python-krtour-map`의 도메인 제약인 한국 지도 bounds만 검증한다.
- `Feature.category_info`, `Feature.category_path`, `Feature.category_label`, `Feature.mapbox_maki_icon`은 `kraddr.base` category helper를 호출한 결과다.

## 금지 기준

- `bjd_code` 같은 legacy 호환 속성을 `python-krtour-map` 모델에 새로 두지 않는다.
- provider별 주소/좌표/category wrapper, adapter, gateway를 만들지 않는다.
- `kraddr.base`에 없는 주소 code, 좌표 변환, category helper가 필요하면 `python-krtour-map`이나 TripMate에 임시 복제하지 않고 `python-kraddr-base`에 먼저 반영한다.
- 주소 문자열만으로 법정동코드를 추정해 저장하지 않는다.

## 주소와 geocoding

좌표에서 주소를 얻는 reverse geocoding 자체는 `python-kraddr-base`의 책임이 아니다.
`python-krtour-map`은 `python-kraddr-geo` 기반 reverse geocoder callable 결과를
`Address`로 병합한다. TripMate가 callable을 직접 넘길 수도 있고, loader resource의
`kraddr_geo_store` 또는 `kraddr_geo_database_path`로 이 라이브러리가 callable을 만들 수도
있다. `python-vworld-api`는 이 라이브러리의 직접 provider가 아니며, VWorld fallback이
필요하면 `python-kraddr-geo` store 설정에서 처리한다.

법정동코드가 아닌 별도 주소 코드는 다음 기준으로 다룬다.

- 도로명주소관리번호는 `RoadNameAddressCode`로 import하고 `legal_dong_code`를 파생해 저장한다.
- 5자리 시군구코드는 `SigunguCode.legal_dong_code`로 시군구 레벨 10자리 표현을 만들어 저장한다.
- VisitKorea `areaCode`/`sigunguCode`, OpiNet `sigun_code`처럼 provider별 지역 코드는 법정동코드로
  보지 않는다. 원문/payload에는 남기고, 좌표 reverse geocoding으로 확정한 법정동코드만
  feature 주소에 저장한다.

매칭 수준과 운영 리포트 기준은 [주소 geocoding과 매칭 리포트](address-geocoding.md)를 따른다.

## Category 위치 결정

`python-kraddr-base`의 categories는 `python-krtour-map`으로 옮기지 않는다.

이유:

- category code는 feature 저장소만의 세부 구현이 아니라 TripMate, provider library, 주소/POI 정규화 코드가 함께 쓰는 공통 vocabulary다.
- categories를 `python-krtour-map`으로 옮기면 `python-kma-api`, `python-kraddr-geo`, `python-krmois-api` 같은 provider/base 계층이 feature 저장소 라이브러리에 의존하게 되어 의존 방향이 뒤집힌다.
- `python-krtour-map`은 category를 소유하지 않고 feature row의 category code를 저장하고 표시 helper를 재노출하는 역할만 맡는다.

따라서 category seed, enum, label/path/icon helper의 표준 source는 계속 `python-kraddr-base`다. `python-krtour-map`과 TripMate 문서는 이 위치를 기준으로 링크하고, 별도 category 사본을 만들지 않는다.
