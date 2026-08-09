# T-VN-33 통합 라이브 실행이 드러낸 제품 결함

- 작성: 2026-08-08
- 출처: 통합 테스트 55개 파일을 최종 스키마로 전환하며 live DB에서 실행한 결과
- **이 결함들은 단위 테스트로 하나도 잡히지 않는다.** 대부분 파스/실행 시점에 죽거나,
  트리거·제약이 붙은 실제 DB에서만 드러난다.

## 이미 고친 것 (커밋 `2f123acb`)

| 위치 | 증상 |
|---|---|
| `pipeline_repo` `job_provider_datasets` | ranked CTE의 정렬 열 미투영 → pipeline projection 전체 사망 |
| `pipeline_repo` 바깥 SELECT | `selected_operation_key` 누락 → dataset latest/snapshot 사망 |
| `consistency._F7_DEDUP_SCORE_ROWS_SQL` | `sr` join 유실 → 정합성 검사 전체가 파스 단계에서 사망 |
| `dedup_refresh_repo._LIST_DEDUP_FEATURES_SQL` | 같은 형태 → dedup 목록 조회 사망 |
| `curated_repo.create_curated_theme` | f-string 누락 → 항상 SyntaxError |
| `admin_feature_repo` issues 질의 | 삭제된 `provider` 참조 → admin 상세·enrichment 리뷰 500 |

## 남은 것

### 1. src/kortravelmap/infra/alembic_exclusions.py:25 (UNCOMPARED_INDEXES) vs alembic/versions/0091_tvn33_cutover_fence.py:64

T-VN-33 cutover가 DROP한 인덱스가 alembic 비교 제외 ledger에 그대로 남아 있다. ledger는 "검증 없는 제외 항목을 막는" 계약인데, 존재하지 않는 객체를 가리켜 계약 테스트가 영구 red가 된다.

```
0091 `_detach_legacy_constraints()`가 `DROP INDEX IF EXISTS provider_sync.idx_source_records_kma_alert_history;` 를 실행하고, 최종 스키마 DB(ktm_t33j)에서 `SELECT indexname FROM pg_indexes WHERE schemaname='provider_sync' AND tablename='source_records'` 결과에 그 이름이 없다(fetched_at/imported_at BRIN, pk, uq_source_records_entity_record, uq_source_records_entity_payload 만 존재). 그런데 src/kortravelmap/infra/alembic_exclusions.py 는 여전히 `("provider_sync", "idx_source_records_kma_alert_history")` 를 포함한다. 결과: tests/integration/test_alembic_upgrade.py:968 `assert set(_UNCOMPARED_INDEX_CONTRACTS) == UNCOMPARED_INDEXES` → "Extra items in the right set: ('provider_sync', 'idx_source_records_kma_alert_history')". 대체 인덱스도 없으므로 계약을 갱신하는 게 아니라 ledger 항목을 삭제하는 것이 맞다.
```

### 2. packages/kor-travel-map-dagster/src/kortravelmap/dagster/assets.py — 389행(_skip_opinet_if_already_succeeded_today), 715행(_guard_notice_snapshot_watermark), 1595행(_record_feature_sync_success)

provider ETL asset이 전부 TypeError로 죽는다. sync cursor를 읽거나 쓰는 asset은 하나도 완주하지 못한다.

```
TypeError: AsyncKorTravelMapClient.record_sync_success() missing 1 required keyword-only argument: 'operation_key' (get_sync_state도 동일). client/__init__.py 2240·2286행에서 operation_key가 keyword-only 필수로 승격됐는데 dagster 쪽 3개 호출부가 provider/dataset_key만 넘긴다. 정본 operation은 provider_sync.provider_dataset_operations에 dataset당 1건씩 있다(예: krex_traffic_notices → feature_notice_krex_traffic_notices_job). probe로 3곳을 메우니 3건 중 2건 통과.
```

### 3. src/kortravelmap/infra/models.py:851-856 — ProviderDatasetRow.capabilities server_default

alembic autogenerate/check가 server-default 비교 단계에서 크래시한다. metadata drift gate(§8.1)가 판정 자체를 못 낸다.

```
sqlalchemy.exc.StatementError: (InvalidRequestError) A value is required for bind parameter '1' / [SQL: SELECT '...'::jsonb = '{"schema_version"$1,"produces":[],"extensions":{}}'::jsonb]. server_default=text("'{\"schema_version\":1,...}'::jsonb") 안의 `:1`을 SQLAlchemy text()가 bind param으로 파싱한다. (이번 작업 지침이 테스트 쪽에 경고한 함정과 정확히 같은 함정이 제품 코드에 있다.)
```

### 4. alembic 0089/0090/0091 ↔ src/kortravelmap/infra/models.py (metadata drift)

freshly-migrated 빈 DB에서 alembic check가 diff 다수를 검출한다 — migration과 ORM metadata가 갈라져 있다.

```
alembic.autogenerate 로그: added index 'idx_curated_sources_dataset'; changed index 'idx_data_integrity_violations_dataset_status' (expression 3→4); removed 'idx_enrichment_review_queue_source_entity_record' + added 'idx_enrichment_review_source_entity'; changed index 'idx_feature_update_request_datasets_dataset_request' (2→4); changed unique constraint 'uq_feature_update_request_datasets_identity' — ('provider_dataset_id','request_id','sync_scope') → ('operation_key','provider_dataset_id','request_id','sync_scope'); feature_update_request_datasets/import_job_datasets/offline_uploads 3개 테이블의 (provider_dataset_id, sync_scope, operation_key) FK removed+added; server default on 'notice_lifecycle_scopes.notice_lifecycle_scope_id' identity ['always']; removed index 'idx_notice_lineage_states_scope_present'.
```

### 5. src/kortravelmap/infra/feature_repo.py — notice snapshot reconcile, core_update RETURNING의 reopened 플래그 (약 3606행)

사라졌던 notice가 feed에 재등장했을 때 valid_end_time은 올바르게 NULL로 되돌아가지만 reopened 집계가 0으로 남는다. Dagster cursor의 notices_reopened가 항상 0이고, 재등장 복구가 로그·metadata에 기록되지 않는다.

