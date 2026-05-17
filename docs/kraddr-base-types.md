# python-kraddr-base 자료형 사용 기준

`python-krtour-map`은 주소, 좌표, 장소 category 체계를 직접 재정의하지 않는다. 공통 자료형은 `python-kraddr-base`의 안정된 public API를 직접 사용한다.

## 코드 기준

- `krtour_map.Address`는 `kraddr.base.Address`를 그대로 노출한다.
- `krtour_map.Coordinate`는 `kraddr.base.PlaceCoordinate`를 그대로 노출한다.
- 행정구역은 `kraddr.base.AddressRegion`을 사용한다.
- 장소 category code는 `kraddr.base.PlaceCategoryCode`와 `category_label`, `category_path`, `get_category`, `is_known_category_code`, `mapbox_maki_icon_for_category`를 사용한다.
- `Feature`는 `PlaceCoordinate`를 받은 뒤 `python-krtour-map`의 도메인 제약인 한국 지도 bounds만 검증한다.
- `Feature.category_info`, `Feature.category_path`, `Feature.category_label`, `Feature.mapbox_maki_icon`은 `kraddr.base` category helper를 호출한 결과다.

## 금지 기준

- `bjd_code` 같은 legacy 호환 속성을 `python-krtour-map` 모델에 새로 두지 않는다.
- provider별 주소/좌표/category wrapper, adapter, gateway를 만들지 않는다.
- `kraddr.base`에 없는 주소 code, 좌표 변환, category helper가 필요하면 `python-krtour-map`이나 TripMate에 임시 복제하지 않고 `python-kraddr-base`에 먼저 반영한다.

## Categories 위치 결정

`python-kraddr-base`의 categories는 `python-krtour-map`으로 옮기지 않는다.

이유:

- category code는 feature 저장소만의 세부 구현이 아니라 TripMate, provider library, 주소/POI 정규화 코드가 함께 쓰는 공통 vocabulary다.
- categories를 `python-krtour-map`으로 옮기면 `python-kma-api`, `python-vworld-api`, `python-krmois-api` 같은 provider/base 계층이 feature 저장소 라이브러리에 의존하게 되어 의존 방향이 뒤집힌다.
- `python-krtour-map`은 category를 소유하지 않고 feature row의 category code를 저장하고 표시 helper를 재노출하는 역할만 맡는다.

따라서 category seed, enum, label/path/icon helper의 canonical source는 계속 `python-kraddr-base`다. `python-krtour-map`과 TripMate 문서는 이 위치를 기준으로 링크하고, 별도 category 사본을 만들지 않는다.
