# T-212d read-heavy 재측정 리포트 (2026-06-10)

## 요약

사용자 지시에 따라 T-216f/g와 TripMate-agent provider 반영 후, read가 압도적으로 많은
운영 전제를 두고 T-212d hot read baseline을 다시 확인했다. 결론은 다음과 같다.

- 클러스터 hot path(`_cluster_bbox_sql`) EXPLAIN 회귀를 새로 추가했다.
- seeded PostGIS 기준 `sido`/`sigungu`/`eupmyeondong` 클러스터는 기존 exact-viewport
  의미를 유지한 채 `idx_features_coord_gist`를 사용한다.
- `mv_feature_cluster_counts`는 이번 PR에서 도입하지 않는다. 현재 API는 viewport bbox 안의
  feature만 세고 그 부분집합의 평균 좌표를 반환하지만, rollup MV는 region-total count와
  region centroid로 의미가 바뀐다. 이 의미 변경은 T-212e live full reload의 실제 row 수와
  P99 측정 뒤 별도 ADR/PR에서 결정한다.
- enrichment review 목록은 단일 `status + provider` 필터에서 `ANY(array)` 때문에 planner가
  composite score index를 안정적으로 선택하지 않는 문제가 있었다. 단일 값 fast path를
  scalar equality SQL로 분리하고, join 전 CTE에 `LIMIT`을 적용해 read work를 줄였다.

## 코드 변경

- `src/kortravelmap/infra/admin_feature_repo.py`
  - enrichment review 목록 SQL을 status/provider 필터 조합별로 분리했다.
  - 단일 `status + provider` 조합은 `q.status = :status`와
    `q.source_provider = :provider`를 사용해
    `idx_enrichment_review_provider_status_score`의 leading column과 정렬축을 맞춘다.
  - review queue 후보 CTE 안에 `LIMIT :limit_plus_one`을 넣어 feature join 전에 후보 수를
    page 크기로 줄인다.
- `tests/integration/test_t212d_perf_explain.py`
  - 클러스터 hot path EXPLAIN 테스트를 추가했다.
  - 단일 provider enrichment 경로는 composite index 이름까지 고정한다.
  - 다중 provider 경로는 `ANY(array)` 특성을 고려해 base table seq scan이 없는지만 검증한다.

## MV 판단

`feature.mv_feature_cluster_counts`는 read-heavy 환경의 1순위 MV 후보로 계속 유지한다. 다만
이번 seeded 재측정에서는 다음 이유로 보류했다.

- 현재 exact-viewport 클러스터 쿼리는 PostGIS GIST 인덱스를 탄다.
- MV는 임의 viewport를 정확히 사전계산할 수 없고, region-total rollup으로 바뀐다.
- edge region count 과대계상과 centroid 의미 변경이 API 관찰 결과에 드러난다.
- 아직 live provider/offline upload full reload row 수와 P99가 없다.

따라서 이번 PR의 결론은 **MV 미도입 + EXPLAIN 회귀 확대 + enrichment read path 튜닝**이다.
T-212e에서 실데이터 full reload 후 row 수, query latency, `pg_stat_statements`/EXPLAIN 결과를
보고 MV 도입 ADR을 다시 판단한다.

## 검증

```bash
/home/digitie/dev/kor-travel-map/.venv/bin/python -m compileall -q \
  src/kortravelmap/infra/admin_feature_repo.py \
  tests/integration/test_t212d_perf_explain.py

/home/digitie/dev/kor-travel-map/.venv/bin/python -m pytest -s \
  tests/integration/test_t212d_perf_explain.py -q
```

결과: `6 passed`.