```
test_krex_notice_asset_snapshot_lifecycle_and_sync_cursor: seed→partial→empty→reappear 시나리오에서 `assert await _valid_end(a_id) is None`은 통과(=복구는 실제로 일어남)하는데 `cursor['notices_reopened'] == 1`이 0으로 실패. -l 로컬 덤프상 cursor는 최신(loaded_at=2026-06-02T12:30:00+09:00 = reappeared_at)이고 notices_closed도 0. dagster 로그: "feed 소멸 닫음 1건, 재등장 복구 0건". T-VN-33 cutover가 feature_repo.py의 notice lineage SQL을 987줄 규모로 갈아엎었고(_notice_lineage_sql → head.lineage_key 기반), was_visible/reopened 판정이 그 영향권에 있다. operation_key 결함을 probe로 메운 뒤에도 이 1건만 남는다.
```

### 6. src/kortravelmap/mois.py:362-367 (_BULK_JOB_KIND을 operation_key로 사용)

`run_mois_license_bulk_job`이 canonical membership 해석에 실패해 항상 FeatureOperationInvariantConflict('runtime dataset does not resolve to exactly one operation membership')로 죽는다 — MOIS bulk 적재(ktmctl import mois, Step A) 경로 전체가 최종 스키마에서 실행 불가.

```
`_BULK_JOB_KIND = "mois_license_full_update"`(mois.py:73)를 import job kind이자 operation_key로 함께 넘기는데, 0089가 seed한 mois_license_features_bulk(provider_dataset_id=30)의 canonical operation_key는 `feature_place_mois_licenses_job`이다(alembic/versions/0089_tvn33_expand_seed.py:282, providers/feature_operation_registry.py:71, dagster/schedules.py:207 모두 동일). 그래서 _OPERATION_DATASET_MEMBERSHIP_SQL이 0행을 돌려준다. incremental/closed는 job kind와 operation key가 우연히 일치해서 이 단계는 통과한다. 컨테이너에서 그 한 인자만 'feature_place_mois_licenses_job'으로 바꾸자 test_cli_import_mois_loads_promoted가 통과했다.
```

### 7. src/kortravelmap/cli/main.py:214-218 (--sync-scope default="default"), src/kortravelmap/client/__init__.py:1425·1462 (sync_scope="default"), src/kortravelmap/mois.py:431·533 (sync_scope: str = "default")

MOIS incremental/closed 적재가 데이터 upsert까지 다 하고 나서 cursor 전진에서 sqlalchemy.exc.NoResultFound로 죽는다(전체 transaction rollback). 기본값 경로라 옵션 없이 돌리는 프로덕션 호출이 전부 해당된다.

```
provider_sync.provider_dataset_operation_scopes의 유효 sync_scope는 dataset_wide(56행)/target_grids(3행)뿐이고 'default'는 없다. _RECORD_SUCCESS_SQL(sync_state_repo.py:125)이 scope 행을 join하므로 sync_scope='default'면 INSERT가 0행 → `.one()`에서 NoResultFound. 같은 함수가 job row용 membership은 `_dataset_membership`으로 제대로 해석해 dataset_wide를 쓰면서(mois.py:187-197), record_sync_success/record_sync_failure에는 낡은 리터럴 파라미터를 넘긴다. 컨테이너에서 CLI 기본값만 dataset_wide로 바꾸자 6/6 통과했다.
```

### 8. alembic/versions/0091_tvn33_cutover_fence.py:74 (_detach_legacy_constraints, ck_import_jobs_update_request_shape DROP)

feature_update_request job의 status/owner 형태 불변식이 통째로 사라졌다. 이제 status='running'인데 dagster_run_id IS NULL이거나, status='queued'인데 owner가 박힌 job, payload가 '{}'가 아닌 job을 DB가 그대로 받는다 — 소유자 없는 running job은 stale 회수 로직이 판정 못 하는 상태다.

```
0053이 만든 이 CHECK은 pair 부분(provider/dataset_key/sync_scope) 외에 parent_job_id IS NULL, load_batch_id IS NULL, trigger_kind='update_request', operation_registry_version IS NULL, dagster_run_status IS NULL, payload='{}', dagster_run_id trim/non-empty, status<>'queued' OR dagster_run_id IS NULL, status<>'running' OR dagster_run_id IS NOT NULL을 함께 들고 있었다(0053_feature_update_scope_dispatch.py:400-411). 0091은 pair 컬럼 때문에 detach만 하고 canonical 잔여분을 재생성하지 않았다. 현재 ops.import_jobs의 CHECK 목록에도, 트리거 목록에도 대체물이 없다. docs/architecture/postgres-schema.md:384는 여전히 이 제약을 정본으로 문서화하고 있다.
```

### 9. alembic/versions/0091_tvn33_cutover_fence.py:126-127 (_replace_pre_tvn33_ownership_guards, enforce_feature_update_job_pair/assert_feature_update_job_pair DROP)

job→request 방향의 pair 불변식이 사라져 request 없는 kind='feature_update_request' import job(비격리 상태)이 commit된다. pair는 이제 request→job 한 방향만 강제된다.

```
0052가 만든 assert_feature_update_job_pair(0052_pipeline_projection_access_paths.py:2145-2196)는 kind/quarantined_at/request 존재만 보는 함수로 provider·dataset_key·배열 컬럼을 전혀 읽지 않는다 — 즉 T-VN-33 때문에 지울 이유가 없었다. 0091은 이것을 지우면서 반대 방향(enforce_feature_update_request_job_identity)만 새로 만들었고, DB에서 feature_update_requests를 참조하는 함수는 이제 0건이다. test_feature_update_request_job_pair_is_bidirectional_and_immutable의 unpaired job INSERT + SET CONSTRAINTS ALL IMMEDIATE가 'DID NOT RAISE'로 실패한다.
```

### 10. packages/kor-travel-map-dagster/src/kortravelmap/dagster/assets.py:1595 (_record_feature_sync_success) vs src/kortravelmap/client/__init__.py:2286 (AsyncKorTravelMapClient.record_sync_success)

provider asset의 적재 성공 경로가 전부 TypeError로 죽는다. record_sync_state=True인 모든 feature asset(_load → _record_feature_sync_success)이 client.record_sync_success(provider=, dataset_key=, cursor=)로 호출하는데, T-VN-33 이후 이 메서드는 keyword-only 필수 인자 operation_key를 요구한다. FeatureUpdateAssetRunner가 이 예외를 ProviderDatasetRefreshFailure('provider refresh asset execution failed')로 감싸므로 원인이 가려진다. runner는 이미 resources에 feature_update_membership(ProviderDatasetOperationMembership)을 주입하지만 assets.py는 그 값을 전혀 읽지 않는다 — record_sync_success_for_operation_membership로 옮겨야 할 것으로 보인다.

