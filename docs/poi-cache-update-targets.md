# poi-cache-update-targets.md - 외부 POI 기반 feature 캐시 갱신 타깃

본 문서는 ADR-045의 OpenAPI 기반 feature update request를 **외부 앱 POI 캐시
갱신** 용도로 구체화한 사양이다. 대표 외부 앱은 PinVi지만, API는 특정 앱 이름에
묶지 않고 `external_system` + `target_key`로 식별한다.

## 1. 목적

외부 앱은 사용자가 저장한 POI 주변의 자주 바뀌는 데이터를 최신으로 유지하고 싶다.
예:

- 주변 날씨
- 주변 유가
- 주변 휴일/영업일 정보
- 기상/재난 경고
- 교통 유고/공지
- provider별 최신 상태가 필요한 주변 feature

하지만 전체 feature를 매번 업데이트하면 provider rate limit과 비용을 낭비한다. 또한
여러 POI를 동시에 업데이트할 때 반경이 겹치면 같은 feature/provider scope가 중복으로
갱신된다. 본 사양은 다음을 보장한다.

1. 외부 POI마다 고유 key와 좌표를 등록한다.
2. key가 삭제되면 그 key로 인한 targeted update를 더 이상 하지 않는다.
3. 여러 key의 반경이 겹치면 교집합 feature/provider scope는 한 번만 업데이트한다.
4. provider별 rate limit과 최적 refresh interval을 넘지 않는다.
5. provider가 filedata 기반이면 POI 등록 여부와 무관하게 기본적으로 시스템 schedule을
   따른다.
6. OpenAPI에서 key를 주면 주변 `n` km feature 목록을 summary로 반환한다.

## 2. 용어

| 용어 | 의미 |
|------|------|
| `external_system` | 외부 호출자. 예: `pinvi` |
| `target_key` | 외부 앱이 보장하는 POI 고유값. 좌표가 아니라 비즈니스 식별자 |
| `cache target` | `external_system + target_key + 좌표 + 반경 + refresh 설정` 한 묶음 |
| `coord_key` | 좌표를 지정 자리수로 반올림해 만든 normalized coordinate key |
| `feature link` | cache target 반경 안에 들어온 feature와 target의 다대다 연결 |
| `targeted update` | cache target 또는 target key 목록을 기준으로 한 feature/provider 갱신 |
| `system schedule` | POI와 무관하게 provider별 기본 주기로 돌아가는 정기 갱신 |

## 3. Key + 좌표 규칙

외부 앱은 좌표만 보내면 안 된다. 반드시 고유 key와 좌표를 함께 보낸다.

필수 입력:

- `external_system`
- `target_key`
- `lon`
- `lat`
- `radius_km`

좌표 precision:

- 기본 `coord_precision_digits`는 6자리 decimal을 권장한다.
- 같은 `external_system + target_key`에 대해 같은 precision으로 normalize한 좌표는
  1:1이어야 한다.
- 같은 key가 다른 normalized 좌표로 들어오면 기본 동작은 `409 COORDINATE_CONFLICT`다.
- POI 이동을 의도한 경우 `on_conflict="move"` 또는 별도 PATCH endpoint로 명시해야
  한다.
- 좌표는 외부 인터페이스에서 항상 `(lon, lat)` 순서다.

Idempotency:

- 같은 key + 같은 normalized 좌표 + 같은 radius/policy 요청은 idempotent upsert다.
- 요청이 반복되어도 target row는 하나만 유지하고 `last_seen_at`만 갱신한다.

삭제:

- 외부 POI가 삭제되면 cache target도 soft delete한다.
- soft deleted target은 targeted update 대상에서 제외한다.
- 이미 연결된 feature 자체는 삭제하지 않는다. feature는 provider/system schedule에
  따라 유지된다.

## 4. Feature 다대다 매핑

POI 여러 개가 같은 feature를 공유할 수 있다.

예:

- POI A 반경 3km 안에 주유소 X가 있음.
- POI B 반경 3km 안에도 주유소 X가 있음.
- 주유소 X는 `target_key=A`, `target_key=B` 두 개와 모두 매핑된다.

업데이트 실행 시에는 다음 단위로 dedup한다.

