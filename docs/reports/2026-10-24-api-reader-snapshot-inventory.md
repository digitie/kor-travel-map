# ADR115 API 읽기 snapshot inventory 및 구현 경계

기준은 `2a53dce7cabfa594ce2a699550ae5dafe78b37ad`다. T-CWRITE01/04 중 다중 SELECT의 읽기 경계만 소유한다. 실제 동시 쓰기/잠금 세분화·정책 활성화·migration·운영 배포를 완료했다고 주장하지 않는다.

기본 `get_session`은 READ COMMITTED이고 auth/쓰기·lease가 공유한다. 이를 일괄 변경하지 않고 새 `get_read_snapshot_session`이 독립 세션에서 **최초 데이터 SELECT 전** read-only REPEATABLE READ를 설정한다. 이미 시작된 트랜잭션의 isolation 변경은 없다. 모든 repo 호출과 응답 조립까지 같은 세션이며 별도 HTTP page 간 snapshot은 약속하지 않는다.

## 다중 SQL 순수 reader — 구현 대상

| router | handler | 실제 조회 호출 경계 |
|---|---|---|
| `admin_features.py` | `get_admin_feature_price` | `resolve_feature_ref_or_error, _admin_feature_exists_or_404, price_repo.build_price_card` |
| `admin_features.py` | `get_feature_creation_provenance_route` | `resolve_feature_ref_or_error, get_admin_manual_feature_provenance` |
| `admin_features.py` | `get_feature_detail_route` | `resolve_feature_ref_or_error, get_admin_feature_detail, curation_repo.list_curation_items_by_feature_ids` |
| `admin_features.py` | `get_feature_revision_route` | `resolve_feature_ref_or_error, get_feature_row_revision` |
| `admin_features.py` | `list_feature_state_transitions_route` | `resolve_feature_ref_or_error, get_feature_row_revision, list_admin_feature_state_transitions` |
| `curations.py` | `get_admin_curation_collection` | `curation_repo.get_curation_collection` |
| `curations.py` | `get_admin_curation_import_batch` | `curation_repo.get_curation_import_batch` |
| `curations.py` | `get_public_curation_collection` | `curation_repo.get_curation_collection` |
| `curations.py` | `get_public_feature_curations` | `resolve_feature_ref_or_error, curation_repo.get_feature_curation_group` |
| `curations.py` | `list_admin_curation_quarantine_items` | `curation_repo.list_curation_quarantine_items` |
| `curations.py` | `list_admin_theme_candidate_transitions` | `curation_candidate_repo.list_theme_candidate_transitions, curation_candidate_repo.get_theme_candidate` |
| `curations.py` | `list_admin_theme_candidates` | `curation_candidate_repo.list_theme_candidates, feature_identity.canonical_feature_id_for_filter` |
| `curations.py` | `list_public_curation_groups` | `curation_repo.list_feature_curation_groups` |
| `dedup_review.py` | `get_review_detail` | `get_dedup_review_detail` |
| `dedup_review.py` | `list_reviews` | `list_dedup_reviews, feature_identity.legacy_id_for_filter` |
| `enrichment_review.py` | `get_review_detail` | `get_enrichment_review_detail` |
| `enrichment_review.py` | `list_reviews` | `list_enrichment_reviews, feature_identity.legacy_id_for_filter` |
| `features.py` | `get_area_contained_features` | `resolve_feature_ref_or_error, _public_feature_row_or_404, feature_repo.features_contained_in_area` |
| `features.py` | `get_feature` | `resolve_feature_ref_or_error, _public_feature_row_or_404, curation_repo.list_curation_items_by_feature_ids` |
| `features.py` | `get_feature_observation_history` | `resolve_feature_ref_or_error, observation_repo.get_observation_history` |
| `features.py` | `get_feature_price` | `resolve_feature_ref_or_error, _public_feature_row_or_404, price_repo.build_price_card` |
| `features.py` | `get_feature_price_snapshot` | `resolve_feature_ref_or_error, _public_feature_row_or_404, price_repo.build_price_snapshot` |
| `features.py` | `get_feature_sources` | `resolve_feature_ref_or_error, observation_repo.get_current_observations` |
| `features.py` | `get_features_batch` | `feature_identity.resolve_feature_identities_bulk, feature_repo.get_service_feature_batch_items` |
| `features.py` | `list_features_nearby_by_target` | `get_poi_cache_target_by_key, feature_repo.features_nearby_poi_cache_target` |
| `features.py` | `search_public_features` | `feature_repo.search_features` |
| `public_views.py` | `get_public_beach` | `resolve_feature_ref_or_error, public_views_repo.get_public_beach` |
| `public_views.py` | `get_public_festival` | `resolve_feature_ref_or_error, public_views_repo.get_public_festival` |
| `public_views.py` | `list_public_festivals_monthly` | `public_views_repo.list_public_festivals_monthly` |

