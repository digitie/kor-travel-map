# address-geocoding.md — geo 유도 값·지오코딩 스탬프·릴리스 재지오코딩

> **구현 정본(ADR-109 accepted, 2026-10-16).** `T-GR-01`~`T-GR-08`이 모두 머지됐다(#1326·#1327·#1328·#1331·#1332·#1333·
> #1334). 결정과 근거는 [ADR-109](../adr/109-geo-release-regeocode.md)가 정본이고 이 문서는 코딩용 상세(표·판정 규칙·run_key·
> 테스트 목록)만 갖는다 — 결정·상수를 여기서 다시 쓰지 않는다. 운영 절차는
> [runbook `geo-release-regeocode.md`](../runbooks/geo-release-regeocode.md). geo 쪽 계약(`data_token`·응답 `dataset`)은
> kor-travel-geo ADR-069(그 저장소, accepted).
>
> 설계와 구현이 달라진 자리는 각 절의 "구현" 메모와 acceptance §T-GR-0N "구현 메모"가 정본이다. 큰 것만 모으면: 항목 1행 =
> Dagster run 1개(`provider_dataset_ids` 배열), 항목 입력 kind는 `refresh`, 기준선은 계획 표의 `baseline` 행, migration 409
> (항목 사유 `superseded`·`canceled`), 센서 기본 STOPPED, run 빈 답 가드의 분자는 행 단위 최종 빈 답, chunk 단위 geo 사실,
> **MOIS는 replay가 없고 센서가 내지 않는다**(운영자 수동 실행 뒤 skip), replay 범위는 9 operation.

## 1. 저장되는 geo 유도 값과 provider별 출처 (현재 사실)

`feature.features`: `address` jsonb(`kortravelmap.dto.Address` 직렬화 — `road/legal/admin/bjd_code/admin_dong_code/
sigungu_code/sido_code/road_name_code/road_address_management_no/zipcode/sido_name/sigungu_name`,
`src/kortravelmap/dto/address.py:63-119`), `legal_dong_code`, `road_name_code`, `road_address_management_no`,
`admin_dong_code`, `sido_code`, `sigungu_code`(`src/kortravelmap/infra/models.py:408-419`). 같은 값이
`feature.feature_base_field_values`(`alembic/head-schema.sql:15657`)·`ops.feature_overrides`(`:17081`)·
`feature.feature_aliases`(`f_{bjd}_` legacy alias)·findings payload에도 흐른다.

geo 호출면은 `KorTravelGeoRestClient`(`src/kortravelmap/geocoding.py:1175`)의 `/v2/reverse`·`/v2/geocode`·
`/v2/regions/within-radius`뿐이고 `.reverse(` 호출처는 `geocoding.py:1405`(`ObservedReverseGeocoder`)와
`packages/kor-travel-map-api/src/kortravelmap/api/routers/admin_issues.py:311` 둘이다. 변환기는
`ReverseGeocoder = Callable[[Coordinate], Awaitable[Address | None]]`(`geocoding.py:201`)만 받는다.

**변환 함수 단위 인벤토리**(`src/kortravelmap/providers/`). "항상"은 좌표가 있고 콜러블이 주입됐으면 payload
변경과 무관하게 부른다는 뜻이다. `address_resolver=`를 **받는 모듈은 7개**(mois·standard_data·
datagokr_file_data·krforest·krheritage·opinet·krex)이고 그중 krex는 받기만 하고 쓰지 않는다.

| 변환 함수 | reverse | `address_resolver`(`/v2/geocode`) | geo에서 취하는 것 |
|---|---|---|---|
| MOIS `license_record_to_bundle`(`mois.py:685`; 공개 `license_records_to_bundles` `:827`) | payload `legal_dong_code` **없을 때만**(`:716-720`) | 그래도 bjd 없으면(`:721-730`) | `_build_address`(`:576`)가 코드 + `admin/admin_dong_code/sido_name/sigungu_name`; geo None이면 전부 None. 호출 여부는 `AdminEvidence.reverse_attempted`(`:817`, `dto/admin_evidence.py:102`) |
| concierge `_item_to_bundle`(`kor_travel_concierge.py:235`, `:275`) → `_address`(`:523-556`) | 항상 | 받지 않음 | payload `legal_dong_code` 우선(시군구·시도는 bjd에서 유도); geo는 bjd 없을 때의 bjd + `admin/admin_dong_code/road_name_code/zipcode/sido_name/sigungu_name`. `raw_payload_hash`는 producer `payload_hash` 채택(`:278-290`) |
| knps(`knps.py:284-285`, `:302`) · krforest `_forest_route_to_bundle`(`krforest.py:486`, `:504`, `:541`) | 항상 | 받지 않음 | reverse가 돌려준 `Address` **그대로** |
| krheritage `_heritage_item_to_bundle`(`krheritage.py:527-589`)·event(`:757-778`) | 항상 | 받음·**사용**(reverse None/빈 bjd → `Address(legal=소재지)`, `:585-586`, `:774-775`) | `_merge_address`(`:483`) — geo `Address` 그대로 + `legal` 빈칸만 원문 |
| krforest `_resolve_address`(`krforest.py:291-338`; 휴양림 `:661`·수목원 `:710`) | 항상 | 받음·**사용**(`:314-315`) | 코드 + `admin/admin_dong_code/road_name_code/zipcode/sido_name/sigungu_name`; `road`는 원문 |
| datagokr_file_data `_resolve_address`(`datagokr_file_data.py:391-420`) | 항상 | 받음·**사용**(`:401-402`) | 위와 같은 집합; `road`는 원문 |
| standard_data `_item_to_bundle`(`standard_data.py:263-310`)·`:574-587` | 항상 | 받음·**사용**(`:296-297`, `:586-587`) | 위와 같은 집합; `road/legal`은 원문 |
| opinet `_station_item_to_bundle`(`opinet.py:393-445`; 공개 `:576-628`) | 항상(place만) | 받음·**사용**(`:431-432`) | `bjd/sigungu/sido/admin/road_name_code`만(`:420-436`); 같은 모듈 price 변환기는 geo 없음 |
| krex `rest_areas_to_bundles`(`krex.py:472-513`) | 항상(place만) | 받지만 **미사용**(`:496`) | 코드 중심 자기 `Address` 조립; 같은 모듈 price·notice 변환기는 geo 없음 |
| khoa(`khoa.py:128-145`) · krairport(`krairport.py:113-135`) · mcst(`mcst.py:570-585`) | 항상 | 받지 않음 | 코드 + `admin`(없으면 provider 텍스트)·`admin_dong_code/zipcode/sido_name/sigungu_name` — 자기 `Address` 조립 |

