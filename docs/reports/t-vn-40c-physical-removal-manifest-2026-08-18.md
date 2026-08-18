# T-VN-40C — legacy 물리 삭제 manifest (사전 작성 · 실행은 receipt complete 뒤)

- 날짜: 2026-08-18 · 상태: **설계/manifest 초안 → 적대 리뷰 2명 → 확정. 실행(0224 적용)은 T-VN-40 인수
  ①~④(migration → import → soak → receipt complete) 뒤에만.**
- 근거: 상세 설계 §6.2 step 6–7, ADR-075 결정 4(soak 전 legacy 제거 금지), `docs/tasks.md` "T-VN-40 인수 —
  실태" 사전 task 3, `contracts/vnext/target-schema-v1.sql` §12(목표 상태에 legacy 없음),
  `contracts/vnext/target-invariants-v1.sql` INV-040-09(post-backfill: `to_regclass('feature.curated_features') IS NULL`).
- 기계 판독본: `contracts/vnext/t-vn-40c-removal-manifest-v1.json`(이 문서와 1:1; typed tombstone —
  static zero gate의 허용 위치). migration 초안: `docs/reports/tvn40c/0224_tvn40c_physical_removal.py.draft`
  (alembic이 읽지 않는 위치. 실행 시점에 `alembic/versions/0224_…py`로 옮기고 head pin을 함께 올린다).

## 0. 실행 선행조건 (전부 참이어야 0224를 적용한다)

| # | 조건 | 확인 방법 |
|---|---|---|
| P1 | T-VN-40 인수 ①~④ 완료: `contracts/vnext/consumer-rollout-v1.json` T-VN-40 receipt `state=complete`, `blocking_reason` 없음 | receipt 파일 + `test_vnext_contract_artifacts` |
| P2 | soak 동안 legacy read ↔ canonical read 대조가 끝났고 legacy read 소비자(admin 화면·public map·PinVi)가 0 | 아래 §3의 소비자 목록이 전부 canonical로 전환·머지됨(코드 grep = 0) |
| P3 | `count(feature.curated_features) == count(ops.curation_cutover_identity_mappings)` (① 이후 legacy 신규 write 0) | prod read-only SQL |
| P4 | PinVi backfill이 mapping을 소비 완료(PinVi 쪽 receipt) — mapping 표는 **남긴다**(삭제 대상 아님) | docker-manager paired receipt |
| P5 | prod 백업/PITR 복구점 확인(0224는 forward-only·데이터 파괴) | runbook `c7-prod-live-e2e.md` 백업 절차 |
| P6 | dedup merge 큐에 same-theme legacy-conflict 후보 0(0224가 merge의 legacy detach 경로를 지우므로) | `ops.dedup_review_queue` pending 중 legacy 관련 0 |

## 1. DB 삭제 순서 (0224 — forward-only, 단일 트랜잭션, 각 DROP은 `RESTRICT`)

`DROP … RESTRICT`를 쓰는 이유(설계 §6.2 step 6): 이 manifest가 모르는 dependent가 있으면 트랜잭션이 죽고
manifest를 고친 뒤 다시 실행한다 — "trigger disable" 같은 우회는 없다.