`price_repo._build_price_card`는 current/history 두 SELECT, admin detail은 본문/files/전이 등 여러 SELECT, dedup/enrichment 목록은 count/items, 상세는 review와 참조 Feature를 분리 조회한다. curation collection/group/import/quarantine은 metadata/count/item 또는 Feature 보조 조회를 분리한다. festival monthly는 count/items가 분리된다. 단일 SQL의 내부 CTE·window는 이미 statement snapshot이므로 그대로다.

## 분류하여 기존 경계를 유지하는 경로

- features bbox/bounds/nearby, admin bbox/list, curated theme/source/rule, curation service snapshot/cutover export: 해당 reader는 한 business SELECT로 조립한다. 쓰기나 세분화가 필요하지 않다.
- curation list/단일 item/candidate 등 단일 SELECT 경로는 그대로다. 선택적 identity 필터가 추가 SQL을 하는 `list_admin_theme_candidates`는 위 대상이다.
- auth, mutation POST/PUT/PATCH/DELETE, GET lease/ack/stream과 read/write 혼합 서비스는 `get_session` 및 기존 transaction을 유지한다. 운영/파일/로그/외부 HTTP 관측은 Feature snapshot과 같은 시점이라고 약속하지 않는다.
- 아래 전수 분류표의 `RR 후속 필요`는 이 checkpoint에 미구현이다. 이번 29개 reader만으로 전체 T-CWRITE01/04 완료를 표시하지 않는다.

## 검증 계획 및 상태

독립 두 PG 세션의 writer commit을 실제 repo SELECT 사이에 주입하여 identity/body, target/nearby, price current/history, admin 또는 curation count/items의 old/old 또는 new/new를 확인한다. read-only/RR 실제 SHOW, 예외 rollback·pool 반환, 기존 mutation 세션의 쓰기 가능성을 별도 검증한다. 구현/단위/PG/CI/두 리뷰/운영 수용은 각 gate 결과를 나누어 기록한다. 현재 실제 운영 호출은 0회다. 실제 PG/ASGI 13개가 통과했으며 READ COMMITTED 혼합 반증, REPEATABLE READ 일관성, 예외 후 pool 복원, pool size=1 cold 인증을 포함한다. 관련 API 198개와 수정된 auth 93개가 통과했다. 전체 API는 1,344 passed/1 failed 후 dependency override를 수정했으므로 그 단일 실행을 전체 성공으로 세지 않는다. 소스 b8f6e677a의 두 독립 리뷰는 PASS이며, 최종 문서 포함 후보의 정확한 CI와 실제 HTTP/UI 수용은 별도 게이트다.

## 나머지 DB session GET 전수 분류

API router의 `Depends(get_session)`/`get_read_snapshot_session` AST와 실제 infra SQL을 대조했다. `단일 SQL`은 한 statement의 CTE/window/집계를 포함하며 statement 내부 snapshot으로 충분하다. `RR 후속 필요`는 복합 읽기가 확인됐고 이 checkpoint에는 아직 미구현이라는 뜻이다. lease/immutable snapshot 발급 같은 GET의 DML을 읽기 전용으로 잘못 바꾸지 않는다.

