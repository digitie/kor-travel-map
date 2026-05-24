# kraddr-base-types.md — `python-kraddr-base` 사용 기준

본 문서는 `python-kraddr-base`(import: `kraddr.base`)의 주소·좌표·CRS 타입을
본 라이브러리에서 어떻게 사용하는지 정리한다.

> 주의: kraddr-base의 **category 모듈**(`kraddr.base.categories`)은 **본
> 저장소로 이전**되었다 — `krtour.map.category` (ADR-023). 따라서 본 문서는
> 주소/좌표/CRS만 다룬다. category는 `docs/category.md`.

## 1. 의존 정책

- `python-kraddr-base`는 본 라이브러리의 의존 dependency (`pyproject.toml`).
- 주소(`Address`), 좌표(`PlaceCoordinate`), CRS 상수만 사용. Category는 본 저장소.
- wrapper class 신규 생성 금지 (ADR-006) — `kraddr.base.*`를 직접 import.

## 2. 사용 타입 카탈로그

### 2.1 주소 (locations.py)

```python
from kraddr.base import (
    Address, AddressRegion,
    RoadNameAddress, JibunAddress,
)
```

| 타입 | 의미 | 본 라이브러리에서의 사용 |
|------|------|------------------------|
| `Address` | display + AddressCodeSet | `Feature.address` 필드 표준 |
| `AddressRegion` | 시도/시군구/읍면동 단위 region | 행정구역 query |
| `RoadNameAddress` | 도로명주소 분해 (road_name_code, road_address_management_no) | optional 보강 |
| `JibunAddress` | 지번주소 분해 | optional 보강 |

`Address` 핵심 필드 (kraddr-base 정의):
- `display_address: str` — 사용자 가시 주소 문자열
- `code_set: AddressCodeSet`
  - `legal_dong_code: str | None` (10자리)
  - `road_name_code: str | None` (12자리)
  - `road_address_management_no: str | None` (25자리)
  - `admin_dong_code: str | None`
  - `sido_code: str | None`, `sigungu_code: str | None`

### 2.2 좌표 (coordinates.py)

```python
from kraddr.base import (
    PlaceCoordinate,            # WGS84 lat/lon — 본 라이브러리 표준
    Wgs84Point, LatLon,         # 동의어 (alias)
    ProjectedPoint,             # EPSG:5179 등 투영 좌표
)
```

| 타입 | 의미 |
|------|------|
| `PlaceCoordinate(lat, lon)` | `Feature.coord` 필드 표준. WGS84 EPSG:4326 |
| `Wgs84Point(x=lon, y=lat)` | xy 형태 alias |
| `LatLon(lat, lon)` | 일반 명칭 |
| `ProjectedPoint(x, y, srid)` | EPSG:5179 (UTM-K, meter) 등 — 반경 검색 변환용 |

### 2.3 CRS 상수

```python
from kraddr.base import (
    WGS84_CRS,    # EPSG:4326
    KATEC_CRS,    # EPSG:5181 (katec, 일부 provider 사용)
    EPSG5174_CRS, # EPSG:5174 (Bessel 1841 한국 중부원점)
    EPSG5179_CRS, # EPSG:5179 (UTM-K, meter — 반경 검색 표준)
)
```

본 라이브러리는 `WGS84_CRS` (display/저장) + `EPSG5179_CRS` (반경 검색)만
적극 사용. 다른 CRS provider response는 변환해서 WGS84로 정규화.

### 2.4 기타 (사용 권장)

```python
from kraddr.base import (
    Poi,            # POI 기본형 (TripMate POI와 별개의 kraddr-base 정의)
    # ... 그 외 도메인 보조
)
```

`Poi`는 본 라이브러리의 `Feature`로 변환 (직접 사용 X). 단, `Feature.address`와
`Feature.coord`의 normalization 시 kraddr-base helper 활용.

## 3. 사용 패턴

### 3.1 provider 응답 → Address 생성

```python
from kraddr.base import Address

def _address_from_visitkorea(item) -> Address:
    return Address(
        display_address=f"{item.addr1} {item.addr2 or ''}".strip(),
        code_set=AddressCodeSet(
            legal_dong_code=None,      # provider 미제공, reverse geocoder가 채움
            road_name_code=None,
            road_address_management_no=None,
            sido_code=None,
            sigungu_code=None,
        ),
    )
```

provider가 주는 `areaCode`/`sigunguCode`는 표준 코드 아닌 경우가 많음
(VisitKorea TourAPI 자체 분류). 본 라이브러리는 표준 `legal_dong_code` 등으로
변환 못하면 None. reverse geocoder가 좌표로 확정.

### 3.2 좌표 → coord 필드

```python
from kraddr.base import PlaceCoordinate

def _coord_from_visitkorea(item) -> PlaceCoordinate | None:
    if not item.mapx or not item.mapy:
        return None
    lon = float(item.mapx)
    lat = float(item.mapy)
    if not (124.0 <= lon <= 132.0 and 33.0 <= lat <= 39.5):
        return None  # 한국 영역 밖 — Feature validator도 거부
    return PlaceCoordinate(lat=lat, lon=lon)
```

