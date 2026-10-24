# 관리·운영 DB reader 스냅샷 후속

기준은 PR1372 `b8f6e677a92a2f42e5a37722efe0d97f3cba69dd`다. 기존 29개 reader와 인증 변경은 그 PR에 고정한다. 이 후속은 아래 13개 GET의 DB phase를 RR로 묶는다. 잠금 없는 12개는 기존 READ ONLY dependency, 행 잠금이 필수인 1개는 좁은 READ WRITE RR dependency를 쓴다. READ COMMITTED 트랜잭션 중간에 isolation을 바꾸지 않으며 SQL·권한·mutation 계약·DTO·OpenAPI를 수정하지 않는다.

## 이번에 적용한 범위

| 모듈 / 함수 | 실제 DB 경계 | 처리 |
| --- | --- | --- |
| `admin_files.files_summary` | kind/status/location의 세 집계 | 하나의 RR/READ ONLY |
| `admin_files.file_detail`, `file_events` | 파일 metadata 후 events | 하나의 RR/READ ONLY |
| `admin_issues.list_admin_issues` | optional canonical/legacy identity 후 목록 | 하나의 RR/READ ONLY |
| `admin_issues.get_admin_issue` | issue 후 연결 feature 주소 | 하나의 RR/READ ONLY |
| `cache_target_streams.get_service_cache_target_reconciliation_snapshot` | principal 범위 확인용 request metadata 후 이미 발급된 snapshot header/items | 행 잠금을 유지하는 RR/READ WRITE; snapshot 발급 없음 |
| `cache_target_streams.get_ops_cache_target_operation` | reconciliation operation 후 delivery fallback | 하나의 RR/READ ONLY |
| `offline_uploads.get_offline_upload_validation_request` | upload 후 validation job | 하나의 RR/READ ONLY; 파일 읽기·검증 실행 없음 |
| `ops.get_ops_metrics` | status 여러 집계 + integrity + consistency report | 하나의 RR/READ ONLY |
| `ops_datasets.list_datasets_grid`, `get_dataset_detail` | sync state/policy/issue/execution/catalog | Dagster schedule HTTP를 최초 DB 조회 앞으로 옮긴 뒤 DB phase만 RR |
| `ops_geo_releases.get_geo_release` | plan 후 coverage | GET의 session만 RR; mutation 뒤 공유 `_detail` 함수의 session은 변경 없음 |
| `ops_pipeline.get_execution_detail` | canonical root/job/request/events/cancellation | 하나의 RR/READ ONLY; cancellation 명령은 변경 없음 |

Dagster HTTP와 DB가 같은 시점이라는 보장은 하지 않는다. schedule HTTP 동안 snapshot/connection을 열지 않고, 그 뒤 최초 SQL부터 응답의 DB 자료만 같은 snapshot으로 읽는다. 인증과 업무 snapshot도 같은 시점이라는 주장을 하지 않는다. 새 pool/auth를 만들지 않는다. 기존 engine의 execution option으로 잠금 조회용 dependency만 추가한다.

## 행 잠금 조회 예외

reconciliation snapshot은 DML이 없지만 `_GET_RECONCILIATION_SNAPSHOT_SQL`의 `FOR SHARE OF request, stream`과 `_GET_SNAPSHOT_SQL`의 `FOR SHARE OF snapshot, material`이 compaction/상태 변경을 보호한다. PostgreSQL READ ONLY에서는 이 잠금을 25006으로 거부하므로 순수 조회와 같은 dependency로 바꾸면 안 된다. 최초 checkpoint008의 잘못된 분류를 자체 점검에서 발견했으며 그 checkpoint를 수용하지 않았다.

`get_locking_read_snapshot_session`은 해당 단일 GET에만 연결한다. 최초 SQL 전에 RR/READ WRITE를 선택하되 기존 DB role/권한과 SQL 잠금을 그대로 유지한다. 기존 READ ONLY dependency의 동작과 기존 mutation의 `get_session`은 변경하지 않는다. READ WRITE는 조회 phase의 행 잠금 호환성을 뜻하며 새로운 쓰기 API를 열지 않는다.

## 혼합 경로와 기존 단일 SQL의 전수 분류

