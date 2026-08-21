# notice-feature-etl.md — 통합 notice ETL (교통/기상/안전/해양)

본 문서는 3개 provider의 짧은 수명 공지성 데이터를 `Feature(kind=notice)` +
`NoticeDetail`로 통합 적재하는 ETL이다.

> **구현 현황 (2026-08-21)**: notice Feature를 emit하는 변환부는
> **krex(`traffic_notices_to_bundles` → `krex_traffic_notices`)**,
> **kma(`weather_alerts_to_notice_bundles` → `kma_weather_alerts`)**,
> **krforest(`krforest_safety.landslide_forecast_issues_to_bundles` →
> `krforest_landslide_forecast_issues`, C05D)** 3개다. C05D는 PR #1037로 구현됐고
> catalog migration `0230`이 2026-08-21 prod에 적용됐다(prod head
> `0232_tvn37d_notice_empty_range`). C03에서 근거 source가 없던 `khoa_coastal_notices`
> 계획은 폐기했다. 해양 지수·관측값을 임의 threshold로 notice화하지 않는다.

## 1. 문서 정보

| 항목 | 값 |
|------|----|
| provider | `python-krex-api`, `python-kma-api`, `python-krforest-api` |
| dataset_key | `krex_traffic_notices`, `kma_weather_alerts`, `krforest_landslide_forecast_issues` (셋 다 구현됨) |
| Feature.kind | `notice` |
| 상세 테이블 | `feature_notices` |
| 코드 entrypoint | `kortravelmap.providers.{krex,kma,krforest,khoa}`, `kortravelmap.notices` |

## 2. 3 dataset 갱신 주기

| dataset_key | provider | 갱신 주기 | 이유 |
|-------------|---------|----------|------|
| `krex_traffic_notices` | `python-krex-api` | **10분** | 사고/공사/통제 즉시 영향 |
| `kma_weather_alerts` | `python-kma-api` | **10분** | 특보 발효/해제 짧은 시간 변경 |
| `krforest_landslide_forecast_issues` | `python-krforest-api` | **하루 6회** (`20 1,5,9,13,17,21 * * *`) | 산사태 발령·해제 — 예보 갱신 주기에 맞춘다 |

## 2.5 카테고리 매핑

`notice` kind는 **`Feature.category`를 out-of-catalog sentinel `99000000`**
으로 설정 (ADR-023 DTO validator가 빈 값·非8자리 숫자를 금지하므로 placeholder
필수). 분류는 `NoticeDetail.notice_type`이 1차 담당 (`docs/architecture/category.md` §4의
8개 Tier 1과는 별도 축).

marker_icon: `notice_type`별 (예: `alert` / `roadblock` / `rainwear`).
marker_color: `notice_type`별 (`P-13` 위험 / `P-08` 기상 / `P-14` 일반).

자세한 marker 매핑은 `notice_marker_style(notice_type, severity)` helper.

## 3. `notice_type` 표준 값

```python
NOTICE_TYPE_TRAFFIC            = "traffic"
NOTICE_TYPE_TRAFFIC_ACCIDENT   = "traffic_accident"
NOTICE_TYPE_ROAD_CLOSURE       = "road_closure"
NOTICE_TYPE_ROADWORK           = "roadwork"
NOTICE_TYPE_WEATHER_ALERT      = "weather_alert"
NOTICE_TYPE_HEAVY_RAIN         = "heavy_rain_warning"
NOTICE_TYPE_HEAVY_SNOW         = "heavy_snow_warning"
NOTICE_TYPE_HEAT_WAVE          = "heat_wave_warning"
NOTICE_TYPE_SAFETY             = "safety"
NOTICE_TYPE_EARTHQUAKE         = "earthquake"
NOTICE_TYPE_LANDSLIDE          = "landslide_warning"
NOTICE_TYPE_COASTAL_ISOLATION  = "coastal_isolation"
NOTICE_TYPE_ACCESS_RESTRICTION = "access_restriction"   # ADR-027 (generic: 입산통제/해수욕장폐장/공원폐쇄/등산로통제 등)
NOTICE_TYPE_FIRE_ALERT         = "fire_alert"           # ADR-027 (generic: 산불경보 + 향후 화재 일반)

NOTICE_TYPES = (
    NOTICE_TYPE_TRAFFIC, NOTICE_TYPE_TRAFFIC_ACCIDENT, NOTICE_TYPE_ROAD_CLOSURE,
    NOTICE_TYPE_ROADWORK,
    NOTICE_TYPE_WEATHER_ALERT, NOTICE_TYPE_HEAVY_RAIN, NOTICE_TYPE_HEAVY_SNOW,
    NOTICE_TYPE_HEAT_WAVE,
    NOTICE_TYPE_SAFETY, NOTICE_TYPE_EARTHQUAKE, NOTICE_TYPE_LANDSLIDE,
    NOTICE_TYPE_COASTAL_ISOLATION,
    NOTICE_TYPE_ACCESS_RESTRICTION, NOTICE_TYPE_FIRE_ALERT,
)
```

