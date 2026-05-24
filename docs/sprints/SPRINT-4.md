# SPRINT-4.md — MOIS 인허가 bulk + dedup queue 운영

> **상태**: proposed (Sprint 3 종료 후 Sprint 4 진입 PR로 accepted 전환)
>
> **목적**: ADR-034 9단계의 ⑦ — `python-mois-api` 인허가 4단계 lifecycle
> 적재. 가장 큰 bulk + 195 슬러그 + PROMOTED 42 분류 + dedup_review_queue
> 본격 운영. Coverage 80% 도달 (ADR-032 목표치).

## 1. 진입 조건 (Sprint 3 DoD)

- [ ] Sprint 3 모든 DoD 충족 (`SPRINT-3.md §6`)
- [ ] knps + krheritage 적재 안정, area/route geometry 처리 동작
- [ ] ADR-033 Phase 1 (F1~F3) 정합성 검증 green + 일 1회 report 생성
- [ ] dedup_review_queue 첫 운영 (knps cultural_resources vs krheritage
      temple) 룰 안정
- [ ] Coverage bar 75% pass
- [ ] Sprint 4 분할 여부 (4a/4b) 결정 — Sprint 3 종료 회고에서

## 2. 산출물

### 2.1 Provider ⑦ — MOIS 인허가 (`python-mois-api`) — 4단계 lifecycle

`docs/mois-feature-etl.md` 사양 그대로 구현.

**Step A — Bulk full snapshot** (`mois_license_features_bulk`):
- 195 슬러그 중 PROMOTED 42종만 feature로 승격, 나머지는 raw + `EXCLUDED`
  reason 표기.
- `psycopg.copy_*` 안전 마진 30k (ADR-013) — 195 슬러그 × 시군구 다수 =
  수십만~수백만 row.
- BRIN 인덱스 `source_records.imported_at` 활용.
- KASI 영업주기 정보로 `valid_start_time`/`valid_end_time` 갱신.

**Step B — Incremental history** (`mois_license_features_history`):
- 일 1회 cron — 신규/변경 인허가만 추출.
- `ProviderSyncState.cursor.last_modified_date` 운영.

**Step C — Closed/cancelled** (`mois_license_features_closed`):
- 일 1회 cron — `license_status='closed'`/`'cancelled'`로 변경된 feature는
  `Feature.status='inactive'`로 update.
- ADR-017 보관 정책: place는 무기한 유지 (status만 inactive로).

**Step D — On-demand detail** (`mois_license_detail`):
- 디버그 UI에서 사용자 명시 트리거 (캐시만, 적재 X).
- Sprint 4 시점에 라우터 `/debug/mois-license/{license_id}` 추가.

**module**: `src/krtour/map/providers/mois.py` (`__init__.py`로 namespace
package), `_steps.py` (4단계), `_slugs.py` (195 슬러그 + PROMOTED 42 분류),
`_address.py` (admin_address parsing).

**fixture (≥ 15)**: PROMOTED 42 슬러그 중 대표 카테고리별 1건 + EXCLUDED
3건 + closed/cancelled 2건 + Step B incremental 2건.

### 2.2 dedup_review_queue 운영 시작

- MOIS는 자기 자신 안에서 sibling 가능 (예: 같은 사업장이 2개 슬러그로
  중복 등록).
- Record Linkage scoring (ADR-016, Sprint 2 검증된 룰) 본격 가동.
- queue size 수만~수십만 건 예상 → 디버그 UI `/dedup-review` 라우터 추가
  + 운영자 검토 UI.

### 2.3 ADR-033 F4 부분 적용

- F4 (`dedup_review_queue` 미해소 N건 초과) — severity=WARN.
- threshold 결정: MOIS 첫 적재 시 dedup 후보 수 측정 후 50%를 초과하면
  WARN. Sprint 4 후반에 baseline 조정.

### 2.4 `ops.import_jobs` advisory lock + SKIP LOCKED (ADR-011)

- MOIS bulk가 다중 worker로 적재될 때 race condition 방지.
- Step A는 단일 worker로만 (advisory lock), Step B/C는 다중 worker 가능.

### 2.5 Coverage 80% 도달 (ADR-032 목표치)