**호출자 인벤토리** — `geo_applied`(§2)는 여기서 유도된다.

| 호출자 | `reverse_geocoder=` | `address_resolver=` |
|---|---|---|
| Dagster feature load asset(`packages/kor-travel-map-dagster/src/kortravelmap/dagster/assets.py`, `_reverse_geocoder(context)` 20곳 + `reverse_geocoder=None` 1곳) | 넘김 — 단 `feature_price_transport_fuel_stations`·`…_rest_areas`(`:410-432`, `:533-`)는 좌표만 싣고, `feature_notice_transport_highway_incidents`는 `reverse_geocoder=None`(`:643`) | **넘기지 않음(0건)** — asset·큐 runner 경로의 `geo_applied.geocode`는 MOIS를 포함해 **전부 False** |
| 큐 runner(`dagster/feature_update_runner.py:121-126`, 같은 asset run 함수) | resource로 넘김 | 넘기지 않음 |
| offline upload(`dagster/offline_uploads.py:62-63`) | 넘김 | `kor_travel_geo_address_resolver(kraddr, fallback="api")`(VWorld 포함) |
| API offline-upload **validation** job(`packages/kor-travel-map-api/src/kortravelmap/api/routers/offline_uploads.py:1503-1504` → `run_offline_upload_validation_job`) | 넘김 | 넘김(`fallback="api"`) — 검증만 하고 적재하지 않으므로(`src/kortravelmap/offline_upload.py:317`) **스탬프·토큰 대상 아님** |
| CLI `ktmctl import`(`src/kortravelmap/cli/main.py:455-456`, `:557-558`, `:568-569`) | 넘김 | 넘김(`fallback="api"`) |
| client import 메서드(`src/kortravelmap/client/__init__.py:1573-1763`) | 인자 전달(기본 None) | 인자 전달(기본 None) |
| admin `/admin/features/new`·curation import | 브라우저가 geo proxy로 받은 코드를 폼에 채움 | provider dataset 없음(ADR-109 열린 결정 2) |

적재 뒤 unchanged 행은 재작성되지 않고(`infra/feature_repo.py:3085-3095`), MOIS는 payload hash가 같은 행의
변환·지오코딩을 건너뛴다(`:3199-3231`). **비-MOIS(ADR-116, 2026-10-23)**: payload·좌표가 그대로이고 스탬프가 `called`·현재
토큰인 행은 역지오코딩하지 않고 저장 주소 열을 역지오코더의 답으로 쓴다 — 공통 helper
`dagster/geo_reuse.py`(변환 두 번: 빈 답 pass 0으로 행을 알아내고 조회 뒤 저장값·실제 geo를 섞어 pass 1, 사후 확인),
조회는 `infra/feature_geocode_reuse.py`(fence 없는 읽기). 역지오코딩 캐시(`cached_reverse_geocoder` `geocoding.py:233`,
`PrefetchingReverseGeocoder` `:279`)는 None도 캐싱하고 예외는 올린다. 클라이언트에 건별 재시도는 없다.

## 2. 스탬프 표와 outcome 판정 (구현 T-GR-01·03)

`feature.feature_geocode_stamps(feature_id uuid PK FK CASCADE, geo_version_token text NOT NULL, geo_data_token text
NOT NULL, reverse_outcome text CHECK IN (called, geocoded, not_called), stamped_at timestamptz NOT NULL)` +
`INDEX (geo_data_token)`. NULL 토큰 스탬프는 만들지 않는다(ADR-109 결정 1 — run 토큰이 없으면 쓰지도 덮지도 않는다;
`not_called`도 토큰을 가진다). migration `407_feature_geocode_stamps`
(직전 head `406_feature_write_gate`(ADR-111); forward-only; 토큰 형식 CHECK `dv1-`/`dd1-` + 32 hex; `SET ROLE ktm_feature_schema_owner` 아래 DDL, `OWNER TO`, RESET ROLE 없음,
receipt head CHECK에 407 추가; lint 4종 `tests/lint/test_migrations_keep_the_schema_owner_role.py`·
`test_routine_ddl_runs_under_its_owner_role.py`·`test_receipt_head_check_covers_the_graph_head.py`·
`test_migration_revision_ids_fit_the_version_column.py`). ORM `infra/models.py` `FeatureGeocodeStampRow`.

