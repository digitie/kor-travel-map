# T-201b Phase 2 consistency dry-run report

## 실행 정보

- 생성 시각: `2026-06-06T17:51:26.033389+09:00`
- 모드: `dry-run`
- batch_id: `bd9b6a94-dc03-400e-935e-fbad0bc316cb`
- severity_max: `OK`
- total_violations: `0`
- cases_evaluated: `8`
- sample_limit: `20`
- F4 dedup pending threshold: `1000`
- F5 provider SLA seconds: `86400`
- F7 score regression warn points: `10`
- F8 object snapshot: `not provided`

## 케이스 요약

| code | effective severity | configured severity | count | description |
|------|--------------------|---------------------|-------|-------------|
| F1 | OK | ERROR | 0 | orphan source_record (source_links 없음 — ETL transform 누수) |
| F2 | OK | ERROR | 0 | detail 누락 (detail-bearing kind인데 detail JSONB 비어있음, ADR-018) |
| F3 | OK | ERROR | 0 | CRS drift (coord_5179 ≠ ST_Transform(coord,5179), ADR-012) |
| F6 | OK | ERROR | 0 | opening_hours 모순 (같은 요일 period에서 open.time > close.time, ADR-019) |
| F4 | OK | WARN | 0 | dedup_review_queue 미해소(pending) 백로그 baseline 1000 초과 (현재 0, ADR-033 F4 — observe-only) |
| F5 | OK | WARN | 0 | provider_sync_state active cursor last_success SLA 초과 (기본 86400s, provider policy interval 우선, ADR-033 F5) |
| F7 | OK | WARN | 0 | cross-provider dedup score baseline 대비 현재 score 회귀 (10점 이상 하락, ADR-033 F7) |
| F8 | OK | WARN | 0 | file object orphan (feature_files metadata ↔ 객체 저장소 스냅샷 불일치, ADR-033 F8) |

## 샘플

### F1

-

### F2

-

### F3

-

### F6

-

### F4

-

### F5

-

### F7

-

### F8

-

## 판정

- `ERROR` 위반은 없다. 실제 gate에서는 OK/WARN이면 다음 단계로 진행 가능하다.