1. target keys를 active target으로 해석한다.
2. target별 주변 feature를 찾는다.
3. feature_id set을 union한다.
4. provider/dataset/source id 또는 provider/dataset/sigungu scope로 group한다.
5. 같은 provider call scope는 한 번만 실행한다.

이렇게 하면 여러 POI의 교집합에 해당하는 feature가 중복 업데이트되지 않는다.

## 5. Provider refresh policy

provider마다 갱신 주기가 다르다. cache target에 등록되었다고 모든 provider가 즉시
업데이트되는 것은 아니다.

정책 값:

| 값 | 의미 |
|----|------|
| `follow_system` | target 등록 여부와 무관하게 provider의 시스템 schedule만 따른다 |
| `allow_targeted` | target 기반 update request가 provider 갱신을 트리거할 수 있다 |
| `disabled` | provider/dataset을 targeted update에서 제외한다 |

기본값:

- OpenAPI로 실시간/준실시간 호출 가능한 provider는 rate limit 안에서
  `allow_targeted`를 기본값으로 둘 수 있다.
- filedata 기반 provider는 기본값이 `follow_system`이다. POI 등록 여부로 파일 다운로드/
  파싱을 매번 트리거하지 않는다.
- 날씨/유가/경고처럼 자주 바뀌는 provider는 최적 interval을 짧게 둘 수 있다.
- 문화유산/휴게소 장소 기본정보처럼 드물게 바뀌는 provider는 target 등록과 무관하게
  시스템 schedule이 기본이다.

사용자 override:

- admin UI, 설정 파일, DB 정책으로 provider/dataset별 refresh interval을 수정할 수
  있다.
- 수정값은 provider rate limit을 절대 넘을 수 없다.
- 너무 짧은 interval이 들어오면 API는 422를 반환하거나 안전한 최소 interval로 clamp한
  뒤 `clamped=true`를 응답해야 한다. 기본은 422 권장.

rate limit 출처:

- rate limit과 최적 기본값은 각 provider API 프로젝트의 문서/코드를 기준으로 조사해
  저장한다.
- ADR-044에 따라 `F:\dev\python-*-api` 로컬 checkout을 1차 source로 본다.
- 공식 API 문서와 provider repo가 충돌하면 provider repo + 공식 문서 기준으로
  정렬하고, 필요하면 provider repo에 PR을 보낸다.
- 추측으로 rate limit을 박지 않는다. 출처 문서 경로, commit sha, 확인일을 같이 저장한다.

## 6. DB 스키마 후보

정식 구현 전 Alembic migration으로 추가한다.

### 6.1 `ops.poi_cache_targets`

```sql
CREATE TABLE ops.poi_cache_targets (
  target_id UUID PRIMARY KEY DEFAULT x_extension.gen_random_uuid(),
  lock_version BIGINT NOT NULL DEFAULT 1,
  external_system TEXT NOT NULL,
  target_key TEXT NOT NULL,
  name TEXT,
  lon NUMERIC(12,8) NOT NULL,
  lat NUMERIC(12,8) NOT NULL,
  coord geometry(Point, 4326) NOT NULL,
  coord_5179 geometry(Point, 5179)
    GENERATED ALWAYS AS (ST_Transform(coord, 5179)) STORED,
  coord_precision_digits SMALLINT NOT NULL DEFAULT 6,
  coord_key TEXT NOT NULL,
  radius_km NUMERIC(8,3) NOT NULL,
  scope_mode TEXT NOT NULL DEFAULT 'center_radius',
  update_enabled BOOLEAN NOT NULL DEFAULT TRUE,
  refresh_policy TEXT NOT NULL DEFAULT 'provider_default',
  provider_overrides JSONB NOT NULL DEFAULT '{}'::jsonb,
  metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
  last_seen_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  last_requested_at TIMESTAMPTZ,
  last_refreshed_at TIMESTAMPTZ,
  last_failed_at TIMESTAMPTZ,
  next_eligible_refresh_at TIMESTAMPTZ,
  deleted_at TIMESTAMPTZ,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  CONSTRAINT ck_poi_cache_targets_scope_mode CHECK (
    scope_mode IN ('center_radius','sigungu_by_radius')
  ),
  CONSTRAINT ck_poi_cache_targets_refresh_policy CHECK (
    refresh_policy IN ('provider_default','follow_system','allow_targeted','disabled')
  ),
  CONSTRAINT ck_poi_cache_targets_radius CHECK (radius_km > 0 AND radius_km <= 100),
  CONSTRAINT ck_poi_cache_targets_coord CHECK (
    ST_X(coord) BETWEEN 124.0 AND 132.0 AND ST_Y(coord) BETWEEN 33.0 AND 39.5
  ),
  CONSTRAINT ck_poi_cache_targets_lock_version CHECK (lock_version >= 1)
);

CREATE UNIQUE INDEX uq_poi_cache_targets_active_key
  ON ops.poi_cache_targets (external_system, target_key)
  WHERE deleted_at IS NULL;
CREATE INDEX idx_poi_cache_targets_coord_5179
  ON ops.poi_cache_targets USING GIST (coord_5179)
  WHERE deleted_at IS NULL;
CREATE INDEX idx_poi_cache_targets_next_refresh
  ON ops.poi_cache_targets (next_eligible_refresh_at)
  WHERE deleted_at IS NULL AND update_enabled;
```

