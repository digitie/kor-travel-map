# 큐레이션 계약 — catalog + collection/item

> **상태**: 2026-08-20 (T-VN-40C 이후). 이 문서는 큐레이션의 **현행 정본**이다.
> **정본 범위**: theme/source/rule catalog, collection/item 데이터 모델, REST 표면,
> PinVi 소비 계약, admin UI·Dagster 경계.
>
> 40C 이전의 `feature.curated_features` overlay 설계(컬럼·인덱스·`/v1/curated-features*`
> API·PinVi copy snapshot 표)는 alembic `0225`에서 물리 삭제됐고, 원문은
> [`docs/archive/curated-features-legacy-overlay.md`](archive/curated-features-legacy-overlay.md)에
> 동결돼 있다. 제거 근거는 ADR-075, 범위는
> `contracts/vnext/t-vn-40c-removal-manifest-v1.json`.

## 1. 결정 요약

- 큐레이션의 단위는 **collection(묶음)과 item(membership)** 이다. 같은 Feature가 여러
  연도·코스·출처에 포함되면 각 사실을 모두 저장하고, 지도는 Feature marker 하나의
  상세에 membership 전부를 표시한다.
- `feature.features`는 원천 POI를 계속 소유한다. 큐레이션은 그 위의 membership일 뿐
  Feature를 복제하지 않는다.
- theme/source/rule **catalog는 남는다**. provider dataset이 후보를 만들 때의 입력이며,
  40C는 catalog가 아니라 그 위의 overlay 본체를 지웠다.
- 공식 item을 기존 Feature와 안전하게 확정하지 못해도 버리지 않는다. nullable
  `feature_id`와 공식 `place_name`/`address_hint`로 보존하고, 좌표는 연결된 기존
  Feature에서만 쓴다.
- PinVi는 kor-travel-map DB를 직접 읽지 않는다. REST로 detail-snapshot을 받아 자기 DB에
  복사한다. `kor-travel-concierge`는 이 flow에 관여하지 않는다.
- 큐레이션 write는 전부 SECURITY DEFINER **typed command**를 통한다. runtime role은
  표에 직접 쓰지 않는다(ADR-075, `0214` 이후).

## 2. 테마형 데이터 소스

테마형 source 조사 결과와 provider별 보강 내역은 아카이브 문서 §2가 원문이다. provider
계약 자체는 [`docs/architecture/provider-contract.md`](architecture/provider-contract.md)가
정본이다. 요지만 옮기면:

- `python-mcst-api` 파일데이터 CSV — 세계음식점, 독립서점, 카페가 있는 서점 등.
- `python-datagokr-api` 표준데이터 — 무장애·다국어·반려동물 편의.
- `kor-travel-concierge` YouTube 장소 후보 — `youtube_place_candidates` dataset.
- 공식 목록 CSV(한국관광 100선 등) — collection import 경로로 들어온다.

## 3. 데이터 모델

Schema는 `feature`다. 큐레이션은 feature 도메인의 표시 정책이므로 `provider_sync`나
`ops`가 아니라 `feature` 소유다. 전체 컬럼 정의는
[`docs/architecture/data-model.md`](architecture/data-model.md)가 정본이고, 여기서는
표 사이의 역할 분담만 고정한다.

### 3.1 catalog — `curated_themes` / `curated_sources` / `curated_source_rules`

| 표 | 역할 |
|----|------|
| `feature.curated_themes` | 테마 slug·표시명·group·visibility(`admin_only`/`public`) |
| `feature.curated_sources` | provider dataset 1건에 대응하는 출처 메타(갱신주기·라이선스·관측 revision) |
| `feature.curated_source_rules` | "이 dataset의 이 조건은 후보/무시" rule. `default_action`은 `candidate`/`ignore` |

catalog write는 `create/patch/archive_curated_{theme,source,source_rule}_command`
procedure가 소유하고, EXECUTE는 `ktm_curation_admin_executor`가 갖는다. rule의 semantic
변경은 같은 transaction에서 affected reconcile을 수행한다.

### 3.2 canonical — `curation_collections` / `curation_items`

collection은 테마·공식 제목·회차·출처·공개 상태를, item은 공식 원천 항목과 Feature
membership을 소유한다.