- 전체 80% / core 90% / providers 70% / infra/client/api 80% / dto 100%
- Sprint 4가 ADR-032 목표치 도달 sprint. Sprint 5는 유지 + 회귀 방지만.

### 2.6 디버그 UI 라우터 확장

- `/dedup-review` (GET pending, PATCH accept/reject/merged)
- `/integrity-violations` (F1~F4 report 조회)
- `/import-jobs` (GET/POST/PATCH)
- `/providers/{name}/sync-state` (GET ProviderSyncState)

### 2.7 Place phone enrichment 시작 (백그라운드)

- Sprint 4 끝 무렵에 `place_phone_enrichment` 도입.
- 후보 dataset: MOIS PROMOTED place 중 전화번호 없는 feature.
- 후보 source: kakao-local-api / naver-search-api / google-places-api-new.
- Google Places는 `PLACE_PHONE_MAX_CANDIDATES=3` 제한 (`external-apis.md
  §8`).
- 결과는 `Feature.phone` 갱신 + `source_links(role='enrichment')`.

## 3. Sprint 4 분할 옵션 (Sprint 3 종료 회고에서 결정)

분할 시 (4a/4b):
- **Sprint 4a** — Step A (bulk) + Step B (incremental) + dedup_review_queue
  운영 시작. Coverage 80% 부분 달성.
- **Sprint 4b** — Step C (closed) + Step D (detail) + F4 baseline + Place
  phone enrichment 백그라운드. Coverage 80% 완전 달성.

분할 결정 기준: Sprint 3 종료 시 burndown 진척도. MOIS 4단계 한 sprint 안에
들어가면 risk 큼 → 보수적으로 4a/4b 분할 권고.

## 4. Sprint 4 ADR/T 항목 진척

| 항목 | 상태 (진입 시) | DoD (Sprint 4 종료) |
|------|---------------|---------------------|
| ADR-013 (bulk insert 30k) | accepted | MOIS Step A 안전 마진 검증 |
| ADR-016 (Record Linkage) | accepted | MOIS bulk에서 본격 검증, 가중치 조정 PR (필요 시) |
| ADR-024 (mois canonical name) | accepted | provider 이름 / dataset_key / migration 일치 |
| ADR-011 (advisory lock) | accepted | MOIS Step A 단일 worker 검증 |
| ADR-033 (Phase 1 F4 부분) | accepted (Sprint 3) | F4 baseline + WARN 동작 |

## 5. 비목표 (Sprint 4)

- 휴양림/수목원 (Sprint 5)
- 박물관/미술관 + `data.go.kr-standard` (Sprint 5)
- Phase 2 F5~F8 + Dagster 게이트 (Sprint 5)
- T-200 batch DAG (Sprint 5)
- T-202~204 pre-commit/CI/branch protection (Sprint 5)

## 6. 위험 / 차단 사유

- **MOIS bulk 적재 시간**: 195 슬러그 × 시군구 다수 = 수십만~수백만 row.
  단일 worker (advisory lock) 적재가 수시간 ~ 일 단위 소요 가능. 첫 적재는
  off-peak (KST 새벽).
- **dedup_review_queue 폭증**: MOIS 자체 sibling만 해도 수만 건 예상.
  Sprint 3에서 검증한 룰이 large dataset에서 false positive율 측정 필요.
  필요 시 가중치 조정 PR (ADR-016 supersede).
- **MOIS provider rate limit**: `python-mois-api` 호출 분당 한도 (provider
  ADR 참조). bulk 적재는 cursor 기반 page-by-page.
- **address 정규화 실패율**: PROMOTED 슬러그 중 일부는 admin_address
  format 깨짐 — `_address.py` fallback 처리.

## 7. 종료 조건 (Sprint 4 → Sprint 5)

- [ ] MOIS Step A/B/C/D 모두 적재 안정 (또는 4a/4b 분할 시 4b 종료 시점)
- [ ] PROMOTED 42 슬러그 카테고리 매핑 정확
- [ ] dedup_review_queue 운영 안정 + F4 WARN baseline 결정
- [ ] Coverage bar 80% pass (목표치 도달, ADR-032)
- [ ] Place phone enrichment 백그라운드 가동
- [ ] `docs/journal.md` Sprint 4 종료 회고 entry
- [ ] `docs/sprints/SPRINT-5.md` 진입 PR 준비