| 경로 / 함수 | 분류와 유지 근거 |
| --- | --- |
| `admin_files.list_files` | `list_managed_files` 단일 SELECT/window total; 기존 session 유지 |
| 파일 rescan/purge | 파일/S3 작업과 DB 쓰기 명령; RR/READ ONLY 적용 안 함 |
| `admin_issues.patch_admin_issue` | geocoding HTTP + 감사/수정; 기존 쓰기 session 유지 |
| cache target / stream discovery / refresh request GET | 각각 단일 repository SELECT |
| cache dead-letter 단건/목록, stream status 목록 | 각각 단일 repository SELECT |
| `get_service_cache_target_snapshot` | 첫 page `_create_generic_snapshot`가 immutable snapshot을 발급하는 DB 쓰기; GET이라는 이유로 읽기 전용으로 바꾸지 않음 |
| reconciliation begin/seal/complete, event claim/ack/nack/replay | 명시적 쓰기·lease 명령; 기존 session 유지 |
| offline upload 목록/단건 | 각각 단일 SELECT |
| offline preview | upload SELECT + 저장 파일 읽기; 파일 시점을 MVCC로 보장하지 않음 |
| offline validate/load/delete | HTTP·파일 및 DB 쓰기; 기존 session 유지 |
| `ops.get_ops_health_deep` | DB/PostGIS/prewarm readiness 진단; Feature 응답 snapshot이 아닌 상태 점검 |
| consistency report / integrity issue 목록 | 각각 단일 SELECT |
| `ops_geo_releases.list_geo_releases` | Geo HTTP 후 `list_geo_release_plans` 단일 SELECT; 기존 session 유지. 선행 보고서의 다중 DB 조회 분류를 정정한다. |
| Geo detect/skip/replan | mutation + 후속 상세 응답; 기존 read-write session 유지 |
| `ops_pipeline.get_pipeline_overview` | DB 상태 단일 CTE + Dagster HTTP; 두 DB image 조립이 아님 |
| `list_executions`, `list_pipeline_events` | 각 단일 repository SELECT/CTE |
| `list_pipeline_schedules` | override 단일 SELECT + Dagster HTTP; 외부 상태와 DB의 원자 시점 보장 없음 |
| Dagster summary/runs/detail/MOIS precheck | 외부 HTTP 조회, 이 DB reader 패치 대상 아님 |
| pipeline schedule/update/preview 명령 | DB 쓰기·외부 HTTP를 포함, read-only로 변경 안 함 |
| reference reconciliation lease GET | DB lease를 변경하므로 기존 session 유지 |
| feature request 단건/목록, manual provider case 단건/목록 | 각 단일 SELECT |
| file alias map page/checksum | 각 단일 SELECT |
| curation theme/source/rule 조회 | 각 단일 SELECT; 다중 조회 reader는 PR1372 소유 |
| curation snapshot item/collection/cutover 조회 | 각 단일 CTE/aggregate SELECT |
| POI cache target 단건/목록, public provider freshness | 각 단일 SELECT |
| public feature/beach/festival 다중 조회 | PR1372 소유; marker/beach 목록 등 단일 SQL는 기존 session 유지 |
| live/file stream | DB snapshot이 파일·외부 상태까지 고정한다는 보장 없음; 본 패치에서 lifecycle 변경 없음 |

## 검증과 한계

관련 router fake는 새 dependency를 명시적으로 override한다. 기존 mutation fake와 권한 판정은 유지한다. 실제 PG/ASGI 반증은 READ COMMITTED control과 새 RR를 모두 실행하며 두 번째 writer의 commit을 SELECT 사이에 주입한다. 운영 호출·수집·배포·활성화는 하지 않았다. 전체 동시 쓰기 gate/kernel과 수집 writer 배선은 이 PR의 완료 범위가 아니다.

- 관련 8개 router 단위 510건 PASS(195.29초). 기존 mutation/권한·filter와 새 명시 dependency override를 함께 확인했다.
- 실제 PostgreSQL/ASGI 8건 PASS(28.42초): metrics 총계→kind 집계, 파일 metadata→event, issue→feature 좌표, dataset state→catalog 각각의 READ COMMITTED 반례와 RR 보존을 확인했다. dataset 회귀는 schedule HTTP가 최초 DB phase보다 앞섬도 확인한다. 파일 실체/외부 상태의 snapshot을 주장하지 않는다.
- 처음 PG 실행의 실패는 시험 fixture가 JSONB 주소에 문자열을 대입한 오류와 새 catalog의 FK cleanup 순서였다. 좌표 변경 반례와 operation-scope→operation→dataset 순서의 fixture 정리로 수정했으며 제품 SQL/DDL은 바꾸지 않았다.
- 변경 API 9개 파일 strict mypy PASS, 변경 파일 Ruff PASS. 정본 Pydantic overlay로 all-profile OpenAPI check PASS, generated spec 변경 0.

두 독립 리뷰·정확 CI 및 실제 운영 HTTP/UI 수용은 아직 미완이다.


행 잠금 보완 후 cache router 178건 PASS(56.64초), DB/cache router strict mypy 2개 PASS. 실제 PG/ASGI 추가 2건 PASS(19.47초): 잘못된 READ ONLY를 주입하면 실제 FOR SHARE에서 25006을 관측하고, 새 dependency에서는 isolation=REPEATABLE READ, transaction_read_only=off를 SHOW로 확인해 정상 200을 받는다. 별도 writer의 `pg_blocking_pids`가 현재 reader PID를 가리키는 동안 snapshot item을 읽고, 응답 종료 뒤 writer 완료와 다음 pool session의 READ COMMITTED/read-write 복구를 확인했다. 시험 초안의 principal role registry 누락은 정본의 4개 exact role profile로 보완했으며 인증 조건을 낮추지 않았다.

최종 새 PG/ASGI 파일 전체 10건 PASS(34.61초). 행 잠금 보완 뒤 all-profile OpenAPI check/Ruff/redaction도 PASS이며 생성 spec 변경 0이다.