```
test_feature_update_executor.py::test_production_asset_runner_rolls_back_load_when_checkpoint_fails 가 error_message == 'RuntimeError: simulated provider checkpoint failure' 대신 'ProviderDatasetRefreshFailure: provider refresh asset execution failed'를 받는다(주입한 2번째 checkpoint 실패에 도달하기 전에 asset이 이미 죽음). grep 확인: assets.py는 feature_update_membership을 한 번도 참조하지 않고, 유일한 호출부(line 1595)는 operation_key 없이 호출한다.
```

### 11. src/kortravelmap/infra/feature_update_executor.py:799 (record_import_job_event 호출) + src/kortravelmap/infra/jobs_repo.py:402-431 (_INSERT_EVENT_SQL membership 가드)

dataset membership을 가진 feature update job은 typed terminal event를 절대 기록할 수 없다. executor가 record_import_job_event(...)를 import_job_dataset_id 없이 호출하는데, enqueue_feature_update_request가 만든 job은 membership이 1개라 dataset_membership_mode='single'이다. _INSERT_EVENT_SQL은 root가 아닌 job에 대해 import_job_dataset_id가 NULL이면 어떤 행도 매칭하지 않으므로 record_import_job_event가 FeatureOperationInvariantConflict('event requires the exact canonical import job membership')를 던진다. 결과적으로 실행이 'failed'로 마감되는 대신 예외가 호출자까지 터져나가고, kma.target_scope_empty 같은 실패 코드 이벤트가 영영 남지 않는다. 앞서 보고된 heartbeat membership 누락과 같은 계열이다.

```
test_feature_update_executor.py::test_bound_kma_empty_target_fails_operation_without_provider_or_state_write 에서 KmaWeatherTargetScopeEmptyError 처리 중 /repo/src/kortravelmap/infra/jobs_repo.py:1010 FeatureOperationInvariantConflict 발생. jobs_repo._membership_mode(line 659)는 membership 1개 → 'single'을 반환하고, _INSERT_EVENT_SQL(line 419-431)은 mode<>'root'일 때 CAST(:import_job_dataset_id AS uuid)와 일치하는 ops.import_job_datasets 행을 EXISTS로 요구한다. executor(line 799)는 그 인자를 넘기지 않는다.
```

### 12. alembic/versions/0091_tvn33_cutover_fence.py:1673~1690 provider_sync.validate_data_integrity_violation_dataset() 트리거 vs ops.data_integrity_violations의 fk_data_integrity_violations_source_record_key_source_records (ON DELETE SET NULL)

같은 head 스키마 안에서 두 규칙이 정면으로 모순된다. 트리거는 UPDATE 시 (provider_dataset_id, source_record_key)를 불변으로 강제하는데, FK는 source_record 삭제 시 source_record_key를 NULL로 UPDATE한다. 그래서 열린 finding이 가리키는 provider_sync.source_records 행은 이제 **삭제 자체가 불가능**하다 — SET NULL이 트리거에 걸려 CheckViolation으로 터진다. record GC/purge 경로가 있으면 그대로 막힌다.

```
test_phase2_ops_repos.py::test_data_integrity_violation_lifecycle_and_fk_behavior — `DELETE FROM provider_sync.source_records WHERE source_record_key='src:violation:1'` 에서 asyncpg.exceptions.CheckViolationError: integrity violation ownership is immutable (constraint ck_data_integrity_violation_ownership_immutable).
```

### 13. 같은 트리거(0091:1673~1690) vs F:\dev\ktm-tvn33\src\kortravelmap\infra\integrity_violation_repo.py — _UPSERT_FINDINGS_BATCH_SQL의 ON CONFLICT DO UPDATE SET source_record_key = CASE ...

recurrence 추적이 구조적으로 불가능해졌다. dedupe_key는 entity 단위(av2_…)라 provider가 같은 entity를 새 payload로 다시 내보내면 새 source_record_key가 붙는데, batch upsert가 그 포인터를 최신으로 갱신하려는 순간 트리거가 23514로 statement 전체를 죽인다. AsyncKorTravelMapClient.sync_address_validation_findings(client/__init__.py:2588 부근)의 광범위 except가 이를 IntegrityFindingPersistenceError로 바꿔 삼키므로 **그 run의 finding이 전부 유실**된다 — 함수 docstring이 batch로 접은 이유로 든 실패 양상 그대로다.

```
test_phase2_ops_repos.py::test_integrity_finding_recurrence_tracks_latest_fk_targets — 두 번째 sync_integrity_findings(같은 dedupe_key, source_record_key만 old→new)에서 CheckViolationError: integrity violation ownership is immutable. 파라미터 로그에 ['src:violation:new'] 확인.
```

### 14. F:\dev\ktm-tvn33\src\kortravelmap\infra\jobs_repo.py:995 record_import_job_event (호출 경로 _insert_import_job:868 → _record_lifecycle_event:1040) / F:\dev\ktm-tvn33\src\kortravelmap\infra\feature_update_repo.py:1156~1188 enqueue_feature_update_request

같은 canonical scope로 create_feature_update_request 2건이 동시에 들어오면 lock order 역전으로 데드락이 난다. 한 트랜잭션 안 순서가 (1) import_jobs + import_job_datasets INSERT — FK가 provider_dataset_operation_scopes 행에 KEY SHARE를 잡는다, (2) import_job_events INSERT — 트리거가 ops.import_job_event_clock 단일 행에 배타 락을 잡는다, (3) feature_update_request_datasets INSERT — 0091의 trg_feature_update_request_membership_overlap이 같은 scope 행에 FOR UPDATE를 잡는다. A가 (1) 뒤 (2)의 clock을 기다리는 동안 clock을 쥔 B가 (3)에서 A의 KEY SHARE를 기다려 순환이 닫힌다. 즉 'reuse 경합' 자체가 성립하지 못하고 FeatureUpdateEnqueueError로 500이 된다.

```
test_feature_update_active_repo.py::test_concurrent_service_create_reuses_one_canonical_active_request — 3회 연속 재현. asyncpg.exceptions.DeadlockDetectedError: deadlock detected → FeatureUpdateEnqueueError('feature update request enqueue failed'), 대기 statement는 jobs_repo.py:995 record_import_job_event. (데드락으로 세션이 checked-out 상태로 남아 teardown DROP DATABASE까지 연쇄 실패한다.)
```

### 15. src/kortravelmap/infra/feature_repo.py — _UPSERT_SOURCE_ENTITY_HEAD_SQL (약 373~404행), load_bundle에서 사용