`coord_key` 예:

```text
126.978000:37.566500:p6
```

Alembic 0058의 BEFORE UPDATE trigger는 caller가 어떤 값을 보내더라도
`NEW.lock_version = OLD.lock_version + 1`을 강제한다. HTTP strong ETag와 body `entity_tag`는
따옴표 자체를 포함한 `"{lowercase-canonical-uuid}:{positive-version}"` raw 문자열이다. consumer는
이를 분해·재합성하지 않고 응답 header와 body 값을 그대로 `If-Match`에 사용한다.

### 6.2 `ops.poi_cache_target_feature_links`

```sql
CREATE TABLE ops.poi_cache_target_feature_links (
  target_id UUID NOT NULL REFERENCES ops.poi_cache_targets(target_id) ON DELETE CASCADE,
  feature_id TEXT NOT NULL REFERENCES feature.features(feature_id) ON DELETE CASCADE,
  provider TEXT,
  dataset_key TEXT,
  distance_m NUMERIC(12,2),
  relation TEXT NOT NULL DEFAULT 'within_radius',
  active BOOLEAN NOT NULL DEFAULT TRUE,
  first_seen_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  last_seen_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  last_refreshed_at TIMESTAMPTZ,
  PRIMARY KEY (target_id, feature_id),
  CONSTRAINT ck_poi_cache_link_relation CHECK (
    relation IN ('within_radius','same_sigungu','manual')
  )
);

CREATE INDEX idx_poi_cache_links_feature
  ON ops.poi_cache_target_feature_links (feature_id)
  WHERE active;
CREATE INDEX idx_poi_cache_links_provider_dataset
  ON ops.poi_cache_target_feature_links (provider, dataset_key)
  WHERE active;
```

### 6.3 `ops.provider_refresh_policies`

```sql
CREATE TABLE ops.provider_refresh_policies (
  provider TEXT NOT NULL,
  dataset_key TEXT NOT NULL,
  source_kind TEXT NOT NULL, -- openapi, filedata, manual, system
  targeted_policy TEXT NOT NULL DEFAULT 'follow_system',
  system_interval_seconds INTEGER,
  optimal_interval_seconds INTEGER,
  min_interval_seconds INTEGER,
  max_requests_per_minute INTEGER,
  max_requests_per_hour INTEGER,
  max_requests_per_day INTEGER,
  max_concurrent INTEGER NOT NULL DEFAULT 1,
  burst_size INTEGER,
  rate_limit_source JSONB NOT NULL DEFAULT '{}'::jsonb,
  config_source TEXT NOT NULL DEFAULT 'db',
  enabled BOOLEAN NOT NULL DEFAULT TRUE,
  revision BIGINT NOT NULL DEFAULT 1,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  PRIMARY KEY (provider, dataset_key),
  CONSTRAINT ck_provider_refresh_source_kind CHECK (
    source_kind IN ('openapi','filedata','manual','system')
  ),
  CONSTRAINT ck_provider_refresh_targeted_policy CHECK (
    targeted_policy IN ('follow_system','allow_targeted','disabled')
  ),
  CONSTRAINT ck_provider_refresh_revision
    CHECK (revision >= 1 AND revision <= 9223372036854775807)
);
```

