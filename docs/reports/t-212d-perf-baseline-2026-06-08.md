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
- `ops.dedup_review_queue`: `status, total_score DESC, review_key DESC`.
- `ops.enrichment_review_queue`: status score 인덱스 + provider filter score 인덱스.

### Query

- `/features/in-bounds`: 공간 후보를 `MATERIALIZED` CTE로 먼저 읽어 `coord` GiST 사용을 고정.
  기존 `ORDER BY feature_id`는 공간 인덱스 사용을 방해하고 API 계약상 순서 보장이 없어 제거했다.
- `/features/search`: `name % :q` 후보를 먼저 materialize해 `idx_features_name_trgm`을 사용한 뒤
  삭제/bbox/kind/category 필터와 score keyset을 적용한다. total count도 같은 q 전용 CTE를 사용한다.
- dedup/enrichment review list: cursor tie-breaker를 UUID `review_key` 그대로 비교하고 queue 후보를
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
- F8 검증용 `feature.feature_files`: 테스트 내부 임시 200건.

## EXPLAIN 검증 범위

- `/features/nearby`: `idx_features_coord_5179_gist` 또는 기존 spatial index.
- `/features/in-bounds`: `idx_features_coord_gist`.
- `/features/search`: `idx_features_name_trgm`.
- `/admin/features`: `idx_features_status_updated` 또는 `idx_features_updated_keyset`.
- `/ops/import-jobs`: `idx_import_jobs_state` 또는 `idx_import_jobs_created_keyset`.
- consistency reports/issues: `idx_reports_severity_started`,
  `idx_violations_provider_status_detected` 또는 `idx_violations_status_detected`.
- dedup/enrichment review list: `idx_dedup_status_score`,
  `idx_enrichment_review_provider_status_score` 또는 `idx_enrichment_review_status_score`.
- dedup refresh: source/provider dataset 또는 feature keyset index.
- consistency F4/F6/F7/F8: dedup score, opening-hours partial, source/feature primary indexes.

## 검증

- `ruff check` targeted: 통과.
- `pytest tests/integration/test_t212d_perf_explain.py -q --capture=no`: 4 passed.
- 관련 통합 테스트: 45 passed.
- 관련 단위 테스트: 44 passed (`--capture=no`; WSL env의 `TEMP/TMP`가 Windows Temp를 가리켜
  기본 capture 종료 단계에서 임시파일 오류가 발생해 capture를 껐다).

## 후속

T-212e에서 DB를 비운 뒤 live provider/offline upload full reload를 수행하고, 실제 row 수,
provider별 성공/실패/skip, Dagster run/import job id, consistency report id, Playwright 실스택
smoke, backup/restore smoke를 최종 리포트로 보강한다.
