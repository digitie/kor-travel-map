# 표준데이터 feature ETL

`krtour_map.standard_data`는 공공데이터포털 표준데이터 5건만 다루는 범위 제한 asyncio client와
feature ETL입니다. 범용 data.go.kr 게이트웨이로 확장하지 않습니다.

## 문서 정보

| 항목 | 값 |
| --- | --- |
| provider | `data.go.kr-standard` |
| `dataset_key` | `standard_tourism_roads`, `standard_museums`, `standard_parking_lots`, `standard_tourist_sites`, `standard_cultural_festivals` |
| `Feature.kind` | `route`, `place`, `event` |
| 상세 테이블 | `feature_route_details`, `feature_place_details`, `feature_event_details` |
| 코드 entrypoint | `krtour_map.standard_data` |

## 대상 dataset

| `dataset_key` | data.go.kr id | feature |
| --- | --- | --- |
| `standard_tourism_roads` | `15017321` | `route` |
| `standard_museums` | `15017323` | `place` |
| `standard_parking_lots` | `15012896` | `place` |
| `standard_tourist_sites` | `15021141` | `place` 우선, 경계 source 확인 후 `area` 후보 |
| `standard_cultural_festivals` | `15013104` | `event` |

## 코드 경계

- `catalog.py`: dataset id, endpoint URL, feature kind, 갱신 주기
- `client.py`: `StandardDataClient.aio()`, `fetch_page()`, `iter_pages()`, `debug_dataset()`
- `etl.py`: raw row를 `Feature`, `SourceRecord`, `SourceLink`, `PlaceDetail`, `EventDetail`, `RouteDetail`로 변환하고 TripMate Dagster op에서 호출할 `EtlJobSpec`를 제공
- `exceptions.py`: client/config/parse error

## 갱신 주기

- 연간 표준데이터는 월 1회 metadata probe, 연 1회 full scan을 기본으로 합니다.
- 주차장은 반기 full scan입니다.
- 문화축제는 분기 공식 주기지만 운영상 주 1회 metadata probe, 월 1회 changed full scan을 권장합니다.
- row payload hash가 같으면 loader는 source record/update를 반복 저장하지 않도록 동일 key upsert를 사용합니다.
- `standard_tourism_roads`는 `route_type`을 추론해 `feature_route_details`에 저장합니다. `무장애산책길`은 `accessible_walk`, `등산로`는 `hiking_trail`, `트레킹`/`트래킹`은 `trekking`, 기본 관광길은 `tourism_road`로 정규화합니다.
- `python-datagokr-api`와 같은 env 관례를 참고해 `DATAGOKR_API_KEY`, `DATA_GO_KR_SERVICE_KEY`, `PUBLIC_DATA_SERVICE_KEY`, `SERVICE_KEY`를 순서대로 확인하고 JSON/XML 응답을 모두 파싱합니다.

## 디버그 UI

로컬 확인은 별도 디버그 UI 패키지에서 실행합니다.

```bash
python -m krtour_map_debug_ui.server
```

UI는 표준데이터 ETL catalog, raw item 미리보기, feature DB 적재, Dagster 계약 기반 수동 실행,
Kakao map feature marker, RustFS 설정/파일 목록, table 브라우저를 제공합니다.
외부 라이브 호출은 `DATAGOKR_API_KEY`, `DATA_GO_KR_SERVICE_KEY`, `PUBLIC_DATA_SERVICE_KEY`,
`SERVICE_KEY` 중 하나가 필요하며 기본 테스트 경로에서는 수행하지 않습니다.
