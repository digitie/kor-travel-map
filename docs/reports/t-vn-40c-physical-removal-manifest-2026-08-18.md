# T-VN-40C — legacy 물리 삭제 manifest (사전 작성 · 실행은 receipt complete 뒤)

- 날짜: 2026-08-18 · 상태: **적대 리뷰 2명(DB/dependency · code/contract/consumer) 1차 — 둘 다 holds=false, P1 5건
  → 아래에 전부 반영(v2). 재리뷰 뒤 확정. 실행(0224 적용)은 T-VN-40 인수 ①~④(migration → import → soak →
  receipt complete) 뒤에만.**
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
| P2 | soak 동안 legacy read ↔ canonical read 대조가 끝났다. legacy read 소비자(admin legacy 화면·`/v1/curated-features*`)는 **40C PR 안에서** 삭제/전환된다(그 전에 0이 될 수는 없다 — route/repo가 40C까지 존재). public map은 이미 canonical(`/v1/curations*`)만 읽는다(§3) | §3 표 + static zero gate(§4.3)는 40C PR의 게이트 |
| P3 | `count(feature.curated_features) == count(ops.curation_cutover_identity_mappings)` (① 이후 legacy 신규 write 0) | prod read-only SQL |
| P4 | PinVi backfill이 mapping을 소비 완료(PinVi 쪽 receipt) — mapping 표는 **남긴다**(삭제 대상 아님) | docker-manager paired receipt |
| P5 | prod 백업/PITR 복구점 확인(0224는 forward-only·데이터 파괴: legacy 4,424행 + detail snapshot 500행) | runbook `c7-prod-live-e2e.md` 백업 절차 |
| P6 | dedup merge 큐에 same-theme legacy-conflict 후보 0(0224가 merge의 legacy detach 경로를 지우므로) | `ops.dedup_review_queue` pending 중 legacy 관련 0 |
| P7 | **PinVi lockstep** — 40C는 `openapi.user.json`을 바꾼다(`/v1/curated-features{,/{id}}` 제거 + public catalog 2 route 제거). `test_vnext_contract_artifacts`가 T-VN-40 receipt(`deployment_receipt_task`)의 `map_user_openapi_sha256`을 현행 spec bytes에, complete 뒤엔 `pinvi_user_vendor_sha256`과 동일하게 묶으므로 PinVi가 post-40C user spec을 재vendor하고 새 paired receipt(map_commit/pinvi_commit)를 같은 rollout에서 발행해야 한다. user-client `gen:types:check`도 같은 PR에서 재생성 | docker-manager paired receipt · PinVi PR · `packages/kor-travel-map-user-client` types 재생성 |

## 1. DB 삭제 순서 (0224 — forward-only, 단일 트랜잭션, 각 DROP은 `RESTRICT`)

`DROP … RESTRICT`를 쓰는 이유(설계 §6.2 step 6): 이 manifest가 모르는 dependent가 있으면 트랜잭션이 죽고
manifest를 고친 뒤 다시 실행한다 — "trigger disable" 같은 우회는 없다.