repo `infra/feature_geocode_stamp_repo.py`(T-GR-01 구현): `upsert_stamps(session, *, current: DatasetRef | None,
outcomes: Mapping[feature_id, ReverseOutcome]) -> int`(current 또는 `current.data_token`이 None이면 0건 — 쓰지도 덮지도
않는다), `get_stamp(session, feature_id)`, `is_stale(session, feature_id, current_data_token)`,
`select_stale_feature_ids(session, current_data_token, *, provider_dataset_id, limit, after=None)`(`feature_id > after`
keyset 페이지; **호출자가 geo 의존 dataset으로 한정**한다 — T-GR-04 `GEO_DEPENDENT_OPERATION_KEYS`),
`decide_outcome(geo_applied, *, has_coord, provider_code_present, legal_dong_code_present, evidence:
GeoAttemptEvidence | None) -> ReverseOutcome | None`. **T-GR-04가 더한다**: `coverage(session, current_data_token, *,
provider_dataset_ids) -> {total_provider_with_coord, stamped_current, stamped_other, unstamped, not_called_by_kind,
excluded_by_skip, unstamped_non_provider}` — 분모 `total_provider_with_coord`는 **인자로 받은 dataset에 primary
source_link를 가진 좌표 보유 활성 feature**다(`excluded_by_skip`이 408 계획 표에 기대므로 T-GR-01에서 미뤘다).
인덱스 `idx_feature_geocode_stamps_data_token`은 T-GR-04 `coverage`의 토큰 동등 계수용이다.

**outcome 판정 표(`decide_outcome`).** 입력은 호출자의 run 신호 `GeoApplied{reverse, geocode}`
(`src/kortravelmap/dto/geo_dataset.py`) + 행 사실. **위에서 아래로 처음 맞는 행이 답이다**(평가 순서가 규칙이다 —
ADR-109 결정 3). "reverse를 불렀다"는 입력이 갖춰졌다는 뜻이지 답이 비지 않았다는 뜻이 아니다(빈 답도 `called`,
그 행은 §4 빈 답 가드가 막는다).

| 순서 | 조건 | outcome |
|---|---|---|
| ① | `geo_applied.reverse=False and geocode=False`(price/notice asset) | **스탬프 없음** |
| ② | MOIS(**행별** 변환 evidence로 정하고 chunk commit 안에서 bulk upsert): 입력은 `GeoAttemptEvidence{reverse_attempted, geocode_obtained_code}`(`dto/geo_dataset.py` — T-GR-03이 `AdminEvidence.reverse_attempted`와 `mois.py:721-730` geocode 분기의 결과로 만든다). `reverse_attempted` → `called`; 아니고 `geocode_obtained_code`(geocode로 `bjd_code`를 받았다) → `geocoded`; 그 외(payload bjd 행, geocode 시도 실패 행) → `not_called` — ④와 같은 결과 기준 | evidence 기준 |
| ③ | `geo_applied.reverse=True and coord IS NOT NULL`(reverse를 불렀다 — payload 코드를 썼어도 geo가 명칭·우편번호·도로명코드를 채우므로 비교 대상; concierge 포함) | `called` |
| ④ | `geo_applied.geocode=True and coord IS NULL and legal_dong_code IS NOT NULL and provider 코드 없음` | `geocoded` |
| ⑤ | 그 외(provider 코드만 썼고 geo 유도 값 0개 — 좌표 없는 concierge payload 코드 행; 좌표·주소 둘 다 없는 행; 좌표 없이 geocode를 시도했으나 코드를 못 받은 행 — 릴리스 재해석 대상 아님, ADR-109 열린 결정 1) | `not_called` |

"provider 코드 있음"은 bundle의 source_record payload에 `legal_dong_code`가 있는가다. 좌표가 있고 reverse가 빈
답이어서 `address_resolver`가 코드를 채운 행은 ③에 먼저 걸려 `called`다 — 두 값 모두 토큰 비교 대상이라 stale
판정은 같고, "reverse 시도가 있으면 `called`"가 MOIS evidence 규칙(②)과도 같다. offline upload·CLI는
`reverse=True, geocode=True`로 ③→④→⑤를 탄다.

**geo 의존 유도의 정본은 core 상수다**(T-GR-04): `src/kortravelmap/core/feature_operation.py`에
`GEO_DEPENDENT_OPERATION_KEYS: frozenset[str]`를 `DEDICATED_JOB_ONLY_OPERATION_KEYS`(`:33-41`) 옆에 둔다 — 센서(Dagster
프로세스)와 `/detect`(API 프로세스, `kortravelmap.dagster`를 import하지 않는다)가 같은 값을 읽는다. 그 상수가 사실과
같다는 것은 lint가 고정한다(`tests/lint/test_geo_heavy_assets_declare_the_pool.py`). **현재 그 lint**는 pool 선언
결박용이다 — `_passes_reverse_geocoder`(`:81-87`)는 `reverse_geocoder` 키워드의 **존재**만 보고(`assets.py:643`의
`=None`도 포함), `_geo_heavy_assets()`(`:101-132`)는 asset **이름** → pool을 돌려주며 run 함수와 `@asset`이 같은
모듈에 있을 때만 잇는다(`feature_notice_transport_highway_incidents`가 빠지는 것은 #1314의 `_run_…_locked` 간접
호출 때문이지 의도가 아니다). T-GR-04는 pool 술어를 **그대로 두고** ① 별도 술어 `_passes_geo_callable`
(`reverse_geocoder=` 또는 `address_resolver=`에 `None` 상수가 아닌 값) ② asset → `FEATURE_LOAD_SCHEDULE_SPECS.job_name`
매핑 ③ 모듈 간 참조 허용(또는 그 한계를 단언)을 더해 유도 집합 == 상수(양방향, 집합 동등)를 단언한다. 런타임
AST 파싱·`tests/` import는 없다. asset별 `geo_applied` 값도 같은 AST 유도로 lint한다(T-GR-02):
`_reverse_geocoder(context)`를 쓰면 `reverse=True`, `address_resolver=`를 넘기면 `geocode=True` — 현재 asset은 전부
`geocode=False`다(§1 호출자 표).