| router / 함수 | 분류 | 실제 근거 / 보존 이유 |
|---|---|---|
| admin_auth: `get_admin_auth_events`, `get_public_api_keys` | 단일 SQL | auth event/key 목록 repository 각각 한 SELECT |
| admin_features: `list_admin_features_in_bounds`, `list_features` | 단일 SQL | bbox의 item/cluster는 선택한 한 SQL; 목록은 같은 SQL의 aggregate |
| admin_files: `list_files` | 단일 SQL | `file_registry.list_managed_files`: items+`count(*) OVER()` 한 SELECT |
| admin_files: `files_summary`, `file_detail`, `file_events` | RR 후속 필요 | `summarize_managed_files` 3 SELECT; file metadata→events 2 SELECT |
| admin_issues: `list_admin_issues`, `get_admin_issue` | RR 후속 필요 | optional identity/filter→issue query; issue→`get_feature_address_snapshot` |
| cache_target_streams: `get_service_cache_target`, `get_service_cache_target_stream`, `get_service_refresh_request`, `get_service_cache_target_dead_letter`, `list_ops_cache_target_streams`, `list_ops_cache_target_dead_letters`, `get_ops_cache_target_dead_letter` | 단일 SQL | `get_cache_target_source`/stream discovery/update request/deadletter/status 각각 한 SELECT |
| cache_target_streams: `get_service_cache_target_snapshot` | 의도적 read/write 혼합 | `get_cache_target_snapshot` 첫 page는 `_create_generic_snapshot`으로 immutable snapshot을 발급한다. 후속 page만 읽기이며 원래 발급 transaction을 보존한다 |
| cache_target_streams: `get_service_cache_target_reconciliation_snapshot`, `get_ops_cache_target_operation` | RR 후속 필요 | access metadata→snapshot header/items 및 operation header→result의 여러 SELECT; snapshot cursor 의미를 보존해 별도 전환 필요 |
| categories: `list_categories` | 단일 SQL | `category_feature_counts` 한 SELECT |
| curated: theme/source/rule 목록·단건 6개 | 단일 SQL | `curated_repo.list/get_*` 각 한 SELECT |
| curation_snapshots: `get_curation_item_detail_snapshot`, `get_curation_collection_detail_snapshot`, `get_curation_cutover_identity_mappings` | 단일 SQL | item/collection/cutover export repository가 한 SELECT의 CTE/집계로 구성 |
| curations: `audit_unattributed_curation_links`, `list_admin_curation_quarantines`, `get_admin_curation_item_current_import_row`, `get_admin_theme_candidate`, `list_public_curation_collections`, `list_admin_curation_collections` | 단일 SQL | 각 `curation_repo`/candidate 조회의 한 SELECT; 다중 SQL 경로는 상단 RR 29개 표에 분리 |
| feature_alias_maps: `get_feature_alias_map_page`, `get_feature_alias_map_checksum` | 단일 SQL | `feature_alias_map_repo.fetch_feature_alias_map_page`/`compute_feature_alias_map_checksum` 각각 한 SELECT |
| feature_requests: `get_feature_request_route`, `list_feature_requests_route` | 단일 SQL | `_queue_item_or_404`→`get_feature_request`, 목록 각각 한 SELECT |
| feature_reference_reconciliations: `lease_feature_reference_reconciliation_event_route` | 의도적 read/write 혼합 | `lease_feature_reference_reconciliation_event`가 lease를 획득하는 command. GET이라는 이유로 READ ONLY 전환 금지 |
| feature_reference_reconciliations: `list_manual_provider_dedup_cases_route`, `get_manual_provider_dedup_case_route` | 단일 SQL | reconciliation repo 각 한 SELECT |
| features: `list_features_in_bbox`, `list_public_features_in_bounds`, `list_features_nearby` | 단일 SQL | 선택한 bbox/cluster/nearby SQL 각각 한 statement |
| offline_uploads: `list_offline_upload_requests`, `get_offline_upload_request` | 단일 SQL | `list_offline_uploads`/`get_offline_upload` 각 한 SELECT |
| offline_uploads: `preview_offline_upload_request` | 의도적 외부 파일 혼합 | DB metadata 후 `store.read_bytes`로 별도 파일을 읽는다. 파일까지 MVCC snapshot이라고 주장하지 않는다 |
| offline_uploads: `get_offline_upload_validation_request` | RR 후속 필요 | `get_offline_upload`→`get_import_job` 별도 SELECT |
| ops: `get_ops_metrics` | RR 후속 필요 | `gather_status_counts`/integrity counts/latest report의 복수 DB SELECT. Feature와 전체 운영 통계의 단일 시점을 현재 보장하지 않는다 |
| ops: `get_ops_health_deep` | 의도적 다중 상태 관측 | `_check_database`/PostGIS/prewarm 각각의 진단. 외부 런타임까지 단일 DB snapshot을 약속하지 않는다 |
| ops: `list_consistency_reports`, `list_integrity_issues` | 단일 SQL | ops repo 목록 SQL |
| ops_contract_fixtures: `get_c6c_cancel_probe` | 단일 SQL | `get_c6c_cancel_probe_fixture`의 current receipt SELECT. 실제 lease/finalize command는 별도 mutation 경로다 |
| ops_datasets: `list_datasets_grid`, `get_dataset_detail` | RR 후속 필요 | `load_datasets_grid/detail`의 catalog·sync state·정책·이벤트·issue 조회. schedule 외부 상태와 DB snapshot은 구분해 phase 설계 필요 |
| ops_geo_releases: `list_geo_releases`, `get_geo_release` | RR 후속 필요 | `_current_dataset`→plans, `_detail`의 plan/coverage/item 조회가 분리됨 |
| ops_logs: `get_system_logs`, `get_api_call_logs` | 단일 SQL | 각각 repository 목록 한 SELECT |
| ops_pipeline: `list_executions`, `list_pipeline_events` | 단일 SQL | pipeline/event repo의 단일 statement/CTE |
| ops_pipeline: `get_execution_detail` | RR 후속 필요 | `_load_execution_detail`: execution→job/request→cancel detail→events 별도 SELECT |
| ops_pipeline: `get_pipeline_overview`, `list_pipeline_schedules` | 의도적 외부 상태 혼합 | DB counts/override와 Dagster HTTP 상태. 두 시스템의 동시 snapshot이라고 주장하지 않는다 |
| poi_cache_targets: `list_poi_cache_target_records`, `get_poi_cache_target_record` | 단일 SQL | target repo 각각 한 SELECT |
| public_providers: `list_providers_freshness`, `get_provider_last_sync` | 단일 SQL | sync state 목록 각각 한 SELECT |
| public_views: `list_public_beaches`, `list_public_beach_markers`, `list_public_festival_markers` | 단일 SQL | public view item/marker 각각 한 SELECT |

