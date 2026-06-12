# standard-data-feature-etl.md — data.go.kr 표준데이터 5종 ETL

본 문서는 공공데이터포털 표준데이터 5종 전용 ETL이다. 별도 provider 라이브러리
없이 본 저장소 내부의 bounded asyncio client (`kortravelmap.standard_data`)로
처리한다. **범용 data.go.kr gateway로 확장 X**.

## 1. 문서 정보

| 항목 | 값 |
|------|----|
| provider | `data.go.kr-standard` (canonical) |
| 코드 entrypoint | `kortravelmap.standard_data` |
| 코드 구조 | `catalog.py` / `client.py` / `etl.py` / `exceptions.py` |
| 갱신 주기 | dataset별 (월 / 반기 / 연 / 주) |

## 2. 5종 dataset (카테고리 매핑 포함)

| dataset_key | data.go.kr id | Feature.kind | category | 권장 갱신 |
|-------------|--------------|--------------|----------|-----------|
| `standard_tourism_roads` | `15017321` | `route` | **`01020103`** `TOURISM_NATURAL_LANDSCAPE_MOUNTAIN_VALLEY_FOREST_TRAIL` 또는 `01080500` `TOURISM_ACTIVITY_TREKKING` (route_type별 분기) | 연 1회 full + 월 1회 metadata probe |
| `standard_museums` | `15017323` | `place` | **`01040101`** `TOURISM_CULTURAL_FACILITY_MUSEUM_PUBLIC` 또는 `01040102` `_PRIVATE` (소속별 분기) | 연 1회 |
| `standard_parking_lots` | `15012896` | `place` | **`06010000`** `TRANSPORT_PARKING` | 반기 1회 |
| `standard_tourist_sites` | `15021141` | `place` (경계 source 확인 후 `area` 후보) | **`01050200`** `TOURISM_NATURE_PARK` 또는 `01000000` `TOURISM` (대분류) | 연 1회 |
| `standard_cultural_festivals` | `15013104` | `event` | event는 카테고리 외 — `EventDetail.event_kind="cultural_festival"`. `features.category`는 `01000000` `TOURISM` (대분류) | 주 1회 metadata + 월 1회 changed full scan |

자세한 Tier 1~4 트리는 `docs/category.md` §4.

## 3. 모듈 구조

```
src/kortravelmap/standard_data/
  __init__.py
  catalog.py        — dataset id, endpoint URL, feature kind, 갱신 주기
  client.py         — StandardDataClient (async), fetch_page, iter_pages, debug_dataset
  etl.py            — raw row → DTO 변환 + EtlJobSpec
  exceptions.py     — StandardDataClientError, StandardDataConfigError, StandardDataParseError
```

## 4. catalog.py

```python
@dataclass(frozen=True)
class StandardDataset:
    key: str                                  # dataset_key (e.g., "standard_tourism_roads")
    data_go_kr_id: str                        # e.g., "15017321"
    endpoint_url: str
    feature_kind: FeatureKind
    suggested_interval: timedelta
    response_format: Literal["json", "xml"] = "json"
    description: str = ""

CATALOG: dict[str, StandardDataset] = {
    "standard_tourism_roads": StandardDataset(
        key="standard_tourism_roads", data_go_kr_id="15017321",
        endpoint_url="http://api.data.go.kr/openapi/tn_pubr_public_trrsrt_tour_road_api",
        feature_kind=FeatureKind.ROUTE,
        suggested_interval=timedelta(days=365),
        description="표준 관광길 (무장애/등산/트레킹/관광길)",
    ),
    "standard_museums": StandardDataset(
        key="standard_museums", data_go_kr_id="15017323",
        endpoint_url="...",
        feature_kind=FeatureKind.PLACE, suggested_interval=timedelta(days=365),
    ),
    "standard_parking_lots": StandardDataset(
        key="standard_parking_lots", data_go_kr_id="15012896",
        endpoint_url="...",
        feature_kind=FeatureKind.PLACE, suggested_interval=timedelta(days=183),
    ),
    "standard_tourist_sites": StandardDataset(
        key="standard_tourist_sites", data_go_kr_id="15021141",
        endpoint_url="...",
        feature_kind=FeatureKind.PLACE, suggested_interval=timedelta(days=365),
    ),
    "standard_cultural_festivals": StandardDataset(
        key="standard_cultural_festivals", data_go_kr_id="15013104",
        endpoint_url="...",
        feature_kind=FeatureKind.EVENT, suggested_interval=timedelta(days=30),
    ),
}
```

## 5. client.py

```python
class StandardDataClient:
    def __init__(self, *, service_key: SecretStr, timeout: int = 30):
        self._service_key = service_key
        self._http = httpx.AsyncClient(timeout=timeout)
    
    async def __aenter__(self): return self
    async def __aexit__(self, *args): await self._http.aclose()
    
    async def fetch_page(self, dataset: StandardDataset, *, page_no: int = 1,
                         num_of_rows: int = 100) -> StandardDataPage:
        ...
    
    async def aiter_pages(self, dataset: StandardDataset, *, page_size: int = 100,
                          max_pages: int | None = None) -> AsyncIterator[StandardDataPage]:
        page_no = 1
        while True:
            page = await self.fetch_page(dataset, page_no=page_no, num_of_rows=page_size)
            yield page
            if max_pages and page_no >= max_pages: break
            if not page.has_more: break
            page_no += 1
    
    async def debug_dataset(self, dataset_key: str, *, page_no: int = 1,
                            num_of_rows: int = 5) -> dict:
        """raw response 한 page만 반환 (디버그 UI 용)."""
        ...
```