변환 **함수** 단위 lint(T-GR-03, `tests/lint/test_converters_call_geo_when_input_present.py`): `reverse_geocoder=`를
받는 함수마다 "좌표 있는 record 수 == reverse 호출 수"(opinet·krex는 모듈 단위면 price 변환기 때문에 반드시
빨갛다 — 함수 단위); `address_resolver=`를 받아 **쓰는** 함수 6모듈(mois·standard_data·datagokr_file_data·
krforest·krheritage·opinet; §1 표)마다 "reverse None/빈 bjd 또는 좌표 없음 → geocode 1회"; krex는 받되 미사용이므로
"geocode 0회"를 센다(유도 제외가 아니라 명시 단언 — 쓰기 시작하면 빨갛다).

## 3. run-scoped 현재 토큰 (구현 T-GR-01·02)

- `KorTravelGeoRestClient.dataset_version()` 신규: `POST /v2/dataset/version` 본문 `{}` → `DatasetRef{version_token,
  data_token | None}`. `_RestReverseV2Response`(`geocoding.py:935`)에 `dataset` **선택 파싱**(없는 옛 응답 → None),
  `GeoCallStats`(`:1112`)에 `observed_data_tokens`와 `empty[endpoint]`(예외 없이 끝났는데 `Address` None 또는
  `bjd_code` None — §4 run 가드의 분자; 현재는 `calls`/`failures`(전송 실패)만 센다 `:1140-1146`),
  `ObservedReverseGeocoder`(`:1405`)가 기록.
- (구현: 경량 `kor_travel_geo_client` resource는 만들지 않았다 — 센서·운영 API는 `geocoding.open_geo_client` helper 하나를
  쓴다, 소유자 위임 결정 T-GR-05.) Dagster resource `kor_travel_geo_dataset`(run
  시작 1회 → `DatasetRef | None`; 실패·`available=false` → None + 경고 1건, run 계속). 같은 팩토리
  `fetch_current_dataset(client)`를 `feature_update_runner._COMMON_RESOURCE_KEYS`(`dagster/feature_update_runner.py:121-126`)·
  asset `required_resource_keys`·`offline_uploads.py`·CLI(`src/kortravelmap/cli/main.py:443-456`)가 쓴다.
  `definitions.py:113-120` `DEFAULT_RESOURCE_DEFINITIONS`에 등록.
- **fail-to-current**: `current_dataset is None` **또는 `current_dataset.data_token is None`**이면 stale 분기 없음,
  MOIS CTE 조건 없음, 스탬프 쓰기·덮기 없음 — unchanged 집합이 토큰 도입 전과 **동일**해야 한다(테스트).
- **불일치**: run 끝에 run-scoped 값과 다른 `observed_data_tokens`가 있으면 WARNING + op 메타
  `geo_dataset_mismatch=true`. 그 run의 스탬프는 옛 토큰 → 다음 tick이 새 토큰으로 재계획(안전 방향).
  **가정**: geo는 MV 교체/DB rename 뒤에 release 행을 넣으므로 "새 토큰, 옛 데이터"는 생기지 않는다.

## 4. 적재 경로의 stale 분기·가드 (구현 T-GR-03)

`load_bundle(session, bundle, *, current_dataset: DatasetRef | None = None, geo_applied: GeoApplied)`
(`feature_repo.py:3035`); `client.load_feature_bundles(bundles, current_dataset=, geo_applied=)`
(`src/kortravelmap/client/__init__.py:1058`), `load_feature_bundles_reobserving`(`:1104`, MOIS chunk 경로),
`find_unchanged_active_source_entities(current_data_token=)`(`:1081`; repo `feature_repo.py:3291`),
`find_fresh_open_findings(expected_payload_fields=)`(`:2654`; repo `infra/integrity_violation_repo.py:399`).

```
stale = current_dataset is not None and current_dataset.data_token is not None
        and outcome in ('called', 'geocoded')
        and (stamp is None or (stamp.reverse_outcome != 'not_called'
                               and stamp.geo_data_token IS DISTINCT FROM current.data_token))
if became_current or feature_missing or stale: 적재 경로
```

MOIS `_UNCHANGED_ACTIVE_ENTITIES_CTE`(`feature_repo.py:3199-3231`)의 `unchanged`에 (`current_data_token`이 있을
때만) 추가:

```sql
AND EXISTS (SELECT 1 FROM feature.feature_geocode_stamps st
             WHERE st.feature_id = feature.feature_id
               AND (st.reverse_outcome = 'not_called' OR st.geo_data_token = :current_data_token))
```

