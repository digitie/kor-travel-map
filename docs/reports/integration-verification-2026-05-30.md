# 통합 검증 종합 리포트 — Sprint 2~3 marathon (2026-05-30)

- **작성**: Claude (claude worktree). **범위**: 사용자 지시 "etl 로직 live test →
  데이터 유입·정합성·DB 적재·debug UI 검증 + 상세 리포트"의 마무리 인덱스 +
  Sprint 3 종료 시점(2026-05-30)까지 누적된 검증 결과 정리.
- **본 문서에는 API 키 값을 절대 기재하지 않는다** (키 이름·마스킹만, ADR-005).
- **연계 작업 ID**: #115(ETL live 수집/검증) · #116(DB 적재 통합 테스트) ·
  #117(Debug UI WSL 기동 + Windows Playwright e2e) · #118(통합 검증 리포트).

본 리포트는 세 개의 개별 리포트를 인덱싱하고 누적 결과를 한 화면에서 검수할
수 있게 한다 — 세부 증거는 각 sub-report 참조.

---

## 0. 요약 (Sprint 4 진입 readiness)

| 영역 | 결과 | 증거 |
|------|------|------|
| ETL provider → DTO 변환 (live) | ✅ 11/11 dataset 변환 동작 (9건 fully OK, 2건 krex 부분 — upstream EX endpoint 이슈) | `etl-live-verification-2026-05-28.md` |
| DB 적재 (testcontainers PostGIS) | ✅ FeatureBundle round-trip + STORED `coord_5179` + JSONB + FK / `ops.dedup_review_queue` 적재 + 검토완료 행 보존 / consistency F1~F3 | `tests/integration/test_*.py` + 본 리포트 §3 |
| Debug UI backend (WSL :8087) | ✅ health/version/ETL providers/ETL fixture preview 실 HTTP 통과 | `debug-ui-e2e-2026-05-29.md` §2 |
| Debug UI frontend (WSL :8610) | ✅ npm workspace 루트 확립 → `next dev` 정상 (PR#92) + maki 글리프·16색 팔레트 공통 마커(PR#97) + kind 필터·상세 패널(PR#98) | `debug-ui-e2e-2026-05-29.md` §1 + 본 리포트 §4 |
| Windows Playwright e2e | ✅ **11/11 통과** (home 4 + etl 3 + features 4) — WSL frontend↔backend 실연동 | 본 리포트 §4 + 자체 spec(`packages/krtour-map-admin/frontend/e2e/*.spec.ts`) |
| frontend CI 게이트 | ✅ `type-check` + `next build` (PR#93). 잠복 syntax(`*/`) 버그 같은 종류 머지 전 차단 | `.github/workflows/frontend.yml` |
| Coverage bar | ✅ Sprint 3 bar 75 ☑ (`pyproject.toml fail_under=75`, 실측 92.66%) | PR#96 |

**Sprint 4 진입 차단 요인 없음.** 잔여는 사람 조치 항목 2건(§5).

---

## 1. ETL live 검증 (#115)

세부: `etl-live-verification-2026-05-28.md`. 본 항목은 그 후 변동만 부연.

- 결과 표(11/11) 변동 없음 (9 fully OK + 2 krex 부분 — `curStateStation` 필드
  불일치로 식음료/주유가격 0건, rest_areas/weather 정상).
- 키 이름 drift 정정(PR#60) + apihub fallback(PR#58) 후 추가 회귀 없음.
- 후속 잠재 PR — **krex EX endpoint 정정**: data.ex.co.kr `introduce02` 기준 신
  endpoint를 python-krex-api에 반영 → 본 lib `providers/krex.py` 매핑 + debug-ui
  loader. 본 lib 측은 사양 변경 시 즉시 흡수 가능 (변환기 구조 안정).

---

## 2. DB 적재 통합 테스트 (#116) — testcontainers PostGIS

본 sprint(3)에서 **Phase 1 적재 경로 + dedup 큐 + 오케스트레이션**까지 통합
테스트 그린.

| 테스트 | 검증 | PR |
|--------|------|----|
| `tests/integration/test_feature_bundle_persist.py` | FeatureBundle → ORM round-trip / JSONB / `coord_5179` STORED / source_link FK | PR#67 |
| `tests/integration/test_feature_repo_load.py` | `infra/feature_repo` raw SQL 3-table upsert(features + source_records + source_links), idempotent, ON CONFLICT | (#116 후속) |
| `tests/integration/test_consistency_reports.py` | F1(orphan source_record) / F2(detail 누락) / F3(CRS drift) 검출 + `ops.feature_consistency_reports` 적재 | (Sprint 3 §2.3) |
| `tests/integration/test_dedup_repo.py` (5건) | `ops.dedup_review_queue` upsert + 점수 0~100 변환 + 검토완료 행 보존(`DO UPDATE WHERE status='pending'`) + FK CASCADE | PR#88 |
| `tests/integration/test_client_orchestration.py` (3건) | `AsyncKrtourMapClient` transaction 소유 + `load_feature_bundles` commit / `sync_dedup_candidates` end-to-end / `include_auto_merge` 패스스루 | PR#89 |
| `tests/integration/test_alembic_upgrade.py` | 0001~0005 모든 migration upgrade head 성공 | PR#88 |

**총 integration 13건 + dedup repo 5건 + client 3건 + alembic 6건 = 27건** (실 PostGIS 컨테이너 자동 부팅) **모두 통과.**

`ops.dedup_review_queue` 첫 운영 안정성: knps 사찰 ↔ krheritage temple 시나리오로 unit 6 + integration 5 + e2e of client 3 = 14건. SPRINT-3 §6 "dedup_review_queue 첫 운영 시작 (룰 안정 확인)" ☑.

---

## 3. Debug UI backend 라이브 (#117 1단계)

`debug-ui-e2e-2026-05-29.md` §2 — 실 HTTP 5경로 통과 (health/version/ETL providers 11 dataset/fixture preview ×2). 본 리포트와 중복 인용은 생략.

---

## 4. Frontend WSL 기동 + Windows Playwright e2e (#117 2단계)

세부: `debug-ui-e2e-2026-05-29.md` §3~5. 본 항목은 그 후 변동(PR#95~#98) 반영.

### 4.1 환경 (재확인)
- backend WSL `0.0.0.0:8087` (`uvicorn`) + frontend WSL `0.0.0.0:8610` (`next dev`).
  Windows `127.0.0.1:8610`/`:8087`은 WSL2 localhost forwarding으로 도달.
- Windows-side `.e2e-win/`(gitignored) — `@playwright/test` 1.60.0 + chromium 캐시.
  스펙은 frontend/e2e/*.spec.ts 커밋본을 런타임 복사(node_modules 플랫폼 충돌 회피).

### 4.2 e2e 결과 — **11/11 통과 (PR#98 시점)**

```
Running 11 tests using 3 workers
  ok 1 home.spec.ts → 타이틀 + ETL 내비 링크 렌더
  ok 2 home.spec.ts → Backend health 섹션이 live /debug/health 결과(status ok)를 표시
  ok 3 home.spec.ts → Versions 섹션이 live /debug/version 결과를 표시
  ok 4 home.spec.ts → Zustand viewport 데모 버튼 동작 (클라이언트 상태)
  ok 5 etl.spec.ts  → provider 목록 로드 + krex_rest_areas fixture preview 실행
  ok 6 etl.spec.ts  → provider 드롭다운에 4개 provider가 모두 있음
  ok 7 etl.spec.ts  → datagokr 축제 fixture preview → event FeatureBundle
  ok 8 features.spec.ts → 페이지 렌더 + 지도 컨테이너 + 헤더 상태
  ok 9 features.spec.ts → 홈에서 → Feature 지도 링크로 이동
  ok 10 features.spec.ts → kind 필터 — 칩 7종 + 토글 + 초기화
  ok 11 features.spec.ts → 선택 안 했을 때 상세 패널은 안 보임
  11 passed
```

PR#91→#92(7/7) → PR#95(9/9, /features 도입) → PR#98(11/11, kind 필터 +
상세 패널).

### 4.3 검출 + 수정한 실 버그(누적)
- **etl/page.tsx 잠복 빌드 버그**(PR#92) — JSDoc 주석 안의 `*/`(블록 주석 조기
  종료)로 PR#44부터 frontend가 컴파일 자체 불가였음(node_modules 미설치
  환경에서 미검출). 라이브 e2e 첫 실행이 검출. 주석 수정 + frontend CI
  게이트(PR#93)로 재발 차단.

### 4.4 NTFS / WSL 운영 노트
- `/mnt/f`(NTFS) inotify의 hot-reload는 신뢰성 낮아 소스 수정 후엔 `rm -rf .next`
  + `next dev` 재시작이 필요한 경우가 있음 (리포트 §5 런북 반영).

---

## 5. 사람 조치 항목 (잔여)

코드/테스트로 해결할 수 없는 외부 의존성 2건:

1. **apihub 활용신청** (`apihub.kma.go.kr`) — 사용자 제공 키 `gagX***Qi`는 인증
   유효하나 사용 API 미신청 상태(403 "활용신청이 필요한 API"). KMA 소스 정책은
   data.go.kr이 primary이므로 본 lib 자체 운영엔 영향 없음. apihub fallback이
   필요한 운영 시나리오(특보 structured regions 등) 진입 시점에 신청.
2. **krex(EX) endpoint 정정** — `data.ex.co.kr/openapi/intro/introduce02` JS
   렌더라 자동 추출 불가. 사람이 신 endpoint 확인 → **python-krex-api** 카탈로그
   /client 정정 → 본 lib `providers/krex.py` 매핑 + debug-ui loader 반영. 본
   lib 측 변환기 구조 안정 → upstream 변경 시 즉시 흡수 가능.

---

## 6. Sprint 4 진입 readiness

- ✅ 모든 SPRINT-3 §6 종료 조건 충족 (PR#96에 표기).
- ✅ Coverage bar 75 (실측 92.66%).
- ✅ ADR-033 Phase 1 + `ops.dedup_review_queue` + `AsyncKrtourMapClient` 안정.
- ✅ Frontend & e2e 인프라(workspace + CI 게이트 + e2e 11/11).
- ✅ 4a/4b 분할 채택 결정(`SPRINT-4.md §3`).

**Sprint 4 진입 차단 요인 없음** — 다음 작업은 `SPRINT-4.md §2.1` Step A bulk
MOIS provider 모듈(`providers/mois.py`)이다.

---

## 7. 변경 일지 (본 통합 검증 marathon)

| PR | 영역 | 내용 |
|----|------|------|
| #58~#65 | ETL live | apihub fallback + 11/11 dataset live 동작 + report 초안 |
| #67 | DB | `test_feature_bundle_persist.py` + `migrated_engine/session` fixture |
| #67~#76 | infra | `feature_repo.py` + alembic 0001~0004 + ADR-033 Phase 1 + consistency |
| #87 (#121) | core | `find_dedup_candidates` 순수 함수 |
| #88 (#122) | infra/DB | `ops.dedup_review_queue` + `dedup_repo.py` (alembic 0005) |
| #89 (#122) | client | `AsyncKrtourMapClient` 오케스트레이터 |
| #90 (#123) | data 통로 | geocoding python API → REST API v2 전환 |
| #91 (#117) | e2e/report | Playwright 스위트 + backend 라이브 검증 리포트 |
| #92 (#117) | e2e/infra | npm workspace 루트 + WSL 기동 + e2e 7/7 + 🐞 fix |
| #93 (a) | CI | frontend type-check + next build 게이트 |
| #94 (b) | docs | CHANGELOG + journal + resume + address-geocoding REST |
| #95 (c) | frontend | `/features` 지도 페이지 + e2e 9/9 |
| #96 (sprint prep) | governance | Sprint 3 종료 + Sprint 4 4a/4b 분할 |
| #97 | marker | `@krtour/map-marker-react` 실제 구현(maki + 팔레트 + factory) |
| #98 | frontend UX | kind 필터 + 상세 패널 + e2e 11/11 |
| **#118**(본 리포트) | 검증 인덱스 | 본 문서 |