`get_engine`을 직접 받는 장기 phase·Dagster HTTP·SSE/WebSocket·Valkey service reader는 위 DB session GET 표와 다르다. 이미 별도 엔진/phase를 소유하는 cancellation·stream·장기 파일 작업을 이 새 의존성으로 감싸지 않는다. Feature/curation의 위 RR 후속 목록을 모두 수용하기 전에는 T-CWRITE01/04 전체 완료가 아니다.

## cold public key 인증의 pool 수명

cold key 캐시가 기존 요청 세션의 connection을 잡은 채 독립 snapshot 세션이 두 번째 checkout을 기다리면 pool1에서 timeout이 난다. 실제 API key 인증·`pool_size=1,max_overflow=0,pool_timeout=0.25`에서 수정 전 QueuePool timeout 반례를 확인했다. 인증 전용 session dependency와 hash 조회의 짧은 context로 connection을 먼저 반납하고, 기존 handler/쓰기 session은 닫지 않는다. 인증 완료 후 업무 snapshot을 시작하며 권한과 업무 데이터가 같은 DB 시점이라는 주장은 하지 않는다.

## checkpoint 검증

- 관련 router 단위 198건 PASS(87.01초), 새로운 실제 PG 반증·pool 회귀 13건 PASS(38.19초). 상세/배치/target/가격/관리 count-items 다섯 경계에서 READ COMMITTED 반례와 새 RR 보존을 함께 관측했다. fixture의 target 이동 명시와 page total 경로 오류는 시험 코드만 정정했다.
- 실제 `SHOW transaction_isolation=repeatable read`, `transaction_read_only=on`, 금지 DDL 실패 뒤 context 종료·pool 다음 writer의 READ COMMITTED/read-write 복구를 확인했다. cold key 캐시/pool1은 단일·동시3 요청200 및 invalid key401 후 pool반납0을 확인했다.
- API DB/auth strict mypy PASS. 정본 `docker/constraints-dagster.txt`의 Pydantic2.13.5/core2.46.5/settings2.15.0을 전용 임시 overlay로 사용한 all-profile OpenAPI check PASS이며 generated spec/DTO 변경은 없다. 다른 작업자의 공유 venv(2.14.1)는 수정하지 않았다.
- 전체 API 단위 suite와 exact CI/독립 두 리뷰는 별도 진행 중이다. 운영 호출·배포·정책 활성화는 0회다. T-CWRITE01/04 전체 및 위 표의 RR 후속은 아직 완료가 아니다.

전체 API suite는 1344 PASS/1 FAIL(439.02초)이었다. 실패는 기존 `test_auth._client`가 새 인증 전용 dependency를 fake로 등록하지 않아 placeholder DB에 연결한 시험 배선 누락이었다. 해당 테스트 파일만 전용 override/context를 명시하고 원래 auth 판정을 보존했다. 정본 constraints로 auth 전체93건 PASS(16.17초)를 재확인했다. 이 마지막 변경은 시험 배선과 기존 일반 session의 잘못된 read-only 주석 교정이며 transaction 동작을 바꾸지 않는다. exact CI 전체 결과는 별도 수용한다.


## 최신 main 통합

#1367의 weather 상태 REST와 Valkey 적재가 들어온 main `e0131ec16`을 합쳤다.
새 weather REST는 Valkey를 읽으며 이 PR의 PostgreSQL snapshot 대상으로 확장하지 않는다.
기존 분류와 29개 DB reader 코드는 유지했다. 운영 export 활성화·Map 연동 검증의 보류도 유지한다.