| 규칙 | 내용 |
|---|---|
| 값 동일 무쓰기 | stale & not `became_current` → 주소 유도 컬럼 **6개** + `address` jsonb를 저장값과 비교한다. 저장값은 `infra/feature_geocode_load.py`의 `read_stored_geo_columns`(chunk에서는 `read_stored_geo_columns_many` 한 문장)가 active override(`ops.feature_overrides`, `core.<col>`)와 함께 읽는다 — `FeatureAddressSnapshot`은 넓히지 않았다(T-GR-03 구현 메모). override가 있는 열은 비교 집합에서 **제외**. 전부 같으면 features UPDATE 생략, 스탬프만 upsert. **부분 퇴행 유지**: 새 답의 `bjd_code`가 저장값과 같은데 `admin_dong_code`·`zipcode`가 새 답에서만 비었으면 저장값을 지킨다. `road_name_code`는 도로명주소와 짝이라 새 도로명 텍스트가 저장값과 같을 때만, 아니면 `road_address_management_no`와 함께 사라졌을 때만 둘을 짝으로 지킨다(서로 다른 릴리스의 코드를 섞지 않는다). 메타 `geo_partial_kept` |
| 빈 답 가드(행) | 판정 집합 **G** = `address.sido_name/sigungu_name/admin_dong_code/road_name_code/zipcode` + `legal_dong_code`·`sigungu_code`(bundle payload에 provider 코드가 있으면 두 코드 열 제외). `road/legal/admin`은 제외(krheritage `:483`·standard_data `:296-297`·concierge `:548`·khoa·krairport·mcst가 원문으로 채운다 — §1 표). 저장 G에 non-NULL이 있는데 새 bundle의 G가 전부 None → features UPDATE·스탬프 모두 쓰지 않고 `reverse_geocode_failed`(`dagster/validation.py:205`) 1건. `became_current` 행도 주소 열은 보존, 나머지 패치만 |
| 빈 답 가드(run) | `GEOCODE_RATIO_MIN_SAMPLE=50`·`plan.geocode_degraded_ratio`(`mois_chunked_load.py:131, 663-678`)의 **상수·비율 계산만** 공통 모듈로 올려 `dagster/etl.py:436-439` 공통 chunk 루프가 쓴다. 비-MOIS 분모 = `GeoCallStats.calls['reverse']`, 분자 = **행 단위 최종 빈 답** `empty['reverse_result']`(`REVERSE_RESULT_EMPTY_KEY` — region fallback까지 거친 최종 `Address`가 None이거나 `bjd_code`가 없는 행; endpoint 빈 답 `empty['reverse']`가 아니다 — 산악 centroid처럼 reverse가 늘 비고 fallback이 채우는 dataset이 정상 run에서 실패하지 않게. run 전체 누적; 좌표 없는 행은 분모에 없다). 행동은 호출처가 정한다: 비-MOIS(공통 루프) = 표본 ≥ 50 & 비율 초과 → run **실패**(그 chunk 스탬프는 commit 전); MOIS 자기 루프 = ADR-108 §3a-2 그대로 **degraded, 실패 아님**(회귀 테스트로 고정) |
| 스탬프 쓰기 | 유효 토큰(`GeoLoadContext.effective_token()` — 토큰이 있고, 관측 집합이 있고, 그 안에 다른 토큰이 없다)이 있으면 가드 행을 뺀 전 행. `load_bundles`(MOIS 포함 모든 적재 경로)는 chunk 단위다 — stale 판정·저장값은 chunk 시작에 각각 한 문장, 스탬프는 chunk 끝 한 문장(그 transaction 안). 토큰이 없으면 **쓰지도 덮지도 않는다**(기존 스탬프 바이트 불변) |
| timeout 재시도 | run 태그 `kor_travel_map.geo_release_plan_id`가 있는 run에서만 reverse timeout 1회 재시도(backoff 1건) — ADR-108 예외, **ADR-109 열린 결정 6 승인 전에는 적용하지 않는다**(`trigger_kind=sensor`는 MOIS 이어 달리기 run에도 붙어 판별자가 아니다, `mois_chunked_load.py:1071-1075`) |
| override | override 값 ≠ 새 geo 값 → finding `address_override_geo_stale`(info, payload `{override_values, geo_values, geo_data_token}`), `(feature_id, geo_data_token)` dedupe; 같으면 무동작. 해소는 `apply_kor_travel_geo_address`(`admin_issues.py:576`) |
| MOIS 표식 | `_record_marker_batch`(`mois_chunked_load.py:905-944`) payload에 `geo_data_token`; `_known_unresolvable`(`:853-882`)이 `expected_payload_fields={"geo_data_token": current}` 전달(None이면 생략) |
| findings 재평가 | `reverse_geocode_failed/unavailable/not_attempted`·`provider_address_region_disagreement`·`admin_code_stale_*`(`validation.py:674-711`)는 평소처럼 재계산, 열린 stale finding은 ADR-080 generation이 닫는다 — 변경 없음 |

**concierge provider(ADR-109 결정 6)**: `_address(payload, geo=)`(`kor_travel_concierge.py:523`)는 payload
`geo_data_token`이 있고 run-scoped `data_token`과 같을 때만 payload 코드. 토큰 전달 경로: `kor_travel_concierge_items_to_bundles(…,
current_data_token: str | None = None)`(`:125-131`, additive kwarg) → `_item_to_bundle` → `_address`; 호출처
`dagster/assets.py:1508`이 `kor_travel_geo_dataset` resource의 `data_token`을 넘긴다(기본 None = 옛 동작 = **payload
코드 우선**, ADR-109 결정 6과 같다). 토큰을 넘기면 payload 토큰이 그것과 같을 때만 payload 코드, 아니면 geo 우선.
`raw_payload_hash`는 payload가 `geo_data_token`을 실어 올 때만 Map이 직접 잰다 — `address.geo_data_token`·producer
해시·export 상태 필드(최상위 `updated_at`·`operation` — producer `_serialize_item`이 토큰만 바뀌어도 `updated_at`을
새로 찍는다)를 뺀 `make_payload_hash(raw_data)`. 토큰 없는 payload는 종전 producer 해시 그대로다. 스탬프는 §2 표 그대로다 —
좌표가 있어 reverse를 불렀으면 payload 코드를 썼어도 `called`(geo가 채운 빈칸이 비교 대상), 좌표 없는 payload 코드
행만 `not_called`. 토큰만 바뀐 payload는 `became_current=False`·`row_revision` 불변·스탬프 current여야 한다.

## 5. 센서·계획·run_key·replay·완료 (구현 T-GR-04·05·08)