재적재 idempotency 파손. 같은 source_record_key를 다시 관측하면 became_current가 true로 나와 feature 본문이 매번 재upsert된다(features_updated>0, row_revision/updated_at churn). T-VN-33 checkpoint(2e76b80c)가 도입한 prior CTE 자체의 버그다.

```
직접 probe: 같은 params로 _UPSERT_SOURCE_RECORD_SQL+_UPSERT_SOURCE_ENTITY_HEAD_SQL를 2회 실행(2회차는 observed_at만 +1h) → r2={'source_record_key':'sr_probe','inserted':False} 인데 h2(became_current)=True. 원인: `prior AS MATERIALIZED (... FOR UPDATE)`가 같은 statement의 upserted CTE가 갱신한 행을 EvalPlanQual로 재조회하면서 cmin=현재 command라 보이지 않아 0행이 되고, `NOT EXISTS (SELECT 1 FROM prior)`가 true가 된다. 결과: tests/integration/test_mois_loader.py::test_loader_idempotent_reload → FeatureLoadResult(features_updated=2, source_records_inserted=0).
```

### 16. src/kortravelmap/mois.py:73 (_BULK_JOB_KIND) + 366 (_dataset_membership 호출)

run_mois_license_bulk_job이 항상 FeatureOperationInvariantConflict('runtime dataset does not resolve to exactly one operation membership')로 죽는다 — MOIS bulk 적재 경로 전체가 막힘.

```
0089가 python-mois-api/mois_license_features_bulk의 operation_key를 'feature_place_mois_licenses_job'으로 seed하고 providers/feature_operation_registry.py:71도 같은 이름만 안다. 그런데 mois.py는 operation_key로 job kind 'mois_license_full_update'를 넘긴다(rg 결과 이 문자열은 mois.py에만 존재). psql: provider_dataset_operations에 mois_license_full_update 행 없음.
```

### 17. src/kortravelmap/mois.py:431,533 · src/kortravelmap/client/__init__.py:1425,1459 · src/kortravelmap/cli/main.py:216

sync_scope 기본값 'default'가 최종 스키마에 존재하지 않는 scope다. record_sync_success/record_sync_failure의 exact_membership CTE가 0행을 내고 .one()이 NoResultFound를 던져 MOIS incremental/closed job과 CLI/client sync-state 경로가 실패한다.

```
psql: provider_dataset_operation_scopes.sync_scope 분포 = dataset_wide(56), target_grids(3). 'default' 없음. is_valid_provider_dataset_sync_scope도 dataset_wide/target_grids/external_system:* 만 허용. 테스트에서는 sync_scope='dataset_wide'를 명시해 우회했으나 기본값은 여전히 깨져 있다.
```

### 18. src/kortravelmap/infra/cache_target_service_repo.py:221 (create_cache_target_refresh_request → enqueue_feature_update_request)

(경미) PinVi 대면 service 경로가 dataset_memberships를 넘기지 않아, 요청한 cache target 반경 안에 feature가 하나도 없으면 typed conflict가 아니라 맨 ValueError('feature update request requires at least one dataset membership')가 그대로 올라간다(500).

```
feature_update_repo._resolve_feature_update_plan은 memberships 미지정 시 scope 해석 결과(resolution.provider_datasets)에서 유도하는데, cache_target_keys scope의 provider_datasets는 target 반경 안 feature의 primary source에서만 나온다. 테스트에서는 반경 안 feature를 seed해 우회했다. create_cache_target_refresh_request에는 membership 인자가 없어 호출자가 손쓸 수 없다.
```

### 19. src/kortravelmap/cli/_h35_csv5.py:196-244 (_provider_dataset_ids_by_pair, _lighthouse_dataset_pairs)

The H35 cutover csv5 step queries a table that does not exist at H35's own target schema, so the frozen 0063 -> 0079 cutover operation can no longer run: `relation "provider_sync.provider_datasets" does not exist`.

```
`SELECT provider, dataset_key FROM provider_sync.provider_datasets WHERE dataset_key = ANY(...) AND dataset_key LIKE 'lighthouse-stamp-tour-season-%'` — provider_sync.provider_datasets is created by alembic 0089_tvn33_expand_seed, but src/kortravelmap/cli/_h35_schema.py pins TARGET_SCHEMA = '0079_cache_target_writer_drain' (PRE_SCHEMA = '0063_pipeline_root_id'). Traceback: h35_cutover._execute -> _h35_csv5.run_csv5 -> _resolved_rows -> _lighthouse_dataset_pairs, in tests/integration/test_h35_cutover_rehearsal.py::test_h35_exact_surface_network_free_rehearsal.
```

### 20. src/kortravelmap/infra/ops_repo.py:367-405 (_list_import_job_events_sql) vs alembic 0090 idx_import_job_events_member_time

Performance regression, not a crash: the dataset/scope-filtered import-job event audit has no bounded index path any more. 0091 dropped idx_import_job_events_provider_time / _provider_dataset_time / _provider_dataset_scope_time and 0090 created idx_import_job_events_member_time as the replacement, but the query shape cannot reach it, so the planner walks the global time index and discards non-matching rows until LIMIT is satisfied. For a rarely-active dataset this degrades toward a full timeline scan.

```
The SQL LEFT JOINs ops.import_job_datasets AS member on import_job_dataset_id, filters member.provider_dataset_id / member.sync_scope, and orders globally by event.occurred_at DESC, event.event_id DESC. EXPLAIN ANALYZE on an 8,000-event fixture (2 members, 4,000 events each) for the exact-scope filter: Limit -> Nested Loop -> (Materialize -> Seq Scan import_job_datasets, 1 row) + Index Scan import_job_events using idx_import_job_events_time, Actual Rows 4052 for 51 returned. Identical plan under both `SET LOCAL plan_cache_mode = force_generic_plan` and `force_custom_plan`, with ANALYZE run on both tables. Because of this I did not pin a plan in tests/integration/test_ops_repo.py::test_exact_scope_event_history_filters_on_canonical_membership; see its docstring.
```

### 21. src/kortravelmap/infra/pipeline_repo.py:1452 (_group_dataset_execution_snapshot_rows)

SQL은 exact membership triple로 `PARTITION BY`하는데 Python 집계는 pair로 키를 잡는다. 한 dataset에 refresh operation을 하나 더 등록하고 두 operation이 각각 실행을 가지면, SQL이 정확히 분리해 낸 두 행이 같은 칸에 떨어져 `RuntimeError: dataset execution snapshot returned duplicate status groups`로 터진다 — dataset 상태 목록/상세가 통째로 500이 된다.

