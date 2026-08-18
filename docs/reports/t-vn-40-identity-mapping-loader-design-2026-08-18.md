# T-VN-40-mapping — `ops.curation_cutover_identity_mappings` 적재 migration 설계

- 날짜: 2026-08-18 · 상태: **적대 리뷰 2명 통과(둘 다 holds=true, P1 없음) → P2 반영 확정 → 구현**
- 근거: 상세 설계 §6.2 step 3·§6.3(`t-vn-40-curation-write-model-detailed-design-2026-08-11.md:895-961`),
  `docs/tasks.md` "T-VN-40 인수 — 실태" 사전 task 2번, ADR-075 결정 4
- 선행: T-VN-40A fence(#994, main `3e0732b3`). **주의(리뷰 P2)**: prod ①에서 fence ACL은 `alembic
  upgrade head` **뒤에** `runtime_privileges` reconcile로 적용된다(`api-entrypoint.sh`). 즉 0223이 도는 동안
  옛 이미지의 API/Dagster가 아직 legacy를 쓸 수 있으므로 loader는 §5의 `LOCK TABLE … IN SHARE MODE`로
  스스로 정지 상태를 확보한다.

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
| B | `curation_items.legacy_projection_id = curated_feature_id`인 item이 **1** | `legacy_projection` | 0045 sync가 만든 canonical companion — legacy row의 canonical identity 그 자체. archived 여부 무관(identity ≠ liveness; PinVi는 mapped-but-archived를 "resolved·retired"로 다루며 orphan이 아니다). 2개는 `uq_curation_items_legacy_projection_id`(partial UNIQUE)로 **불가** |
| C | B가 0이고, `collection.theme_id = legacy.theme_id AND item.feature_id = legacy.feature_id AND item.archived_at IS NULL AND item.legacy_projection_id IS NULL`(다른 legacy의 projection은 후보에서 제외)인 item이 **정확히 1**이며 그 item이 `current_import_row_id IS NOT NULL` | `official_membership` | canonical import가 만든 official membership |
| D | C와 같은 조건인데 `current_import_row_id IS NULL`이고 `(created_by IS NOT NULL OR operator_updated_by IS NOT NULL)` | `manual_membership` | admin이 만든 membership |
| E | C/D 후보 ≥ 2 · 후보 0(0045의 옛 UUID-mirror 형태 `legacy_projection_id IS NULL AND curation_item_id = curated_feature_id`도 여기 — prod 0) · C/D 조건에 걸리는 item이 있는데 import/admin 근거가 둘 다 없음 · **같은 item을 legacy 2행이 잡음**(PK/UNIQUE 위반 대신 구조화된 사유로 먼저 잡는다) | — **중단** | ambiguous/unmapped. 원인별 count를 RAISE EXCEPTION 메시지에 담는다 |

`legacy_projection`이 있는데 C/D 후보도 함께 있는 경우: B가 우선(첫 매치). 같은 legacy가 두 item에
동시에 대응되는 것이 아니라 identity는 projection이고 나머지는 별도 membership이다.
`mapping.collection_id`는 언제나 **item.collection_id**다(legacy theme에서 유도하지 않는다).

## 4. `source_row_hash`

legacy 행의 **stable identity + 분류 시점 상태**의 SHA-256 hex. 정의(이 문서와 migration docstring,
그리고 검증 테스트가 같은 식을 갖는다):

```
sha256( concat_ws('|',
  curated_feature_id::text, theme_id::text, feature_id,
  coalesce(source_id::text,''), coalesce(source_record_key,''),
  curation_status, curation_relation, reuse_policy, selection_origin ) )   -- UTF-8
```

**의미(리뷰 P2로 정정)**: 이 hash는 **Map이 적재 시점에 찍은 legacy 행 스냅샷 digest**다. PinVi는 재계산할
수 없고(자기 provenance에 theme_id/source_id/selection_origin/text feature_id가 없다) 어떤 소비자도 이 값을
대조하지 않는다 — soak 중 0222 merge mirror가 `curation_status/selection_origin/relation/reuse`·`feature_id`를
바꿔도 mapping 행은 immutable이므로 "현재 행과 hash가 다르다"는 정상이다. 역할은 Merkle root(`KTMCUR*`,
recovery-preflight-v1.json)의 leaf 입력 하나일 뿐이다. 바이트 인코딩은
`encode(x_extension.digest(convert_to(<text>, 'UTF8'), 'sha256'), 'hex')`로 고정(`text::bytea` 금지 — backslash
오해석). `'|'`는 오늘 어떤 필드에도 없고(prod 0건, feature_id는 `f_<bjd>_<k>_<hex>`) enum 꼬리가 서로 겹치지
않아 충돌 불가 — 검증 테스트가 이 사실을 단언한다.

## 5. 실행 형태·불변식

- migration 본문은 **plpgsql DO 블록 하나**(단일 트랜잭션, 실패 시 전체 rollback). 순서:
  0. `LOCK TABLE feature.curated_features, feature.curation_items, feature.curation_collections IN SHARE MODE`
     — READ COMMITTED에서 statement마다 snapshot이 달라 TOCTOU가 생기고, ① 시점엔 fence ACL이 아직
     적용 전이라 옛 이미지 writer가 살아 있을 수 있다(리뷰 P2).
  1. 사전조건: `SELECT count(*) FROM ops.curation_cutover_identity_mappings` = 0 아니면 중단(재적용·
     오염 방지). 표는 immutable이라 부분 적재 뒤 재실행 자체가 불가능하다.
  2. A/E bucket count 계산 → 하나라도 > 0이면 원인별 count를 담아 RAISE EXCEPTION.
  3. B→C→D 순으로 INSERT … SELECT (한 번에).
  4. 사후조건: 적재 수 = legacy 행 수. 아니면 RAISE(→ rollback).
  5. bucket별 count는 **RAISE NOTICE로 남기지 않는다** — `alembic/env.py`는 asyncpg로 돌고 log listener가
     없어 NOTICE가 버려진다(리뷰 P2). manifest는 적재 뒤 `SELECT mapping_kind, count(*) … GROUP BY 1`로
     읽어 migration 로그(Python `logging`)와 journal에 남기고, docker-manager receipt는 이미 service
     endpoint의 count/root를 기록한다.
- 실행 role: migration 기본(schema_owner). runtime ACL은 SELECT만(이미 `runtime_privileges` 표에 있음).
- forward-only(downgrade `RuntimeError("… forward-only …")`) — 0220~0222와 같고 `test_migration_forward_only`가
  문자열로 잡는다. immutable 표라 되돌릴 방법이 원래 없다.
- **트랜잭션 의미(리뷰 P2)**: `alembic/env.py`에 `transaction_per_migration`이 없고 0202~0223 어디에도
  `autocommit_block`이 없다 → prod ①의 `upgrade head`(0104→0223)는 **한 트랜잭션**이다. 0223이 RAISE하면
  0202~0223 전부 롤백돼 head는 0104로 남고 표도 생기지 않으며 `api-entrypoint.sh`는 30회 재시도 뒤 종료한다
  (= 컨테이너 기동 실패, 재시도는 재배포). 그래서 ① **직전에** 아래 read-only precheck을 prod에서 돌리고,
  ①까지 dedup merge를 금지한다(prod는 2026-08-13 이미지라 merge가 아직 성공하며 detached 행을 만들 수 있다).
  precheck: 이 문서 §2의 쿼리(detached·projection 0/2·theme mismatch·item 2중 claim) 전부 0.
- **새 FK가 만드는 불변식(리뷰 P2)**: `ops.curation_cutover_identity_mappings.curation_item_id →
  curation_items(curation_item_id)`는 `ON UPDATE CASCADE`가 아니다. merge의 legacy-conflict detach가
  `curation_item_id`를 rekey하는 경로(`merge_repo._DETACH_CONFLICTING_LEGACY_CURATION_ITEMS_SQL`)는 mapping이
  잡은 item에 대해 FK로 **막힌다** — identity 안정성 측면에서 원하는 바다. 0223 이후 same-theme legacy-conflict
  dedup merge는 raw FK 오류가 아니라 명시적 MergeConflictError여야 하므로 merge_repo가 그 경우를 먼저
  검사한다(이 PR 범위). 40C manifest는 이 표를 삭제 대상에서 제외하고 FK를 다뤄야 한다.
- **A/E 발생 시 해소 경로**: fence + immutable 표 + migration-only writer라 "사람이 legacy를 고쳐 재실행"할
  합법 경로가 없다. 규칙: precheck에서 걸리면 ①을 시작하지 않고, 원인을 dedup merge 취소·item 정리 등
  **canonical 쪽 admin command**로 해소한 뒤(legacy는 건드리지 않는다) 재실행. 그래도 남으면 별도 0224
  override migration으로 결정을 코드에 남긴다.
- 시점: 0222 다음(0223). fresh DB(legacy 0행)에서는 0건 적재로 통과 — 사후조건 0=0. **fresh DB에서
  "0건 통과"가 "무시"가 아닌 이유**: 사전조건·bucket 검사·사후조건이 다 돌고, 통합 테스트가 seed된
  legacy 행으로 각 bucket과 각 중단 사유를 개별로 실측한다.

## 6. 검증

- 통합(testcontainers, n150). loader SQL은 `alembic/versions/0223_*.py`의 모듈 상수이고 테스트는
  `importlib.util.spec_from_file_location`으로 로드한다(선례 `test_migration_forward_only.py`,
  `test_curation_link_basis.py`). `src/kortravelmap/`에는 두지 않는다 — runtime은 이 표에 SELECT만이다.
  (a) **dedicated DB**(baseline → `stamp 0104` → seed → `upgrade head`, 선례
  `test_alembic_metadata_consistency.py`)로 진짜 migrator 경로·전체 체인 롤백 의미를 실측: seed 없이 0건,
  seed 있으면 bucket B 1건 + `get_curation_cutover_identity_mapping_export(session)` root 일치;
  (b) `migrated_session` + `_run_loader`로 bucket 단위: legacy row seed는 0045 trigger가 projection item을
  자동 생성하므로 C/D/E 형태를 만들려면 `SET LOCAL session_replication_role = replica`(superuser)로
  trigger를 끄고 item을 직접 만든다; hash를 Python으로 재계산해 일치; (c) C/D 각 1건; (d) 중단 사유별
  1건(detached · 후보 0 · 후보 2 · 근거 없음 · item 2중 claim) → 예외 + 표 0행 유지; (e) 재적용 방지;
  (f) FK 불변식: mapping이 잡은 item의 `curation_item_id` UPDATE가 FK로 거부되고 merge_repo가 그 경우
  MergeConflictError를 낸다.
- head pin 이동 전수(리뷰 P2): `tests/unit/test_alembic_squash_boundary.py::_EXPECTED_REVISIONS`,
  `src/kortravelmap/_application_migration_graph.json`(재생성), `tests/unit/test_docker_dagster_runtime.py`
  image_head, `tests/integration/test_alembic_metadata_consistency.py` 2곳, `docs/architecture/postgres-schema.md`,
  `docs/tasks.md`·`docs/resume.md`의 "→0222", 배포 env `KOR_TRAVEL_MAP_MIGRATION_EXPECTED_HEAD`.
  `contracts/vnext/*`·`test_vnext_target_freeze`는 catalog 객체 비교라 행 적재와 무관.
- prod ①에서 실행 후 NOTICE의 count(=4,424 · legacy_projection 4,424 · 나머지 0)를 journal에 기록.
  `KOR_TRAVEL_MAP_MIGRATION_EXPECTED_HEAD`는 0223으로.

## 7. 열어 둔 것

- detached row(A)의 처리 규칙은 merge 의미론(dedup)과 함께 정해야 한다 — 지금은 fail-closed. prod 0건.
- 40C 물리 삭제 뒤에도 이 표는 남는다(PinVi cutover 증거). FK `ON DELETE RESTRICT`(+ UPDATE 비cascade)가
  item 삭제/rekey를 막으므로 40C manifest는 이 표를 삭제 대상에서 제외하고 FK를 먼저 다뤄야 한다 —
  40C-manifest 과제.
- §6.2 step 3의 나머지(legacy source_rule → candidate `legacy_backfill`, `default_action='curated'` 퇴역과
  `ck_curated_source_rules_action` VALIDATE)는 소유 줄이 없다 → `docs/tasks.md` T-VN-40B 아래에 명시 backlog
  줄을 추가한다(② blocker 아님 — candidate는 admin 전용이지 PinVi 입력이 아니다).
