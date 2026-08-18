# T-VN-40-mapping — `ops.curation_cutover_identity_mappings` 적재 migration 설계

- 날짜: 2026-08-18 · 상태: 설계(코딩 전) → 적대 리뷰 2명 → 구현
- 근거: 상세 설계 §6.2 step 3·§6.3(`t-vn-40-curation-write-model-detailed-design-2026-08-11.md:895-961`),
  `docs/tasks.md` "T-VN-40 인수 — 실태" 사전 task 2번, ADR-075 결정 4
- 선행: T-VN-40A fence(#994, main `3e0732b3`) — legacy write는 이미 막혀 있어 mapping을 뜨는 동안
  legacy 표가 움직이지 않는다(merge의 mirror만 0222 procedure로 남아 있고, 그것도 admin executor만).

## 1. 무엇을 만드나

migration `0223_tvn40_identity_mappings` 하나. 실행 시점에 `feature.curated_features`(legacy overlay)의
각 행을 정확히 하나의 canonical `feature.curation_items` 행에 대응시켜
`ops.curation_cutover_identity_mappings`(0202가 만든 immutable 표: PK legacy id · UNIQUE item id ·
UPDATE/DELETE/TRUNCATE trigger 거부)에 **한 번** INSERT한다. 이 표는 PinVi가
`GET /v1/service/curation-cutover/identity-mappings`(keyset + Merkle root, 이미 구현)로 소비해 old
plan/POI의 legacy UUID를 canonical item UUID로 backfill하는 **유일한** 입력이다.

**loader 외에 만들지 않는 것**: candidate lifecycle backfill(§6.2 step 3 전반부 — T-VN-40B `[~]`의 몫),
manifest 파일 artifact(receipt는 docker-manager가 service endpoint의 count/root로 남긴다), 새 표/열/API.

## 2. prod 실측 (2026-08-18, 읽기 전용, n150 map DB · head `0104_tvn36_final_fence`)

| 항목 | 값 |
|---|---|
| legacy 행 | **4,424** — 전부 `curated` · `archived_at IS NULL` · `selection_origin='source_rule'` · detached 0 |
| `curation_items.legacy_projection_id` | 4,424건, distinct legacy 4,424 → **정확히 1:1** |
| legacy 행당 projection item 수 | 1 × 4,424 (0도 2+도 없음) |
| collections | 59, 전부 `metadata.migrated_from = feature.curated_features`(0045 sync 산물) |
| items | 4,424 전부 `source_present=t` · `status='included'` · 미보관 |
| `ops.curation_cutover_identity_mappings` | prod에 아직 없음(0202 미적용 — ① 단계에서 생김) |

즉 prod는 가장 단순한 bucket(`legacy_projection`) 하나로 100% 덮인다. 그래도 loader는 §6.3의 다른
bucket과 fail-closed 규칙을 그대로 구현한다 — "0건이면 무시" 없음, 분류 불가 1건이면 중단.

## 3. 분류 규칙 (행 단위, 순서대로 첫 매치)

대상 = `feature.curated_features` 전체 행. `mapping_kind`는 0202 CHECK의 세 값이다.

| # | 조건 | mapping_kind | 근거 |
|---|---|---|---|
| A | `metadata @> '{"merge_projection_detached": true}'` | — **중단** | detached legacy row는 merge로 identity가 master로 옮겨진 뒤의 잔해다. PinVi가 어느 item을 봐야 하는지는 merge 의미의 결정이지 loader가 추정할 것이 아니다. prod 0건. 발생 시 사람 결정 뒤 재실행 |
| B | `curation_items.legacy_projection_id = curated_feature_id`인 item이 **정확히 1** | `legacy_projection` | 0045 sync가 만든 canonical companion — legacy row의 canonical identity 그 자체. archived 여부 무관(identity는 archive와 별개) |
| C | B가 0이고, `collection.theme_id = legacy.theme_id AND item.feature_id = legacy.feature_id AND item.archived_at IS NULL`인 item이 **정확히 1**이며 그 item이 `current_import_row_id IS NOT NULL` | `official_membership` | canonical import가 만든 official membership |
| D | C와 같은 조건인데 `current_import_row_id IS NULL`이고 `(created_by IS NOT NULL OR operator_updated_by IS NOT NULL)` | `manual_membership` | admin이 만든 membership |
| E | B ≥ 2 · C/D 후보 ≥ 2 · 후보 0 · C/D 조건에 걸리는 item이 있는데 import/admin 근거가 둘 다 없음 | — **중단** | ambiguous/unmapped. 원인별 count를 RAISE EXCEPTION 메시지에 담는다 |

`legacy_projection`이 있는데 C/D 후보도 함께 있는 경우: B가 우선(첫 매치). 같은 legacy가 두 item에
동시에 대응되는 것이 아니라 identity는 projection이고 나머지는 별도 membership이다.

## 4. `source_row_hash`

legacy 행의 **stable identity + 분류 시점 상태**의 SHA-256 hex. 정의(이 문서와 migration docstring,
그리고 검증 테스트가 같은 식을 갖는다):

```
sha256( concat_ws('|',
  curated_feature_id::text, theme_id::text, feature_id,
  coalesce(source_id::text,''), coalesce(source_record_key,''),
  curation_status, curation_relation, reuse_policy, selection_origin ) )   -- UTF-8
```

timestamp·content_version·metadata는 넣지 않는다(soak 중 mirror로 움직일 수 있는 값이라 "같은
identity인데 hash가 다르다"를 만든다). PinVi는 이 hash를 자기 provenance와 대조하는 tamper 증거로만
쓴다 — Merkle root(`KTMCUR*`, recovery-preflight-v1.json)는 이 5필드 leaf 위에서 이미 정의돼 있다.

## 5. 실행 형태·불변식

- migration 본문은 **plpgsql DO 블록 하나**(단일 트랜잭션, 실패 시 전체 rollback). 순서:
  1. 사전조건: `SELECT count(*) FROM ops.curation_cutover_identity_mappings` = 0 아니면 중단(재적용·
     오염 방지). 표는 immutable이라 부분 적재 뒤 재실행 자체가 불가능하다.
  2. A/E bucket count 계산 → 하나라도 > 0이면 원인별 count를 담아 RAISE EXCEPTION.
  3. B→C→D 순으로 INSERT … SELECT (한 번에).
  4. 사후조건: 적재 수 = legacy 행 수. 아니면 RAISE(→ rollback).
  5. RAISE NOTICE로 bucket별 count와 총계 — 운영 로그가 곧 manifest다.
- 실행 role: migration 기본(schema_owner). runtime ACL은 SELECT만(이미 `runtime_privileges` 표에 있음).
- forward-only(downgrade RAISE) — 0220~0222와 같다. immutable 표라 되돌릴 방법이 원래 없다.
- 시점: 0222 다음(0223). fresh DB(legacy 0행)에서는 0건 적재로 통과 — 사후조건 0=0. **fresh DB에서
  "0건 통과"가 "무시"가 아닌 이유**: 사전조건·bucket 검사·사후조건이 다 돌고, 통합 테스트가 seed된
  legacy 행으로 각 bucket과 각 중단 사유를 개별로 실측한다.

## 6. 검증

- 통합(testcontainers, n150): (a) 0223 적용 뒤 fresh DB에서 0건·NOTICE; (b) seed helper로 legacy row +
  projection item → `legacy_projection` 1건, hash가 Python 재계산과 일치, `GET …/identity-mappings`
  root가 `curation_cutover_identity_mapping_root`와 일치; (c) C/D bucket 각 1건; (d) 중단 사유별
  1건씩(detached · projection 2개 · 후보 0 · 후보 2 · 근거 없음) → migration 함수가 예외, 표는 0행 유지;
  (e) 재적용 방지(표에 1행 있으면 중단). 마이그레이션 함수를 테스트에서 직접 부를 수 있게 SQL 본문을
  모듈 상수로 두고 `_run_loader(session)`으로 노출한다.
- 단위: `_application_migration_graph.json` 재생성·head pin(0223)·docs `postgres-schema.md`.
- prod ①에서 실행 후 NOTICE의 count(=4,424 · legacy_projection 4,424 · 나머지 0)를 journal에 기록.
  `KOR_TRAVEL_MAP_MIGRATION_EXPECTED_HEAD`는 0223으로.

## 7. 열어 둔 것

- detached row(A)의 처리 규칙은 merge 의미론(dedup)과 함께 정해야 한다 — 지금은 fail-closed. prod 0건.
- 40C 물리 삭제 뒤에도 이 표는 남는다(PinVi cutover 증거). FK `ON DELETE RESTRICT`가 item 삭제를
  막으므로 40C manifest는 이 표를 삭제 대상에서 제외하거나 FK를 먼저 다뤄야 한다 — 40C-manifest 과제.