| # | 대상 | 조치 | 비고 |
|---|---|---|---|
| D1 | `feature.merge_lock_legacy_curated_features(text,text)` · `merge_archive_conflicting_legacy_curated_features(text,text)` · `merge_sync_master_legacy_curated_features(text)` · `merge_move_legacy_curated_features(text,text)` (0222 ①~④) | `DROP PROCEDURE … RESTRICT` | `merge_lock_curation_collections`(0222 ⑤, canonical)은 **유지** |
| D2 | `feature.trg_sync_curated_feature_collection` (ON `curated_features`) · `feature.sync_curated_feature_collection()` (0045) | DROP TRIGGER → DROP FUNCTION RESTRICT | canonical companion 생성 경로 종료 |
| D3 | `feature.trg_curation_items_source_rule_decision` (ON `curation_items`) · `feature.issue_curation_source_rule_decision()` — 유일한 입력이 legacy projection(`selection_origin='source_rule'` 행)이며 그것으로 `match_basis='source_rule'` link decision을 발행 | DROP TRIGGER → DROP FUNCTION RESTRICT | **리뷰 정정**: canonical 경로는 `source_rule` decision을 내지 않는다(0204 promotion은 `admin_review`, 0205 generation은 decision 없음). 그래도 삭제가 맞다 — canonical item에는 no-op이고 표가 없으면 오류만 낸다. `source_rule` basis decision은 **이력 전용**이 된다(prod 4,424건 보존, 신규 0) |
| D3b | **(리뷰 P1 추가)** `feature.trg_curation_items_legacy_component_identity` (BEFORE INSERT ON `curation_items`) · `feature.set_curation_item_legacy_component_identity()` — 본문이 `NEW.legacy_projection_id`를 읽는다. plpgsql 본문은 pg_depend 추적 대상이 아니라 D5가 성공한 뒤 **모든 curation_items INSERT가 42703으로 죽는다**(n150 실측; prod 0104에도 trigger 존재) | DROP TRIGGER → DROP FUNCTION RESTRICT, **D5보다 먼저** | target-schema-v1.sql §12에는 이 trigger가 없다 — 목표와 일치 |
| D4 | **(리뷰 P1 추가)** 0214 `feature.patch_curation_item_command`·`feature.archive_curation_item_command` — 본문이 `v_hint.legacy_projection_id` 분기·`curated_features` FOR UPDATE·mirror UPDATE를 갖는다(0214:335-357, 485-504, 565-576, 597-603). D7 RESTRICT는 plpgsql 본문을 못 잡고 실행 시 42703 | legacy 분기 제거본으로 `CREATE OR REPLACE PROCEDURE` — owner가 `ktm_curation_command_owner`이므로 `SET ROLE ktm_curation_command_owner` 아래서(grant는 replace 뒤에도 유지). 0213 collection command·0204 promotion 본문도 같은 검사(리뷰: 참조 없음) | catalog-zero 테스트는 이름만이 아니라 `pg_proc.prosrc`도 grep |
| D5 | `feature.curation_items.legacy_projection_id` — FK `fk_curation_items_legacy_projection_id_curated_features` · partial UNIQUE `uq_curation_items_legacy_projection_id` · 컬럼 | DROP CONSTRAINT → DROP INDEX → DROP COLUMN (D3b·D4 뒤) | 0045 mirror identity의 마지막 흔적 |
| D6 | `feature.curated_feature_detail_snapshots` (FK → curated_features; index 2) | `DROP TABLE … RESTRICT` | 읽는 코드 0(#994 확인) |
| D7 | `feature.curated_features` (PK·FK 4·index 4·partial UNIQUE 1) | `DROP TABLE … RESTRICT` | D2·D5·D6이 먼저 풀려야 RESTRICT가 통과한다 |
| D8 | 0074의 4 FK `fk_curation_import_rows_item` · `fk_curation_link_decisions_import_row` · `fk_curation_link_decisions_item` · `fk_curation_link_decisions_supersedes` — `ON UPDATE CASCADE` | 같은 정의로 `ON UPDATE NO ACTION`으로 재생성 | rekey 경로(merge detach)가 D1·D5로 사라짐 |
| D9 | `feature.reject_curation_history_mutation()` — "curation_item_id 하나만 바뀐 UPDATE 통과" 분기 | 무조건 거부로 `CREATE OR REPLACE` | 설계 §6.2 step 6 |
| D10 | ACL: `runtime_privileges._FEATURE_TABLE_PRIVILEGES`에서 `curated_features`·`curated_feature_detail_snapshots` 제거 → 배포 후 reconcile | 코드 변경 + `reconcile_runtime_privileges` | 표 없는 항목은 phantom(#994 교훈) — 같은 PR |
| D11 | **남기는 것**: `ops.curation_cutover_identity_mappings`(+ FK → `curation_items` ON DELETE RESTRICT, UPDATE 비cascade **및** FK → `curation_collections` ON DELETE RESTRICT) | 유지 | PinVi cutover 증거. `curation_items`는 물리 삭제하지 않는 표라(archived_at) RESTRICT가 실무를 막지 않는다 — 앱 코드에 `DELETE FROM feature.curation_items` 0건. 단 0215 quarantine release는 빈 quarantine collection을 DELETE한다 — mapping이 잡은 item의 collection이 0065 quarantine이면 막힌다(prod 오늘 quarantine collection 0 → 해당 없음; 발생 시 그 collection은 남긴다). `mapping_kind='legacy_projection'` enum 값도 유지(static zero 예외) |
| D12 | `alembic check` 정합: `models.py`의 `CuratedFeatureRow`·`CuratedFeatureDetailSnapshotRow` 제거 **+ `CurationItemRow.legacy_projection_id` 컬럼·`uq_curation_items_legacy_projection_id` index 매핑 제거**, `_application_migration_graph.json` 재생성, head pin 0224 전수(`test_alembic_squash_boundary`·`test_alembic_metadata_consistency` 2곳·`test_docker_dagster_runtime` 2곳·`test_migration_forward_only`·`postgres-schema.md`·`KOR_TRAVEL_MAP_MIGRATION_EXPECTED_HEAD`) | 코드 | `test_alembic_metadata_consistency` |

## 2. 코드 삭제 (같은 PR — API/repo/lint/ACL)

| 영역 | 삭제 | 유지 |
|---|---|---|
| `packages/kor-travel-map-api/src/kortravelmap/api/routers/curated.py` | `/features/curated*` 5 + `/curated-features*` alias 5 + `detail-snapshot` + `place-search` route, `_fence_legacy_curated_writes` dependency, `CuratedFeature*` 응답 모델, **public `GET /v1/curated-themes`·`GET /v1/curated-sources`**(Q5 — `openapi-diff-v1.json` `surfaces.user.removed`가 이미 T-VN-40C basis로 tombstone: "retained catalog는 admin typed surface만") | **admin** `/v1/admin/curated-themes|sources|source-rules` catalog route(plan:28 "catalog input만 유지") |
| `route_policy.py` · `domain_command_registry.py` · `curated_public_schema.py` · `prometheus.py` | legacy route/command/metric 항목(13·5·3·1) | — |
| `src/kortravelmap/infra/curated_repo.py` | `list_curated_features` · `get_curated_feature` · `get_curated_feature_detail_snapshot` · `create/update/set_curated_feature_status/archive_curated_feature` · legacy SQL 상수 · `CuratedFeature*` DTO | `list/get_curated_themes/sources/source_rules` + `*_command` catalog 함수 |
| `src/kortravelmap/infra/legacy_write_fence.py` · `tests/lint/test_legacy_write_fence.py` · `tests/integration/test_tvn40a_legacy_write_fence_acl.py` · router 410 테스트 | 전부(표가 없으면 fence도 없다) | — |
| `src/kortravelmap/infra/merge_repo.py` | legacy mirror CALL 4곳 · `_DETACH_CONFLICTING_LEGACY_CURATION_ITEMS_SQL` · `_PINNED_LEGACY_CONFLICT_ITEMS_SQL` · `_ARCHIVE_CONFLICTING_LEGACY_CURATED_FEATURES_SQL` 사용부 | canonical lock/reconcile |
| `src/kortravelmap/infra/curation_repo.py` | `_lock_legacy_projections_for_item` · `update_curation_item`의 legacy sync 분기 · legacy_projection 관련 SQL 조각 | canonical item/collection/import |
| `src/kortravelmap/infra/db.py` | `_ADMIN_CURATION_FEATURE_PROCEDURES`의 merge legacy 4개 signature | `merge_lock_curation_collections` |
| `src/kortravelmap/infra/models.py` | `CuratedFeatureRow` · `CuratedFeatureDetailSnapshotRow` + `infra/__init__` 재수출 | — |
| tests | unit+integration `test_curated_repo.py`(legacy read/seed) · `test_merge_repo.py` legacy conflict 시나리오 · `test_public_features_view.py`/`test_notice_defensive_cast.py`의 legacy seed helper · `test_tvn40_identity_mapping_loader.py`(loader는 표가 있어야 도니 **삭제 대상** — 0223은 이력으로 남고 재실행되지 않는다) · **리뷰 추가**: `packages/kor-travel-map-api/tests/test_export_openapi.py`(user path 정확 집합 + PinVi curated union schema) · `test_route_policy.py:401-402` · `test_auth.py:1073` · `test_admin_curated_snapshot_contract.py`(전체) · `tests/unit/test_curated_routes.py:172-184,766-990` · `tests/integration/test_curation_repo.py:1772-2423`(legacy seed) · `tests/unit/test_curation_repo.py`(`_lock_legacy_projections_for_item` patch 3곳) · `tests/integration/test_merge_under_runtime_role.py`(dagster 음성이 legacy proc을 CALL → canonical `merge_lock_curation_collections`로 교체) · `tests/integration/test_tvn33_migration_contract.py:185-197`(`issue_curation_source_rule_decision` 정의 단언 → 제거) | canonical 테스트 |
| `scripts/tvn40_identity_mapping_precheck.sql` | ① 이후 용도 없음 → 40C에서 삭제(내용은 설계 문서에 남음) | — |
| API 모듈 | `curated_public_schema.py`(+`_CURATED_FEATURE_BASE_TYPES` — PinVi user-schema contract; **명시 결정**: 삭제, PinVi는 canonical snapshot 계약만) · `route_policy.py`·`domain_command_registry.py`·`prometheus.py` legacy 항목 | canonical 모듈 |

## 3. 프론트엔드·소비자 (legacy read 표면 — P2 조건)

| 대상 | 조치 |
|---|---|
| `src/app/admin/curated-features/**` (redirect + detail read) · `src/app/admin/features/curated/[curatedFeatureId]/` (legacy detail) | 삭제; `/admin/features/curated`(canonical collections)만 남긴다 |
| `src/app/curated-features/**` (public map) | **유지 — 이미 canonical**(`src/api/public-curations.ts`가 `/v1/curations`·`/v1/curations/collections`만 읽고 e2e도 `/v1/curations**` mock). 남은 legacy 참조는 `href="/admin/curated-features"` 링크 1곳(`curated-feature-map-client.tsx:494`) → `/admin/features/curated`로 |
| `src/api/curated.ts` legacy hooks(`useAdminCuratedFeature`, `useCuratedFeatureDetailSnapshot`, `useAdminCuratedFeatures` 계열) · `api/types.ts` 재생성 | 삭제/재생성; theme/source hooks 유지 |
| e2e: `curated-features.spec.ts`(canonical 화면 — 유지) · `curated-features-map.spec.ts`(canonical mock — 유지) · scenario catalog `curated-features` surface의 legacy readApis(`/v1/admin/features/curated`)·`curated-feature-detail` surface·generator의 `F.CURATED_IDS`/"pinvi-copy parity"(`admin-scenario-catalog.ts:212-236,520-532`, `.live.spec.ts:20-23`) · `e2e/live/_fixtures.ts:14 CURATED_IDS`(legacy UUID; `uploads-backups-poi.live.spec.ts`·`reviews.live.spec.ts`가 사용) | catalog/fixture를 canonical item id로 전환, legacy surface 삭제 |
| user-client(`packages/kor-travel-map-user-client`) · PinVi vendor OpenAPI | **정정**: `openapi.user.json`에 `/v1/curated-features{,/{id}}`가 있고 생성 타입(`user-client/src/types.ts:51-76,3027,3079`)과 PinVi vendored user json에도 있다 → 40C PR에서 user-client 타입 재생성(`gen:types:check`), PinVi는 P7 lockstep(재vendor + paired receipt). PinVi runtime 호출자는 0(정적 참조만) |

## 4. 계약·검증 (static zero gate — 설계 §6.2)

1. `packages/kor-travel-map-api/openapi*.json`(user/full/service) 재생성 → `contracts/vnext/openapi-diff-v1.json`의 T-VN-40C
   tombstone(**이미 존재**: admin 9 + user 2)을 `applied: true`로 표시(`test_vnext_contract_artifacts.py:163-190`이 없는
   op를 applied 없이 두면 실패); receipt에는 `compat_drop_applied` 같은 **새 키를 넣지 않는다**(receipt 키 집합은 exact
   — `:399-410`; n150에서 추가 시 red 확인) — 적용 사실은 openapi-diff `applied`와 이 manifest JSON `status: applied`로
   기록. `test_vnext_contract_artifacts` sha 재고정. `recovery-preflight-v1.json`의 `final_zero`(PinVi
   `source_curated_feature_id` 정적 호출자 0 · snapshot route/type/cache 0) 축을 §4.3 gate가 함께 만족시킨다.
2. `contracts/vnext/target-invariants-v1.sql` INV-040-09는 **freeze 테스트에서 이미 통과 중**(target-schema DB에는 legacy가
   원래 없다) — 40C의 실질 게이트가 아니다. 실질 게이트는 §4.4 **migrated head DB catalog zero**(새 통합 테스트).
3. **static zero**(리뷰 정정 — 넓은 식별자는 살아 있는 canonical 경로와 충돌한다: `/features/curated`는 canonical
   `admin/features/curated/` 디렉터리, `curated-features`는 canonical public map route, `legacy_projection`은 유지되는
   `mapping_kind` enum). 식별자: `feature.curated_features` · `curated_feature_detail_snapshots` · `legacy_projection_id` ·
   `CuratedFeatureRow` · `CuratedFeatureDetailSnapshotRow` · `legacy_write_fence` · `/v1/curated-features` ·
   `/v1/admin/features/curated` · `/admin/curated-features` · `merge_\w+_legacy_curated_features` ·
   `sync_curated_feature_collection` · `set_curation_item_legacy_component_identity` · `issue_curation_source_rule_decision`.
   active scope: `src/`, `packages/*/src`, `packages/kor-travel-map-admin/frontend/{src,e2e}`, `docs/architecture`,
   `docs/runbooks`, `docs/*.md`(현행) — allowlist: `alembic/legacy_versions/`, `alembic/versions/0045~0223`, `alembic/baseline/`,
   `docs/archive/`, `docs/reports/`, `docs/adr/`(불변), `docs/journal.md`, `docs/tasks*.md`, `docs/resume.md`,
   `contracts/vnext/openapi-diff-v1.json#/surfaces/*/removed`, `t-vn-40c-removal-manifest-v1.json`,
   `target-invariants-v1.sql#INV-040-09`, `recovery-preflight-v1.json`. `tests/lint/test_tvn40c_static_zero.py`가 fail-closed.
   갱신할 현행 문서: `docs/curated-features.md`, `architecture/data-model.md`, `rest-api.md`, `openapi-admin-contract.md`,
   `integration-map.md:140-147`(PinVi가 curated_features를 REST로 읽는다는 서술), `runbooks/admin-ui-screen-checklist.md`,
   `backup-restore.md`, `postgres-schema.md`, `test-strategy.md`, `provider-contract.md`.
4. DB catalog zero(migrated head DB, 통합 테스트): `pg_class/pg_trigger/pg_constraint/pg_index`에 legacy 이름 0 **그리고
   `pg_proc.prosrc`에 legacy 식별자 0**(이름만 보면 D4의 0214 procedure를 놓친다).
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
- Q4 (답) canonical 경로는 `source_rule` decision을 내지 않는다 — `source_rule` basis는 이력 전용. 삭제는 유효.
- Q5 public catalog route(`GET /v1/curated-themes`·`/v1/curated-sources`) — openapi-diff가 이미 T-VN-40C tombstone으로
  선언("retained catalog는 admin typed surface만") → 40C에서 **제거**(admin typed catalog만 유지). 이 문서 v1의 "public
  catalog 유지"는 계약과 충돌했으므로 정정.
- Q6 `curated_public_schema.py`/`_CURATED_FEATURE_BASE_TYPES`(PinVi user-schema 계약) 삭제 — PinVi는 canonical snapshot 계약만.