> **ADR-027 결정**: `access_restriction` / `fire_alert`는 forest/beach/urban
> 등 모든 도메인에서 재사용. provider별 출처는 `NoticeDetail.payload.domain`
> 으로 구분 (예: `'forest'`, `'beach'`, `'urban'`). `road_closure`(도로)는
> 별도 유지 — *도로 통제*와 *지역/시설 출입 제한*은 의미 분리.

`normalize_notice_type(value)`가 한/영 alias 정규화:

| 입력 | 출력 |
|------|------|
| `"호우주의보"`, `"호우경보"`, `"heavy_rain"` | `heavy_rain_warning` |
| `"대설"`, `"폭설"`, `"heavy_snow"` | `heavy_snow_warning` |
| `"폭염"`, `"폭염주의보"` | `heat_wave_warning` |
| `"지진"`, `"earthquake"` | `earthquake` |
| `"산사태"`, `"landslide"` | `landslide_warning` |
| `"바다갈라짐"`, `"coastal_isolation"` | `coastal_isolation` |
| `"교통사고"`, `"accident"` | `traffic_accident` |
| `"통제"`, `"도로통제"`, `"road_closure"` | `road_closure` |
| `"공사"`, `"도로공사"`, `"roadwork"` | `roadwork` |
| `"입산통제"`, `"입산제한"`, `"forest_access"`, `"hiking_closure"` | `access_restriction` (ADR-027) |
| `"해수욕장폐장"`, `"beach_closure"`, `"공원폐쇄"`, `"park_closure"` | `access_restriction` (ADR-027) |
| `"산불경보"`, `"forest_fire"`, `"fire"`, `"화재경보"` | `fire_alert` (ADR-027) |

provider 원문 등급/문구는 `NoticeDetail.payload`에 보존.

## 4. NoticeDetail

```python
class NoticeDetail(BaseModel):
    feature_id: str
    notice_type: str                          # NOTICE_TYPES 중 (validator로 정규화)
    severity: int | None = Field(default=None, ge=0, le=5)   # 공통 등급
    valid_start_time: datetime | None = None
    valid_end_time: datetime | None = None
    source_agency: str | None = None          # 발령기관
    officer_name: str | None = None
    payload: dict = Field(default_factory=dict)
```

`severity` 공통 등급:
- `0`: 정보 알림
- `1`: 주의보
- `2`: 경보
- `3`: 긴급
- `4`: 위험
- `5`: 매우 위험 / 즉시 대응

provider 원문 등급은 `payload`. 예시:
```python
severity = 2  # 경보
payload = {"krex_grade": "Level3", "krex_grade_desc": "차량 통행 통제"}
```

## 5. dataset별 매핑

### 5.1 krex_traffic_notices