## 6. API key 우선순위

env 우선순위 (위가 더 우선):
1. `DATAGOKR_API_KEY`
2. `DATA_GO_KR_SERVICE_KEY`
3. `PUBLIC_DATA_SERVICE_KEY`
4. `SERVICE_KEY`

JSON/XML 모두 파싱 (provider별로 응답 format 차이).

## 7. etl.py 변환

### 7.1 tourism_roads (route)

```python
def tourism_road_row_to_bundle(row, *, dataset, fetched_at):
    route_type = _classify_route_type(row.road_name)
    feature_id = make_feature_id(
        bjd_code=row.bjd_code, kind=FeatureKind.ROUTE,
        category=STANDARD_ROUTE_CATEGORY,
        source_type="tourism_road", source_natural_key=row.road_id,
    )
    return FeatureBundle(
        feature=Feature(
            feature_id=feature_id, kind=FeatureKind.ROUTE,
            name=row.road_name, ...,
            detail=RouteDetail(
                feature_id=feature_id,
                route_type=route_type,
                total_distance_meters=row.distance_m,
                expected_duration_minutes=row.duration_min,
                ...
            ),
            ...
        ),
        ...
    )

def _classify_route_type(road_name: str) -> str:
    name = road_name.strip()
    if "무장애" in name or "장애물없는" in name:
        return ROUTE_TYPE_ACCESSIBLE_WALK
    if "등산" in name:
        return ROUTE_TYPE_HIKING_TRAIL
    if "트레킹" in name or "트래킹" in name:
        return ROUTE_TYPE_TREKKING
    return ROUTE_TYPE_TOURISM_ROAD                       # 기본
```

### 7.2 museums (place)

`place_kind="museum"` 또는 `"art_gallery"`. category: `CULTURE_MUSEUM` /
`CULTURE_ART_GALLERY`.

### 7.3 parking_lots (place)

`place_kind="parking_lot"`. category: `TRANSPORT_PARKING_LOT`. 시설 정보:
주차면 수, 운영시간, 유료/무료.

### 7.4 tourist_sites (place)

`place_kind="tourist_site"`. category: `TOURISM_*`. 경계가 있는 일부는 향후
`area`로 변환 후보.

### 7.5 cultural_festivals (event)

`event_kind="cultural_festival"`. `EventDetail.starts_on`/`ends_on`. category:
`EVENT_CULTURAL_FESTIVAL`.

## 8. EtlJobSpec

각 dataset마다 `JOB_SPEC: EtlJobSpec` 노출:

```python
def make_standard_data_job_spec(dataset: StandardDataset) -> EtlJobSpec:
    return EtlJobSpec(
        provider="data.go.kr-standard",
        dataset_key=dataset.key,
        source_entity_type=_default_source_entity_type(dataset),
        feature_kind=dataset.feature_kind,
        full_scan_interval_days=int(dataset.suggested_interval.days),
        interval_minutes=None,
        suggested_concurrency=2,
        suggested_group_name=f"features_{dataset.feature_kind.value}",
        description=dataset.description,
    )

JOB_SPECS: dict[str, EtlJobSpec] = {
    key: make_standard_data_job_spec(ds) for key, ds in CATALOG.items()
}
```

## 9. payload_hash → upsert

같은 payload_hash는 `source_records` 한 번만 저장 (`docs/data-model.md` §2
UNIQUE constraint).

## 10. Dagster

| asset (TripMate) | dataset_key | cron | group |
|-----------------|-------------|------|-------|
| `feature_route_standard_tourism_roads` | `standard_tourism_roads` | `0 2 1 1 *` (연 1회) | `features_route` |
| `feature_place_standard_museums` | `standard_museums` | `0 2 1 1 *` (연 1회) | `features_place` |
| `feature_place_standard_parking_lots` | `standard_parking_lots` | `0 2 1 1,7 *` (반기) | `features_place` |
| `feature_place_standard_tourist_sites` | `standard_tourist_sites` | `0 2 1 1 *` (연 1회) | `features_place` |
| `feature_event_standard_festivals` | `standard_cultural_festivals` | `0 2 * * 1` (주 1회) | `features_event` |

ConcurrencyConfig: `datagokr_api: max_concurrent=2`.

## 11. 검증

### fixture (≥ 3)

- `tourism_road_accessible.json` — 무장애산책길 (`route_type=accessible_walk`)
- `tourism_road_hiking.json` — 등산로 (`route_type=hiking_trail`)
- `tourism_road_trekking.json` — 트레킹 코스
- `museum_typical.json` — 박물관 정상
- `parking_lot_typical.json` — 주차장 정상
- `cultural_festival_typical.json` — 축제

### 통합 테스트

- `_classify_route_type` 분기 전수
- payload_hash 같으면 source_record 1개만 (idempotent)
- API key fallback chain (env 순서)

## 12. 디버그

```bash
# 디버그 패키지에서 (별도)
curl -X POST http://127.0.0.1:12301/debug/standard-data \
     -H 'content-type: application/json' \
     -d '{"dataset_key": "standard_tourism_roads", "page_no": 1, "num_of_rows": 5}'
```

`StandardDataClient.debug_dataset()`가 raw response 한 page만 반환.

## 13. 후속

- 새 표준데이터 dataset 추가는 ADR + `CATALOG` 확장. **범용 gateway 확장 금지**
  — 5종 bounded.
- 무료 표준데이터 ↔ 유료 dataset 분리 검토 (data.go.kr 비용 정책 확인).
- 표준데이터별 `source_entity_id` 안정성 검증 (provider 변경 시 deprecation).
