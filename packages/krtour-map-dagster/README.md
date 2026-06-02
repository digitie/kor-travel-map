# krtour-map-dagster

`python-krtour-map` 독립 프로그램의 Dagster code location 패키지다.

- 본 패키지는 Dagster asset/job/resource 정의를 소유한다.
- 메인 라이브러리 `krtour.map`은 Dagster를 import하지 않는다.
- asset은 provider record resource를 받아 기존 `krtour.map.providers.*` 변환 함수로
  `FeatureBundle`을 만들고, 주소/좌표 검증 후 `AsyncKrtourMapClient`로 PostGIS에
  적재한다.

```bash
dagster dev -m krtour.map_dagster.definitions -h 0.0.0.0 -p 9013
```

## 1차 resource 계약

공통 resource:

- `krtour_map_client`: `AsyncKrtourMapClient`.
- `reverse_geocoder`: kraddr-geo REST v2 기반 reverse geocoder.
- `fetched_at`: batch 기준 aware `datetime`. 기본값은 실행 시점 KST.
- `strict_address`: 주소/좌표 error 시 적재 전 중단 여부. 기본 `true`.

provider record resource:

- `datagokr_cultural_festivals`
- `opinet_stations`
- `krex_rest_areas`
- `krex_traffic_notices`
- `krheritage_items`
- `krheritage_events`
- `mois_license_records`
- `knps_point_records`
- `knps_geometry_records`