provider `krex.models.Incident`(`openapi/burstInfo/realTimeSms`, apiId 0611 —
krex#8/PR#9, #378) 기준:

| provider 필드 | NoticeDetail 매핑 |
|--------------|------------------|
| `incident_type` (돌발유형명) | `notice_type` (정규화, 실패 시 `traffic` fallback) |
| — (등급 컬럼 없음) | `severity = None` |
| `occurred_date` + `occurred_time` | `valid_start_time` (KST; 종료 컬럼 없음 → `valid_end_time = None`) |
| `route_no`/`route_name`/`point_name`/`direction`/`process_status(_code)` | `payload` 보존 |
| `message` (smsText) | `payload.description` |

좌표: `latitude`/`longitude`(원천 키 `altitude`가 경도) — 일부 row만 보유.
있으면 `Feature.coord`, 없으면 coordless(노선/지점/방향이 `raw_address` 단서).

### 5.2 kma_weather_alerts

| provider 필드 | NoticeDetail 매핑 |
|--------------|------------------|
| `alert_type` (예: 호우경보) | `notice_type` 정규화 |
| `level` | `severity` |
| `effective_time` / `expiration_time` | `valid_*_time` |
| `affected_areas[]` | `payload.areas` (행정구역 리스트) |
| `description` | `Feature.detail.description` |

특보는 지역 단위 → 한 알림이 여러 행정구역에 영향. 한 alert를 N개 feature로
복제하거나, 단일 feature + `payload.affected_areas`로 처리. v2 1차: 후자
(단일 feature).

### 5.3 krforest_landslide_forecast_issues _(C05D 구현됨)_

authoritative source는 공공데이터포털 `15074798`
`forecastIssueService/forecastIssueList` 하나다. 산불위험지수는 WeatherValue,
산불·산사태 통계는 이력, 사방댐·취약지는 시설/영역 데이터이므로 notice에 섞지 않는다.

| 공식 원문 필드 | 목표 typed 필드 | NoticeDetail 매핑 |
|----------------|-----------------|------------------|
| `frcstIssuKindNm` | `issue_kind` | `notice_type=landslide_warning`, 원문 종류는 payload |
| `ocrnFrcstIssuInsttNm` | `issuing_agency` | `source_agency`와 영향 행정구역 단서 |
| `frcstIssuStts` | `issue_status` | 발령은 present, 해제는 absent event |
| `frstFrcstIssuDt` | `issued_at` | `valid_start_time` 또는 lifecycle event 시각 |

`python-krforest-api@f9254e6`은 이 endpoint를 `RawRecord`로만 노출한다. C05D에서
typed model과 시각 정밀도·기관/종류 기반 사건 identity를 먼저 고정하고, 같은 계보의
발령·해제를 `event` lifecycle로 처리한다. 좌표를 추정하지 않고 공식 기관/행정구역
필드가 제공하는 scope만 보존한다.

### 5.4 사건 단위 identity + 라이프사이클 (#632)

notice feature의 정체성은 **발표/스냅샷이 아니라 사건**이다 — 발표 단위 키가
재발표마다 새 feature를 만들던 중복(prod 6,164건 중 계보 1,317개, ~4.7×)을
identity 재설계로 해소했다:

| dataset | 자연키 (사건 단위) | 라이프사이클 |
|---------|-------------------|-------------|
| `kma_weather_alerts` | `{region_code}::{현상 토큰}` (`kma_alert_natural_key`) — tm_fc/seq/등급 제외. 현상 토큰(호우/풍랑/…)은 `notice_type`이 generic으로 접는 특보를 구분한다 | rolling window의 발표·해제를 계보별 최신 event로 접는다. 발표는 `present=true`, 해제는 `present=false`이며 bundle 적재·event 상태·Feature 종료/재개를 한 transaction에서 반영한다 |
| `krex_traffic_notices` | 사건 단서 `occurred_date::…::incident_type_code` (기존) — **feature_id에서 bjd_code 제거**(이동하는 정체가 동 경계를 넘으면 재키잉되던 버그) | authoritative snapshot의 활성 계보 집합을 CAS한 뒤 bundle 적재·member 상태·중복 정리·Feature 종료/재개를 한 transaction에서 반영한다 |

Alembic 0046부터 라이프사이클 정본은
`provider_sync.notice_lifecycle_scopes`와 `provider_sync.notice_lineage_states`다. scope PK는
`(provider, dataset_key, source_entity_type)`이며 `mode`는 전체 목록형 `snapshot`과
발표·해제형 `event` 중 하나다. member row가 없는 계보는 `unknown`으로 취급하며, 특히 KMA
3일 rolling window에서 보이지 않았다는 이유만으로 `false`로 바꾸지 않는다. 0046은 기존
계보를 backfill하지 않으므로 이 보수적 규칙이 배포 직후의 오종료도 막는다.

모든 notice 상태 materialize는 전역 transaction advisory lock
`hashtextextended('kortravelmap:notice-snapshot-reconcile', 0)`으로 직렬화한다. 같은 Feature가
여러 provider/dataset 계보에 연결돼도 scope 하나만 보고 닫지 않고, 계보별 구조적 winner를
전역으로 다시 계산한다. open-ended `present=true`가 하나라도 있으면 Feature를 열고, finite
present만 있으면 가장 늦은 provider `valid_until`까지 노출한다. `unknown` winner가 섞이면
이미 열린 종료시각을 줄이지 않고 명시 finite present가 더 길 때만 연장한다. 모든 winner가
`false`일 때만 닫으며 `valid_end_time`에는 그 winner들의 마지막 `changed_at`(최댓값)을 쓴다.
이 규칙으로 한 provider의 소멸·해제가 다른 provider의 활성 공지를 지우지 않는다.

KMA는 발표 bundle 원문의 `issued_at`(없으면 `valid_start_time`/`fetched_at`)과 해제의
`closed_at`을 event 시각으로 사용하고, 발표의 `effective_until`은 member `valid_until`로
분리해 보존한다. 한 rolling window 안에서는 계보별 최신 한 건만 남긴다. 저장된 같은
계보보다 오래된 event는 상태와 bundle 적재에서 모두 무시하고, 같은 시각의 발표·해제 또는
예정 종료 충돌은 실패시킨다. 반면 다른 계보의 늦은 event는 scope watermark와 무관하게
적용한다. 발표·해제 상태, 수락된 최신 bundle 적재, 공유 winner 재평가가 원자적이므로 이전
해제보다 늦은 재발표는 같은 Feature를 다시 열고, 실제 해제가 예정 종료보다 빠르면 더 이른
시각에 닫는다. 이미 지난 finite 발표 bundle은 soft-delete Feature를 되살리지 않는다. event가
없는 batch도 scope `applied_at`을 전진시켜 관측 사실을 남긴다.

read 경로 — **수집 feed에 없는(종료된) notice는 모든 API read에서 기본 제외**한다
(사용자 요구: "수집 시 notice가 없으면 과거 자료로 보여주지 말고 노출하지 않음").
종료 판정은 `valid_end_time`이 채워졌는지로만 하며(last_seen 최신성에 의존하지 않으므로
이후 poll이 실패해도 이미 닫힌 notice는 계속 숨는다), KREX snapshot 상태 반영과 KMA 해제가
이 컬럼을 채운다:

- 지도 bbox·클러스터, 이름 검색(`search_features`), 주변
  (`features_nearby`/POI target), 영역 포함(`features_contained_in_area`), 카테고리
  카운트(`category_feature_counts`)는 모두 계보별 latest만 남기고
  `valid_end_time`이 지난 notice를 숨긴다(`_PUBLIC_ACTIVE_NOTICE_FILTER_SQL`).
- admin feature 목록(`list_admin_features`)도 **기본 제외**로 전환 —
  감사가 필요하면 `include_ended=true`(API query param) / `종료 포함`으로 조회.
- infra raw 단건/다건(`get_feature_row`/`get_feature_rows_by_ids`)은 admin 감사와 내부
  참조를 위해 종료 notice도 보존한다. 그러나 public feature 상세·observation history·
  service batch는 `public_active_notice_feature_ids`로 같은 active/latest 필터를 적용해
  종료/구버전 ID를 404 또는 `missing`으로 처리한다.

중복 자체는 원자적 lifecycle materialize가 write 시점에 soft-delete하고, 구세대 identity
잔존분은 마이그레이션 `0040_notice_dedup_cleanup`이 일회성 정리했다.
latest 판정은 feature·계보에 연결된 current source record 중
`(COALESCE(last_seen_at, imported_at, fetched_at), source_record_key)` 내림차순의
**실제 한 행**을 먼저 고른 뒤, feature 사이에서 같은 tuple → 현 canonical identity →
`feature_id` 오름차순으로 결정한다. 두 컬럼의 `max()`를 따로 합성하면 존재하지 않는
tuple이 생겨 read에서 winner가 둘 남거나 write lifecycle materialize가 다른 feature를
남길 수 있으므로 그 방식은 사용하지 않는다.

KREX 조회는 전체 현재 목록 snapshot 계약이다. 요청 page size를 서버가 더 작게 제한해도
응답 `total_count`까지 모든 페이지를 읽는다. `python-krex-api`의 범용 EX normalizer는
HTTP 200의 `{}`/message-only/count-only 응답도 빈 `Page`로 만들 수 있으므로, map-side
lifecycle 경계에서 `page.raw.realTimeSMSList`와 `count`, 페이지 사이 count 불변성까지
검증한다. count가 그대로여도 수집 중 page boundary가 이동하면 앞 page의 사건이 다음
page에 중복되고 다른 사건이 누락될 수 있다. 따라서 map 자연키와 같은
`occurred_date/occurred_time/route_no/direction/point_name/incident_type_code` identity를
전체 page에서 추적하고, 중복이면 snapshot을 실패시킨다. 자연키 단서가 모두 비면 raw
payload 전체 hash를 converter와 동일한 fallback으로 쓴다(`series_no`가 raw에 있으면
hash에 자연스럽게 포함되지만 별도 identity로 취급하지 않는다). 예외·중간 빈 페이지·
구조 누락·사건 중복처럼 snapshot 완결성을 입증할 수 없는 경우에는
원자 적재·상태 반영·sync 성공 기록을 하지 않는다.

단일 pass 안에 중복이 없어도 수집 도중 `A,B,C`가 `A,B,D`로 교체되면 count와 unique
건수만으로 누락을 알아낼 수 없다. destructive 종료 근거는 같은 client로 전체 pagination을
**연속 2회** 수집하고, 두 pass의 record 수와 lineage identity set이 모두 같을 때만 성립한다.
각 pass에 위 envelope/count/page/duplicate 검증을 독립 적용하며, 일치 확인 전에는 record를
한 건도 asset에 yield하지 않는다. 일치하면 더 최신인 두 번째 pass payload를 적재하고,
불일치하면 `RuntimeError`로 원자적 snapshot apply를 전부 건너뛴다. 반대로 2회 모두 예외 없이
완결된 **0건 snapshot은 authoritative empty**이므로 `active_lineage_keys=∅`로 알려진 모든
KREX 계보를 `false`로 전이하고, 다른 active/unknown winner가 없는 Feature를 종료한다. 같은
payload가 다음 snapshot에 재등장해 source record upsert가 생략되더라도 영속된
`present=true` 상태가 `valid_end_time`을 지워 자동 복구한다. sync cursor는 bundle 적재,
scope/member 상태, Feature lifecycle transaction이 모두 성공한 뒤에만 전진한다.

KREX snapshot의 활성 계보 집합은 정렬·중복 제거 후 fingerprint를 만든다. 0046 scope의
`applied_at`보다 과거인 snapshot은 거부하고, 같은 시각·같은 fingerprint는 멱등 replay로
허용하지만 같은 시각·다른 fingerprint는 충돌로 실패시킨다. member `changed_at`은
`present`가 실제로 바뀔 때만 갱신한다. bundle 적재 전에 이 CAS를 검사하고, bundle 적재,
scope/member 상태 동기화, 중복 정리, 종료·재개를 같은 DB transaction에서 실행하므로 어느
단계가 실패해도 부분 반영되지 않는다.

이 raw 구조 검증은 종료 오판을 막는 map-side 최소 방어다. `python-krex-api`의 strict snapshot
envelope와 dependency pin을 정렬한 뒤에도 lifecycle의 destructive 종료 경계에서 독립 검증을
유지한다. `realTimeSMSList`는 provider 계약대로 다건 list와 단건 object를 모두 허용한다.

10분 schedule보다 한 run이 오래 걸릴 수 있으므로 asset은 `krex_notice_snapshot` Dagster
pool을 사용한다. `docker/dagster.yaml`의 run 단위 기본 한도 1이 snapshot fetch부터
원자 apply까지 직렬화해, 늦게 끝난 이전 run이 새 snapshot 결과를 다시 덮는 순서 역전을
막는다. load 전 preflight는 0046 scope의 `applied_at`과 sync cursor의
`snapshot_applied_at`(구 cursor는 `loaded_at` fallback)을 함께 확인해 과거
`fetched_at` run을 실패시킨다. 같은 시각 run은 DB transaction 안의 scope CAS로
넘겨 exact fingerprint replay는 self-heal하고 다른 fingerprint는 충돌로 실패시킨다. 이 CAS가
우회 호출까지 최종 방어하며, 성공 cursor는 원자 apply 뒤에만 새 watermark를 기록한다.

10분 freshness critical path에서는 KREX row별 reverse geocoding을 하지 않는다. 운영 실측상
원격 주소 보강이 포함된 run은 약 38분 걸려 다음 schedule보다 늦게 끝났고, 그동안 종료
notice 반영도 지연됐다. incident의 원천 위·경도는 geocoder 없이도 `Feature.coord`와
`SourceRecord.raw_latitude/raw_longitude`에 그대로 보존되며, 사건 identity/feature_id도
행정코드와 무관하다. 따라서 snapshot fetch→원자 적재·상태 반영을 먼저 끝내고 행정구역 주소는
이 짧은 수명 lifecycle 경로의 필수 조건으로 두지 않는다.
두 pass 검증으로 KREX HTTP 호출 수는 page 수의 2배가 되지만, 기존 run 대부분을 차지하던
row별 reverse geocoding을 제거했으므로 10분 cadence 안에서 snapshot 안정성을 우선한다.

`run_feature_notice_krex_traffic_notices`는 targeted feature update worker가 Dagster asset
pool을 우회해 직접 호출하는 경로도 있으므로, fetch 시작 전부터 원자 apply와 sync cursor 성공
기록까지 PostgreSQL session advisory lock
(`provider-run:python-krex-api:krex_traffic_notices`)도 잡는다. 이 session lock은 서로 다른
process/instance의 KREX fetch 전체를 직렬화하고, 위 전역 transaction lock은 KREX·KMA를
포함한 모든 notice의 DB 적용을 직렬화한다. pool은 불필요한 run 시작과 lock 대기를 줄인다.
watermark/CAS는 배포 전 queued run처럼 이미 반영된 과거 snapshot의 재적용을 거부한다.
process/connection 종료 시 session lock은 자동 해제된다.

## 6. 핵심 함수

```python
# providers/krex.py
async def traffic_notice_to_bundle(item, *, fetched_at) -> FeatureBundle:
    ...

# providers/kma.py
async def weather_alert_to_bundle(item, *, fetched_at) -> FeatureBundle:
    ...

# providers/krforest_safety.py  (구현됨 — dataset_key: krforest_landslide_forecast_issues)
def landslide_forecast_issues_to_bundles(
    items: Iterable[LandslideForecastIssueItem], *, fetched_at: datetime
) -> list[FeatureBundle]:
    ...

# providers/khoa.py  (planned/미구현 — 현재 beaches_to_bundles(place)만 존재)
async def coastal_notice_to_bundle(item, *, fetched_at) -> FeatureBundle:
    ...

# notices.py
from kortravelmap.dto.etl import EtlJobSpec

def notice_job_specs() -> list[EtlJobSpec]:
    return [
        EtlJobSpec(
            provider="python-krex-api", dataset_key="krex_traffic_notices",
            source_entity_type="traffic_notice",
            feature_kind=FeatureKind.NOTICE,
            full_scan_interval_days=None, interval_minutes=5,
            suggested_concurrency=1, suggested_group_name="features_notice",
            description="한국도로공사 교통 공지 (5분)",
        ),
        EtlJobSpec(
            provider="python-kma-api", dataset_key="kma_weather_alerts",
            source_entity_type="weather_alert",
            feature_kind=FeatureKind.NOTICE,
            interval_minutes=10, suggested_group_name="features_notice",
            ...
        ),
        # --- C05D (구현됨) ---
        EtlJobSpec(
            provider="python-krforest-api",
            dataset_key="krforest_landslide_forecast_issues",
            source_entity_type="landslide_forecast_issue",
            feature_kind=FeatureKind.NOTICE,
            interval_minutes=30, ...
        ),
    ]
```

## 7. 마커 스타일

| notice_type | maki icon | color |
|-------------|-----------|-------|
| `traffic`, `traffic_accident`, `road_closure`, `roadwork` | `roadblock` | `P-14` (검정) |
| `weather_alert`, `heavy_rain_warning` | `rainwear` | `P-08` (파랑) |
| `heavy_snow_warning` | `snowflake` | `P-07` (하늘) |
| `heat_wave_warning` | `temperature` | `P-15` (주홍) |
| `earthquake` | `alert` | `P-14` |
| `landslide_warning` | `alert` | `P-12` (갈색) |
| `coastal_isolation` | `alert` | `P-13` (회색) |
| `access_restriction` (ADR-027) | `barrier` | `P-13` (회색) |
| `fire_alert` (ADR-027) | `fire-station` | `P-15` (주홍) |
| 기타 `safety` | `alert` | `P-14` |

`notice_marker_style(notice_type, severity)` helper 제공.

## 8. Dagster

| asset | dataset_key | cron | group |
|-------|-------------|------|-------|
| `notice_krex_traffic` | `krex_traffic_notices` | `*/10 * * * *` | `features_notice` |
| `notice_kma_weather_alerts` | `kma_weather_alerts` | `*/10 * * * *` | `features_notice` |
| `feature_notice_krforest_landslide_forecast_issues` | `krforest_landslide_forecast_issues` | `20 1,5,9,13,17,21 * * *` | `features_notice` |

ConcurrencyConfig: provider별 `max_concurrent=1`.

## 9. 보관 정책

`docs/architecture/data-model.md` §7 + ADR-017:
- notice 종료일(없으면 발표일) +1년 후 purge — **구현됨(#632)**:
  `feature_repo.purge_expired_notices`(soft-delete, ADR-017 원문 보존)를
  maintenance job(`consistency_dedup_refresh`)의 `purge_expired_notices` op가
  주기 실행한다. 보존 기간은 op config `retention`(기본 `'1 year'`).
- 활성(현재 유효) notice만 frontend에 표시 — bbox/검색 read 필터가
  `valid_end_time` 지난 notice를 숨긴다(§5.4).

## 10. 검증

### fixture

- `krex_traffic_accident.json`, `krex_road_closure.json`, `krex_roadwork.json`
- `kma_heavy_rain_warning.json`, `kma_earthquake.json`, `kma_heat_wave.json`
- C05D: `krforest_landslide_issued.json`, `krforest_landslide_released.json`,
  `krforest_landslide_same_lineage_reissued.json`

### 통합 테스트

- `normalize_notice_type` 한/영 alias 전수 검증
- `severity` 정규화 (provider 등급 → 0-5)
- 만료 notice purge 동작
- frontend 표시 필터 (`valid_end_time > now()`)

## 11. 후속

- KMA 영향예보, 폭염주의보 추가 등급 검토.
- 산사태 발령의 공식 행정구역 코드/geometry source가 제공될 때만 위치·영역을 보강한다.
- 알림 자동 전송 (PinVi trip POI가 영향 지역과 겹치면 사용자에게 push).