```
스키마가 이 조합을 허용한다는 것을 live로 확인했다(ktm_t33j, 롤백 트랜잭션):
provider_dataset_operations PK는 (provider_dataset_id, operation_key)이므로 한 dataset에
refresh operation이 여러 개 있을 수 있고, provider_dataset_operation_scopes PK가 triple이라
그 둘이 같은 'dataset_wide'를 함께 가질 수 있다 — 두 번째 refresh operation + 같은 scope
삽입이 모두 성공해 scope 행이 2개가 됐다. scope의 refresh-only CHECK가 막는 것은 preview
operation(23개)이지 복수 refresh가 아니다.

지금 터지지 않는 것은 seed된 카탈로그가 dataset마다 refresh operation을 하나씩만 주기
때문일 뿐(58쌍, 충돌 0건), 제약이 막아 주기 때문이 아니다. 스키마 변경 없이 카탈로그에
operation 하나를 더 등록하는 평범한 작업만으로 재현된다.

재현: tests/integration/test_pipeline_repo.py::
test_dataset_execution_snapshot_separates_operations_on_one_scope
A/B — 집계 키가 pair일 때 위 RuntimeError, triple로 고치면 통과(25/25).

API 표면 테스트가 이 결함을 못 잡은 이유: packages/kor-travel-map-api/tests/
test_ops_datasets_router.py가 monkeypatch.setattr로 list_dataset_execution_snapshots
자체를 스텁으로 교체한다(4곳). 실제 집계 코드가 한 번도 실행되지 않는다.
```

### 22. src/kortravelmap/infra/models.py:970 (ProviderDatasetOperationScopeRow)

ORM이 DB보다 좁은 PK를 선언했다. DB `pk_provider_dataset_operation_scopes`는 triple인데 ORM은 `(provider_dataset_id, sync_scope)` 2열만 `primary_key=True`로 뒀다. SQLAlchemy identity map이 `operation_key`만 다른 두 행을 같은 객체로 접어 뒤에 읽은 행이 앞의 행을 덮는다.

```
이 부류를 아무도 검사하지 않고 있었다 — ORM 메타데이터의 PK를 DB와 대조하는 테스트가
저장소에 없었다. tests/integration/test_alembic_upgrade.py::
test_alembic_head_primary_keys_match_orm_declarations로 게이트를 세웠고, A/B로 증명했다
(되돌리면 두 모양을 나란히 지목하며 실패). 현재 어긋난 mapped table은 이 하나뿐이었다.
게다가 tests/unit/test_tvn33_source_lineage_models.py가 틀린 2열 모양을 단언해 어긋남을
고정하고 있었다.
```

### 23. API 표면이 identity triple 중 2/3만 노출 (4개 record)

아래 계층 DTO는 triple을 온전히 들고 있는데 HTTP 표현에서만 `operation_key`가 사라지고, `sync_scope`가 근거 없이 nullable로 넓어진다. 소비자가 member를 구분하거나 deep link를 만들 수 없다.

```
- routers/ops_pipeline.py PipelineProviderDatasetIdentityRecord — operation_key 없음,
  sync_scope: str | None (원본 PipelineProviderDatasetIdentity는 sync_scope: str + operation_key)
- routers/offline_uploads.py OfflineUploadRecord — operation_key 없음
  (ops.offline_uploads의 세 열이 모두 NOT NULL, repo DTO OfflineUpload도 셋을 보유)
- infra/ops_repo.py OpsImportJobDataset + _IMPORT_JOB_MEMBERSHIPS_SQL — jsonb_build_object가
  operation_key를 아예 select하지 않음
- infra/dataset_status_repo.py DatasetLatestExecution / DatasetExecutionSnapshot — 위 21번과 동반

같은 커밋의 ops_dataset_schema.py OpsDatasetProviderDataset은 셋을 모두 노출하며 docstring에
"셋 다 non-null이라야 UI가 member를 구분해 표시하고 deep link를 만들 수 있다"고 적어 두었다
— 내부 불일치다. feature_update 경로(FeatureUpdateDatasetMembership)는 이미 triple이 온전하다.
```

---

## 적대 리뷰 2명이 REJECT하며 추가로 드러난 것 (2026-08-08)

리뷰어 둘이 독립적으로 REJECT했고, 지적의 핵심은 **"바꾼 것 중 틀린 것은 없으나, 스스로 '전수/부류 전체'라고 선언한 범위 안에 같은 결함이 남았다"**는 것이다. 아래는 그 목록이다.

### 24. packages/kor-travel-map-admin/frontend/src/api/types.ts (CI 블로커)

`openapi.json`을 바꾸고 그 스펙에서 생성돼 **체크인된** `types.ts`를 재생성하지 않았다. `.github/workflows/frontend.yml:70`의 `gen:types:check`가 이를 게이트한다.

```
리뷰어 A/B 실증: 직전 커밋(2eaf6600)의 openapi.json 기준 exit 0 → 이 브랜치 HEAD 기준 exit 1.
직전 커밋 26edbdee는 같은 상황에서 types.ts를 함께 재생성했다. 이번엔 빠졌다.

왜 못 봤는가: ktm-battery 컨테이너 하네스가 src/tests/packages/contracts/alembic만
복사해 프론트 게이트(gen:types:check / tsc / next build)를 한 번도 돌리지 않는다.
파이썬 스위트가 4,529 passed로 green이던 시점에 프론트 게이트는 red였다.
"잔여는 환경 노이즈"라는 판정 자체가 프론트를 보지 못한 판정이었다.
재발 방지: docs/dev-environment.md §10.8에 절차를 박았다.
```

### 25. ops_dataset_service._states_by_api_scope + _dataset_execution_projection (두 리뷰어가 독립 지목)

repo 계층을 triple로 고쳐 놓고 **API service가 한 층 위에서 도로 pair로 접었다.** `_states_by_api_scope`가 `dict[str, SyncState]`—scope 문자열 단일 키—라 operation만 다른 state가 first-wins로 덮인다. 실패 중인 operation이 형제에 가려 보이지 않는다.

```
tie-break `current.sync_scope != logical_scope`는 최초 삽입 후 항상 False다 —
`_logical_state_scope`가 cutover 뒤 `del entry; return state_scope`인 항등함수이기 때문.
즉 갱신 조건이 죽어 있어 조용한 first-wins가 된다.

이건 실수가 아니라 명시적 결정이었다: test_states_fold_to_one_logical_scope_and_drop_
noncanonical_rows가 "같은 logical scope에 operation만 다른 row가 여러 개 남을 수 있다"고
docstring에 적고서 "API scope resource는 그래도 하나여야 한다"며 형제의 paused 상태가
버려지는 것을 단언했다. 테스트가 결함을 고정하고 있었다.

또 프론트는 이미 grid 행을 triple로 모델링해 두었다 —
datasets-client.tsx:118이 rowKey를 [provider_dataset_id, sync_scope, operation_key]로
만든다. API가 뒤처져 있었고 그래서 tsc가 TS2339로 red였다.
```