정책 write는 `expected_revision` CAS를 사용한다. 신규 행만 `null`로 revision 1을
생성하고, 기존 행은 일치하는 revision에서만 원자적으로 `revision + 1`한다. HTTP 경계는
BIGINT를 양수 10진 문자열로 표현하며 conflict는 현재 record/revision을 반환한다.
기존 행의 `source_kind`는 불변이고, revision 최댓값에서는 `+1`을 평가하지 않고 typed
소진 conflict를 반환한다.

`rate_limit_source`에는 다음을 저장한다.

```json
{
  "provider_repo": "F:/dev/python-kma-api",
  "provider_commit": "abc123",
  "docs": ["docs/rate-limit.md", "src/.../config.py"],
  "official_docs_url": "https://...",
  "checked_at": "2026-06-01T12:00:00+09:00",
  "notes": "초단기 예보는 ... 기준"
}
```

## 7. OpenAPI

### 7.1 Cache target 등록/upsert

#### `PUT /admin/poi-cache-targets/{external_system}/{target_key}`

요청:

```json
{
  "coord": {"lon": 126.978, "lat": 37.5665},
  "coord_precision_digits": 6,
  "radius_km": 5.0,
  "scope_mode": "center_radius",
  "update_enabled": true,
  "refresh_policy": "provider_default",
  "provider_overrides": {
    "python-kma-api:kma_ultra_short_nowcast": {
      "targeted_policy": "allow_targeted"
    },
    "python-knps-api:knps_trails": {
      "targeted_policy": "follow_system"
    }
  },
  "on_conflict": "reject",
  "metadata": {
    "pinvi_poi_id": "poi_123",
    "labels": ["hotel"]
  }
}
```

`provider_overrides`는 provider 또는 `provider:dataset_key` key를 최대 64개까지
받는다. 각 override 값은 `targeted_policy`, `min_interval_seconds`,
`max_requests_per_minute`, `max_requests_per_hour`, `max_requests_per_day`,
`max_concurrent`, `note`만 허용하며 unknown key는 `422`다. `metadata`는 외부 JSON
필드명으로 유지하지만 서버 모델 내부에서는 `metadata_` alias로 다룬다. 허용
metadata key는 `pinvi_poi_id`, `external_ref`, `source_url`, `labels`, `note`다.

`on_conflict`:

- `reject`: 같은 key가 다른 normalized 좌표로 들어오면 409.
- `move`: 기존 target 좌표를 새 좌표로 이동하고 feature links를 재계산한다.

응답:

```json
{
  "data": {
    "target_id": "uuid",
    "external_system": "pinvi",
    "target_key": "poi_123",
    "coord_key": "126.978000:37.566500:p6",
    "radius_km": 5.0,
    "update_enabled": true,
    "last_updated_at": "2026-06-01T12:10:00+09:00"
  },
  "meta": {"duration_ms": 20}
}
```

### 7.2 Cache target 목록

#### `GET /admin/poi-cache-targets`

Query:

| 이름 | 타입 | 설명 |
|------|------|------|
| `external_system` | string | 선택. 특정 외부 시스템만 조회 |
| `update_enabled` | boolean | 선택. targeted update 활성/비활성 필터 |
| `include_deleted` | boolean | 기본 `false`. soft-deleted target 포함 |
| `page_size` | int | 기본 200, 최대 500 |
| `cursor` | string | 이전 응답의 `next_cursor` |

응답은 `updated_at DESC, target_id DESC` keyset cursor를 사용한다. 다음 페이지가 있으면
`next_cursor`가 채워지고, 잘못된 cursor는 DB 조회 전에 `422`로 거절한다.

```json
{
  "count": 1,
  "items": [
    {
      "target_id": "uuid",
      "external_system": "pinvi",
      "target_key": "poi_123",
      "coord_key": "126.978000:37.566500:p6",
      "metadata": {"pinvi_poi_id": "poi_123"}
    }
  ],
  "next_cursor": null
}
```

### 7.3 Cache target 삭제

#### `DELETE /admin/poi-cache-targets/{external_system}/{target_key}`

처리:

