# 장소 테마 속성 — MCST 테마 목록을 master Feature의 속성으로

> **상태**: accepted(2026-11-10, Map #1468 항목 A). 결정 요약은
> [ADR-121](../adr/121-mcst-theme-lists-as-place-attributes.md). 소유자 결정 D1~D3은 §9.
> **범위**: MCST 파일데이터 13개 목록(`providers/mcst.py`)의 Feature 생성 방식, 속성 데이터
> 모델, 붙임(matching) 규칙, 공개 API·OpenAPI, 기존 MCST Feature 전환, PinVi 영향, rollout.
> **범위 밖**: dedup 우선순위·schedule 재가동(#1468 B), 새 쌍 규칙(#1468 C), 국가유산
> 행사(#1468 D). §11에 경계를 적는다.

## 1. 문제

MCST 행 하나가 Feature 하나다. 식별은 목록마다 갈린다.

- legacy seed: `make_feature_id(..., category=spec.category,
  source_type="python-mcst-api:mcst_<slug>", source_natural_key="이름::주소")`
  (`mcst.py:709-715`).
- 운영 앵커(ADR-098 이후 실제 정본): `provider_sync.provider_feature_identities`의 PK
  `(provider_dataset_id, feature_kind, natural_key)` — dataset이 키에 들어 있다.

그래서 같은 박물관이 무장애 목록·가족 목록·반려동물 목록에 모두 있으면 Feature가 셋이고,
박물관 표준데이터 Feature까지 넷이다. 운영은 dedup 병합이 0건이고(#1468) dedup schedule도
멈춰 있어 겹침은 그대로 공개된다.

## 2. 운영 실측 (2026-11-10, 읽기 전용)

운영 Map DB(alembic 442)에서 rollback-only transaction과 임시 표로 잰 수치. 판정은 거친
근사다 — "master"는 primary link가 MCST가 아닌 active place Feature, 이름 점수는 정규화 없는
`similarity(name, name)`. 정확한 수는 R2 dry-run이 §5 규칙으로 낸다.

| dataset | active | 좌표 없음 | 비MCST master (100m, s≥0.5) | (30m, s≥0.7) | 다른 MCST 목록 (30m, s≥0.7) |
|---|---:|---:|---:|---:|---:|
| barrier_free | 12,529 | 0 | 1,059 | 731 | 8,164 |
| family_infant | 8,566 | 0 | 1,021 | 716 | 7,888 |
| pet_friendly | 23,928 | 0 | 898 | 688 | 940 |
| media_famous | 8,803 | 1 | 1,139 | 695 | 258 |
| world_restaurants | 9,494 | 0 | 702 | 429 | 122 |
| cafe_bookstores | 1,059 | 0 | 83 | 57 | 119 |
| independent_bookstores | 327 | 0 | 46 | 37 | 106 |
| children_bookstores | 786 | 0 | 16 | 6 | 18 |
| used_bookstores | 411 | 0 | 52 | 47 | 28 |
| leisure_activity | 14,554 | 0 | 74 | 19 | 293 |
| leisure_camping | 2,476 | 0 | 160 | 57 | 17 |
| leisure_classes | 5,074 | 5,074 | 0 | 0 | 0 |
| **합계** | **88,007** | | | | |

(골프장 현황은 운영에 active 행이 없다.)

- master 쪽 dataset(최상위 후보 50건 이상): 박물관 표준 `datagokr_museums`(무장애 686·가족 684·
  반려 733), 관광지 표준(146·132·57), 휴양림(80·75), MOIS bulk(촬영지 945·세계음식 690·캠핑 119·
  반려 63), 서울 서점(북카페 53·중고 52), YouTube 후보(촬영지 63).
- 반려동물 목록 `CATEGORY2`: 동물약국 8,443 · 반려동물용품 5,390 · 동물병원 4,488 · 미용 2,014 ·
  위탁관리 61(반려 업종 **20,396**) / 여행지 874 · 박물관 854 · 카페 809 · 펜션 464 · 미술관 262 ·
  문예회관 254 · 식당 14 · 호텔 1(동반 가능 장소 **3,532**).
- **겹침의 대부분은 MCST끼리다**(무장애↔가족 약 8천). **비MCST master 일치는 속성 목록에서
  4~13%뿐이다** — 업종 master(MOIS 동물병원·약국·카페 등)를 아직 적재하지 않았기 때문이다.

## 3. 목록 분류

| slug | 갈래 | 속성 코드 | tier 1 master 분류 호환(접두) |
|---|---|---|---|
| pet_friendly_culture_facilities_csv | 속성(반려 업종 행은 적재 안 함, D2) | `pet_friendly` | 제한 없음 |
| barrier_free_places_csv | 속성 | `barrier_free` | 제한 없음 |
| family_infant_culture_facilities_csv | 속성 | `family_friendly` | 제한 없음 |
| media_famous_places_csv | 장소(촬영지는 큐레이션, D3) | — | 제한 없음 |
| independent_bookstores_csv | 장소 + 속성 | `bookstore_independent` | `0104`·`0202` |
| cafe_bookstores_csv | 장소 + 속성 | `bookstore_cafe` | `0104`·`0202` |
| children_bookstores_csv | 장소 + 속성 | `bookstore_children` | `0104` |
| used_bookstores_csv | 장소 + 속성 | `bookstore_used` | `0104` |
| world_restaurants_csv | 장소 + 속성 | `world_cuisine` | `02` |
| leisure_activity_facilities_csv | 장소 | — | `0108` |
| leisure_classes_csv | 장소 | — | `0108` |
| leisure_camping_facilities_csv | 장소 | — | `0306` |
| golf_courses_status | 장소 | — | `010801` |

- **모든 목록에서 master가 없으면 MCST 장소 Feature가 된다**(D1 = b). 같은 장소의 다른 MCST 목록
  행은 그 Feature에 붙는다(tier 2). 그래서 "장소 목록"과 "속성 목록"의 차이는 속성 코드를 내느냐
  뿐이다.
- 속성 코드는 **사실**만 뜻한다("반려동물 동반 가능", "무장애 편의 있음", "영유아 동반 편의",
  서점 유형, "세계음식"). 평가·추천 의미를 담지 않는다.
- 레저·캠핑·골프는 분류 코드가 이미 같은 정보를 담으므로 속성을 만들지 않는다.
- 분류 호환 접두는 `kortravelmap.category` 코드 기준이고 규칙 버전에 묶인다.

## 4. 데이터 모델

### 4.1 속성은 source link에서 유도한다

> Feature F가 속성 A를 가진다 ⇔ F에 걸린 `primary` 또는 `enrichment` source link 중
> 하나의 source entity가 A에 묶인 (dataset, entity 유형)에 속한다.

```sql
-- 공개 catalog (seed는 migration).
CREATE TABLE feature.place_attributes (
  attribute_code  text PRIMARY KEY CHECK (attribute_code ~ '^[a-z][a-z0-9_]{1,47}$'),
  label_ko        text NOT NULL,
  attribute_group text NOT NULL CHECK (attribute_group IN
                    ('companion','accessibility','bookstore','cuisine')),
  visibility      text NOT NULL DEFAULT 'public' CHECK (visibility IN ('public','admin_only')),
  sort_order      integer NOT NULL DEFAULT 0
);

-- 어떤 dataset·원천 entity 유형의 link가 어떤 속성을 뜻하는가.
CREATE TABLE provider_sync.dataset_place_attributes (
  provider_dataset_id bigint NOT NULL REFERENCES provider_sync.provider_datasets,
  source_entity_type  text   NOT NULL,
  attribute_code      text   NOT NULL REFERENCES feature.place_attributes,
  PRIMARY KEY (provider_dataset_id, source_entity_type, attribute_code)
);

-- apply 모드 적재가 행마다 남기는 붙임 판정(관리자 조회용). link가 정본이고 이 표는 근거다.
CREATE TABLE provider_sync.theme_attach_decisions (
  provider_dataset_id bigint NOT NULL REFERENCES provider_sync.provider_datasets,
  natural_key  text NOT NULL,
  state        text NOT NULL CHECK (state IN
                 ('owner','matched','sticky','redirected','created','ambiguous','unresolved')),
  target_feature_id uuid,                  -- link가 걸린 Feature(보류 상태면 NULL)
  rule_version text NOT NULL,              -- 'theme-attach-v1'
  evidence     jsonb NOT NULL,             -- 후보 상위 3개의 거리·이름점수·tier
  decided_at   timestamptz NOT NULL,
  PRIMARY KEY (provider_dataset_id, natural_key)
);
```

- 공개 여부는 Feature의 공개 projection(ADR-067)이 정한다. 속성이 비공개 Feature를 새게
  하지 않는다. 퇴역 Feature에 남은 link는 속성을 만들지 않는다(공개 projection 밖).
- 판정 표는 dataset별 snapshot과 같이 움직인다 — snapshot에 없는 natural key의 판정은 지운다.

### 4.2 버린 대안

| 대안 | 버린 이유 |
|---|---|
| `features.attribute_codes text[]` + GIN | link와 같은 사실의 두 번째 정본. merge·link 해제·퇴역·재적재마다 동기화가 필요하다. 성능 근거는 아직 없다(§7.4). |
| `feature_places.payload`/`facility_info`에 기록 | 색인 불가, 다른 원천의 값이 master의 원천 소유 필드에 섞인다. |
| 속성 전체를 큐레이션으로 | 편집 membership이고 운영자 승격이 필요하다(ADR-092). 수만 행을 수동 승격할 수 없다. 촬영지만 큐레이션이 맞다(D3). |
| dedup 큐로 병합 | 운영 큐는 0건 병합 상태이고, 속성 행을 MCST Feature로 먼저 만든다는 전제다. |
| MCST 공용 식별 namespace(새 앵커 + dataset 없는 alias seed) | 설계 리뷰 1차안. 새 앵커 procedure·alias seed·앵커 이전이 필요하다. 같은 효과(목록과 무관한 한 Feature)를 tier 2 붙임과 기존 목록별 앵커로 얻으므로 단순한 쪽을 택했다(§6.2). |

### 4.3 link 역할

- 붙은 MCST 행의 link는 **`enrichment`**다. master의 `primary`는 바뀌지 않는다.
  snapshot 부재 퇴역은 `primary`만 보므로 MCST 목록이 행을 빼도 master가 퇴역하지 않는다.
- MCST 장소 Feature는 그 장소를 처음 만든 목록의 link가 `primary`, 같은 장소의 다른 목록 행은
  `enrichment`다.
- **`apply_feature_merge`를 바꾼다**(현행 `_MOVE_LINKS_SQL`은 역할을 그대로 옮긴다,
  `merge_repo.py:149-159`): master에 이미 `primary`가 있으면 옮겨 오는 `primary`를 `enrichment`로
  강등한다. 전환(§8), 수렴 병합(§6.4), 일반 dedup merge(#1468 B) 모두 이 procedure를 탄다.
- **snapshot 부재 퇴역 가드**: `_SOFT_DELETE_NOT_IN_SNAPSHOT_SQL`(`feature_repo.py:2548`)은 Feature에
  그 dataset 밖의 다른 `primary` link가 남아 있으면 퇴역시키지 않는다. 기존 이중 primary가 있어도
  한 원천의 부재가 Feature를 내리지 않게 한다.
- **MCST entity 하나에 link는 최대 하나다.** `source_links` PK는 `(feature_id, source_entity_key)`라
  DB가 막지 않는다. 붙임 엔진이 다른 Feature로 다시 붙일 때 그 entity의 옛 link를 같은
  transaction에서 지운다.

## 5. 붙임 규칙 `theme-attach-v1`

정본 구현은 하나다: SQL은 거리로 후보만 가져오고, 정규화·점수·채택·동점 판정은 순수 Python
모듈 `kortravelmap.core.theme_attach`가 한다. `core/scoring.py`의 Jaro-Winkler
`name_similarity`(dedup용)와는 다른 척도이며 섞어 쓰지 않는다.

### 5.1 후보

- 후보 조회: `kind='place'`, `lifecycle_state='active'`, `publication_state='published'`,
  `quality_state='valid'`, 좌표 150m 이내. 술어가 부분 GiST 색인
  `idx_features_coord_5179_gist`의 조건을 그대로 담아야 색인을 탄다.
  입력 점은 `MATERIALIZED` CTE에서 한 번 `ST_Transform`하고 술어는 `ST_DWithin(f.coord_5179,
  p.pt_5179, 150)` — 열끼리 비교라 색인을 탄다(ADR-012: 술어 안 `ST_Transform` 금지).
- tier 1: primary link의 provider가 MCST가 **아닌** Feature. tier 2: MCST Feature. tier 1이
  하나라도 채택되면 tier 2는 보지 않는다.
- suppressed Feature는 후보가 아니다(공개 projection 밖, 색인도 없다). 2026-11-10 운영에 active·
  valid·suppressed place는 0건이다. 운영자가 숨긴 장소 옆에 MCST 장소가 새로 생기면 dedup 리뷰가
  다룬다.
- 분류 호환(§3)이 맞지 않는 tier 1 후보는 버린다. tier 2는 분류를 보지 않는다(같은 원천 계열).

### 5.2 점수

- 이름 정규화 `norm()`: NFKC → 소문자 → 법인 표기(`(주)`, `주식회사`) 제거 → **공백으로 분리된**
  끝 지점 토큰(`○○점`·`○○지점`·`본점`)만 떼어 지점 토큰으로 둔다(붙어 있는 `서점`·`반점`의
  `점`은 건드리지 않는다) → 괄호 안 내용도 지점 토큰으로 떼어 둔다 → 공백·구두점 제거.
- 양쪽 모두 지점 토큰이 있는데 다르면(`스타벅스(강남점)`↔`스타벅스(역삼점)`) 후보에서 버린다.
- 점수 `s`는 정규화 이름의 trigram 유사도(pg_trgm `similarity`와 같은 정의: 앞 공백 둘·뒤 공백
  하나를 붙인 trigram 집합의 Jaccard).
- 채택(하나라도): `d ≤ 50m ∧ s ≥ 0.6` · `d ≤ 150m ∧ s ≥ 0.8`. 일반명(`공영주차장`·`관광안내소`·
  `화장실` 등 stop-name 목록)은 `d ≤ 30m ∧ s ≥ 0.9`에서만 채택한다. 거리 제한 없는 이름 일치나
  포함 보너스는 두지 않는다.
- 동점: `(s, -d)`로 정렬. **tier 1**의 1위와 2위가 다른 Feature이고 `s` 차 < 0.05이면 `ambiguous`.
  tier 2(MCST끼리)의 동점은 같은 장소가 여러 목록에 있는 것이라 다툼이 아니다 — 1위를 고르고
  전환 계획이 묶음을 하나로 접는다(R2 첫 dry-run에서 ambiguous의 3/4이 tier 2 동점이었다).

### 5.3 좌표 없는 행

레저 강습(5,074, 전부 좌표 없음)과 골프장 현황은 좌표가 없다. 실측 겹침이 0이므로 v1은 이
행들을 붙이지 않고 자기 목록의 장소 Feature로 둔다(현행과 같음). 주소 기반 붙임은 필요가
확인되면 규칙 버전을 올려 더한다.

### 5.4 정밀도 게이트

R2 dry-run 보고서에 목록별 무작위 표본(목록당 50쌍)을 싣고, 사람이 판정한 `attach`/`collapse`
정밀도 ≥ 0.97을 R4의 전제로 한다. 미달 목록은 전환하지 않는다.

## 6. 적재 경로

### 6.1 모드

`KOR_TRAVEL_MAP_MCST_THEME_ATTACH_MODE` = `off`(기본) | `dry_run` | `apply`.

- `off`: 현행 적재(목록별 Feature).
- `dry_run`: 현행 적재를 그대로 하고, 같은 transaction 안에서 행마다 apply였다면 내렸을 판정을
  계산해 asset metadata·로그에 상태별 개수로 남긴다. DB에 판정을 쓰지 않는다.
- `apply`: §6.2 경로. **R4 전환과 같은 운영 창에서만 켠다** — 전환 전에 켜면 옛 목록별 Feature와
  새 경로가 섞인다. 전환 뒤 `off`로 되돌리는 것은 롤백이 아니다(옛 앵커가 퇴역 Feature를 다시
  claim한다). 전환 뒤 문제는 forward fix다.

D2 반려 업종 제외는 모드와 무관하게 변환 단계에서 한다(§6.5).

### 6.2 apply — 행마다

1. **자기 앵커**: `resolve_provider_feature_id(자기 dataset, place, natural_key)`.
   - active Feature → **owner**: 기존 `load_bundle` 그대로(그 목록이 그 Feature의 primary다).
   - 퇴역 Feature → **redirect**: `ops.feature_merge_history`를 따라(최대 8단계) active 생존자를
     찾는다. 있으면 생존자에 `enrichment` link(`match_method='theme_attach_redirect'`). 없으면
     `unresolved` — link를 만들지 않고 퇴역 Feature를 되살리지 않는다.
2. **sticky**: 그 entity의 기존 `enrichment` link가 active Feature를 가리키면 그대로 두고 원천
   record만 갱신한다.
3. **붙임**(§5): tier 1·2 채택 → `matched`, 그 Feature에 `enrichment` link. `ambiguous` → link 없음.
   같은 적재에서 먼저 만들어진 Feature도 tier 2 후보에 든다(같은 목록 안의 중복 행).
4. 아무것도 없으면 → **created**: `load_bundle`로 그 목록이 primary인 MCST 장소 Feature를 만든다.

source record·entity·head는 모든 상태에서 갱신한다(ambiguous·unresolved 포함) — provenance와
seal은 dataset별 그대로다. link를 새로 걸 때 그 entity의 다른 link는 지운다(§4.3).

### 6.3 snapshot에서 빠진 행

수집이 완결된 dataset만(기존 `McstSlugAttempt`/`Failure` 규칙) 그 dataset entity 가운데 snapshot에
없는 것의 **`enrichment` link와 판정을 지운다** — master의 속성만 사라진다. MCST가 primary인
Feature의 부재 처리는 현행과 같다(퇴역하지 않음, `mcst_features.py:236`). 그래서 primary 승계도
아직 필요 없다 — 부재 퇴역을 도입할 때 승계와 함께 결정한다.

### 6.4 수렴(D1-b)

MCST 장소 Feature가 나중에 생긴 master와 겹치면 master로 병합해야 한다. 적재 transaction 안에서
하지 않는다 — 병합은 curation item rebind·M05 사건까지 묶인 무거운 command다. 대신 §8 계획기가
`attach` action으로 잡고, 전환 executor가 같은 의미론으로 실행한다. 전환 뒤에는 같은 계획·실행을
주기적으로 돌린다(R5).

### 6.5 반려 업종 제외(D2)

`file_rows_to_bundles(slug="pet_friendly_culture_facilities_csv")`는 `CATEGORY2`가
`동물약국`·`반려동물용품`·`동물병원`·`미용`·`위탁관리`인 행을 건너뛴다(장소도 속성도 아니다).
이미 그 행으로 만들어진 운영 Feature는 MCST가 부재 퇴역을 하지 않으므로 남아 있다 — §8의 `retire`
action으로 내린다.

### 6.6 그 밖

- 쓰기 순서·잠금은 기존 provider 적재와 같다(ADR-111 전역 gate, ADR-115 §11). 한 dataset이 한
  transaction이다.
- **curation seal**(ADR-099): seal 입력은 dataset의 head·link와 link된 Feature 상태를 접는다.
  enrichment link 때문에 MCST seal 입력에 master 상태가 들어가지만 capture와 seal이 한
  transaction이고 전역 gate가 다른 Feature 쓰기를 막으므로 같은 적재 안에서는 흔들리지 않는다.
- master의 `row_revision`은 올리지 않는다. 상세 응답 ETag가 속성 변화를 놓치는 문제는 §7.2에서
  ETag에 속성 digest를 섞어 푼다.
- `_CATEGORY_REPROJECTION_SCOPES`는 그대로다(D1-b라 MCST 장소 Feature를 계속 소유한다).

## 7. API·검색·OpenAPI

### 7.1 필터

- `attribute`(반복, 최대 5개, **AND**)를 추가한다: `GET /v1/features/search`, `/v1/features`,
  `/v1/features/in-bounds`(item·cluster), `/v1/features/nearby`, `/v1/features/nearby/by-target`,
  `GET /v1/admin/features`, `/v1/admin/features/in-bounds`. 모르는 코드·`admin_only` 코드(공개
  경로) → 422.
- 술어는 **공용 fragment 하나**(`place_attribute_filter_sql`)로 두고 모든 읽기 경로가 쓴다.
  공개 읽기 SQL 목록을 열거해 fragment가 빠진 경로를 잡는 테스트를 둔다.

  ```sql
  EXISTS (SELECT 1 FROM provider_sync.source_links sl
            JOIN provider_sync.source_entities se ON se.source_entity_key = sl.source_entity_key
            JOIN provider_sync.dataset_place_attributes dpa
                 ON dpa.provider_dataset_id = se.provider_dataset_id
                AND dpa.source_entity_type = se.source_entity_type
           WHERE sl.feature_id = f.feature_id
             AND sl.source_role IN ('primary','enrichment')
             AND dpa.attribute_code = :code)      -- 코드마다 하나(AND)
  ```
- 검색 cursor: version은 올리지 않는다. fingerprint(`_FeatureSearchContract`)에 정렬된 attribute
  목록을 **비어 있지 않을 때만** 넣어, 필터 없는 진행 중 cursor가 그대로 유효하게 한다.
- `q`는 속성어("반려동물")를 해석하지 않는다.

### 7.2 응답

- `FeatureDetailResponse.attributes: list[FeatureAttributeView]` — `{code, label, group}`.
  상세 ETag는 `row_revision`과 공개 속성 코드 집합의 digest를 함께 쓴다.
- `FeatureSummary.attribute_codes: list[str]`(정렬). 목록·in-bounds item·search·nearby에 실린다.
  공개 경로는 `admin_only` 코드를 뺀다.
- `GET /v1/place-attributes`(공개): catalog(`code`, `label`, `group`, `sort_order`).
- `FeatureTripCard`(service batch)는 **바꾸지 않는다**.
- admin: `GET /v1/admin/theme-attach-decisions`(dataset·state 필터, 읽기 전용). 수동 붙임·보류
  command는 R5.

### 7.3 OpenAPI·PinVi

- `openapi.json`(admin 포함)과 `openapi.user.json`이 바뀐다. `openapi.service.json`은 바뀌지
  않는다.
- 순서: **Map API PR 머지 → PinVi 재vendor PR(user + admin 핀, M05 pair contract 재생성) 머지 →
  pair 회전**. PinVi feature 읽기는 plain dict라 추가 필드로 깨지지 않는다 — 코드 변경 없음.
- 큐레이션 `curation_relation`의 `pet_support`/`accessibility_support`/`family_support`는
  편집 membership 역할로 그대로 둔다. 속성과 이름이 비슷하지만 다른 축이다.

### 7.4 성능

필터는 EXISTS 세 표 조인이고 `source_links`·`source_entities`·`dataset_place_attributes` PK가
받친다. 공개 검색은 `q`나 bbox가 필수라(`feature_repo.py:6890`) 무bbox 경로는 없다.
`attribute_codes`는 페이지 행마다 같은 조인의 집계다. 구현 PR에서 운영 크기 fixture로 전국 bbox
cluster·in-bounds의 EXPLAIN을 재고, ADR-073 예산을 넘으면 파생 materialization을 별도 결정으로
둔다(정확성·단일 정본이 성능보다 앞).

## 8. 기존 MCST Feature 전환

### 8.1 계획기(dry-run, R2)

`ktm mcst-theme-plan`(읽기 전용)이 운영 MCST active Feature 전부를 §5 규칙으로 판정해 보고서를
낸다. action:

| action | 대상 | 처리(R4) |
|---|---|---|
| `retire` | 반려동물 목록의 반려 업종 행 Feature(D2) | 퇴역 + M05 `detach` |
| `attach` | tier 1 master가 채택된 Feature | master로 병합(link 강등) + M05 `rebind` |
| `collapse` | tier 2로 다른 MCST Feature와 같은 장소 | 생존자로 병합 + M05 `rebind` |
| `keep` | 위에 해당 없음(생존자 포함) | 그대로(`feature_id`·앵커 불변) |
| `ambiguous` | 후보 다툼 | 손대지 않음 → 관리자 판정 |

- `collapse` 묶음 = tier 2 채택 관계로 이어진 MCST Feature(union-find). 생존자: 장소 목록 Feature >
  속성 목록 Feature, 그다음 `created_at` 이른 것, 그다음 `feature_id` 작은 것. 생존자는 `keep`.
- `attach`가 우선한다: tier 1이 채택된 Feature는 tier 2 묶음에 들지 않는다.
- 보고서: 목록별 × action 개수, 목록별 정밀도 표본, PinVi 참조 수(§8.3).

### 8.2 실행(R4)

- dataset별(작은 것부터) 한 묶음 ≤ 2,000 Feature, `apply_feature_merge`와 같은 의미론: link 이동
  (강등 포함), curation item rebind/archive와 link decision, 패자 `retired`+`suppressed`, lifecycle
  override(재활성화 차단), `ops.feature_merge_history`. 퇴역마다 M05 사건을 같은 transaction에서
  남긴다.
- 실행 직전 계획이 기록한 master·패자의 `row_revision`을 현재 값과 대조해 다르면 그 행을
  재계획한다.
- 멱등: 이미 퇴역한 패자는 건너뛴다. 되돌림은 forward-only다.
- 앵커는 옮기지 않는다. 퇴역 패자의 목록 앵커는 그대로 남고, apply 모드 적재가 그 앵커를 만나면
  병합 이력을 따라 생존자로 간다(§6.2 redirect).

### 8.3 PinVi 참조

- PinVi는 `trip_day_pois`·`curated_plan_pois`·`feature_suggestions`에 `feature_id`/
  `feature_uuid`를 저장한다. 퇴역 id는 batch에서 `retired`, 단건 GET에서 404가 되고 PinVi는
  `feature_snapshot`으로 대체 표시한다(현행).
- `attach`·`collapse`는 M05 `rebind`, `retire`는 `detach` 사건을 남긴다. 현재 사건 표
  (`ops.feature_reference_reconciliation_events`)는 manual-provider dedup에 묶여 있다 —
  `case_id`·`resolution_id`(UNIQUE)·`manual_retire_transition_id`·
  `manual_retire_row_revision_after_transition`·`command_id`가 모두 NOT NULL FK이고, insert 권한은
  `ktm_manual_provider_dedup_procedure_owner`만, append-only trigger도 manual-dedup 함수다. R4
  executor PR에서 **사건 출처를 일반화**한다: 새 출처 쌍(`ops.provider_feature_retire_cases`/
  `_resolutions`), 사건 행의 `origin_kind`, 실제 transition id·command id로 모든 필드를 채운다.
  PinVi M05 모델은 `case_id`/`resolution_id`를 불투명 UUID로만 쓰므로 코드 변경은 없고 M05 pair
  contract만 재생성한다.
- PinVi 운영 M05 소비자는 기본 꺼짐이다. R2 보고서가 **PinVi DB에서 퇴역 예정 id를 참조하는 행
  수**를 읽기 전용으로 센다. 0보다 크면 소비자 활성화 또는 수용(옛 card snapshot 표시) 중 소유자가
  고른다.
- redirect·alias·batch의 새 `merged` 상태는 만들지 않는다(PinVi `trip_card.feature_id ==
  item.feature_id` 불변식, ADR-092 §4 shim 금지).

## 9. 소유자 결정 (2026-11-10)

- **D1 = (b)**: master가 없는 속성 목록 행은 목록과 무관한 MCST 장소 Feature 하나로 남고, master가
  생기면 그 master로 병합된다(§6.4).
- **D2**: 반려 업종 행(동물약국·반려동물용품·동물병원·미용·위탁관리, 약 20,396)은 **적재하지
  않는다**. 기존 운영 Feature는 R4 퇴역 계획(`retire`)에 들어가고 PinVi 참조 수·M05 사건은 다른
  퇴역과 같다. 동반 가능 행(약 3,532)만 `pet_friendly`를 낸다.
- **D3**: 촬영지(8,803)는 속성이 아니라 **큐레이션 collection**이다(§9.1).

### 9.1 촬영지 큐레이션 (D3)

기존 모델에 그대로 맞는다(`docs/curated-features.md`, ADR-092).

- 행은 다른 장소 목록처럼 master에 `enrichment`로 붙거나 MCST 장소 Feature가 된다. 속성 코드는
  없다.
- catalog는 이미 있다: 테마 `media-places`(public), source `37715bcb…`(dataset 48), rule
  `c09e1efd…`(`default_action='candidate'`). 후보 생성은 link 역할을 가리지 않으므로 master에 붙은
  촬영지 행도 후보가 된다 — 단 rule selector의 `place_kind='media_famous_place'`가 master의
  place_kind와 맞지 않는다. **R4에서 운영자가 admin API로 rule의 `place_kind`를 비운다**(PATCH는
  같은 transaction에서 rule reconcile을 돌린다). migration으로 catalog를 직접 고치지 않는다.
- 후보(`theme_feature_candidates`)는 admin 전용이다. **공개에는 운영자 승인이 두 번 필요하다**:
  (1) 후보를 collection item으로 승격(`POST /v1/admin/theme-feature-candidates/{id}/promote`, 대상
  collection 명시), (2) collection을 `status=published`·`visibility=public`으로 PATCH. collection은
  `media-places` 테마 아래 draft·admin_only로 만든다.
- 8,803건을 한 건씩 승격하는 것은 비현실적이다. **R5에서 일괄 승격 command**(운영자가 rule·지역
  등 필터와 대상 collection을 명시하고 한 번에 최대 500건, 각 후보는 기존 promote procedure를
  그대로 탄다)를 더한다. 이것도 운영자 명시 행위라 ADR-092의 자동 승격 금지와 맞는다.
- CSV import는 쓰지 않는다 — collection을 즉시 published/public으로 만들고 후보 lifecycle을
  건너뛴다.
- 승격 전까지 촬영지 장소는 지도에 보이지만 "촬영지"로 묶여 드러나지 않는다.

## 10. Rollout

| 단계 | 내용 | 게이트 |
|---|---|---|
| R0 | 설계·ADR-121 accepted | 소유자 결정(완료) |
| R1 | migration(catalog 2표·판정 표), 붙임 엔진 `off`/`dry_run`/`apply`(기본 off), 반려 업종 제외, merge 강등·부재 퇴역 가드·redirect, 계획기 CLI | 실패 우선 테스트, n150 게이트, 적대 리뷰, CI green |
| R3 | API: 필터·응답·catalog·admin 판정 조회, OpenAPI 재생성 → Map PR 머지 → **PinVi 재vendor PR 머지** | Map·PinVi CI |
| R2 | 운영 dry-run 계획 보고(목록별 × action, 표본, PinVi 참조 수) | 소유자 확인 |
| R4 | 전환 executor(+M05 사건 출처 일반화) → 운영 창: 적재·dedup 동결 → 계획 실행 → `apply` 켬(회전) → 촬영지 rule selector PATCH | 목록마다 공개 수·검색 표본 확인 후 다음 |
| R5 | 수렴 주기 실행, ambiguous 관리자 처리·수동 붙임 command, 촬영지 일괄 승격 command | — |
| R6 | `docs/etl/mcst-feature-etl.md` 갱신 | 운영 실측 |

R1과 R3은 한 Map PR로 묶어도 된다(둘 다 `off` 기본이라 동작이 바뀌지 않는다 — 반려 업종 제외만
즉시 적용되며 기존 Feature를 지우지 않는다). R4 운영 창의 env(`..._ATTACH_MODE`,
`DISABLED_FEATURE_LOAD_SCHEDULES`)는 pair 회전이 필요하다.

## 11. 다른 항목과의 경계(#1468)

- **B**(`core/scoring.py` 우선순위·dedup 재가동): 이 설계는 scoring.py를 고치지 않는다.
- **C**(`maintenance.py` 쌍 규칙): C 담당이 MCST 관련 쌍 규칙을 범위에서 뺐다(2026-11-10, 리뷰
  큐만). 캠핑 MOIS↔MCST, 세계음식↔MOIS, 박물관 표준↔MCST, KNPS 야영장↔MCST는 이 붙임이 대신한다.
- **D**(국가유산 행사): 무관.

## 12. 검증 계획

- 붙임 규칙: 채택·거절 경계값(50/150m, 0.6/0.8), 지점 토큰 불일치 거절, `서점`·`반점` 보존, 일반명
  30m 제한, 분류 호환, ambiguous, tier 1 우선.
- 적재(apply): 두 목록에 같은 장소 → Feature 하나·속성 둘. master가 있으면 MCST Feature 없음.
  owner·sticky·redirect·created·ambiguous 각 경로. 목록에서 행이 빠지면 enrichment link만 사라지고
  master는 남음. 수집 실패 slug는 link를 지우지 않음. entity당 link ≤ 1.
- merge 강등, 부재 퇴역의 다른-primary 가드(각각 실패 우선).
- 반려 업종 제외.
- 계획기: action 분류·collapse 생존자·attach 우선.
- API: 필터 AND, 422, cursor fingerprint(필터 없는 기존 cursor 유효), fragment 누락 탐지,
  `admin_only` 코드·비공개 Feature 비노출, 속성 변화 시 ETag 변경, OpenAPI drift gate.

## 13. 설계 리뷰 기록

2026-11-10 적대 리뷰 2인(데이터·적재·전환 / 붙임·API·rollout). 반영한 High: merge의 primary
역할 유지와 부재 퇴역 가드(§4.3), 병합으로 퇴역한 Feature 재claim(§6.2 redirect), `created` 행이
master로 수렴하지 않음(§6.4), entity당 link 다중화(§4.3), snapshot 정리가 새 동작임(§6.3 — enrichment
link만), 150m 조회 밖 300m 규칙·`점` 제거·포함 규칙 오결합(§5.2), M05 사건 필드 전부의 출처(§8.3),
primary 부재 퇴역(§6.3 — 현행 유지로 회피), 공용 namespace의 alias 충돌(§4.2 — namespace 자체를
버림). Medium: seal 입력의 master 상태, ETag, 필터 SQL 경로 누락, `attribute_codes` 비용, D1 근사
수치, R4 창 동결·계획 신선도, 모드 플래그는 롤백 아님, cursor version 유지, 재vendor 순서.
