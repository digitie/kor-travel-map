# ADR-016: Record Linkage 가중치 0.45/0.35/0.20 + 임계값 0.85/0.65

- **상태**: accepted
- **날짜**: 2026-05-24
- **결정자**: 사용자 (SPEC V8 D-14)
- **컨텍스트**: 같은 장소가 여러 provider에서 다른 이름/좌표로 올라온다.
  자동 병합 vs 수동 검토 임계값이 필요.
- **결정**:
  - Blocking: `ST_DWithin(coord::geography, 100)` + 같은 `bjd_code` + 같은 `kind`
  - Scoring: `0.45 * name_sim + 0.35 * spatial_sim + 0.20 * category_sim`
    - name_sim: `jellyfish.jaro_winkler_similarity(normalize_kr_place_name(a), ...)`
    - spatial_sim: `math.exp(-haversine_m / 50.0)`
    - category_sim: Jaccard on category tag set
  - 임계값: `THRESHOLD_AUTO=0.85` (자동 병합), `THRESHOLD_MANUAL=0.65`
    (수동 검토 큐 `dedup_review_queue`).
  - 마스터 선정: (1) 좌표 정밀도 → (2) `updated_at` 최신 → (3) `source_type`
    우선순위 (행안부 > TourAPI > 사용자 등록).
  - `feature_merge_history(loser_id, master_id, score, merged_at)` 보존.
- **근거**: SPEC V8 D-14.
- **결과 (긍정)**: 자동/수동 흐름 명확. 운영자가 임계값 조정 가능.
- **결과 (부정)**: 가중치는 도메인 지식 기반 추정 — 운영 데이터로 재조정
  필요 시 ADR superseded.
- **후속**: `core/scoring.py`에 함수 박힘. 통합 테스트에 명시적 케이스.