- 목록/직전 GET/PUT body의 `entity_tag`를 합성 없이 `If-Match`로 필수 전달한다.
- `If-Match` 누락은 RFC7807 `428`, weak/wildcard/multiple/noncanonical/malformed 값은 RFC7807 `422`로
  거절한다.
- active natural key를 `FOR UPDATE`로 잠근 뒤 expected UUID+version이 같은 row만 갱신한다.
  concurrent PUT/recreate면 삭제 없이 `412`, READ COMMITTED 재조회에도 active row가 없으면 `404`다.
- `deleted_at`을 설정한다.
- active feature links를 false로 바꾼다.
- 이후 targeted update request에서 제외한다.
- feature 자체는 삭제하지 않는다.
- PUT/DELETE 성공 응답 `meta.dataset_projection_revision`은 같은 transaction에서 증가한 live
  topic revision이다. mutation 전부터 열린 같은 socket의 update frame
  `data.live_revision >= receipt`만 causal 검증에 사용하고 snapshot/fingerprint는 제외한다.
- 성공 DELETE는 trigger가 증가시킨 새 version의 strong `ETag`를 반환한다.
- executor link sync는 UUID 순서로 모든 active parent의 `FOR KEY SHARE` lock을 먼저 얻은 뒤 기존
  link 비활성화와 새 link upsert를 수행한다. inactive parent는 건너뛰며 delete의 parent `FOR UPDATE`
  → link 비활성화 순서와 직렬화된다.

### 7.4 주변 feature 목록

#### `GET /features/nearby/by-target`

Query:

| 이름 | 타입 | 설명 |
|------|------|------|
| `external_system` | string | 예: `pinvi` |
| `target_key` | string | 외부 POI 고유 key |
| `radius_km` | number | 없으면 target 기본 radius 사용 |
| `kind` | string[] | 선택 |
| `category` | string[] | 선택 |
| `status` | string[] | 기본 `active` |
| `provider` | string[] | 선택 |
| `page_size` | int | 기본 100, 최대 500 |
| `cursor` | string | keyset cursor |
| `sort` | string | `distance`, `name`, `last_updated_at` |

응답 item은 summary만 반환한다. `feature.detail` JSONB, provider raw payload,
source raw data와 provider/dataset 내부 식별자는 목록 응답에 포함하지 않는다.
Target summary도 외부 key와 좌표만 반환하며 `target_id`, `refresh_policy`,
`update_enabled`, `next_eligible_refresh_at` 같은 운영 필드는
`/admin/poi-cache-targets*`에서만 조회한다(D-7).

```json
{
  "data": {
    "target": {
      "external_system": "pinvi",
      "target_key": "poi_123",
      "lon": 126.978,
      "lat": 37.5665
    },
    "items": [
      {
        "feature_id": "f_1111010100_p_...",
        "kind": "place",
        "name": "주변 주유소",
        "category": "06020000",
        "status": "active",
        "lon": 126.98,
        "lat": 37.56,
        "distance_m": 320.5
      }
    ],
    "next_cursor": null
  },
  "meta": {"count": 1, "duration_ms": 14}
}
```

### 7.4 Target 기반 update request

#### `POST /ops/pipeline/requests`

feature update request는 운영자/admin 영역이다. scope에 `cache_target_keys`를
추가해 등록된 target 묶음 기준 refresh를 실행한다. PinVi 사용자 제안 큐는
PinVi app DB가 소유하고, 운영자 승인 뒤 admin API로 이 요청을 만든다.

```json
{
  "scope": {
    "type": "cache_target_keys",
    "external_system": "pinvi",
    "target_keys": ["poi_123", "poi_456"],
    "radius_km": 5.0,
    "scope_mode": "center_radius"
  },
  "run_mode": "queued",
  "operator": "pinvi",
  "reason": "저장 POI 주변 캐시 갱신"
}
```

처리:

- 삭제된 target key는 무시하고 응답 `skipped_deleted_keys`에 포함한다.
- 존재하지 않는 key는 404 또는 partial mode에 따라 `skipped_missing_keys`에 포함한다.
- active target들의 주변 feature를 union한다.
- provider/dataset/scope별로 dedup해서 한 번만 queue한다.
- provider policy가 `follow_system`이면 targeted update에서 제외하고
  `follow_system_skipped`에 기록한다.
