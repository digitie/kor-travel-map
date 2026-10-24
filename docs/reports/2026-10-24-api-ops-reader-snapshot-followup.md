# 관리·운영 DB reader 스냅샷 후속

기준은 PR1372 `b8f6e677a92a2f42e5a37722efe0d97f3cba69dd`다. 기존 29개 reader와 인증 변경은 그 PR에 고정한다. 이 후속은 아래 13개 GET의 DB phase에 기존 `get_read_snapshot_session`을 연결한다. READ COMMITTED 트랜잭션 중간에 isolation을 바꾸지 않으며 SQL·권한·mutation 계약·DTO·OpenAPI를 수정하지 않는다.

## 이번에 적용한 범위

| 모듈 / 함수 | 실제 DB 경계 | 처리 |
| --- | --- | --- |
| `admin_files.files_summary` | kind/status/location의 세 집계 | 하나의 RR/READ ONLY |
| `admin_files.file_detail`, `file_events` | 파일 metadata 후 events | 하나의 RR/READ ONLY |
| `admin_issues.list_admin_issues` | optional canonical/legacy identity 후 목록 | 하나의 RR/READ ONLY |
| `admin_issues.get_admin_issue` | issue 후 연결 feature 주소 | 하나의 RR/READ ONLY |
| `cache_target_streams.get_service_cache_target_reconciliation_snapshot` | principal 범위 확인용 request metadata 후 이미 발급된 snapshot header/items | 하나의 RR/READ ONLY; snapshot 발급 없음 |
| `cache_target_streams.get_ops_cache_target_operation` | reconciliation operation 후 delivery fallback | 하나의 RR/READ ONLY |
| `offline_uploads.get_offline_upload_validation_request` | upload 후 validation job | 하나의 RR/READ ONLY; 파일 읽기·검증 실행 없음 |
| `ops.get_ops_metrics` | status 여러 집계 + integrity + consistency report | 하나의 RR/READ ONLY |
| `ops_datasets.list_datasets_grid`, `get_dataset_detail` | sync state/policy/issue/execution/catalog | Dagster schedule HTTP를 최초 DB 조회 앞으로 옮긴 뒤 DB phase만 RR |
| `ops_geo_releases.get_geo_release` | plan 후 coverage | GET의 session만 RR; mutation 뒤 공유 `_detail` 함수의 session은 변경 없음 |
| `ops_pipeline.get_execution_detail` | canonical root/job/request/events/cancellation | 하나의 RR/READ ONLY; cancellation 명령은 변경 없음 |

Dagster HTTP와 DB가 같은 시점이라는 보장은 하지 않는다. schedule HTTP 동안 snapshot/connection을 열지 않고, 그 뒤 최초 SQL부터 응답의 DB 자료만 같은 snapshot으로 읽는다. 인증과 업무 snapshot도 같은 시점이라는 주장을 하지 않는다. 새 engine/pool을 만들거나 DB/auth 구현을 바꾸지 않는다.

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
- 변경 API 9개 파일 strict mypy PASS, 변경 파일 Ruff PASS. 정본 Pydantic overlay로 all-profile OpenAPI check는 별도 종료 결과를 수용한다.

두 독립 리뷰·정확 CI 및 실제 운영 HTTP/UI 수용은 아직 미완이다.