### 26. OpsDatasetGridRow / OpsDatasetScopeState / OpsDatasetExecution (자기모순)

23번에서 "identity triple을 표면에 노출한다"고 하고 정작 **admin UI가 쓰는 grid·상세 표면**을 건너뛰었다. `OpsDatasetExecution.sync_scope`는 "근거 없는 `| None`을 좁혔다"는 커밋 주장과 반대로 nullable 그대로였다.

```
덤으로 test_ops_datasets_router.py가 `str` 선언 필드에 sync_scope=None을 5곳에서
넣고 있었다. dataclass라 런타임 통과, mypy는 tests를 검사하지 않아 CI도 통과 —
테스트가 커밋의 핵심 주장을 반증하는 모양으로 남아 있었다.
```

### 27. feature_update_active_repo.find_active_provider_dataset_request (거짓 409)

`_FIND_ACTIVE_REQUEST_SQL`이 pair로 조회하는데 상위 `_assert_reusable_active_request`는 triple로 비교한다. operation만 다른 정당한 요청이 형제의 active request를 자기 것으로 잡고 비교 불일치로 409를 받는다. **DB trigger는 triple로 판정하므로 Python 가드가 자기가 흉내 내는 DB 가드보다 엄격했다.**

```
모듈 docstring부터 "active identity는 provider_dataset_id × sync_scope다"로 pair 계약을
박아 두고 있었다. 호출부 feature_update_service.py는 membership.operation_key를 갖고
있으면서 넘기지 않았다.

A/B: tests/integration/test_feature_update_active_repo.py::
test_active_lookup_does_not_match_sibling_operation_on_same_scope —
술어를 되돌리면 형제 request를 잡아 실패, 고치면 8/8 통과.
```

### 28. 근거 서술 오류 (22번 정정)

22번의 "identity map이 두 행을 접어 뒤 행이 앞 행을 덮는다"는 **이 저장소에서 도달 불가능하다.** `models.py`는 raw SQL 저장소의 Alembic `target_metadata` 원천일 뿐이고(ADR-004), `ProviderDatasetOperationScopeRow`를 ORM 방식(`session.get`/`relationship`/`select`)으로 쓰는 코드가 0건이다.

```
변경은 옳지만 이유가 틀렸다. 올바른 이유는 리뷰어 A가 A/B로 실증했다 —
alembic autogenerate가 PK 제약을 비교 대상에 넣지 않아, ORM PK를 pair로 되돌려도
`alembic check`와 test_alembic_metadata_consistency는 통과한다. 새 PK 대조 게이트만
실패한다. 즉 실효는 "아무 게이트도 이 어긋남을 못 보던 사각을 메운 것"이다.

같은 리뷰에서 게이트의 실제 한계도 드러났다: contype='p'만 보므로 unique/FK/CHECK/
nullable은 검사하지 않는다. 실재하는 nullability divergence 1건 확인 —
models.py:4494 poi_cache_targets.coord_5179가 Computed 열에 nullable 미지정이라
ORM은 NOT NULL, head는 nullable(실해는 없다 — 원본 coord가 NOT NULL).
```

### 29. (미해결) offline upload 리졸버가 500을 낸다 — 21번과 전제조건이 같다

`_resolve_scope_operation_key`는 scope에 operation이 둘 이상이면 `OfflineUploadScopeOperationUnresolved(ValueError)`를 던지는데, 호출부는 `DomainCommandPending`만 잡아 catch-all이 **500 INTERNAL_ERROR**로 만든다.

```
리뷰어 A의 지적이 날카롭다: 21번은 "dataset에 refresh operation 하나 더 등록하는
평범한 작업"이라고 규정했는데, 바로 그 상태에서 offline upload 기능 전체가 500으로
죽는다. 둘 중 하나는 틀렸다 — 그 조합이 평범하면 이건 실제 결함이고, 평범하지
않으면 21번의 심각도가 과장이다.

판단: 21번이 맞다(스키마가 허용하고 카탈로그 등록만으로 도달). 따라서 이건 실제
결함이며, 최소한 500이 아니라 typed 4xx여야 한다. 이번 PR 범위 밖으로 두되
후속으로 남긴다.
```

### 30. contracts/vnext/tvn33-reference-ownership-v1.sql ↔ alembic head 대조 게이트 부재

계약 파일은 스스로 "T-VN-33 **도착점**"이라 선언하는데(파일 머리말), 실제 마이그레이션이 도착하는 곳과 어긋난다. 그리고 **둘을 대조하는 게이트가 없어** 무한정 벌어질 수 있다 — `test_vnext_target_freeze`는 계약을 *새 DB*에 적용해 자기 자신과의 일관성만 본다.

```
실측 divergence (bench DB = alembic head 적용본):
  계약 512행  ops.import_job_events.event_id  bigint GENERATED ALWAYS AS IDENTITY
  head                                        uuid
  계약 334행  uq_import_job_datasets_identity
  head        uq_import_job_datasets_exact_identity
  계약 346행  idx_import_job_datasets_dataset_job (provider_dataset_id, job_id)
  head        idx_import_job_datasets_exact_operation_job
              (provider_dataset_id, sync_scope, operation_key, job_id)
  계약        idx_import_job_events_member_time 에 event_id DESC 열 없음
  — 그런데 ops_repo.py:390-400의 성능 논증("member 마다 상위 :limit만 뽑아 합치면
    전체 상위 :limit이 된다")이 바로 그 열에 의존한다.

이 부류는 이번 작업에서 ORM↔DB PK 어긋남으로 이미 한 번 나왔다(22번). 그때 세운
게이트(test_alembic_head_primary_keys_match_orm_declarations)와 같은 성격의
대조가 계약↔head 사이에는 없다.

판단: 선재 결함이고 이번 PR이 만든 것은 아니지만 T-VN-33이 소유한 아티팩트 안에
있다. 개별 divergence를 손으로 맞추는 것은 다음 drift를 막지 못하므로, 계약이
선언한 테이블에 한해 head와 대조하는 게이트를 세우는 것이 정본 수정이다.
아티팩트 fingerprint 재생성이 딸리므로 이번 PR 범위 밖으로 두고 후속으로 남긴다.
```