- provider policy가 `disabled`이면 제외한다.
- `/v1/ops/pipeline/requests/preview`로 보내면 실제 job을 만들지 않고 대상
  feature 수, provider call scope, skipped reason만 반환한다.

## 8. 업데이트 시간 규칙

국내 데이터만 다루므로 모든 API 시간은 KST aware ISO-8601로 반환한다.

필수 API 필드:

- feature summary: `last_updated_at`
- feature detail: `last_updated_at`
- detail section: 가능하면 `detail_last_updated_at`
- weather/price/source/file 관련 section: 각 item 또는 section에 `last_updated_at`
- cache target: `last_updated_at`, `last_refreshed_at`, `next_eligible_refresh_at`
- update request: `created_at`, 정수 `generation`; canonical job: `created_at`,
  `started_at`, `heartbeat_at`, `finished_at`

DB 규칙:

- `feature.features.updated_at`은 feature summary의 `last_updated_at` 정본이다.
- source 기반 갱신은 `provider_sync.source_records.imported_at` 또는 관련 row
  `updated_at`을 함께 갱신한다.
- weather/price처럼 시계열 row는 `observed_at`/`valid_at`과 별개로 적재/갱신 시각을
  API에서 알 수 있어야 한다. 기존 스키마에 `updated_at`이 없으면 migration 후보로
  추가한다.
- API는 naive datetime을 반환하지 않는다.

## 9. 목록과 상세 응답 분리

목록 API:

- feature_id
- kind
- name
- category
- status
- lon/lat
- distance_m 또는 bbox 관련 값
- primary provider/dataset
- issue badge/count
- `last_updated_at`

목록 API에서 제외:

- `feature.detail` JSONB 전체
- `raw_refs`
- `provider_sync.source_records.raw_data`
- source raw payload
- file payload

상세 API:

- `GET /features/{feature_id}`에서 `detail`, `address`, `urls`, source summary,
  file summary, 관련 weather/price 최신값, JSON 추가 데이터를 반환한다.
- raw payload 전체는 운영자용 toggle 또는 별도 `/features/{id}/sources`에서만
  노출한다.

## 10. Admin UI

필수 화면:

- Cache target 목록: external_system, target_key, 좌표, radius, update_enabled,
  linked feature count, last_refreshed_at, next_eligible_refresh_at.
- Cache target 상세: 지도, 주변 feature, provider별 refresh policy, 최근 update
  request/job.
- 등록/upsert form: controlled React state + `src/lib/form-validation.ts`.
- 삭제 action: soft delete 확인 모달.
- Dry-run 버튼: target key 목록 또는 현재 target 기준 update scope 미리보기.
- Provider refresh policy 화면: provider/dataset별 source_kind, targeted_policy,
  optimal/min interval, rate limit source 확인과 수정.

수정 UI는 rate limit을 넘는 값을 저장할 수 없어야 한다. 저장 전에 backend validation
결과를 보여준다.

## 11. 구현 순서

1. ✅ `ops.provider_refresh_policies` 스키마/repository.
2. ✅ `ops.poi_cache_targets` + upsert/delete/get/list repository.
3. ✅ `PUT/GET/DELETE /admin/poi-cache-targets` +
   `GET /features/nearby/by-target` API.
4. ✅ `scope.type='cache_target_keys'` dry-run/실행 scope 해석.
5. ✅ target feature link 계산과 저장(T-206d executor).
6. ✅ Dagster queue 실행 연결(T-208e sensor).
7. ✅ Admin UI target 목록/상세/등록/삭제. relay/dead/reconciliation 상태와 recovery action은
   T-VN-41 producer foundation에서 확장한다.

### 11.1 vNext generation/outbox producer foundation (ADR-081, T-VN-41)

기존 admin target resource는 **PinVi 이외 수동 소유 external system**의 운영자 관리와 ETag CAS를
유지한다. `external_system='pinvi'`의 admin PUT/DELETE는 `409
CACHE_TARGET_SOURCE_PROTOCOL_REQUIRED`로 거부한다. PinVi 전파는 admin route를 재사용하지 않고
ServiceToken 전용 `/v1/service/cache-targets/*`, refresh operation, stream control, pull
claim/ACK/NACK, dead/replay, fixed snapshot resource를 사용한다. 따라서 활성 relay stream의
source head/outbox를 우회하는 writer는 없다.