| # | 대상 | 조치 | 비고 |
|---|---|---|---|
| D1 | `feature.merge_lock_legacy_curated_features(text,text)` · `merge_archive_conflicting_legacy_curated_features(text,text)` · `merge_sync_master_legacy_curated_features(text)` · `merge_move_legacy_curated_features(text,text)` (0222 ①~④) | `DROP PROCEDURE … RESTRICT` | `merge_lock_curation_collections`(0222 ⑤, canonical)은 **유지** |
| D2 | `feature.trg_sync_curated_feature_collection` (ON `curated_features`) · `feature.sync_curated_feature_collection()` (0045) | DROP TRIGGER → DROP FUNCTION RESTRICT | canonical companion 생성 경로 종료 |
| D3 | `feature.trg_curation_items_source_rule_decision` (ON `curation_items`) · `feature.issue_curation_source_rule_decision()` — 유일한 입력이 legacy projection(`selection_origin='source_rule'` 행)이며 그것으로 `match_basis='source_rule'` link decision을 발행 | DROP TRIGGER → DROP FUNCTION RESTRICT | canonical 대체는 T-VN-40B promotion(0204)이 같은 트랜잭션에서 accepted link decision을 기록하는 경로. **리뷰 확인 항목**: 0204/0205 경로가 `source_rule` basis decision을 빠짐없이 내는지 |
| D4 | (삭제 — 초안의 `provider_sync.validate_data_integrity_violation_dataset` legacy 참조는 grep 범위 오류였다; 본문에 참조 없음) | — | — |
| D5 | `feature.curation_items.legacy_projection_id` — FK `fk_curation_items_legacy_projection_id_curated_features` · partial UNIQUE `uq_curation_items_legacy_projection_id` · 컬럼 | DROP CONSTRAINT → DROP INDEX → DROP COLUMN | 0045 mirror identity의 마지막 흔적 |
| D6 | `feature.curated_feature_detail_snapshots` (FK → curated_features; index 2) | `DROP TABLE … RESTRICT` | 읽는 코드 0(#994 확인) |
| D7 | `feature.curated_features` (PK·FK 4·index 4·partial UNIQUE 1) | `DROP TABLE … RESTRICT` | D2·D5·D6이 먼저 풀려야 RESTRICT가 통과한다 |
| D8 | 0074의 4 FK `fk_curation_import_rows_item` · `fk_curation_link_decisions_import_row` · `fk_curation_link_decisions_item` · `fk_curation_link_decisions_supersedes` — `ON UPDATE CASCADE` | 같은 정의로 `ON UPDATE NO ACTION`으로 재생성 | rekey 경로(merge detach)가 D1·D5로 사라짐 |
| D9 | `feature.reject_curation_history_mutation()` — "curation_item_id 하나만 바뀐 UPDATE 통과" 분기 | 무조건 거부로 `CREATE OR REPLACE` | 설계 §6.2 step 6 |
| D10 | ACL: `runtime_privileges._FEATURE_TABLE_PRIVILEGES`에서 `curated_features`·`curated_feature_detail_snapshots` 제거 → 배포 후 reconcile | 코드 변경 + `reconcile_runtime_privileges` | 표 없는 항목은 phantom(#994 교훈) — 같은 PR |
| D11 | **남기는 것**: `ops.curation_cutover_identity_mappings`(+ FK → `curation_items` ON DELETE RESTRICT, UPDATE 비cascade) | 유지 | PinVi cutover 증거. `curation_items`는 물리 삭제하지 않는 표라(archived_at) RESTRICT가 실무를 막지 않는다 — 앱 코드에 `DELETE FROM feature.curation_items` 0건 확인 |
| D12 | `alembic check` 정합: `models.py`의 `CuratedFeatureRow`·`CuratedFeatureDetailSnapshotRow` 제거, `_application_migration_graph.json` 재생성, head pin 0224 | 코드 | `test_alembic_metadata_consistency` |

## 2. 코드 삭제 (같은 PR — API/repo/lint/ACL)

| 영역 | 삭제 | 유지 |
|---|---|---|
| `packages/kor-travel-map-api/src/kortravelmap/api/routers/curated.py` | `/features/curated*` 5 + `/curated-features*` alias 5 + `detail-snapshot` + `place-search` route, `_fence_legacy_curated_writes` dependency, `CuratedFeature*` 응답 모델 | `curated-themes/sources/source-rules` catalog route(plan:28 "catalog input만 유지") |
| `route_policy.py` · `domain_command_registry.py` · `curated_public_schema.py` · `prometheus.py` | legacy route/command/metric 항목(13·5·3·1) | — |
| `src/kortravelmap/infra/curated_repo.py` | `list_curated_features` · `get_curated_feature` · `get_curated_feature_detail_snapshot` · `create/update/set_curated_feature_status/archive_curated_feature` · legacy SQL 상수 · `CuratedFeature*` DTO | `list/get_curated_themes/sources/source_rules` + `*_command` catalog 함수 |
| `src/kortravelmap/infra/legacy_write_fence.py` · `tests/lint/test_legacy_write_fence.py` · `tests/integration/test_tvn40a_legacy_write_fence_acl.py` · router 410 테스트 | 전부(표가 없으면 fence도 없다) | — |
| `src/kortravelmap/infra/merge_repo.py` | legacy mirror CALL 4곳 · `_DETACH_CONFLICTING_LEGACY_CURATION_ITEMS_SQL` · `_PINNED_LEGACY_CONFLICT_ITEMS_SQL` · `_ARCHIVE_CONFLICTING_LEGACY_CURATED_FEATURES_SQL` 사용부 | canonical lock/reconcile |
| `src/kortravelmap/infra/curation_repo.py` | `_lock_legacy_projections_for_item` · `update_curation_item`의 legacy sync 분기 · legacy_projection 관련 SQL 조각 | canonical item/collection/import |
| `src/kortravelmap/infra/db.py` | `_ADMIN_CURATION_FEATURE_PROCEDURES`의 merge legacy 4개 signature | `merge_lock_curation_collections` |
| `src/kortravelmap/infra/models.py` | `CuratedFeatureRow` · `CuratedFeatureDetailSnapshotRow` + `infra/__init__` 재수출 | — |
| tests | `test_curated_repo.py`(legacy read/seed) · `test_merge_repo.py` legacy conflict 시나리오 · `test_public_features_view.py`/`test_notice_defensive_cast.py`의 legacy seed helper · `test_tvn40_identity_mapping_loader.py`(loader는 표가 있어야 도니 **삭제 대상** — 0223은 이력으로 남고 재실행되지 않는다) | canonical 테스트 |

## 3. 프론트엔드·소비자 (legacy read 표면 — P2 조건)

| 대상 | 조치 |
|---|---|
| `src/app/admin/curated-features/**` (redirect + detail read) · `src/app/admin/features/curated/[curatedFeatureId]/` (legacy detail) | 삭제; `/admin/features/curated`(canonical collections)만 남긴다 |
| `src/app/curated-features/**` (public map, `/v1/curated-features` read) | **결정 필요**: canonical public `/v1/curations*`로 전환(권장) 또는 삭제. 설계 §40B step 4: "Feature aggregate, public `/v1/curations*`, … 는 canonical만 읽도록 전환하고 `/v1/curated-features`는 같은 release에서 제거" → 전환 |
| `src/api/curated.ts` legacy hooks(`useAdminCuratedFeature`, `useCuratedFeatureDetailSnapshot`, `useAdminCuratedFeatures` 계열) · `api/types.ts` 재생성 | 삭제/재생성; theme/source hooks 유지 |
| e2e: `curated-features.spec.ts`(mock, canonical 화면이면 유지) · `curated-features-map.spec.ts` · scenario catalog `curated-feature-detail` surface | 전환/삭제 |
| user-client(`packages/kor-travel-map-user-client`) · PinVi vendor OpenAPI | `/v1/curated-features*` 없음을 확인(현재 0) |

## 4. 계약·검증 (static zero gate — 설계 §6.2)

1. `packages/kor-travel-map-api/openapi*.json` 재생성 → `contracts/vnext/openapi-diff-v1.json`에 제거 route를 typed
   tombstone으로 기록(허용 위치); `consumer-rollout-v1.json` T-VN-40 receipt에 `compat_drop_applied` 기록;
   `test_vnext_contract_artifacts` sha 재고정.
2. `contracts/vnext/target-invariants-v1.sql` INV-040-09가 이제 **실행 가능**(post-backfill 축) — freeze 테스트에서 통과.
3. **static zero**: `rg`로 `curated_features|legacy_projection|curated-features|/features/curated|CuratedFeatureRow|legacy_write_fence`가
   active code(`src/`, `packages/*/src`, `packages/kor-travel-map-admin/frontend/src`, `docs/` 현행 문서)에서 0 —
   허용 위치는 이 manifest JSON이 열거(`alembic/legacy_versions/`, `alembic/versions/0045~0223` 이력, `docs/archive/`,
   `docs/reports/`, `contracts/vnext/openapi-diff-v1.json.surfaces.*.removed`, `t-vn-40c-removal-manifest-v1.json`).
   `tests/lint/test_tvn40c_static_zero.py`가 이 allowlist로 fail-closed.
4. DB catalog zero: `pg_class/pg_proc/pg_trigger/pg_constraint`에 legacy 이름 0(예외 없음) — 통합 테스트.
5. `alembic check` clean · runtime preflight(API/Dagster 로그인이 EXECUTE 가능한 procedure 집합 = allowlist) ·
   `reconcile_runtime_privileges` 뒤 ACL 표 = DB.
6. API smoke: 제거 route 404, catalog route 200 · admin frontend build/e2e · PinVi vendor sha 대조.

## 5. 롤백 없음 — forward fix

0224는 데이터를 파괴하므로 되돌리는 migration은 없다. 실패 시(RESTRICT가 미지의 dependent를 잡음): 트랜잭션
전체 롤백 → manifest에 dependent를 추가 → 재실행. 적용 뒤 문제는 forward fix(백업은 P5).

## 6. 열린 결정 (리뷰에서 답할 것)

- Q1 public map(`/curated-features`)을 canonical `/v1/curations*`로 전환하는 범위(별도 PR? 40C와 같은 release?) —
  설계는 같은 release.
- Q2 `ops.curation_cutover_identity_mappings`의 FK를 유지할지(현재 유지 안): PinVi가 mapping을 소비 완료한 뒤에도
  identity 증거로 남기고 item 삭제를 영구히 RESTRICT — item은 원래 물리 삭제하지 않으므로 유지가 맞다고 본다.
- Q3 `test_tvn40_identity_mapping_loader.py`·0223 loader의 dedicated-DB 테스트는 표 삭제 뒤 돌 수 없다 → 삭제. 0223
  자체는 체인에 남는다(0104→0223 fresh replay 시 legacy 0행 → 0건 적재 → 0224가 표를 지움; **fresh DB에서도
  0202~0224 전체가 통과해야 한다** — dedicated-DB 테스트로 고정).
- Q4 D3 trigger 삭제 뒤 `source_rule` link decision 발행이 canonical 경로(0204 promotion·0205 generation)로 완전히
  덮이는지 — 통합 테스트로 고정한 뒤 삭제.