### 31. (선재, 이 브랜치 무관) `audit:high`가 red — nanoid advisory

`.github/workflows/frontend.yml:44`의 `audit:high`가 exit 1이다. `nanoid <3.3.17` high (GHSA-2v37-7h3g-55p8), 배포 의존성(`postcss` → `nanoid`).

```
origin/main의 package-lock.json도 nanoid-3.3.16이다 — 이 브랜치가 만든 것이 아니라
lockfile이 고정된 뒤 advisory가 새로 등록된 drift다. main도 같이 red이므로 #966만의
머지 블로커가 아니다.

고치려면 package.json overrides에 nanoid를 박고 lockfile을 재생성해야 한다. 52커밋짜리
identity PR에 lockfile 변경을 끼워 넣으면 리뷰만 어려워지므로 분리한다.
루트 파일이라 컨테이너 하네스가 이미지에 구운 사본을 쓴다는 점도 주의해야 한다
(scripts/verify-all-gates.sh 머리말 참조) — 고칠 때는 이미지를 다시 빌드해야 한다.
```

### 32. 컨테이너 하네스가 루트 파일을 이미지 사본으로 읽는다

`scripts/verify-all-gates.sh`의 `py()`는 `src tests packages contracts alembic alembic.ini`만 복사한다. `package.json` · `package-lock.json` · `pyproject.toml` · `.github/` · `docker-compose*.yml` · `.env.example`은 **이미지에 구워진 사본**이 쓰인다.

```
이 파일들을 읽는 테스트가 7개 있다: test_frontend_dependency_security /
test_ci_workflows / test_docker_dagster_runtime / test_backup_artifacts /
test_deploy_automation / test_c7_prod_live_runner_contract / test_docker_backup_runbook.

이번에는 false-fail 1건으로만 드러났다(이미지의 stale package.json에 `--omit=dev`가
없어 test_frontend_dependency_security가 실패). 그러나 루트 파일을 **고치는** PR에서는
false-pass를 낸다 — 고친 내용이 컨테이너에 반영되지 않으므로 옛 값으로 통과한다.
이 브랜치는 .env.example을 고쳤다.

대응: 스크립트 머리말에 명시했다. 근본 해결은 py()가 루트 파일도 복사하거나 이미지를
다시 빌드하는 것이다 — 후속 태스크로 남긴다.
```

### 33. CI 미러링을 고치자 드러난 기능 손실 — MOIS 사전점검이 사라져 있었다

`react-doctor` 게이트(구 스크립트가 안 돌리던 것)가 죽은 export `useMoisSourceSyncPrecheck`를 잡았고, 파고드니 **이 브랜치가 기능을 통째로 잃은 것**이었다.

```
main의 request-dialog.tsx는 이 훅으로 MOIS 적재 전 Dagster 선행 작업
(mois_localdata_source_sync) 상태를 경고로 보여 준다. T-VN-33이 provider 이름
입력을 없애면서, 그 입력으로 MOIS 여부를 판정하던 moisSelected가 함께 사라졌고
경고·MoisPrecheckNotice 컴포넌트·gating이 전부 없어졌다. 서버 엔드포인트
(/ops/pipeline/prechecks/mois-source-sync)는 그대로 살아 있었다.

복원하되 판정 근거를 옮겼다: provider 이름 문자열이 아니라 **선택된 catalog 행의
provider**로 본다 — 같은 사실을 triple 선택에서 읽는 것이라 T-VN-33 모델과
어긋나지 않는다.

교훈: 게이트 목록을 좁게 잡으면 못 보는 것이 "실패"만이 아니라 **조용히 사라진
기능**이다. 이 손실은 타입체크도 테스트도 잡지 못했다 — 아무도 안 쓰는 export가
남았을 뿐이라 컴파일은 통과한다.
```

### 34. 프론트 게이트 red 2건의 귀속 판정 (선재 vs branch-caused)

`audit:high`와 `admin react-doctor`가 red다. 둘 다 **main에서도 red**임을 실측했다.

```
audit:high — origin/main의 package-lock.json도 nanoid-3.3.16이다(31번).

react-doctor — origin/main의 프론트 src를 git archive로 떠서 같은 명령을 돌렸다:
  origin/main : 10 issues (errors 2, warnings 8)
  이 브랜치   :  7 issues (errors 2, warnings 5)
이 브랜치가 오히려 3건 줄였다. 남은 7건 중 이 브랜치가 건드린 파일은
pipeline-client.tsx(ref mutated during render)와 execution-timeline.tsx(large
component)인데, 전자의 패턴은 main의 같은 위치에도 있다(선재).

branch-caused였던 2건은 이번에 해소했다:
  - deslop/unused-export useMoisSourceSyncPrecheck → 33번으로 기능 복원
  - deslop/unused-file combobox-multiple.tsx → 삭제. main에서는 request-dialog가
    providers[]/dataset_keys[] 다중선택에 썼는데 T-VN-33이 그 배열을 의도적으로
    없앴으므로 기능 손실이 아니라 진짜 죽은 코드다.
```

### 31-정정. `audit:high`는 **#966의 머지 블로커다**(선재이지만 면제되지 않는다)

31번에서 "main도 red이므로 #966만의 블로커가 아니다"라고 적었는데, 그 서술이 잘못을 가린다. 적대 리뷰 6라운드의 지적이 옳다 — **책임 소재를 바꿀 뿐 머지 가능성을 바꾸지 않는다.** CLAUDE.md §5-1이 "CI green 후 머지"를 요구하고 `frontend.yml`의 `audit:high`는 `continue-on-error`가 없는 차단 스텝이므로, 이 상태로는 어떤 PR도 머지될 수 없다.

```
현상: nanoid 3.3.16 (postcss가 끌어옴) — GHSA-2v37-7h3g-55p8, high.
      advisory는 >=3.3.17을 요구하고 그것은 lockfile의 `^3.3.16` 범위 안이다.
정본 수정: `npm audit fix` 또는 lockfile의 nanoid를 3.3.17로 올린다.

**이번 세션에서 하지 않은 이유**: 이 환경의 node가 v20.20.2인데 저장소는
`^22.22.2 || ^24.15.0 || >=26.0.0`을 요구해 `npm audit fix`가 engine 검사로 거부된다.
손으로 lockfile을 편집하면 `npm ci`가 통과하는지 로컬에서 확인할 방법이 없고,
검증 못 한 변경을 "고쳤다"고 선언하는 것은 이 브랜치가 다섯 번 REJECT된 바로 그
패턴이다. 그래서 하지 않고 블로커로 남긴다 — Node 22+ 환경에서 처리해야 한다.
```

