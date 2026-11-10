# 장소 테마 속성 — MCST 테마 목록을 master Feature의 속성으로

> **상태**: 설계(2026-11-10, Map #1468 항목 A). 결정 요약은
> [ADR-121](../adr/121-mcst-theme-lists-as-place-attributes.md). 구현 전 소유자 확인 대상이다
> — 검색·필터 동작과 공개 Feature 수가 바뀐다.
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

#1468 조사 수치: 무장애↔가족/영유아 8,036, 박물관 표준↔MCST 반려동물 769(73%), 서울 서점↔
MCST 서점 목록. 목록 규모: 반려동물 23,928 · 무장애 12,529 · 가족/영유아 8,566 · 북카페 1,059 ·
아동서점 786 · 중고서점 411 · 독립서점 327 · 캠핑 2,476 · 세계음식 9,494 · 촬영지 8,803 ·
레저 14,554 / 5,074.

## 2. 운영 실측 (2026-11-10, 읽기 전용)

운영 Map DB(alembic 442)에서 rollback-only transaction과 임시 표로 잰 수치. 판정은 거친
근사다 — "master"는 primary link가 MCST가 아닌 active place Feature, 이름 점수는 정규화 없는
`similarity(name, name)`.

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

master 쪽 dataset(100m, s≥0.5 최상위 후보, 50건 이상): 박물관 표준 `datagokr_museums`(무장애 686·
가족 684·반려 733), 관광지 표준(146·132·57), 휴양림(80·75), MOIS bulk(촬영지 945·세계음식 690·
캠핑 119·반려 63), 서울 서점(북카페 53·중고 52), YouTube 후보(촬영지 63).

반려동물 목록 `CATEGORY2`: 동물약국 8,443 · 반려동물용품 5,390 · 동물병원 4,488 · 미용 2,014 ·
위탁관리 61(반려 업종 합계 **20,396**) / 여행지 874 · 박물관 854 · 카페 809 · 펜션 464 · 미술관 262 ·
문예회관 254 · 식당 14 · 호텔 1(동반 가능 장소 합계 **3,532**).

읽는 법:

- **겹침의 대부분은 MCST끼리다.** 무장애↔가족 약 8천 건이 가장 크다. 목록 무관 식별(§6)만으로
  이 겹침이 사라진다.
- **비MCST master에 붙는 행은 속성 목록에서 4~13%뿐이다.** 동물약국·병원·용품, 카페·식당 같은
  업종 master(MOIS 해당 업종)가 아직 Map에 거의 없기 때문이다.
- "master 없으면 보류"(D1-a)의 손실 근사: 무장애·가족 합집합 약 1만 1천(두 목록이 약 8천 건
  겹친다), 반려 동반 장소 약 2천 6백(반려 업종 20,396은 D2로 장소 취급이라 제외), 촬영지 약 7천
  7백 — **합계 약 2만 1천~2만 2천 개 공개 장소**가 지도·검색에서 빠진다.
- 이 표는 **근사**다 — 정규화 없는 이름 점수, 100m/30m 기준이고 §5의 v1 규칙과 다르다. 정확한
  수는 R2 dry-run이 v1 규칙으로 낸다. 소유자는 D1을 지금 잠정으로 고르고 R2 보고서로 확정한다.

## 3. 목록 분류

| slug | 갈래 | 속성 코드 | master 분류 호환(접두) | master 없을 때 |
|---|---|---|---|---|
| pet_friendly_culture_facilities_csv | 속성(반려 업종 행은 장소, D2) | `pet_friendly` | 제한 없음 | D1 |
| barrier_free_places_csv | 속성 | `barrier_free` | 제한 없음 | D1 |
| family_infant_culture_facilities_csv | 속성 | `family_friendly` | 제한 없음 | D1 |
| media_famous_places_csv | 속성 | `filming_location` | 제한 없음 | D1(D3) |
| independent_bookstores_csv | 장소 | `bookstore_independent` | `0104`·`0203`(카페) | MCST Feature |
| cafe_bookstores_csv | 장소 | `bookstore_cafe` | `0104`·`0203` | MCST Feature |
| children_bookstores_csv | 장소 | `bookstore_children` | `0104` | MCST Feature |
| used_bookstores_csv | 장소 | `bookstore_used` | `0104` | MCST Feature |
| world_restaurants_csv | 장소 | `world_cuisine` | `02` | MCST Feature |
| leisure_activity_facilities_csv | 장소 | — | `0108` | MCST Feature |
| leisure_classes_csv | 장소 | — | `0108` | MCST Feature |
| leisure_camping_facilities_csv | 장소 | — | `0306` | MCST Feature |
| golf_courses_status | 장소 | — | `010801` | MCST Feature |

- 속성 코드는 **사실**만 뜻한다("반려동물 동반 가능", "무장애 편의 있음", "영유아 동반
  편의", "영상 촬영지", 서점 유형, "세계음식"). 평가·추천 의미를 담지 않는다.
- 레저·캠핑·골프는 분류 코드가 이미 같은 정보를 담으므로 속성을 만들지 않는다. 이 넷의
  변화는 "master가 있으면 붙는다"와 "식별이 목록과 무관하다" 두 가지뿐이다.
- 분류 호환 접두는 `kortravelmap.category` 코드 기준이다. 구현 때 `category.md` 표와 대조해
  확정하고 rule version에 묶는다.
- 촬영지의 `MEDIATITLE`, 세계음식의 `CATEGORY2/3`(국가·요리) 같은 행 고유 값은 속성의
  근거(evidence)로 상세 응답에 싣는다(§7.2). 속성 코드를 세분화하지 않는다.

## 4. 데이터 모델

### 4.1 결정: 속성은 source link에서 유도한다

> Feature F가 속성 A를 가진다 ⇔ F에 걸린 `primary` 또는 `enrichment` source link 중
> 하나의 source entity가 A에 묶인 (dataset, entity 유형)에 속한다.

새 정본 상태는 catalog와 붙임 판정뿐이다.

```sql
-- 공개 catalog (seed는 migration). 라벨 변경은 typed command.
CREATE TABLE feature.place_attributes (
  attribute_code  text PRIMARY KEY CHECK (attribute_code ~ '^[a-z][a-z0-9_]{1,47}$'),
  label_ko        text NOT NULL,
  attribute_group text NOT NULL,           -- 'companion' | 'accessibility' | 'media' | 'bookstore' | 'cuisine'
  visibility      text NOT NULL DEFAULT 'public' CHECK (visibility IN ('public','admin_only')),
  sort_order      integer NOT NULL DEFAULT 0
);

-- 어떤 dataset·원천 entity 유형의 link가 어떤 속성을 뜻하는가.
-- entity 유형까지 키에 넣는 것은 D2 때문이다: 반려동물 목록의 반려 업종 행은
-- source_entity_type 'pet_business'로 적재하고 이 표에 묶지 않는다.
CREATE TABLE provider_sync.dataset_place_attributes (
  provider_dataset_id bigint NOT NULL REFERENCES provider_sync.provider_datasets,
  source_entity_type  text   NOT NULL,
  attribute_code      text   NOT NULL REFERENCES feature.place_attributes,
  PRIMARY KEY (provider_dataset_id, source_entity_type, attribute_code)
);

-- 행(원천 entity)마다의 붙임 판정. 대상 Feature는 여기 두지 않는다 — link가 정본이다.
CREATE TABLE provider_sync.theme_attach_decisions (
  source_entity_key text PRIMARY KEY REFERENCES provider_sync.source_entities,
  state        text NOT NULL CHECK (state IN
                 ('matched','created','ambiguous','unmatched','manual_attach','manual_hold')),
  rule_version text NOT NULL,              -- 'theme-attach-v1'
  evidence     jsonb NOT NULL,             -- 후보 상위 3개의 거리·이름점수·분류호환, 입력 정규화값
  input_fingerprint text NOT NULL,         -- 정규화 이름·좌표(5m 격자)·주소 — sticky 판정 키
  decided_at   timestamptz NOT NULL,
  decided_by   text NOT NULL               -- 'rule' | admin actor
);
```

- `matched`/`manual_attach`/`created`이면 그 entity의 link가 하나 있다(matched·manual은
  master에 `enrichment`, created는 MCST Feature에 `primary`). `ambiguous`/`unmatched`/
  `manual_hold`이면 link가 없다. 이 대응은 적재 transaction 끝에서 검사한다(어긋나면 실패).
- 공개 여부는 Feature의 공개 projection(ADR-067)이 정한다. 속성이 비공개 Feature를 새게
  하지 않는다. 퇴역 Feature에 남은 link는 속성을 만들지 않는다(공개 projection 밖).

### 4.2 버린 대안

| 대안 | 버린 이유 |
|---|---|
| `features.attribute_codes text[]` + GIN | link와 같은 사실의 두 번째 정본. merge(link 이동)·link 해제·퇴역·재적재마다 동기화가 필요하고 어긋남 검사 장치가 또 생긴다. 성능 근거는 아직 없다(§7.4). |
| `feature_places.payload`/`facility_info`에 기록 | 색인 불가, 원천 행 소유가 아닌 값이 master의 원천 소유 필드에 섞인다(field ownership 위반). |
| 큐레이션(`curated_themes`·collection/item) 재사용 | 편집 membership이고 운영자 승격이 필요하다. ADR-092가 source rule의 자동 공개 승격을 금한다. 수만 행을 수동 승격할 수 없다. |
| dedup 큐로 병합 | 속성 목록은 장소가 아니다 — "병합"은 MCST Feature를 먼저 만든다는 전제다. 운영 큐는 0건 병합 상태다. |

### 4.3 link 역할

- 붙은 MCST 행의 link는 **`enrichment`**다. master의 `primary`는 바뀌지 않는다.
  `retire_features_absent_from_snapshot`은 `primary`만 보므로 MCST 목록이 행을 빼도 master가
  퇴역하지 않는다(`feature_repo.py:4610`).
- MCST Feature(장소 목록, master 없음)는 처음 만든 목록의 link가 `primary`, 같은 장소의 다른
  MCST 목록 행은 `enrichment`다.
- **`apply_feature_merge`를 바꾼다**(현행 `_MOVE_LINKS_SQL`은 역할을 그대로 옮긴다,
  `merge_repo.py:149-159`): master에 이미 `primary`가 있으면 옮겨 오는 `primary`를
  `enrichment`로 강등한다. 전환 §8, 재판정 병합(§6), 이후 일반 dedup merge(#1468 B) 모두 이
  procedure를 탄다. master에 primary가 둘이면 표시 원천이 흔들리고, 옛 snapshot soft-delete
  SQL(`feature_repo.py:2548-2560`)에는 "다른 primary가 있으면 건너뜀" 가드가 없어 master가
  퇴역할 수 있다 — 그 가드도 같은 PR에서 넣는다. R1에서 운영의 기존 이중 primary를 센다.
- **theme entity 하나에 link는 최대 하나다.** `source_links` PK는 `(feature_id,
  source_entity_key)`라 DB가 막지 않는다. 판정이 바뀔 때마다 그 entity의 다른 link를 같은
  transaction에서 지우고, 적재 command 끝에서 "MCST entity당 link ≤ 1"을 검사해 어기면 실패한다.
- **MCST 장소 Feature의 primary 승계**: primary 목록이 행을 빼도 다른 MCST 목록의 link가 남아
  있으면 Feature를 퇴역시키지 않고 남은 link 하나를 결정적으로(장소 목록 > 속성 목록, 그다음
  link `created_at`) `primary`로 올리고, 이름·좌표·분류 base를 그 원천에서 기존 field-patch
  procedure로 다시 투영한다.

## 5. 붙임 규칙 `theme-attach-v1`

### 5.1 후보

- tier 1: `kind='place'`, `lifecycle_state='active'`, `quality_state='valid'`,
  `publication_state='published'`, primary link가 MCST가 **아닌** Feature. 별도로 같은 조건의
  suppressed Feature를 base 표에서 한 번 더 찾는다 — 채택 조건을 만족하는 suppressed 후보가
  있으면(운영자가 숨긴 장소) 붙이지도 MCST Feature를 만들지도 않고 `ambiguous`로 남긴다.
- tier 2(장소 목록·속성 목록 모두): 위 조건의 MCST 장소 Feature. tier 1이 없을 때만 본다.
  같은 장소의 여러 MCST 목록 행이 한 Feature로 모이는 길이다.

### 5.2 점수 — 좌표 있는 행

- 입력 점은 staging 표에 `ST_Transform(ST_SetSRID(ST_MakePoint(lon,lat),4326),5179)`로 **한 번**
  계산해 둔다. 후보 술어는 `ST_DWithin(f.coord_5179, s.pt_5179, 150)` — 열끼리 비교라 색인을
  탄다(ADR-012: 술어 안 `ST_Transform` 금지).
- 이름 정규화 `norm()`: NFKC → 소문자 → 법인 표기(`(주)`, `주식회사`) 제거 → **공백으로
  분리된** 끝 지점 토큰(`○○점`·`○○지점`·`본점`)만 제거(붙어 있는 `서점`·`반점`의 `점`은
  건드리지 않는다) → 괄호 안 내용은 **지점 토큰**으로 따로 떼어 두고 → 공백·구두점 제거.
  양쪽 모두 지점 토큰이 있는데 다르면(`스타벅스(강남점)`↔`스타벅스(역삼점)`) 후보에서 버린다.
  점수 `s`는 정규화 이름의 trigram 유사도(pg_trgm `similarity`와 같은 정의).
- **정본 구현은 하나다**: SQL은 거리로 후보만 가져오고(`ST_DWithin` 150m, 분류 호환), 점수·채택·
  동점 판정은 순수 Python 함수(`kortravelmap.core` 새 모듈) 하나가 한다. `core/scoring.py`의
  Jaro-Winkler `name_similarity`(dedup용)와는 다른 척도이며 섞어 쓰지 않는다.
- 채택(하나라도): `d ≤ 50m ∧ s ≥ 0.6` · `d ≤ 150m ∧ s ≥ 0.8`. 거리 제한 없는 "이름 완전 일치"
  규칙은 두지 않는다(체인 지점 오결합).
- 포함 보너스(한쪽이 다른 쪽을 포함하면 `s`를 올리는 규칙)는 두지 않는다 — `공영주차장`·
  `관광안내소` 같은 일반명에서 오결합한다. 일반명 목록(stop-name)은 `d ≤ 30m`에서만 채택한다.
- 분류 호환(§3 표)이 맞지 않는 후보는 버린다. "제한 없음" 목록은 분류를 보지 않는다. 단 D2의
  반려 업종 행은 장소 목록처럼 반려 업종·의료 계열 분류 접두로 제한한다(접두는 구현 때
  `category.md`에서 확정).
- 동점 처리: 점수 `(s, -d)`로 정렬. 1위와 2위가 **다른 Feature**이고 `s` 차 < 0.05이면
  `ambiguous`(붙이지 않음).

### 5.3 좌표 없는 행(레저 강습·골프 등)

- 주소 단서에서 시군구 코드를 얻고, 같은 시군구 후보 중 정규화 도로명주소가 같고 `s ≥ 0.8`,
  또는 같은 법정동에서 `s ≥ 0.9`. 둘 다 아니면 `unmatched`(장소 목록이면 MCST Feature).

### 5.4 sticky와 재판정

- `input_fingerprint`가 같고 붙은 대상이 active·published면 다시 계산하지 않는다(대상 고정).
- 다시 판정하는 경우: 정규화 이름·주소 변경, 지난 판정 좌표(evidence에 저장)에서 10m 넘게
  이동(격자 경계 떨림을 피하려고 격자가 아니라 거리로 본다), 대상이 퇴역·suppressed,
  `rule_version` 상향, 이전 상태가 `ambiguous`/`unmatched`, **이전 상태가 `created`이고 이번
  적재에서 tier 1 후보가 채택 조건을 만족**(D1-b가 수렴하는 길 — §6 승격 병합).
- `manual_attach`/`manual_hold`는 rule이 덮지 않는다(관리자 해제로만 풀린다).
- 임계값은 코드 상수 + `rule_version`. 바꾸면 version을 올리고 전 행을 재판정한다.

### 5.5 정밀도 게이트

enforce 전 dry-run(§10 R1)에서 목록별 무작위 200행(표본 부족 목록은 전수)을 사람이 판정해
`matched` 정밀도 ≥ 0.97, `ambiguous` 비율을 보고한다. 미달 목록은 enforce하지 않는다.

## 6. 적재 경로

- `file_rows_to_bundles`는 그대로 행을 정규화한다. 바뀌는 것은 load다 — MCST dataset은
  `load_bundle` 대신 **붙임 적재**(`attach_theme_observations`, SECURITY DEFINER typed
  command)를 탄다.
  1. source entity·record·head upsert(기존 경로, provenance·sync cursor·seal은 그대로 dataset별).
  2. 판정(§5) → decision upsert.
  3. `matched`: master에 `enrichment` link upsert. `created`: 공용 식별 namespace로 MCST
     Feature claim/생성(아래) + link. 보류 상태: link 없음. 어느 경우든 그 entity의 **다른**
     link는 같은 transaction에서 지운다(§4.3 entity당 link ≤ 1).
  4. **승격 병합**: 이전 상태가 `created`인 행이 이번에 tier 1 master를 얻으면(§5.4) MCST
     Feature를 master로 병합한다 — §8.2와 같은 procedure(link 강등 이동, curation item rebind,
     패자 `retired`+`suppressed`, lifecycle override, merge history, M05 `rebind` 사건). D1-b가
     수렴하는 유일한 길이다. 새 master 적재(MOIS 등)는 MCST 판정을 부르지 않으므로 수렴은 다음
     MCST 적재(주 1회) 또는 관리자 `re-judge` command 때 일어난다.
- **공용 식별 namespace**: `provider_feature_identities`에 MCST 전용 `system` dataset 행
  (`mcst_place_identity`)을 하나 두고 natural key를 `norm(이름)::norm(주소)`로 claim한다.
  어느 목록에서 먼저 왔든 같은 장소는 같은 Feature다. `feature_id`는 기존처럼 UUIDv7
  (ADR-098) — "결정적"은 값 계산이 아니라 **앵커가 목록과 무관하다**는 뜻이다.
  - 주소가 비면 key에 bjd 코드(없으면 좌표 100m 격자)를 넣는다 — `이름::`만으로는 전국 동명
    장소가 한 Feature로 접힌다.
  - `create_provider_feature_with_initial_state`가 요구하는 legacy alias(`head-schema.sql:4204`)도
    **dataset 없는 namespace seed**(`source_type="python-mcst-api:mcst_place"`)로 만든다. 옛
    dataset seed alias는 기존 Feature에 묶인 채 그대로 둔다(ADR-068 fence로 갱신 불가, 재사용
    안 함) — 그래서 collapse 뒤 다른 목록 행이 와도 23505 `alias_bound_elsewhere`가 나지 않는다.
  - **앵커가 퇴역 Feature를 가리키면 다시 claim하지 않는다.** 현행 merge는 앵커를 옮기지 않으므로
    (`merge_repo.py:149-165`), claim이 퇴역 Feature를 만나면 `ops.feature_merge_history`를 따라
    생존자로 가서 그쪽에 link를 붙인다(생존자 없음 = 퇴역 사유가 merge가 아님 → 새 Feature를 만들지
    않고 `ambiguous`). 이 추적 procedure와 grant는 R1 migration에 들어간다. 일반 provider 적재에도
    같은 재claim 문제가 있을 수 있다 — 범위 밖으로 기록만 한다.
- **snapshot에서 빠진 행 — 새 동작이다.** 현행 MCST 적재는 빠진 행을 아무것도 하지 않는다
  (`mcst_features.py:236`, `retire_absent_from_snapshot` 미사용). 새 경로는 수집이 완결된 dataset만
  (기존 `McstSlugAttempt`/`Failure` 규칙) 그 dataset entity 가운데 snapshot에 없는 것의 link와
  decision을 지운다. 그 뒤 link가 하나도 남지 않은 MCST 장소 Feature만 퇴역하고, primary만 빠진
  경우는 §4.3 승계를 한다. MCST dataset은 `retire_features_absent_from_snapshot`을 **쓰지
  않는다**(primary 부재만으로 퇴역시키므로 승계와 충돌). 자연키가 원문 `이름::주소`라 그동안 쌓인
  낡은 행이 첫 enforce에서 한꺼번에 정리된다 — R2 보고서에 dataset별 낡은 행 수를 싣고 게이트한다.
- 쓰기 순서·잠금은 기존 provider 적재와 같다(ADR-111 전역 gate, ADR-115 §11 순서).
- **master `row_revision`**: master의 공개 속성 코드 집합이나 공개 evidence `note`가 **실제로
  바뀔 때만** 올린다. 이유는 상세 ETag(= `row_revision`, `features.py:1441-1449`)다. service batch
  trip card에는 속성이 없으므로 PinVi `unchanged` 판정과는 무관하다. 공개 evidence에는
  `observed_at`을 싣지 않는다(재적재마다 본문이 바뀌어 ETag가 거짓이 된다).
- **curation seal**(ADR-099): `current_provider_curation_input_set`은 dataset의 head·link와 **link된
  Feature의 상태**(`row_revision` 등, `head-schema.sql:4353-4405`)를 접는다. enrichment link 때문에
  MCST seal 입력에 master 상태가 들어간다. capture와 seal이 한 transaction이고 ADR-111 전역 gate가
  다른 Feature 쓰기를 막으므로 같은 적재 안에서는 흔들리지 않는다 — R1에서 "master 적재와 MCST
  적재 교차" 통합 테스트로 확인한다. 위 `row_revision` 상향은 master dataset의 **다음** seal 입력을
  바꿀 뿐 이미 봉인된 것을 깨지 않는다.
- `_CATEGORY_REPROJECTION_SCOPES`(`feature_repo.py:3806`): D1-a면 속성 목록 4종은 Feature를
  소유하지 않으므로 빠진다. D1-b면 MCST 장소 Feature를 계속 소유하므로 **남는다**.

## 7. API·검색·OpenAPI

### 7.1 필터

- `attribute`(반복, 최대 5개, **AND**)를 추가한다: `GET /v1/features/search`, `/v1/features`,
  `/v1/features/in-bounds`(item·cluster), `/v1/features/nearby`, `GET /v1/admin/features`,
  `/v1/admin/features/in-bounds`. 모르는 코드·`admin_only` 코드(공개 경로) → 422.
- SQL: 술어는 **공용 fragment 하나**로 두고 모든 공개·admin 읽기 경로가 쓴다 —
  `_bbox_attribute_filter_sql`(bbox·cluster), 검색 `filtered` CTE, `q` 없는 bbox 검색
  `_FEATURE_SEARCH_CTE_SQL`(`feature_repo.py:1762`), 지역 검색 변형(2227-2245), nearby 좌표
  (2422-2454)·nearby by-target(2309-2363, `/nearby/by-target`), admin 목록
  (`admin_feature_repo.py:710`). 공개 읽기 SQL 목록을 열거해 fragment가 빠진 경로를 잡는 테스트를
  둔다(일부러 하나 빼서 빨갛게 확인).

  ```sql
  EXISTS (SELECT 1 FROM provider_sync.source_links sl
            JOIN provider_sync.source_entities se USING (source_entity_key)
            JOIN provider_sync.dataset_place_attributes dpa
                 ON dpa.provider_dataset_id = se.provider_dataset_id
                AND dpa.source_entity_type = se.source_entity_type
           WHERE sl.feature_id = f.feature_id
             AND sl.source_role IN ('primary','enrichment')
             AND dpa.attribute_code = :code)      -- 코드마다 하나(AND)
  ```
- 검색 cursor: version은 올리지 않는다. fingerprint(`_FeatureSearchContract`)에 정렬된 attribute
  목록을 **비어 있지 않을 때만** 넣어, 필터 없는 진행 중 v5 cursor가 그대로 유효하게 한다.
- `q`는 속성어("반려동물")를 해석하지 않는다. 자연어 해석은 이 설계 범위 밖이다.

### 7.2 응답

- `FeatureDetailResponse.attributes: list[FeatureAttributeView]` —
  `{code, label, group, evidence: [{dataset_key, observed_at, note}]}`. `note`는 촬영지
  `media_title`, 세계음식 원천 분류처럼 행 고유 값 한 줄(없으면 null).
- `FeatureSummary.attribute_codes: list[str]`(정렬). in-bounds item·search·nearby 목록에 실린다.
  공개 경로의 `attribute_codes`·`attributes`는 `admin_only` 코드를 뺀다.
- `GET /v1/place-attributes`(공개): catalog(`code`, `label`, `group`, `sort_order`).
- `FeatureTripCard`(service batch)는 **바꾸지 않는다**. PinVi trip card는 속성을 쓰지 않는다.
- admin: `GET /v1/admin/theme-attach-decisions`(state·dataset·rule_version 필터),
  `POST .../{source_entity_key}/attach`(대상 지정) · `/hold` · `/release`. typed command +
  audit, If-Match.

### 7.3 OpenAPI·PinVi

- `openapi.json`(admin 포함)과 `openapi.user.json`이 바뀐다. `openapi.service.json`은 바뀌지
  않는다(trip card·batch 불변).
- PinVi는 user·admin spec을 **머지된 Map commit** 기준 SHA 핀으로 vendor하고 회전 preflight가
  digest 불일치를 거부한다(2026-10-12 t1013b). 순서: **Map API PR 머지 → PinVi 재vendor PR(user +
  admin 핀, M05 pair contract 재생성) 머지 → pair 회전**. PinVi feature 읽기는 plain dict라
  (`app/schemas`에 `extra="forbid"` 없음) 추가 필드로 깨지지 않는다 — 코드 변경 없음.
- M05 사건의 출처 일반화(§8.3)는 `openapi.service.json`을 바꾸지 않아도 사건 의미가 바뀌므로
  `generate_m05_pair_contract.py`를 다시 돌린다.
- 큐레이션 `curation_relation`의 `pet_support`/`accessibility_support`/`family_support`는
  편집 membership 역할로 그대로 둔다. 속성과 이름이 비슷하지만 다른 축이다.

### 7.4 성능

공개 필터는 EXISTS 세 표 조인이다. `source_links` PK `(feature_id, source_entity_key)`,
`source_entities` PK, `dataset_place_attributes` PK가 받친다. 공개 검색은 `q`나 bbox가 필수라
(`feature_repo.py:6890`) 진짜 무bbox 경로는 없다. 위험은 둘이다.

- 전국 크기 bbox + cluster 모드에서 `(:attrs IS NULL OR EXISTS …)` 형태가 planner를 속성 쪽에서
  시작하지 못하게 한다 — 필터가 있을 때는 별도 SQL 분기로 속성 쪽(`idx_source_links_entity`)에서
  출발하는 계획을 쓴다.
- `attribute_codes` 응답 필드는 in-bounds·cluster hot path에서 행마다 세 표 집계다(ADR-073 예산).

구현 PR에서 운영 크기 fixture로 두 경우의 EXPLAIN·p95를 잰다. 예산을 넘으면 그때 파생
materialization을 별도 결정으로 둔다(정확성·단일 정본이 성능보다 앞, CLAUDE.md §1).

## 8. 기존 MCST Feature 전환

### 8.1 계획표(dry-run)

`ops.mcst_theme_migration_plan(feature_id, dataset_key, action, target_feature_id, evidence,
rule_version, planned_at)` — 실행 전 읽기 전용으로 채운다. `action`:

| action | 대상 | 처리 |
|---|---|---|
| `attach` | tier 1 master가 있는 MCST Feature | master로 병합, link `enrichment`로 강등 |
| `collapse` | 같은 장소의 다른 MCST Feature가 있음(무장애↔가족 8,036 등) | 생존자로 병합 |
| `keep` | 장소 목록, master 없음, 생존자 | `feature_id` 유지, 앵커만 공용 namespace로 이전 |
| `hold` | 속성 목록, master 없음 | D1에 따름(기본: 퇴역·비공개) |
| `ambiguous` | 후보 다툼 | 손대지 않음 → 관리자 판정 후 재계획 |

- `collapse` 묶음 = (거리·이름 채택 조건으로 이어진 MCST Feature) ∪ (같은 공용 namespace key를
  계산하는 MCST Feature). key가 같은데 서로 150m 넘게 떨어진 묶음은 `ambiguous`로 보낸다 — 그대로
  두면 `keep` 두 개가 같은 앵커를 claim하다 PK 충돌한다.
- `collapse` 생존자: 장소 목록 Feature > 속성 목록 Feature, 그다음 `created_at` 이른 것,
  그다음 `feature_id` 작은 것. 생존자는 이후 `keep` 또는 `attach`를 받는다(연쇄 1단계).
- D2를 따르면 반려 업종 행은 새 `source_entity_type`(`pet_business`)으로 다시 적재되어 entity
  key가 바뀐다(`uq_source_entities_provider_identity`가 유형을 포함). 계획표는 옛 entity의 Feature를
  새 entity에 이어 주는(`keep` 앵커 이전 + link 교체) 행을 함께 만든다. 이후 `CATEGORY2`가 업종↔
  비업종으로 바뀌는 드문 행은 entity가 바뀌어 재판정된다.
- 계획표는 소유자 확인 게이트의 근거다: 목록별 action 수, 정밀도 표본, 낡은 행 수(§6), PinVi
  참조 수(§8.3).

### 8.2 실행

- dataset별(작은 것부터, §10 R4) typed command 한 번에 한 묶음(≤ 2,000 Feature)으로,
  `merge_repo.apply_feature_merge`와 같은 의미론을 쓴다: link 이동(강등 포함), curation item
  rebind/archive와 link decision, 패자 `retired`+`suppressed`, lifecycle override(재활성화
  차단), `ops.feature_merge_history`. 각 퇴역마다 소비자 사건(§8.3)을 같은 transaction에서 남긴다.
- `keep`은 공용 namespace 앵커를 **추가**한다(같은 `feature_id`). 옛 dataset 앵커는 지우지 않고
  비활성 이력으로 남긴다 — 그 표에는 DELETE 권한이 없고(`head-schema.sql:27832`) 지울 이유도 없다.
  collapse 묶음의 다른 구성원 key도 생존자를 가리키는 앵커로 추가한다. 값은 바뀌지 않는다
  (ADR-048 #11).
- 모드 플래그를 `off`로 되돌리는 것은 **롤백이 아니다**. 전환 뒤 `off`로 돌리면 옛 경로가 옛
  dataset 앵커로 다시 claim해 퇴역 Feature를 만나거나 중복을 만든다. 전환 뒤 문제는 forward fix다.
- 실행 뒤 decision 표를 계획표에서 채운다(`attach`→`matched`, `keep`→`created`, `hold`→
  `unmatched`).
- 다시 돌려도 같은 결과(멱등): 이미 퇴역한 패자·이미 옮긴 앵커는 건너뛴다.
- 되돌림은 forward-only다. 잘못 붙은 행은 관리자 `release` → 재판정으로 고치고, 퇴역한 패자는
  되살리지 않는다(새 MCST Feature가 필요하면 새 id).

### 8.3 PinVi 참조

- PinVi는 `trip_day_pois`·`curated_plan_pois`·`feature_suggestions`에 `feature_id`/
  `feature_uuid`를 저장한다. 퇴역 id는 batch에서 `retired`, 단건 GET에서 404가 되고 PinVi는
  `feature_snapshot`으로 대체 표시한다(현행).
- 병합 대상이 있는 퇴역(`attach`·`collapse`)은 M05 `rebind`, 대상 없는 퇴역(`hold`)은
  `detach` 사건을 남긴다. 현재 사건 표(`ops.feature_reference_reconciliation_events`)는
  manual-provider dedup에 묶여 있다 — `case_id`·`resolution_id`(UNIQUE)·
  `manual_retire_transition_id`·`manual_retire_row_revision_after_transition`·`command_id`가 모두
  NOT NULL FK이고, insert 권한은 `ktm_manual_provider_dedup_procedure_owner`만, append-only trigger도
  manual-dedup 함수다(`head-schema.sql:17477-17497, 20447, 22781, 27620`). **사건 출처를 일반화**한다.
  - 새 출처 쌍 `ops.provider_feature_retire_cases`/`_resolutions`(전환 실행·승격 병합·MCST 퇴역
    공용). 퇴역 Feature 하나당 case 하나·resolution 하나(UNIQUE 유지).
  - 사건 행에 `origin_kind`(`manual_provider_dedup`|`provider_feature_retire`)를 두고 case/
    resolution FK를 출처별 CHECK + FK 쌍으로 바꾼다. `manual_retire_transition_id`는 실제
    `transition_feature_state`가 남긴 transition id, `command_id`는 전환·적재 typed command의
    `ops.domain_commands` 행으로 채운다 — 이름에 `manual`이 남지만 배선 계약을 바꾸지 않으려고
    열 이름은 그대로 둔다.
  - insert는 새 procedure owner 역할(`ktm_provider_feature_retire_procedure_owner`) + append-only
    trigger 일반화.
  - PinVi M05 모델은 `extra="forbid"`이고 위 세 값의 범위(≥1, ≥2)를 검사하지만
    `case_id`/`resolution_id`는 불투명 UUID로만 쓴다(PinVi `app/services`에 사용처 없음) — 위처럼
    모든 필드를 실제 값으로 채우면 PinVi 코드 변경은 없다. 그래도 사건 의미가 넓어지므로 M05 pair
    contract를 재생성한다(§7.3).
- PinVi 운영 M05 소비자는 기본 꺼짐이다(활성화 receipt 필요). 실행 전 **PinVi DB에서 계획표의
  퇴역 id를 참조하는 행 수**를 읽기 전용으로 센다. 0이면 진행, 0보다 크면 소비자 활성화 또는
  수용(옛 card snapshot 표시) 중 소유자가 고른다.
- redirect·alias·batch의 새 `merged` 상태는 만들지 않는다(PinVi `trip_card.feature_id ==
  item.feature_id` 불변식을 깨고 ADR-092 §4 shim 금지와도 어긋난다).

## 9. 열린 결정 (소유자)

§2 실측 때문에 D1이 이 설계에서 가장 큰 선택이다.

- **D1 — 속성 목록에서 비MCST master가 없는 행**(무장애·가족·반려 동반·촬영지).
  - (a) **보류**: 공개 Feature 없음. 원천 행·판정은 보존하고 매 적재 재판정해 master가 생기면
    자동으로 붙는다. "속성 목록은 Feature를 만들지 않는다"를 그대로 따른다. 대가: 지금 공개된
    장소 약 2만 1천~2만 2천 개(§2 근사)가 지도·검색에서 빠진다.
  - (b) **목록 무관 MCST 장소 하나로 남김**(권고): 장소 목록과 같은 규칙. 같은 장소의 여러 목록
    행은 Feature 하나 + 속성 여럿이 되고(무장애↔가족 8천 건 겹침 해소), 나중에 master가 생기면
    재판정이 그 Feature를 master로 병합한다(§8과 같은 사건). 중복 제거와 속성화는 모두 얻고
    데이터는 잃지 않는다.
  - (c) 절충: (b)이되 구조화 분류가 미분류(`00000000`)인 행은 (a). 촬영지 전부와 반려 업종
    대부분이 미분류라 사실상 "무장애·가족·반려 동반 장소만 남김"이 된다.
  - 권고 근거: §2에서 master가 없는 이유는 행이 장소가 아니어서가 아니라 업종 master(MOIS
    동물병원·약국·카페 등)를 아직 적재하지 않아서다. (a)는 그 공백을 데이터 손실로 바꾼다.
    (b)는 공백이 메워지면 자동 수렴한다.
- **D2 — 반려동물 목록의 반려 업종 행**(동물약국 8,443·용품 5,390·병원 4,488·미용 2,014·
  위탁 61). "동반 가능 장소"가 아니라 반려 업종 장소 자체다. 기본안: 구조화 `CATEGORY2`가 반려
  업종이면 그 행은 **장소 목록**으로 다루고 속성 `pet_friendly`를 붙이지 않는다(약국·용품점에
  "동반 가능" 배지는 사실이 아니다). 대안: 다른 행과 같이 속성 행.
- **D3 — 촬영지**(8,803, 전부 미분류). 기본안: 속성 목록(`filming_location`), master 없는 행은
  D1을 따른다. 대안: 큐레이션 collection(편집 공개)으로 옮기고 속성 목록에서 뺀다.

D1이 (b)로 정해지면 §3 표의 "master 없을 때" 열은 속성 목록도 "MCST Feature"가 되고, §8.1의
`hold` action은 쓰이지 않는다.

## 10. Rollout

| 단계 | 내용 | 게이트 |
|---|---|---|
| R0 | 이 설계·ADR-121 머지 | 소유자 확인(D1~D3) |
| R1 | migration: catalog 2표·decision 표·계획표·사건 출처 일반화. 붙임 엔진 + `KOR_TRAVEL_MAP_MCST_THEME_ATTACH_MODE=off\|dry_run\|enforce`(기본 off). dry-run CLI가 계획표·보고서 생성 | 단위·통합 테스트, n150 게이트(`~/gate-slot.sh`) |
| R2 | 운영 dry-run(읽기 전용 계획) → 보고서: 목록별 action 수, 정밀도 표본, ambiguous, PinVi 참조 수 | 소유자 확인 |
| R3 | API: 필터·응답·catalog·admin decision 화면. OpenAPI 재생성. Map PR 머지 → **PinVi 재vendor PR 머지 → 회전** | Map PR CI·리뷰 2인, PinVi 계약 CI |
| R4 | enforce + 전환 실행. 순서: 서점 4종 → 가족/영유아 → 무장애 → 촬영지 → 반려동물 → 세계음식 → 캠핑·레저·골프 | 목록마다 공개 수·검색 표본 확인 후 다음 |
| R5 | 판정 큐 운영(ambiguous 관리자 처리), dedup(#1468 B) 재가동과 정합 확인 | — |
| R6 | `docs/etl/mcst-feature-etl.md` 갱신, ADR-121 accepted | 운영 실측 |

- migration 번호: 현재 head `442`. 구현 PR을 열 때 열린 PR의 alembic 번호를 다시 확인하고
  다음 빈 번호를 쓴다. 모든 migration은 `SET ROLE ktm_feature_schema_owner`로 끝난다(RESET
  ROLE 금지).
- enforce 이전에 들어오는 새 MCST 적재는 현행 방식 그대로다.
- R4 운영 창: 모드 플래그와 `DISABLED_FEATURE_LOAD_SCHEDULES`는 env라 바꾸려면 pair 회전(재배포)이
  필요하다 — 창 안의 토글이 아니다. 창 동안 **모든** feature 적재 operation(MCST뿐 아니라 master 쪽
  MOIS·박물관·TourAPI 등)과 dedup(#1468 B 재가동분)을 닫는다. 묶음을 실행하기 직전에 계획표가
  기록한 master·패자의 `row_revision`을 현재 값과 대조해 다르면 그 행을 재계획한다(낡은 계획 차단).

## 11. 다른 항목과의 경계(#1468)

- **B**(`core/scoring.py` 우선순위·dedup 재가동): 이 설계는 scoring.py를 고치지 않는다. 이름
  유사도 helper가 필요하면 읽기만 한다. B가 `python-mcst-api` 우선순위를 넣는 것과 충돌하지
  않는다 — 전환 뒤 MCST가 master가 되는 경우는 장소 목록의 `keep`뿐이다.
- **C**(`maintenance.py` 쌍 규칙): 캠핑 MOIS↔MCST, 세계음식 MCST↔MOIS 0201, 박물관 표준↔MCST
  쌍은 이 붙임이 대신한다. C가 이 쌍을 dedup 규칙으로 넣으면 R4 이전에는 큐에만 쌓이고(운영
  병합 0건), R4 이후에는 MCST 쪽 Feature가 없어 후보가 사라진다. **C 담당과 이 세 쌍을 C 범위에서
  빼거나 R4까지 enqueue만 하도록 맞춘다.** KNPS 야영장↔MCST 4건도 같다.
- **D**(국가유산 행사): 무관.

## 12. 검증 계획(구현 PR)

- 붙임 규칙: 채택·거절 경계값(50/150m, 0.6/0.8), 지점 토큰 불일치 거절(`스타벅스(강남점)`),
  `서점`·`반점` 보존, 일반명 30m 제한, 분류 호환, ambiguous, suppressed 후보, 좌표 없는 행,
  sticky·재판정 사유별(10m 이동, `created`→tier 1 등장), manual 판정 보존.
- 식별: collapse 뒤 다른 목록 행 `created` 적재가 alias 충돌 없이 생존자에 붙음, 병합된 앵커를
  만나면 생존자로 추적, 주소 없는 동명 장소가 접히지 않음.
- link: entity당 link ≤ 1, primary 목록 행이 빠지면 승계, merge의 primary 강등, 옛 snapshot
  soft-delete의 다른-primary 가드.
- 적재: 두 목록에 같은 장소 → Feature 하나·속성 둘. 목록에서 행이 빠지면 속성만 사라지고
  master는 남음. MCST 장소 Feature는 마지막 link가 빠질 때만 퇴역. 수집 실패 slug는 link를
  지우지 않음.
- link·decision 대응 불변식 위반 시 transaction 실패(일부러 빨갛게 만들어 본다).
- 전환: 계획표 → 실행 → 재실행 멱등, `keep`의 `feature_id` 불변, 사건 수 = 퇴역 수, curation
  item rebind, lifecycle override로 재활성화 차단.
- API: 필터 AND, 422, cursor fingerprint(필터 없는 기존 cursor 유효), 공용 fragment 누락 탐지,
  `admin_only` 코드·비공개 Feature 비노출, 속성 변화 때만 ETag 변경, OpenAPI drift gate.
- seal: master 적재와 MCST 적재가 교차해도 stale-input이 나지 않음.
- 성능: 전국 무bbox `attribute=pet_friendly` 목록 EXPLAIN(운영 크기 fixture).

## 13. 설계 리뷰 기록

2026-11-10 적대 리뷰 2인(데이터·적재·전환 / 붙임·API·rollout). 반영한 High: collapse 뒤 legacy
alias 충돌(§6 namespace alias), merge가 앵커를 옮기지 않아 퇴역 Feature 재claim(§6 추적), merge의
primary 역할 유지와 snapshot soft-delete 가드(§4.3), `created` 행 재판정 부재로 D1-b 미수렴(§5.4·§6
승격 병합), entity당 link 다중화(§4.3), snapshot 정리가 새 동작임(§6), 150m 조회 밖 300m 규칙·
`점` 제거·포함 규칙 오결합(§5.2), M05 사건 필드 전부의 출처(§8.3), primary 부재 퇴역(§4.3 승계).
Medium: seal 입력의 master 상태, `row_revision` 상향 범위·ETag, 필터 SQL 경로 누락, `attribute_codes`
비용, D1 근사 수치 정정, 반려 업종 분류 제한, R4 창 동결·계획 신선도, `keep` 앵커 충돌, 모드 플래그는
롤백 아님, cursor version 유지, 재vendor 순서.