| 테이블/컬럼 | 의미 |
|-------------|------|
| `curation_collections.collection_id` | UUID PK |
| `collection_key` | 파일 재업로드와 외부 참조에 쓰는 안정 unique key |
| `theme_id`, `source_id` | catalog 참조 |
| `title`, `edition_key` | 한국관광 100선 제목·2023-2024 같은 회차 |
| `status`, `visibility` | draft/published/archived, admin_only/public |
| `curation_collections.created_by`, `updated_by` | 신뢰된 admin actor 감사값 |
| `curation_items.curation_item_id` | UUID PK — **큐레이션 membership의 정본 식별자** |
| `collection_id` | collection FK, 물리 삭제 시 CASCADE |
| `feature_id` | 기존 Feature 선택 연결. 미확정 공식 항목은 NULL, Feature 삭제 시 SET NULL |
| `external_item_id` | collection 안 공식 item 안정키. 복합 장소를 여러 Feature로 펼쳐도 공유 |
| `place_name`, `address_hint` | Feature 미연결 상태에서도 보존하는 공식 장소 정보 |
| `status`, `sort_order` | candidate/included/rejected/archived, 공식 순서 |
| `item_title`, `item_summary` | membership 표시 override |
| `curation_relation`, `reuse_policy` | 역할과 재사용 정책 |
| `metadata` | 하위 코스·공식 순번·매칭 근거·원문 부가 정보 |
| `curation_items.created_by`, `updated_by` | 신뢰된 admin actor 감사값 |

active unique identity는 `(collection_id, external_item_id, feature_id) NULLS NOT DISTINCT`다.
같은 공식 item을 한 collection에 미연결 상태로 중복 저장하지 않되, 한 복합 item을 여러
Feature에 연결하는 것은 허용한다. 같은 Feature가 서로 다른 collection 또는 서로 다른
원천 item으로 참여하는 것도 제한하지 않는다. 단, 같은 collection과 `external_item_id`에
Feature 연결 행과 미연결 행이 동시에 active인 혼합 상태는 repository가 거절한다.

`curation_relation` 값: `primary_stop` / `food_stop` / `cafe_stop` / `bookstore_stop` /
`nearby_option` / `accessibility_support` / `pet_support` / `family_support` /
`theme_area_anchor`. `reuse_policy` 값: `allowed` / `blocked` / `manual_review`.

### 3.3 cutover 증거 — `ops.curation_cutover_identity_mappings`

40C가 legacy 표를 지울 때 이 표는 **남긴다**. legacy `curated_feature_id` → canonical
`(collection_id, curation_item_id)` 대응과 `source_row_hash`를 담은 불변 기록이며,
PinVi가 자기 쪽 예전 참조를 canonical로 옮기는 데 쓴다
(`GET /v1/service/curation-cutover/identity-mappings`). 이 표에 매핑된 item의 collection은
quarantine-release DELETE 대상에서 제외된다(`0215`).

## 4. REST API 계약

전 표면은 `/v1` + `{data, meta}` envelope를 쓴다. 스키마 정본은
`packages/kor-travel-map-api/openapi.json`(admin 포함)과 `openapi.user.json`(공개)이며,
admin 계약 규약은
[`docs/architecture/openapi-admin-contract.md`](architecture/openapi-admin-contract.md)다.

### 4.1 공개 read

```
GET /v1/curations
GET /v1/curations/collections
GET /v1/curations/collections/{collection_id}
GET /v1/curations/features/{feature_id}
```

published + public collection만 보인다. Feature 자체의 공개 여부는 ADR-067 단일 공개
projection(`feature.public_features`)이 판정하므로, 비공개 Feature는 membership을
통해서도 새지 않는다.

### 4.2 admin catalog

```
GET,POST         /v1/admin/curated-themes
GET,PATCH,DELETE /v1/admin/curated-themes/{theme_id}
GET,POST         /v1/admin/curated-sources
GET,PATCH,DELETE /v1/admin/curated-sources/{source_id}
GET,POST         /v1/admin/curated-source-rules
GET,PATCH,DELETE /v1/admin/curated-source-rules/{rule_id}
```

세 표 모두 strong ETag + CAS다. PATCH/DELETE는 `If-Match`를 요구하고, 표현(ETag)과
CAS 입력(`row_revision`)을 분리한다. DELETE는 물리 삭제가 아니라 archive다.

### 4.3 admin collection/item과 CSV import