### 31-해소. `audit:high` 머지 블로커 제거 (Node 22 설치 후)

이 환경에 Node 22.22.2를 설치해 `npm audit fix`를 정상 실행했다. 손으로 lockfile을 짐작해 편집한 것이 아니라 **도구가 만들고 도구가 검증한** 변경이다.

```
npm audit fix --package-lock-only --omit=dev
  nanoid 3.3.16 -> 3.3.18   (^3.3.16 범위 내, advisory 요구 >=3.3.17 충족)
  부수: "dev": true / "peer": true 플래그 정리 — resolver가 postcss 경유 prod
        의존이라는 실제 분류로 바로잡았다.

검증(직전 커밋이 못 해서 블로커로 남겼던 바로 그것):
  npm run audit:high                                      -> EXIT=0 (이전 1)
  npm ci --workspaces --include=optional --no-audit
     --no-fund --dry-run                                  -> EXIT=0
     (postinstall의 @redocly/openapi-core vendor patch까지 정상)

교훈: "환경이 없어 검증할 수 없다"는 상태를 방치하면 그 자리에 미검증 주장이 쌓인다.
환경을 올리는 것이 검증 없는 변경을 넣는 것보다 싸다.

### 29-해소. offline upload 500 → typed 4xx (커밋 이후 `6c4ac6de` 이전)

후속으로 미루려던 것을 이번 브랜치에서 닫았다. 21번이 맞다는 판단을 유지한 채로,
그 조합에서 죽던 표면을 고쳤다.

```
OfflineUploadScopeOperationUnresolved에 `resolved: int`를 실어, 라우터가
  resolved == 0  -> "이 scope에 refresh operation이 없다"
  resolved  > 1  -> "형제 operation이 둘 이상이라 지목이 필요하다"
로 갈라 409를 낸다. 둘은 운영자가 취할 조치가 정반대라 같은 메시지로 뭉치면 안 된다.
그리고 처리 **전에** parse_canonical_sync_scope로 422 가드를 세웠다 — 비정규
scope 문자열이 리졸버까지 내려가 다른 이유로 터지는 경로를 없앤다.
프론트 기본값도 "default" -> "dataset_wide"로 고쳤다(T-VN-33 정규 scope 이름).
```

## 적대 리뷰 7라운드가 드러낸 것 (2026-08-09)

### 35. run history가 요청한 축을 넘었다 (exact triple 상세에 형제 operation 혼입)

`load_dataset_detail`은 `dataset_operation_key`로 **root를** 고르지만, 고른 root의
`provider_datasets` membership 목록에는 형제 operation이 그대로 들어 있다.
`_run_history_records`가 `sync_scope`만 보고 membership마다 행을 내니, exact triple을
지목한 상세 화면이 옆 operation의 실행을 섞어 보여줬다. 화면 안내문("서버가 cursor와
page limit 전에 선택한 exact scope를 적용한 canonical operation만 표시합니다")과도
정면으로 어긋난다.

```
고침: _run_history_records(operation_keys=...)로 걸러내고, scope 롤업(None)일 때만
전부 싣는다. 양방향 단언을 박았다 — 롤업은 형제 둘 다, exact는 하나만.

이 결함은 "형제 operation을 접지 말자"는 이번 작업의 방향 자체에서 나왔다. 확장을
하면 그 확장이 **어디서 멈추는지**도 같이 정해야 한다.
```

### 36. 그 확장의 프론트 쪽 대가 — row id 충돌 + 구분 불가

행이 membership마다 나오는데 `datasets-client.tsx`의 `getRowId`는 `${kind}:${id}`였다.
형제 둘이 같은 row id를 갖는다 — React key 중복이고, DataTable의 선택/확장 상태가
뒤섞인다. 게다가 `operation_key` 열이 없어 운영자에게는 **같은 실행이 두 번 찍힌
것으로만** 보인다.

```
고침: row id를 `kind:id:sync_scope:operation_key`로, `operation` 열 추가.
서버 스키마는 이미 operation_key: str(non-null)였다 — 데이터는 있었고 표면이 없었다.
```

### 37. 게이트 스크립트가 소스 복사 실패를 삼켰다

`py()`의 컨테이너 명령이 `... && cp -r ... . && cp alembic.ini 2>/dev/null; $1`이었다.
`;` 앞이 실패해도 `$1`이 그대로 돌고, 종료코드는 `$1`의 것이다 — **이미지에 구워진 낡은
트리 위에서** 게이트가 통과할 수 있다.

```
고침: 복사 실패를 exit 97로 만든다. 게이트 스크립트의 존재 이유가 "무엇을 검사했는지
거짓말하지 않는 것"인데, 그 자리에 조용한 거짓이 있었다.
```

### 38. (BLOCKER) 감사기가 로컬 게이트의 **약화**를 원리적으로 못 잡았다

리뷰어의 지적: 이 브랜치가 여섯 번 REJECT된 실패 모드(더 좁은 집합을 돌리고 green
선언)가 그대로 감사 사각이다. 실증으로 변이 3종이 생존했다.

```
M7  실행문을 지우고 같은 문자열을 주석으로만 남김
    원인: 조각을 파일 어디서든 찾았다. 헬퍼 함수 본문에 문자열이 남으면 통과.
    고침: run_gate 호출 줄 + **그 줄이 이름으로 부르는 함수 본문**만 증거로 인정
          (도달성 판정). 줄바꿈 이어쓰기는 한 논리 줄로 합친다.
N6  export_openapi.py에서 --check 제거(검사가 아니라 재작성이 된다)
    원인: 일반 `scripts/*.py` 분기가 먼저 걸려 경로만 조각이 됐다.
    고침: 분기 순서를 뒤집고, 순서가 곧 계약임을 주석에 박았다.
M8  uses: ./.github/actions/... 로컬 composite action 스텝
    원인: 마켓플레이스 액션 면제 키 "actions/"가 로컬 경로에도 부분문자열로 걸렸다.
    고침: `uses ./`로 시작하는 명령은 면제에서 제외.

도달성 판정 자체를 겨냥한 M9(게이트를 아무도 안 부르는 함수로 이동)를 추가했다.
scripts/audit-mutation-battery.py = 20/20.
```

교훈은 앞의 것과 같은데 한 겹 위다: 감사기가 **통과하는 것**과 감사기가 **유효한
것**은 다른 문제다. 변이를 심어 확인하지 않은 감사는 그 위의 green을 지탱하지 못한다.