> T-GR-04 구현과 아래 계획의 차이(정본은 acceptance §T-GR-04 구현 메모): 계획 상태에 `baseline`(첫 관측 토큰의 기준선
> 행), 항목 입력 kind는 `refresh`, **항목 1행 = run 1개**(`provider_dataset_ids` 배열 — MCST 13 dataset이 항목 1개),
> 항목 UNIQUE에서 `attempt_seq` 제외(같은 행에서 단조 증가), 계획에 `sweep_started_at`, 최신 행이 이 토큰의 `done`이면
> 재계획 없음, replay 항목은 `launch_blocked_reason`(core `SENSOR_LAUNCHABLE_REPLAY_OPERATION_KEYS` 게이트).
> 센서(T-GR-05): `dagster/geo_release_sensor.py`, 기본 STOPPED, run_key `geo_release/{token}/{plan_seq}/{operation}/{position}/{attempt}`,
> 한 번에 run 1개, CANCELED → `failed(canceled)`, supersede → 그 계획의 `requested` 항목 `failed(superseded)`(migration 409),
> geo client는 `geocoding.open_geo_client`. T-GR-08(replay 구현) 뒤 1단계 replay 항목은 모두 launchable이고
> MOIS 항목은 run_config 없이 계획에 들되 센서가 내지 않는다(`SENSOR_MANUAL_OPERATION_KEYS` — 운영자 수동 실행 뒤
> `skip`, #1333 리뷰). 그 항목이 남은 계획은 운영자가 skip할 때까지 `running`이다.
> 판정은 `infra/geo_release_repo.py` `plan_geo_release`(센서·`/detect` 단일 정본), 완료는 `complete_plan`.

**표** `ops.kor_travel_geo_releases(plan_id identity PK, geo_data_token NOT NULL, plan_seq int DEFAULT 1,
geo_version_token NOT NULL, activated_at, reference_months jsonb, observed_at, state CHECK IN
(planned, running, done, superseded), residual_stale int, completed_at, UNIQUE (geo_data_token, plan_seq))` +
부분 UNIQUE `(geo_data_token) WHERE state IN ('planned','running')`; `ops.kor_travel_geo_release_items(plan_id FK
CASCADE, position, operation_key, provider_dataset_id bigint FK provider_sync.provider_datasets, run_config jsonb,
attempt_seq int DEFAULT 1, state CHECK IN (pending, requested, done, failed, skipped), state_reason, run_key,
dagster_run_id, requested_at, PK (plan_id, position), UNIQUE (plan_id, operation_key, provider_dataset_id,
attempt_seq))`. migration `408_kor_travel_geo_releases`(owner role·receipt CHECK, 407과 같은 규약).
`state_reason ∈ disabled | no_geo_dependency | queue_only | run_not_launched | no_progress | …`.

**센서** `kor_travel_geo_release_sensor`(구현 `dagster/geo_release_sensor.py`). tick 순서·Skip 조건·전이 규칙·완료 판정·주기·
MOIS 이어 달리기 상한은 **ADR-109 결정 5가 정본**이다 — 여기서는 그 결정을 코드에 매는 이름만 둔다.

- 선언(구현): resource 없이 tick 안에서 in-process client와 `open_geo_client`를 연다, `jobs=FEATURE_LOAD_JOBS`, 기본
  STOPPED·300초·진행 중 run 1개. **커서는 없다** — 기준선·멱등 판단은 계획 표 행(`baseline` 상태)이 갖는다(`/detect`와 공유).
- 감지(결정 5.1): `dataset_version()` 실패/`available=false` → Skip(커서 불변); `data_token is None` →
  `SkipReason("geo data_token 없음 — 지문 backfill/복구 필요")`(계획 없음, 커서 불변; UI 상단 빨간 상태).
- 계획(결정 5.2·5.3): `client.create_geo_release_plan(current)` → `plan_geo_release(session, dataset_ref)`
  (`infra/geo_release_repo.py`; `/detect`와 같은 함수). 항목 입력 `provider_dataset_operations(feature_load,
  is_enabled) ⋈ provider_datasets.is_active`, geo 의존은 `GEO_DEPENDENT_OPERATION_KEYS`(§2). 순서 ① 공개 필터·
  클러스터에 노출되는 `place` kind dataset, stale 수 DESC ② `event`·geo 의존 `price` ③ concierge ④
  datagokr_file_data·standard_data(**replay**)·MOIS(운영자 수동, 맨 끝) ⑤ geo 미사용 `skipped(no_geo_dependency)`;
  `DISABLED_FEATURE_LOAD_OPERATION_KEYS` → `skipped(disabled)`. `run_config_for_dataset(operation_key, dataset_key)
  -> dict | None`: KNPS는 `knps_schedule_binding` 꼴(`schedules.py:158-165`) dataset마다, 쿼터 민감은
  `{"resources": {"<records_resource>": {"config": {"source_mode": "replay"}}}}` 합성.
- Skip 조건(결정 5.4)의 조회: 활성 큐 worker run은 `map_runs_filter(job_name=…, statuses=active)`(`dagster/run_scope.py:58`),
  같은 `operation_key` run은 `map_owned_runs_filter(tags={"kor_travel_map.operation_key": job})`(`:80`).
- 전이(결정 5.5)의 이름: run 조회는 `dagster_run_id`(없으면 `dagster/run_key` 태그); `MOIS_LOAD_OUTCOME_TAG ==
  budget_exhausted`(`mois_chunked_load.py:99-103`) → `mois_load_continuation_decision(last)`(`:1132-1154`) 재사용;
  상한 상수 `MOIS_RELEASE_ATTEMPT_CAP`(12); `requested` 무run 판정 `GEO_RELEASE_RUN_LAUNCH_TIMEOUT_SECONDS`(900초 = 3 tick),
  비-MOIS 재요청 `NON_MOIS_RETRY_ATTEMPTS`(2). 구현에서 MOIS 항목은 `SENSOR_MANUAL_OPERATION_KEYS`라 센서가 내지 않으므로
  MOIS 이어 달리기 전이는 운영에서 도달하지 않는다(규칙은 테스트로 고정).
- RunRequest(결정 5.4): `RunRequest(job_name=operation_key, run_key=f"geo_release/{data_token}/{plan_seq}/{operation_key}/{position}/{attempt_seq}",
  run_config, tags={"kor_travel_map.trigger_kind": "sensor", "kor_travel_map.geo_release_plan_id": str(plan_id)})`
  — `geo_release_plan_id`가 전용 run의 유일한 판별자(§4 timeout 재시도). job 정의 태그(`operation_key`·RecoveryPolicy·
  `max_runtime`, `schedules.py:436-446`)는 상속.
- 완료(결정 5.6): `complete_plan` — sweep은 다음 `attempt_seq`, 링크 재동기화는
  `sync_poi_cache_target_feature_links`(`infra/poi_cache_target_repo.py:862`), 그 뒤 `done`·`completed_at`.

**replay 모드**(T-GR-08): records resource config `source_mode ∈ fetch | replay`. `mois_license_records`
(`dagster/resources.py:695`)·`PROVIDER_RECORD_RESOURCE_DEFINITIONS`의 datagokr_file_data·standard_data 자원이
replay면 `provider_dataset_id` 단위 keyset으로 entity head의 current `source_records.raw_data`를 읽어 record
모델 `from_raw(raw_data)`로 되살린다(**가정**: fetch 시 직렬화와 1:1 — golden으로 확인 안 되는 provider는 fetch
유지). MOIS replay 제외 술어 = `feature_geocode_stamps.reverse_outcome = 'not_called'`인 entity(§4 CTE 조건과 같은
술어 — 별도 제외 코드 없음; keyset 선필터는 같은 술어로만). `raw_data.legal_dong_code` 유무로 빼지 **않는다** —
스탬프 없는 payload-bjd 행은 replay에 포함되어 reverse 없이 변환되고 `not_called` 스탬프만 받는다(geo 0회).
`fetched_at`은 원 레코드 값 → `became_current` 항상 False.
**구현(T-GR-08)**: `dagster/source_replay.py`(`ReplayRecordStream`·`apply_replay_provenance`·
`ensure_replay_complete`), 읽기 `infra/source_replay_repo.py`(primary Feature `active` entity만 — retired는 되살리지
않는다; 같은 술어로 읽어야 할 건수도 센다), 복원 함수 `resources.REPLAY_FROM_RAW`. 읽기는 적재 전에 끝낸다(Dagster
client 연결 1개). bundle에는 저장된 `fetched_at`과 head `observed_at`(→ `imported_at`)을 되돌려 head가 전진하지
않고, sync state·curation seal을 쓰지 않으며, 부분·빈 replay(`ReplayIncomplete`)와 hash 불일치
(`ReplayPayloadDrift`)는 commit 전에 실패한다. **MOIS는 golden 실패로 replay가 없고 센서도 내지 않는다**(ADR-109
결정 7 결과).
replay로 다시 지오코딩해도 그 dataset의 stale 주소 finding(`reverse_geocode_failed` 등)은 **다음 fetch run까지 열려
있다** — replay는 sync 성공을 기록하지 않아 "이번 run이 관측하지 않은 finding 닫기"(stale-close)를 하지 않는다.

**롤아웃 첫 tick**: ~~커서·스탬프가 비어 있으므로 전 geo-의존 dataset 계획 1회가 생긴다~~ — **소유자 결정
(2026-10-15, ADR-109 결정 5.1)**: 커서가 빈 첫 관측 토큰은 **기준선**으로 기록하고 계획 0건이다. 스탬프 없는 행은
평소 적재가 채운다(`stamp is None` = stale은 적재 경로 규칙) — 값 동일 행은 무쓰기라 ETag·seal 불변. geo
backfill 전에 Map을 배포하면 `data_token` 없음으로 Skip만 하고(계획 0), backfill 뒤 처음 관측한 토큰도 커서가 비어
있으므로 **기준선으로 기록하고 계획 0건**이다. 계획은 기준선 이후 토큰이 바뀐 릴리스에서만 생긴다. 배포 순서(geo
backfill → PinVi 재vendor → Map pair → Manager `dagster.yaml` concierge lane(concierge ADR-49
`concierge_admin_region_refresh` job용 — Map 변경 아님, ADR-109 결정 5.4) → concierge; 설계 §9)는 이 결과를 바꾸지 않는다.

## 6. 운영 API·UI (구현 T-GR-04·06)

admin 프로필(`require_ops_operator`, `api/auth.py:426`) `packages/kor-travel-map-api/src/kortravelmap/api/routers/ops_geo_releases.py`,
prefix `/ops/geo-releases`: `GET /`(목록 + 현재 geo 토큰 + Skip 사유), `GET /{plan_id}`(항목·coverage),
`POST /detect`(센서와 같은 `plan_geo_release`), `POST /{plan_id}/items/{position}/skip`, `POST /{plan_id}/replan`.
`app.py` mount; `packages/kor-travel-map-api/scripts/export_openapi.py --profile all` — `openapi.user.json`·
`openapi.service.json` byte 불변 단언. PinVi admin 스냅샷 재vendor 선행([`integration-map.md` §4](../integration-map.md)).

UI `/admin/ops/geo-releases`(T-GR-06): 현재 `version_token/data_token/activated_at/reference_months`(`data_token`
없음 = 빨간 상태 + Skip 사유), 커버리지 게이지(`stamped_current/total_provider_with_coord`, `stamped_other`,
`unstamped`, `not_called`(kind별), `excluded_by_skip`, `unstamped_non_provider`), `plan_seq`별 항목 표(상태·
`state_reason`·attempt_seq·run 링크·skip), 버튼 "지금 감지"·"다시 계획". `docs/runbooks/admin-ui-screen-checklist.md`
route 행은 구현 PR(T-GR-06)에서. `/admin/issues`·features 목록 변경 없음.

## 7. 테스트 전략 요약과 의도적 빨강 (설계 당시 목록 — 실제 테스트는 각 acceptance 절)

원칙(memory `detector-floors-count-what-was-seen`): 새 검사는 먼저 일부러 빨갛게 만든다; geo fake는 `dataset`
**있음/없음** 둘 다 갖는다(Map은 geo 스펙을 vendoring하지 않는다 — ADR-106 방식, 자체 픽스처).

| 층 | 케이스 |
|---|---|
| 단위 | `_RestReverseV2Response.dataset` 선택 파싱; `dataset_version()`; `is_stale`/`select_stale_feature_ids` 5분기(스탬프 없음·`not_called`·`geocoded` 다른 토큰·다른 토큰·같은 토큰) + 현재 None → stale 없음; `decide_outcome` 표 전부; 계획 항목 생성(`provider_dataset_operations` 입력, geo 의존 유도, DISABLED skip, KNPS 5 dataset → 5 항목·run_config 상이, 쿼터 민감 → replay, concierge·MOIS 마지막); `run_config_for_dataset`; run_key 조립 |
| 통합(DB) | 407/408 + receipt CHECK + owner role lint 4종. CTE: 같은 payload+옛 토큰(`called`) → unchanged 아님; +현재 토큰 → unchanged; +`not_called` 옛 토큰 → unchanged; 토큰 None → 도입 전과 동일 집합. `load_bundle`: stale+값 동일 → `row_revision` 불변·스탬프만 전진; stale+값 변경 → UPDATE + alias(**`road_name_code`만 바뀐 행도 UPDATE** — 스냅샷 열 추가 결박); 현재 None → 쓰기 없음; `DatasetRef(data_token=None)` 픽스처 → 기존 스탬프 행 바이트 불변; **빈 답 가드**(저장 G non-NULL + 새 G 전부 None → `row_revision` 불변·스탬프 미전진·finding 1건 — knps 픽스처뿐 아니라 **krheritage·standard_data·concierge 픽스처(원문 `legal` 있음 + geo None)**에서도); run 비율 가드(좌표 있는 50건 중 빈 답 3건 > 5% → run 실패·그 chunk 스탬프 0; 좌표 없는 1,000건을 섞어도 분모 불변); **override**(불일치 → `row_revision` 불변·finding 1건, 두 번째 run 0건); price dataset 적재 뒤 스탬프 0·분모 불변; `geocoded` 행 토큰 변경 시 stale; MOIS 표식 토큰 조건; concierge payload 토큰 ≠ 현재 → geo bjd·`called`·스탬프 current, == 현재 → payload 코드·좌표 있으면 `called`(geo 빈칸 채움)·좌표 없으면 `not_called`, **토큰만 바뀐 payload → `became_current` False**, asset run에서 resource 토큰 ≠ payload 토큰 픽스처 → geo `bjd_code` 채택(전달 경로 결박); MOIS 비율 가드 조건에서 MOIS run은 FAILURE가 아니다(ADR-108 §3a-2 회귀); 스탬프 토큰 NULL 삽입은 NOT NULL이 거부; 큐 경로 적재도 스탬프; replay golden(축제·standard·fileData — MOIS는 실패로 제외) + provider HTTP 0회; MOIS(fetch): 스탬프 없는 payload-bjd N행 픽스처 → 1 run 뒤 `not_called` 스탬프 N·reverse 0회·`coverage.unstamped` 0; 완료 단계 `same_sigungu` 링크 이동 |
| 계약 | `openapi.user.json`·`openapi.service.json` byte 불변; PinVi `_kor_travel_map_snapshot_pin.py` admin sha + `test_kor_travel_map_admin_contract.py` 이중 핀 + `test_m05_pair_contract_is_derived`; user/service 스냅샷 diff 0 |
| 효과 lint | 센서 tick 외부 효과 = `dataset_version` HTTP 1회 + DB 조회(`reverse_geocoder` resource 미초기화, WARNING 0건); `jobs=` == `FEATURE_LOAD_SCHEDULE_SPECS` job 집합; 새 pool/limit 태그 없음; 변환 함수 단위 geo 호출 lint; `lint-imports`(`DatasetRef`·`GeoApplied`는 dto) |
| 센서 | geo 실패 → Skip·커서 불변; `data_token` None → 계획 0·Skip 문구; **빈 커서 + 토큰 → 커서에 기준선 기록·계획 0행·RunRequest 0**(소유자 결정 2026-10-15); 기준선 뒤 토큰 변경 → 계획 1행; 두 번 → 1행; 재빌드 → 0; A→B→A → `plan_seq=2`·RunRequest ≥ 1; terminal+커버리지 0 → 계획 0; SUCCESS → done; FAILURE → attempt 2 한 번만; SUCCESS+`budget_exhausted` → 재요청(`converted==0` → `no_progress`); `replan` run_key 유일; 3 tick 무run → `run_not_launched`; 활성 worker run → Skip; DISABLED → `skipped`(센서·`/detect` 동일); DISABLED 1개 포함 계획이 sweep 없이 done; `trigger_kind=sensor` run이 Map 소유로 집계 |
| e2e(n150 격리) | 첫 tick이 기준선을 기록한 뒤(계획 0) `manual_rebuild` → 요청 0; 소량 delta → 1 tick → 계획 → RunRequest 1 → 커버리지 상승; UI skip → badge, "지금 감지" → 계획 행 |
| 실측 | 35,754행 전량 재처리 **p95 + 실패 run 수**(p50 순차 ≈ 51 min은 하한), concierge refresh 동시 실행 조건 1회; geo p95 변동 < 20%; (MOIS replay 없음 — T-GR-08) |

**의도적 빨강 3건(PR 본문 기록)**: 빈 답 가드를 빼면 주소 열이 NULL로 덮인다; override 열을 비교에 넣으면
`row_revision`이 전진한다; 토큰을 `raw_payload_hash`에 넣으면 concierge 전 행이 `became_current`가 된다.
