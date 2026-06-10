# T-212d 성능 baseline 리포트 (2026-06-08)

## 요약

T-212d는 Sprint 5 운영 진입 전 DB/API hot path가 대량 데이터에서도 인덱스 친화적인지
확인하는 작업이다. 이번 PR은 실 provider full reload 전 단계이므로, 실제 로컬 DB를 먼저
확인한 뒤 성능 기준으로 부족한 부분은 seeded PostGIS/testcontainers로 재현 가능한 baseline을
만들었다.

- 로컬 live DB: alembic `0016`, `features/source_records/source_links/import_jobs` 각 1건,
  `consistency_reports`/`dedup_review_queue` 0건, `enrichment_review_queue` 없음.
- 결론: 현재 로컬 live DB는 planner baseline으로 부적합. 실제 운영 규모 측정은 T-212e
  live full reload에서 수행한다.
- 이번 baseline: 3,200 feature + source/link + ops/review live-like seed로 EXPLAIN JSON을
  통합 테스트에서 검증한다.

## 변경 사항

### DB schema

마이그레이션 `0020_t212d_perf_keyset_indexes`를 추가했다.

- `feature.features`: updated/status keyset, lower(name) keyset, opening-hours 후보 partial index.
- `ops.import_jobs`: created/state/kind keyset 인덱스. queue claim은 `queue_sequence`로
  `created_at` 동률에서도 FIFO 의미를 유지한다.
- `ops.feature_consistency_reports`: started/severity keyset 인덱스.
- `ops.data_integrity_violations`: status/provider/feature별 detected_at keyset 인덱스.
- `ops.dedup_review_queue`: `status, total_score DESC, review_id DESC`.
- `ops.enrichment_review_queue`: status score 인덱스 + provider filter score 인덱스.

### Query

- `/features/in-bounds`: 공간 후보를 `MATERIALIZED` CTE로 먼저 읽어 `coord` GiST 사용을 고정.
  `LIMIT` 초과 시 잘리는 subset이 흔들리지 않도록 후보 CTE 뒤 `feature_id ASC` 정렬은 유지한다.
- `/features/search`: `name % :q` 후보를 먼저 materialize해 `idx_features_name_trgm`을 사용한 뒤
  삭제/bbox/kind/category 필터와 score keyset을 적용한다. total count도 같은 q 전용 CTE를 사용한다.
- dedup/enrichment review list: cursor tie-breaker를 UUID `review_id` 그대로 비교하고 queue 후보를
  먼저 정렬한다.
- consistency F6: `detail ?| ARRAY['business_hours','opening_hours']`와 partial index로 후보 범위를
  줄인다.
- consistency F7: pending dedup 후보를 score keyset CTE로 먼저 고정한다.

## 테스트 데이터

`tests/integration/test_t212d_perf_explain.py`가 다음 분포를 seed한다.

- `feature.features`: 3,200건. 서울/부산/제주 좌표, place/event/weather, active/inactive,
  `광화문`/`해운대`/`제주` 계열 이름, opening-hours detail 혼합.
- `provider_sync.source_records/source_links`: 각 3,200건. MOIS, datagokr, visitkorea,
  opinet, krheritage provider/dataset 분포.
- `ops.import_jobs`: 900건. queued/running/failed, kind 분포.
- `ops.feature_consistency_reports`: 600건.
- `ops.data_integrity_violations`: 900건.
- `ops.dedup_review_queue`: 500건.
- `ops.enrichment_review_queue`: 500건, provider 3종 분포.
- F8 검증용 `feature.feature_files`: 테스트 내부 임시 200건. 실제 Alembic 테이블은 아직 없으며,
  첫 파일 업로드 PR 전까지는 F8 실행 계획 형태 검증용 임시 DDL이다.

## EXPLAIN 검증 범위

- `/features/nearby`: `idx_features_coord_5179_gist` 또는 기존 spatial index.
- `/features/in-bounds`: `idx_features_coord_gist`.
- `/features/search`: `idx_features_name_trgm`.
- `/admin/features`: `idx_features_status_updated` 또는 `idx_features_updated_keyset`.
  `sort=name`은 `idx_features_lower_name_keyset`을 별도 검증한다.
- `/ops/import-jobs`: `idx_import_jobs_state` 또는 `idx_import_jobs_created_keyset`.
- consistency reports/issues: `idx_reports_severity_started`,
  `idx_violations_provider_status_detected` 또는 `idx_violations_status_detected`.
- dedup/enrichment review list: `idx_dedup_status_score`,
  `idx_enrichment_review_provider_status_score` 또는 `idx_enrichment_review_status_score`.
- dedup refresh: source/provider dataset 또는 feature keyset index.
- consistency F4/F6/F7/F8: dedup score, opening-hours partial, source/feature primary indexes.
- 대표 hot path는 `enable_seqscan=off` 없이도 base table `Seq Scan`을 선택하지 않는지 확인한다.
- dedup/enrichment review cursor는 첫 두 page disjoint만 보지 않고 끝까지 순회해 전체 정렬셋과
  1:1로 맞는지 확인한다.

## 검증

- `ruff check .`: 통과.
- `mypy src/krtour/map`: 85 source files 통과.
- `lint-imports`: 4 contracts kept.
- `pytest tests/integration/test_t212d_perf_explain.py -q --capture=no`: 5 passed.
- `pytest tests/integration/test_feature_repo_load.py::test_features_in_bbox_returns_stable_feature_id_subset -q --capture=no`:
  1 passed.

## 유의 사항

- `tests/integration/test_t212d_perf_explain.py`의 대부분 EXPLAIN은 인덱스 적격성 회귀를 잡기
  위해 `enable_seqscan=off`를 사용한다. 후속 리뷰 반영으로 대표 bbox/admin-name sort 경로는
  seqscan hint 없이도 base table `Seq Scan`이 없는지 추가 검증한다.
- 마이그레이션 `0020`의 `CREATE INDEX`는 Alembic transaction 안의 일반 DDL이다. T-212e처럼
  DB를 비우고 reload하는 경로에서는 무해하지만, 데이터가 있는 운영 DB에 적용하면 쓰기 잠금이
  생길 수 있다.
- `idx_import_jobs_state(state, created_at, queue_sequence)`는 queue claim FIFO에 맞춘 인덱스다.
  import job 목록의 keyset tie-breaker는 `job_id`이므로 대량 운영 데이터에서 state 필터 목록
  EXPLAIN을 다시 확인한다.

## 후속

T-212e에서 DB를 비운 뒤 live provider/offline upload full reload를 수행하고, 실제 row 수,
provider별 성공/실패/skip, Dagster run/import job id, consistency report id, Playwright 실스택
smoke, backup/restore smoke를 최종 리포트로 보강한다.
