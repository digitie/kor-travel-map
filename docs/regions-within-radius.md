# regions-within-radius.md — POI 반경 행정구역 조회

ADR-045 D-11의 구현 사양이다. krtour-map은 행정구역 경계 polygon을 복제하지 않고,
`python-kraddr-geo` REST v2의 `POST /v2/regions/within-radius`를 호출해 POI 좌표
기준 `n` km 반경에 포함되거나 겹치는 시군구/읍면동을 얻는다.

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

- `RegionWithinRadiusLevel`: `"sido" | "sigungu" | "emd"`
- `RegionWithinRadiusItem`: `code`, `name`, `relation`
- `RegionsWithinRadiusResponse`: `center`, `radius_km`, `sido`, `sigungu`, `emd`

`resolve_sigungu_by_radius(...)`는 기존 scope resolver가 시군구 코드만 필요할 때 쓰는
얇은 보조 함수다. 내부적으로 `levels=("sigungu",)`만 요청한다.

## 3. REST 계약

`KraddrGeoRestClient.regions_within_radius(...)`는 kraddr-geo 서비스 루트에
`/v2/regions/within-radius`를 붙여 호출한다. 운영 기본 base URL이
`http://127.0.0.1:9001`라면 실제 호출은 다음과 같다.

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
    {"code": "11110", "name": "종로구", "relation": "contains"},
    {"code": "11140", "name": "중구", "relation": "overlaps"}
  ],
  "emd": [
    {"code": "11110101", "name": "청운동", "relation": "contains"}
  ]
}
```

`relation`은 kraddr-geo 원문을 보존한다. 현재 값은 `contains`(중심점을 포함하는
행정구역)와 `overlaps`(중심점은 포함하지 않지만 반경에 걸친 행정구역)다.
krtour-map은 이 판정을 재구현하지 않는다.

## 4. 디버깅 위치

행정구역 반경 계산 자체의 디버깅은 `python-kraddr-geo` REST/API 문서와 그
프로젝트의 테스트/UI에서 수행한다. krtour-map-admin은 geocoding 전용 debug 화면이나
`/debug/geocoding/*` 라우터를 제공하지 않는다.

krtour-map에서 확인해야 하는 것은 다음 둘이다.

- `KraddrGeoRestClient.regions_within_radius(...)`가 kraddr-geo REST v2
  `POST /v2/regions/within-radius`를 호출하는지.
- 반환된 `sigungu.code`/`emd.code`를 feature update scope resolver가 그대로 쓰는지.

## 5. 테스트 표면

단위 테스트는 다음을 고정한다.

- client가 `/v2/regions/within-radius`로 POST하고 body에 `lon`, `lat`, `radius_km`,
  `levels`를 보낸다.
- 기본 level은 `sigungu`, `emd`다.
- `resolve_sigungu_by_radius`는 `sigungu`만 요청한다.
- `center`의 `lon/lat`와 `x/y` fallback을 모두 파싱한다.
- malformed item은 제외하고, 잘못된 `center`/`radius_km`와 HTTP error는 실패한다.
- admin frontend/backend는 geocoding 전용 debug route를 갖지 않는다. 해당 화면
  검증은 kraddr-geo 프로젝트 책임이다.

2026-06-02 실제 kraddr-geo 서버(현재 로컬 API 포트 `http://127.0.0.1:9001`) + T-027 최종 적재
PostGIS DB(`kraddr-geo-t027-final`, `tl_scco_ctprvn=17`, `tl_scco_sig=255`,
`tl_scco_emd=5067`) 기준으로 같은 요청을 확인했다. 응답은 HTTP 200이었고,
`sigungu` 6건(`11140` 중구 `contains`, `11110` 종로구 `overlaps` 등)과 `emd`
190건을 반환했다. krtour-map `KraddrGeoRestClient` parser도 동일 응답을
`RegionsWithinRadiusResponse`로 파싱했고, `resolve_sigungu_by_radius`는
`("11140", "11110", "11170", "11290", "11410", "11440")`를 반환했다.