`Feature` Pydantic validator도 한국 영역 검증 (`docs/feature-model.md` §4.1).
변환 함수에서 미리 None 처리하면 ValidationError 회피.

### 3.3 provider CRS → WGS84 변환

OpiNet (EPSG:5181 KATEC) → WGS84 예시:

```python
from kraddr.base import PlaceCoordinate, KATEC_CRS, WGS84_CRS, transform_coordinate

def _wgs84_from_opinet(item) -> PlaceCoordinate | None:
    if not item.gis_x_coor or not item.gis_y_coor:
        return None
    projected = ProjectedPoint(x=float(item.gis_x_coor), y=float(item.gis_y_coor),
                                srid=KATEC_CRS.srid)
    wgs = transform_coordinate(projected, target_crs=WGS84_CRS)
    return PlaceCoordinate(lat=wgs.y, lon=wgs.x)
```

`transform_coordinate`는 kraddr-base가 pyproj 기반으로 제공.

## 4. import-linter 측면

본 라이브러리의 의존 계층 (`pyproject.toml`):

```
krtour.map.category   ← 최하 (외부 의존: pydantic만)
  ↑
krtour.map.dto        ← `from kraddr.base import Address, PlaceCoordinate` OK
  ↑
krtour.map.core
  ↑
krtour.map.infra      ← `from kraddr.base import KATEC_CRS, transform_coordinate` OK
  ↑
krtour.map.providers  ← provider 응답 → kraddr.base 타입 변환 here
  ↑
krtour.map.client
  ↑
krtour.map.cli
```

`kraddr.base`는 외부 의존이므로 어떤 계층에서든 import 허용. 단,
`kraddr.base.categories`는 ADR-023으로 본 라이브러리 `krtour.map.category`로
이전되었으므로 신규 코드는 본 저장소 import만 사용.

## 5. 라이선스

`python-kraddr-base`: GPL-3.0-or-later. 본 라이브러리와 호환 (둘 다 GPL-3.0).

## 6. category 모듈 이전 (ADR-023)

| 옛 import (v1, kraddr-base) | 새 import (v2, 본 저장소) |
|----------------------------|--------------------------|
| `from kraddr.base import PlaceCategory` | `from krtour.map.category import PlaceCategory` |
| `from kraddr.base import PlaceCategoryCode` | `from krtour.map.category import PlaceCategoryCode` |
| `from kraddr.base import get_category` | `from krtour.map.category import get_category` |
| `from kraddr.base import is_known_category_code` | `from krtour.map.category import is_known_category_code` |
| `from kraddr.base import iter_categories` | `from krtour.map.category import iter_categories` |
| `from kraddr.base import category_label, category_path` | `from krtour.map.category import category_label, category_path` |
| `from kraddr.base import mapbox_maki_icon_for_category` | `from krtour.map.category import mapbox_maki_icon_for_category` |
| `from kraddr.base import mapbox_maki_icon_or_none` | `from krtour.map.category import mapbox_maki_icon_or_none` |
| 그 외 `PLACE_CATEGORY_*` 상수 전체 | 동일 — `krtour.map.category` |

자세한 모듈 사양은 `docs/category.md`.

## 7. provider 라이브러리 commit sha 핀

`python-kraddr-base`는 본 라이브러리 dependency. `pyproject.toml`:

```toml
dependencies = [
  "python-kraddr-base @ git+https://github.com/digitie/python-kraddr-base.git@<sha>",
  ...
]
```

업그레이드 절차:
1. kraddr-base에서 변경된 내용 확인 (CHANGELOG)
2. 본 라이브러리 PR로 sha 핀 갱신
3. 통합 테스트 통과 확인
4. journal.md / decisions.md (호환성 변경 시 ADR) 갱신

category 외 영역 (주소/좌표)에서 BREAKING 변경 시 사용처 (`providers/`, `infra/`)
모두 영향 — 신중히 평가.

## 8. 사용 안 하는 kraddr-base 영역

다음은 본 라이브러리에서 사용하지 않는다:
- `kraddr.base.domains` — 도메인 enum (필요 시 본 저장소 enum으로 정의)
- `kraddr.base.airports` — TripMate 공항 도메인은 TripMate 또는 별도 라이브러리
- `kraddr.base.fuel` — OpiNet 변환은 본 저장소의 `providers/opinet.py`에서

## 9. 운영 체크리스트

- [ ] `python-kraddr-base` git sha 핀 (`pyproject.toml`)
- [ ] `Address`, `PlaceCoordinate` 사용처에서 wrapper 신규 생성 없음
- [ ] `kraddr.base.categories` 신규 import 없음 (ADR-023 위반 차단 — codeql/ruff 룰 검토)
- [ ] CRS 변환은 `kraddr.base.transform_coordinate`만 사용 (직접 pyproj 사용 안 함)