```
GET,POST         /v1/admin/curations
GET,PATCH,DELETE /v1/admin/curations/{collection_id}
POST             /v1/admin/curations/{collection_id}/items
PATCH,DELETE     /v1/admin/curations/{collection_id}/items/{curation_item_id}
GET              /v1/admin/curations/import-template.csv
POST             /v1/admin/curations/imports/preview
POST             /v1/admin/curations/import-plans/{import_plan_id}/commit
GET              /v1/admin/curations/import-batches/{import_batch_id}
GET              /v1/admin/curations/items/{curation_item_id}/current-import-row
GET              /v1/admin/curations/link-audit
GET              /v1/admin/curations/quarantine
GET              /v1/admin/curations/quarantine/{collection_id}/items
POST             /v1/admin/curations/quarantine/{collection_id}/reclassify
```

import는 preview(dry-run) → plan → commit 3단이다. preview는 형식 오류와 미연결·복수
후보 행을 모두 보고하되 반영을 막지 않는다. commit은 plan revision을 claim해 같은
plan이 두 번 반영되지 않게 한다.

### 4.4 service — detail snapshot

```
GET /v1/service/curation-collections/{collection_id}/detail-snapshot
GET /v1/service/curation-items/{curation_item_id}/detail-snapshot
GET /v1/service/curation-cutover/identity-mappings
```

PinVi가 소비하는 표면이다. snapshot은 닫힌 JSON payload + `sha256:*` ETag이며, 토큰은
PinVi curation token pair(`KOR_TRAVEL_MAP_API_PINVI_CURATION_{SNAPSHOT,CUTOVER_MAPPING}_TOKEN_SHA256`)로
분리된다.

## 5. PinVi 소비 계약

PinVi는 collection/item detail-snapshot을 받아 자기 `app.curated_trip_plans` /
`app.curated_plan_pois`로 복사한다. 저장 권장 컬럼:

- `curated_trip_plans.source_system = 'kor-travel-map'`
- `curated_trip_plans.source_collection_id`
- `curated_trip_plans.source_etag`
- `curated_trip_plans.source_imported_at`
- `curated_plan_pois.source_curation_item_id`
- `curated_plan_pois.source_feature_id`

PinVi는 `feature_id`를 파싱하지 않는다. item에 `feature_id`가 없으면 PinVi도 nullable로
저장하고, `curated:<id>` 같은 가짜 feature id를 만들지 않는다. 40C 이전 참조를 옮기는
경로는 §3.3 identity mapping이며, 전환 절차는
[`docs/runbooks/tvn40-pinvi-cutover.md`](runbooks/tvn40-pinvi-cutover.md)가 정본이다.

## 6. Admin UI 요구사항

정본 화면은 `/admin/features/curated` 하나다(collection 관리 + quarantine 패널).
40C가 `/admin/curated-features`(legacy 목록)와 legacy 상세 라우트를 삭제했다.

- collection 관리 탭에서 기존 theme 선택 또는 theme slug/name/group 직접 입력,
  제목·회차·출처·상태·공개범위를 수동 입력한다.
- CSV 양식 다운로드, dry-run preview, 형식 오류 0건 확인 뒤 전체 반영을 제공한다.
  미연결·복수 후보 행은 그대로 표시하지만 반영을 막지 않는다.
- collection 상세는 연결/미연결 item을 모두 표시한다. Feature 지도·목록·상세는 한
  Feature에 연결된 여러 회차·출처 membership과 여러 provider 현재 관측을 모두 표시한다.
- quarantine 패널은 소유자 불명 collection을 분리해 보여주고 reclassify를 제공한다.
- source rule 화면에서 "이 provider dataset은 기본 candidate/ignore"를 지정한다.
- `rejected`/`archived` item은 "되살리기"를 명시 action으로만 처리한다.

화면별 점검 목록은
[`docs/runbooks/admin-ui-screen-checklist.md`](runbooks/admin-ui-screen-checklist.md)다.

## 7. Dagster 경계

독립 curated metadata/rule/sweep/cache asset은 없다(T-VN-40). authoritative provider
full-snapshot terminal transaction만 source observation과 candidate generation을 시작할
수 있고, catalog semantic 변경은 typed command가 affected rule reconcile을 같은
transaction에서 수행한다.

중요 규칙:

- `rejected`/`archived`는 자동 rule apply가 되살리지 않는다.
- source metadata refresh가 공공데이터포털 수정일을 바꿨다면 admin UI와 service
  snapshot payload에 새 값을 노출한다.