`feature_update_requests.generation`, target `lock_version`, Map `restore_epoch`, PinVi
`source_generation`, result `target_sequence`, delivery `relay_order`는 서로 다른 값이다. 특히
source generation을 target row에만 저장하지 않는다. 별도 natural-key head와 durable tombstone이
삭제 후 재생성까지 fence하고, producer event ledger가 Idempotency-Key/body/result replay를 보존한다.

target/link/refresh 결과와 strict typed outbox event는 같은 transaction에서 기록한다. relay I/O는
critical write transaction에 없고, PinVi가 lease claim을 pull한 뒤 자기 DB에 inbox+projection을
commit하고 contiguous global prefix를 ACK한다. permanent poison은 dead letter로 stream을 막으며
같은 event를 replay하고 fixed snapshot checksum이 다시 맞기 전에는 ready가 아니다.

restore fence는 새 epoch보다 낮은 `pending|retry|leased|dead` delivery를 같은 transaction에서
terminal `superseded`로 종결한다. 구 dead도 새 epoch의 DLQ·replay·dead 집계에서 제외하고, claim은
현재 epoch event만 선택한다. 운영 status는 backlog와 별도로 누적 `superseded_count`를 보여 준다.
동시에 active reconciliation은 terminal `superseded`/`restore_fenced`로 종결하고 active slot을
비운다. fence receipt와 service 응답은 claim/delivery/reconciliation count 및 대체 request UUID를
고정하므로 재시도도 같은 결과를 반환하고 새 epoch reconciliation은 즉시 begin할 수 있다.

snapshot checksum은 active와 tombstone을 모두 포함한 ADR-081 Merkle v1이다. Map/PinVi는
`cache-target-source-v1` canonical serializer golden vector와 pinned service OpenAPI를 함께
검증한다. 성공 reconciliation event는 request UUID와 그 request에 seal된 fixed snapshot UUID를
exact payload에 함께 기록하고 expected root를 envelope fingerprint에도 반복해 인과관계를 고정한다.
producer foundation만으로 task를 완료 표시하지 않으며 paired PinVi consumer와 n150
isolated live 증명 뒤에만 `T-VN-41A/B/C`를 닫는다.

## 12. 테스트 기준

- 같은 key + 같은 normalized 좌표 upsert는 idempotent.
- 같은 key + 다른 normalized 좌표는 기본 409.
- `on_conflict=move`는 기존 links를 재계산한다.
- delete된 target은 update request에서 제외된다.
- target A/B의 반경이 겹치면 같은 feature/provider scope가 한 번만 queue된다.
- filedata provider는 기본적으로 targeted update에서 제외된다.
- provider override가 rate limit을 넘으면 422.
- `GET /features/nearby/by-target` 목록 응답에 detail JSONB/raw payload가 없다.
- 모든 응답 item에 KST aware `last_updated_at`이 있다.
- same event/body retry는 최초 결과를 replay하고 다른 body는 `409`다.
- 낮은 source generation, 과거 restore epoch, tombstone보다 오래된 create는 projection을 바꾸지 않는다.
- target/link/refresh transaction rollback은 대응 outbox event도 남기지 않는다.
- claim crash/lease expiry 뒤 동일 event가 재전달돼도 consumer side effect는 0회 추가다.
- global cursor는 target semantic precedence에 쓰이지 않고 ACK는 contiguous prefix만 전진한다.
- permanent NACK/dead letter는 후속 order를 block하고 동일 event replay+Merkle 일치 뒤에만 해제된다.
- restore fence 뒤 구 epoch non-delivered는 모두 superseded이고 old dead는 DLQ/claim을 막지 않는다.
- 같은 fence command replay는 superseded delivery version을 다시 증가시키지 않는다.
- preparing/running 중 restore fence가 오면 구 request의 snapshot/seal/completion은 모두
  `reconciliation_superseded`이고 새 epoch begin은 즉시 성공한다.
- fence exact replay는 최초 무효화/대체 count, 대체 reconciliation UUID와 모든 phase version을 보존한다.
