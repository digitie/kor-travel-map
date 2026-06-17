# kraddr-base-types.md — kraddr-base 사용 기준 (SUPERSEDED)

> **정본**: ADR-041. `python-kraddr-base` 의존은 제거됐고, 신규 코드에서
> `kraddr.base.*`를 import하지 않는다.

이 문서는 과거 ADR-023 시점의 kraddr-base 사용 계획을 대체한다. 호환 shim을
남기지 않는 정책(ADR-046)에 따라, 구 `Address`/`PlaceCoordinate`/CRS helper
사용 예시는 보존하지 않는다.

## 현재 매핑

| 과거 kraddr-base 개념 | 현재 정본 |
|----------------------|-----------|
| `kraddr.base.Address` | `kortravelmap.dto.Address` |
| `kraddr.base.PlaceCoordinate` | `kortravelmap.dto.Coordinate` |
| `kraddr.base.categories` | `kortravelmap.category` |
| `normalize_bjd_code`, `extract_sigungu_code` 등 주소 utility | `kortravelmap.core.address` |
| provider 좌표계 변환 | provider 라이브러리가 WGS84로 제공하거나 `kortravelmap.infra.crs`/전용 변환 helper 사용 |

## 신규 코드 규칙

- `from kraddr.base import ...` 신규 import 금지.
- 좌표 DTO는 항상 `Coordinate(lon=..., lat=...)` 의미로 다룬다. 외부 API와
  PostGIS 입력 순서는 `(lon, lat)`다.
- 주소는 `kortravelmap.dto.Address`에 저장하고, 행정코드 정규화는
  `kortravelmap.core.address`를 사용한다.
- category/maki/icon 매핑은 `kortravelmap.category`와
  `@kor-travel-map/map-marker-react`를 사용한다.
- 과거 PinVi 직접 import 예시는 ADR-045/ADR-046 이후 폐기됐다. PinVi는
  OpenAPI로 kor-travel-map을 호출한다.

## 관련 문서

- `docs/adr/README.md` ADR-041 — kraddr-base 코드 흡수와 `PlaceCoordinate` 제외.
- `docs/architecture/address-geocoding.md` — kor-travel-geo REST v2와 `Address`/`Coordinate` 보강.
- `docs/architecture/category.md` — category 모듈 이전 결과.
