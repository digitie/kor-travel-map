# regions-within-radius.md — POI 반경 행정구역 조회

ADR-045 D-11의 구현 사양이다. krtour-map은 행정구역 경계 polygon을 복제하지 않고,
`python-kraddr-geo` REST v2의 `POST /v2/regions/within-radius`를 호출해 POI 좌표
기준 `n` km 반경에 포함되거나 교차하는 시군구/읍면동을 얻는다.

## 1. 책임 경계

- 경계 polygon 보관, 좌표계 처리, 반경 버퍼, 포함/교차 판정은 `python-kraddr-geo`
  책임이다.
- krtour-map은 REST 응답을 typed dataclass로 파싱하고, 반환된 행정코드를 그대로
  feature scope resolver나 admin 디버깅 도구에서 사용한다.
- `sigungu.code`는 krtour-map `features.sigungu_code`와 같은 5자리 체계다.
  별도 매핑 테이블이나 코드 변환을 두지 않는다.
- 외부 인터페이스 좌표 순서는 항상 `(lon, lat)`다.

## 2. Python API

```python
from krtour.map.geocoding import resolve_regions_within_radius

regions = await resolve_regions_within_radius(
    client,
    lon=126.978,
    lat=37.5665,
    radius_km=3.0,
    levels=("sigungu", "emd"),
)

sigungu_codes = [item.code for item in regions.sigungu]
emd_codes = [item.code for item in regions.emd]
```

공개 타입:

- `RegionLevel`: `"sido" | "sigungu" | "emd"`
- `RegionWithinRadiusItem`: `code`, `name`, `relation`
- `RegionsWithinRadiusResponse`: `center`, `radius_km`, `sido`, `sigungu`, `emd`

`resolve_sigungu_by_radius(...)`는 기존 scope resolver가 시군구 코드만 필요할 때 쓰는
얇은 보조 함수다. 내부적으로 `levels=("sigungu",)`만 요청한다.

## 3. REST 계약

`KraddrGeoRestClient.regions_within_radius(...)`는 kraddr-geo 서비스 루트에
`/v2/regions/within-radius`를 붙여 호출한다. 운영 기본 base URL이
`http://127.0.0.1:8888`라면 실제 호출은 다음과 같다.

```http
POST /v2/regions/within-radius
Content-Type: application/json
```

```json
{
  "lon": 126.978,
  "lat": 37.5665,
  "radius_km": 3.0,
  "levels": ["sigungu", "emd"]
}
```

응답은 요청하지 않은 level이 생략되어도 krtour-map에서 빈 tuple로 정규화한다.
malformed item은 버리고, `center` 또는 `radius_km`가 잘못된 응답은 `ValueError`로
실패시킨다.

```json
{
  "center": {"lon": 126.978, "lat": 37.5665},
  "radius_km": 3.0,
  "sigungu": [
    {"code": "11110", "name": "종로구", "relation": "intersects"}
  ],
  "emd": [
    {"code": "1111010100", "name": "청운동", "relation": "within"}
  ]
}
```

`relation`은 kraddr-geo 원문을 보존한다. krtour-map은 현재 `within`/`intersects`
해석을 재구현하지 않는다.

## 4. Admin 디버깅

backend:

- `GET /debug/geocoding/regions/within-radius`
- `GET /debug/geocoding/regions/within-radius/raw`

query:

- `lon`, `lat`: WGS84 POI 좌표
- `radius_km`: 0보다 크고 100 이하, 기본 3.0
- `level`: 반복 가능. 미지정 시 `sigungu`, `emd`

frontend:

- `/geocoding` 페이지의 `Regions within radius` 폼
- 기본 level은 `sigungu`, `emd`
- raw toggle을 켜면 kraddr-geo 원문 JSON을 그대로 확인한다.

## 5. 테스트 표면

단위 테스트는 다음을 고정한다.

- client가 `/v2/regions/within-radius`로 POST하고 body에 `lon`, `lat`, `radius_km`,
  `levels`를 보낸다.
- 기본 level은 `sigungu`, `emd`다.
- `resolve_sigungu_by_radius`는 `sigungu`만 요청한다.
- `center`의 `lon/lat`와 `x/y` fallback을 모두 파싱한다.
- malformed item은 제외하고, 잘못된 `center`/`radius_km`와 HTTP error는 실패한다.
- admin router는 schema 변환, 반복 `level` query, raw passthrough, base URL 누락
  503, upstream error 502를 검증한다.
- frontend e2e는 세 geocoding form 노출과 level toggle 상태 보존을 확인한다.
