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
| `datagokr_museums` | `15017323` | `place` | **`01040000`** `TOURISM_CULTURAL_FACILITY` (fclty_type으로 박물관 `01040100`/미술관 `01040200` 정밀화) | 연 1회 |
| `datagokr_parking_lots` | `15012896` | `place` | **`06010000`** `TRANSPORT_PARKING` | 반기 1회 |
| `datagokr_tourist_attractions` | `15021141` | `place` (경계 source 확인 후 `area` 후보) | **`01000000`** `TOURISM` (대분류, 세부는 trrsrt_se로 분기) | 연 1회 |
| ~~`datagokr_cultural_festivals`~~ | `15013104` | ~~`event`~~ | **퇴역(2026-11-10, migration 449)** — 축제 원천은 TourAPI다(`docs/etl/event-feature-etl.md` §0). dataset 비활성·operation 꺼짐, 기존 Feature는 퇴역 | — |
| `datagokr_traditional_markets` | `15012894` | `place` | **`05070000`** `CONVENIENCE_TRADITIONAL_MARKET` (§7.6) | 월 1회(원천 연간 갱신, 기관 등록분 매월 초 병합) |

자세한 Tier 1~4 트리는 `docs/architecture/category.md` §4.

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
    "datagokr_museums": StandardDataset(
        key="datagokr_museums", data_go_kr_id="15017323",
        endpoint_url="...",
        feature_kind=FeatureKind.PLACE, suggested_interval=timedelta(days=365),
    ),
    "datagokr_parking_lots": StandardDataset(
        key="datagokr_parking_lots", data_go_kr_id="15012896",
        endpoint_url="...",
        feature_kind=FeatureKind.PLACE, suggested_interval=timedelta(days=183),
    ),
    "datagokr_tourist_attractions": StandardDataset(
        key="datagokr_tourist_attractions", data_go_kr_id="15021141",
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

**원천은 포털 공개 파일이다(2026-11-10).** Open API `tn_pubr_prkplce_info_api`는 운영 키가
HTTP 403 `SERVICE_KEY_IS_NOT_REGISTERED_ERROR`(마지막 성공 2026-11-03)라
`client.parking.iter_file_pages()`(15012896, 서비스키 없음)로 옮겼다 — 실측 18,994행, 좌표 없음
750. 행은 같은 `PublicParkingLot` 모델이고 자연키 `prkplce_no`도 같은 문자열이라 feature
identity는 그대로다(prod 17,986 entity 중 17,875가 파일에 있다. 나머지 111은 다음 적재에서
갱신되지 않을 뿐 은퇴하지 않는다 — 이 asset은 은퇴 경로가 아니다). 파일의 `PRKPLCE_NO`는
18,994행 중 17,878개만 고유하고 같은 번호의 행 내용이 다르다(1,030개 번호). Open API 시절에는 나중
행이 덮었다(순서 의존). 이제 fetcher가 번호마다 원문 정렬 JSON이 가장 작은 행 하나만 내준다 —
순서와 무관하게 같은 행이 남는다(첫 적재에서 이 번호들의 내용이 한 번 바뀔 수 있다). 페이지 크기
1만·5천·단일 페이지 다운로드 결과가 같음을 확인했다. 행에는 `colNmList`에 없는 `INSTT_CODE`도
실려 `instt_code`가 Open API 때처럼 채워진다. 선언 건수와 받은 행 수가 다르거나 0이면 `StandardFileSnapshotIncomplete`로
실패한다.

### 7.4 tourist_sites (place)

`place_kind="tourist_site"`. category: `TOURISM_*`. 경계가 있는 일부는 향후
`area`로 변환 후보.

### 7.5 cultural_festivals (event) — 퇴역

2026-11-10 소유자 결정("datagokr 축제 소스는 아예 쓰지마")으로 쓰지 않는다. 키가 403
`SERVICE_KEY_IS_NOT_REGISTERED_ERROR`(마지막 성공 2026-10-31)였다. 변환기·fetcher·asset·job·
schedule을 지웠고 migration 449가 operation을 끄고 dataset을 비활성으로 내리며 기존 Feature를
퇴역한다. 축제 정본은 `docs/etl/event-feature-etl.md`(TourAPI `searchFestival2`).

### 7.6 traditional_markets (place, #1459)

원천: 공공데이터포털 15012894 전국전통시장표준데이터(소상공인시장진흥공단, 갱신 연간,
수정일 2025-11-26 확인)의 **포털 공개 파일**이다 — `client.traditional_market.iter_file_pages()`
(provider PR#24 `9922dd2`)가 상세 화면의 파일 다운로드와 같은 경로(`download/columList.json` →
`download/standard.json`)로 **서비스키 없이** 전량을 받는다(2026-11-09 실측 1,393행, 좌표 없음 16).
표준 Open API `tn_pubr_public_trdit_mrkt_api`는 운영 키가 활용신청되지 않아 HTTP 403이라 쓰지
않는다(fallback도 두지 않는다 — 같은 키로는 403이다).

- 파일 검산(provider): 선언 0·5만 건 상한 거부, 페이지 길이 불일치·기형 행 거부, 순회 전후
  메타데이터 변경 거부, UTF-8(BOM)/CP949 해독. Map fetcher는 받은 행 수가 선언 `totalCount`와
  같지 않거나 0이면 `StandardFileSnapshotIncomplete`로 실패한다(은퇴 전에).
- 컬럼: 파일은 원천 테이블의 대문자 snake(`MRKT_NM`)라 Open API의 camelCase(`mrktNm`)와 다르다.
  provider가 소문자로 typed 필드(`mrkt_nm`)에 대응하고 원문 행은 `raw`에 둔다 — Map 변환·
  `raw_data`·replay는 typed 필드만 읽으므로 원천 경로와 무관하다. 파일에만 `INSTT_NM`이 있다.

- 변환: `providers.standard_data.traditional_markets_to_bundles` → place, category `05070000`
  (`docs/architecture/category.md` §12), `place_kind="traditional_market"`, maki `shop`, `P-04`.
- 자연키(`source_entity_id`): `시장명::시도시군구`(도로명, 없으면 지번 주소의 앞 두 토큰, 공백 제거) —
  원천에 관리번호가 없고(`instt_code`는 제공 지자체 코드라 공유된다) 시장명은 전국에 겹친다("중앙시장").
  번지·도로명 정정, 괄호 동명, 비어 있던 도로명 채움 같은 연간 편집이 키를 바꾸지 않게 지역까지만 쓴다.
  같은 snapshot에서 시장명·지역이 겹치는 행만 `::전체 주소`를 붙이고(새 동명 시장이 같은 시군구에 생기면 그
  둘의 키가 바뀐다 — 감수한 비용), 주소가 없으면 좌표(소수 4자리)가 지역을 대신한다. 그래도 같은 키는 원천
  payload hash가 가장 작은 행 하나만 남긴다(페이지 순서 무관). 그래서 변환은 snapshot 전량을 한 번에 받는다.
- 좌표: 원천 위경도. 없거나 무효면 공용 정지오코더(`_address_geocoder`, #1463)로 도로명 → 지번 순으로 찾고
  (`facility_info.coord_source="geocode"`), 그 좌표도 역지오코딩한다. 정지오코딩 좌표는
  `raw_data`에 넣지 않는다(replay가 원천 그대로 다시 변환한다). 2026-11-09 공식 미리보기 499행 중
  좌표 없는 행은 3행.
- `facility_info`: 시장유형·개설주기·점포수·취급품목·사용가능상품권·홈페이지·공중화장실/주차장
  보유여부(원문 `Y`/`N`)·개설연도·데이터기준일자.
- dedup: `maintenance.DEFAULT_DEDUP_SCOPE_PAIRS`에 MOIS 대규모점포(`05050000`·`05030000` — 업태
  '시장'인 대규모점포도 백화점 기본값으로 적재된다)와 관광지 표준데이터 pair. 범주가 달라 점수 상한
  0.80 → manual_review만 생긴다.
- 은퇴: 1,400건 안팎이라 snapshot을 한 번에 받아 `retire_absent_from_snapshot=True`로 적재한다
  (krforest와 같은 경로) — 다음 적재에 없는 시장은 은퇴한다. **0행 snapshot은 실패시킨다**(datagokr는
  resultCode 03을 빈 페이지로 주므로 "못 받았음"이 "없음"으로 읽혀 전부 은퇴할 수 있다). replay run은
  은퇴·봉인·sync 성공 기록을 하지 않는다.
- schedule `feature_place_standard_traditional_markets_monthly_schedule`(`40 5 5 * *`, 기본 STOPPED).

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

같은 payload_hash는 `source_records` 한 번만 저장 (`docs/architecture/data-model.md` §2
UNIQUE constraint).

## 10. Dagster

| asset (PinVi) | dataset_key | cron | group |
|-----------------|-------------|------|-------|
| `feature_route_standard_tourism_roads` | `standard_tourism_roads` | `0 2 1 1 *` (연 1회) | `features_route` |
| `feature_place_datagokr_museums` | `datagokr_museums` | `0 2 1 1 *` (연 1회) | `features_place` |
| `feature_place_datagokr_parking_lots` | `datagokr_parking_lots` | `0 2 1 1,7 *` (반기) | `features_place` |
| `feature_place_datagokr_tourist_attractions` | `datagokr_tourist_attractions` | `0 2 1 1 *` (연 1회) | `features_place` |
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
curl -X POST http://127.0.0.1:12701/debug/standard-data \
     -H 'content-type: application/json' \
     -d '{"dataset_key": "standard_tourism_roads", "page_no": 1, "num_of_rows": 5}'
```

`StandardDataClient.debug_dataset()`가 raw response 한 page만 반환.

## 13. 후속

- 새 표준데이터 dataset 추가는 ADR + `CATALOG` 확장. **범용 gateway 확장 금지**
  — 5종 bounded.
- 무료 표준데이터 ↔ 유료 dataset 분리 검토 (data.go.kr 비용 정책 확인).
- 표준데이터별 `source_entity_id` 안정성 검증 (provider 변경 시 deprecation).

## 14. 이관된 결정 (구 ADR)

- **표준데이터 2종을 place/event 1차 source로 채택** (구 ADR-042): 전국관광지정보
  표준데이터(place)와 전국문화축제표준데이터(event)를 1차 source로 쓴다. 표준
  데이터는 행안부/공공데이터포털이 안정 운영하여 갱신 주기가 명시되고 schema
  변경이 announce되며, visitkorea TourAPI 대비 좌표 nullable·축제 데이터 정합성
  문제가 적다. (5종 dataset·dataset_key·갱신주기는 §2에 정본.)
- **[대체됨 2026-11-10 → `event-feature-etl.md` §0]** 아래 축제 결정은 더 이상 유효하지
  않다. 축제는 TourAPI가 유일한 1차 원천이고 표준데이터 축제·이름 매칭 enrichment는 퇴역했다.
- **축제 1차 source 전환 + visitkorea enrichment 강등** (구 ADR-042): 축제의
  1차 source를 visitkorea festival → `standard_cultural_festivals`로 바꾸고,
  visitkorea는 image/상세 description/contentId 매핑을 채우는 enrichment
  (`source_role='enrichment'`)로 활용한다. "여러 source가 같은 entity를 채운다"는
  본 라이브러리의 1차 use case에서 표준데이터 primary + visitkorea enrichment가
  정석 패턴이기 때문이다.
- **참고 — 이후 변경된 항목**: ADR-042는 provider 경계를 별도
  `python-datagokr-api` 라이브러리에 두기로 했으나, 현재는 별도 provider 라이브러리
  없이 본 저장소 내부의 bounded asyncio client(`kortravelmap.standard_data`)로
  처리한다(§1·§3). ADR-042의 임시 dataset_key(`datagokr_tourism_points` /
  `datagokr_cultural_festivals`)는 현 §2 명명(`datagokr_tourist_attractions` /
  `standard_cultural_festivals`)으로 대체됐다.

### 7.7 special_streets (place anchor, 공개 파일 — 2026-11-09)

`standard_special_streets`도 같은 이유(운영 키 403, prod 0행)로 Open API에서 **포털 공개 파일**
(15017322, `client.special_street.iter_file_pages()`)로 옮겼다 — 실측 274행, 좌표 없음 28. 좌표 없는 행은
공용 정지오코더로 찾는다. 적재는 전통시장과 같은 snapshot 은퇴 경로(`retire_absent_from_snapshot`, 0행·
선언 미달 실패)다. 자연키 `거리명::도로명(없으면 지번)`은 그대로 둔다(prod 0행이라 재키 비용이 없고,
실데이터에 같은 키가 없다). `DISABLED_FEATURE_LOAD_SCHEDULES`에서 뺐고 schedule은 STOPPED로 생긴다.

