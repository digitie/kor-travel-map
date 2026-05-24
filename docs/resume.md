# resume.md — 현재 진척도와 다음 한 작업

## 현재 상태

**v2 설계 단계**. main은 orphan으로 새로 시작. v1은 `v1` 브랜치에 보존.
**코드 작성 금지** — 사용자의 별도 요청이 있을 때까지 본 저장소는 문서/계약/결정의
저장소다.

**중요 신규 룰 (ADR-021~023, 2026-05-24)**:
- main 직접 push 금지 — feature branch + PR만 (ADR-021).
- Python import는 `from krtour.map import ...` (`krtour_map` flat 금지, ADR-022).
- Category 모듈은 `krtour.map.category` (kraddr-base에서 이전, ADR-023).

스택 확정 (ADR-007):
- PostgreSQL 16 + PostGIS 3.5 + pg_trgm + pgcrypto
- SQLAlchemy 2.x async + GeoAlchemy2 + asyncpg + psycopg[binary,pool]>=3.2
- GeoPandas + Shapely 2 + GDAL
- Pydantic v2 / FastAPI + Uvicorn / httpx + tenacity / Alembic

TripMate 연계 (ADR-003): 함수 직접 호출. REST 없음. 디버그 REST/UI는 별도
Python 패키지 `krtour-map-debug-ui` (ADR-020, `packages/krtour-map-debug-ui/`,
인증 없음 + 내부망 전용 ADR-005).

## 다음 한 작업

**PR#2 검토 + merge 후 다음 backlog**:
- T-200/T-201 (Sprint 5 운영 진입 직전 — batch DAG + consistency_reports)
- ADR-020~024 후속 (캐시 전략, OpenAPI 정책 등)
- **코드 작성 단계 진입 결정** — 사용자 승인 후 별도 PR로 시작.

## 진척도

### 핵심 governance / 결정

- [x] `AGENTS.md` (지시 우선순위, DO NOT 룰, TripMate 경계)
- [x] `README.md` (정체성, 빠른 시작, 문서 지도)
- [x] `SKILL.md` (DO NOT, 자주 묻는 작업, 도메인 어휘)
- [x] `CLAUDE.md` (1쪽 진입 요약)
- [x] `LICENSE` (GPL-3.0-or-later)
- [x] `.gitignore`, `.gitattributes`, `.env.example`
- [x] `pyproject.toml` (스택 + import-linter 계약 placeholder)
- [x] `docs/architecture.md` (의존 방향 + 데이터 흐름 + 모듈 표)
- [x] `docs/decisions.md` (ADR-001 ~ ADR-019)
- [x] `docs/data-model.md` (전체 table + 인덱스 + CHECK)
- [x] `docs/performance.md` (인덱스 + 공간 쿼리 + bulk + 안티패턴)
- [x] `docs/test-strategy.md` (4단계 테스트 + Coverage + EXPLAIN 검증)
- [x] `docs/backend-package.md` (라이브러리 API + 디버그 REST)
- [x] `docs/agent-guide.md` (첫 5분 + 체크리스트)
- [x] `docs/dev-environment.md` (WSL ext4/NTFS)
- [x] `docs/windows-reinstall-recovery.md` (세션 복구)
- [x] `docs/feature-model.md` (Feature DTO + detail 7 kind)
- [x] `docs/provider-contract.md` (wrapper 금지 + 카탈로그)
- [x] `docs/external-apis.md` (API 키 발급/호출)
- [x] `docs/tasks.md` (백로그)
- [x] `docs/resume.md` (본 문서)
- [x] `docs/journal.md` (작업 일지)
- [x] `docs/debug-ui-package.md` (ADR-020에 따른 별도 패키지 사양)
- [x] `packages/krtour-map-debug-ui/` (별도 패키지 skeleton — pyproject + README)
- [x] ADR-021 (PR-only) + `docs/agent-guide.md` §7.5 (PR 워크플로 + commit format)
- [x] ADR-022 (`krtour` implicit namespace) + 전 docs/pyproject 일괄 rename
- [x] ADR-023 (kraddr-base category 이전) + `docs/category.md` 신설

### v1 → v2 도큐먼트 이관 (2026-05-24 완료)

- [x] T-002 `docs/weather-feature-normalization.md`
- [x] T-003 `docs/feature-files-rustfs.md`
- [x] T-004 `docs/feature-opening-hours.md`
- [x] T-005 `docs/kraddr-base-types.md` + `docs/address-geocoding.md`
- [x] T-006 provider별 ETL 문서 10건 (event/mois-license/opinet/khoa/krheritage/forest/
      krex-rest-area/standard-data/notice/kma-weather/place-phone-enrichment)
- [x] **ADR-024** + `docs/mois-feature-etl.md` 신설 — `python-mois-api` full lifecycle
      (Step A/B/C/D), 195 슬러그 카탈로그, PROMOTED 42종 + EXCLUDED 분류
- [x] 일괄 rename `krmois` → `mois` (canonical name 정정, ADR-024)
- [x] **ADR-025** — 디버그 UI frontend `maplibre-vworld-js` 채택
- [x] `docs/debug-ui-package.md` §14 frontend 사양 + `packages/krtour-map-debug-ui/frontend/`
      skeleton (package.json / .env.example / .gitignore / README)
- [x] **ADR-025 사용자 보강 (2026-05-25)** — VWorld key는
      `KRADDR_GEO_VWORLD_API_KEY` 공유 / 별도 발급 금지 / maplibre-vworld-js
      upstream에 직접 PR로 적극 수정
- [x] **ADR-026** — TripMate 사용자 UI도 `maplibre-vworld` 채택 (SPEC V8 v8_3
      supersede), Kakao Maps JS SDK 제거
- [x] T-007 `docs/dagster-boundary.md`
- [x] T-008 `docs/postgres-schema.md`
- [x] T-009 `docs/debug-fixture-workflow.md`
- [x] T-010 `docs/feature-db-initialization.md`
- [x] T-011 `docs/tripmate-integration.md`

### 코드 작성 단계 진입 전

- [ ] T-012 ADR-020+ 후속 결정 (proposed 4건 — PR#10에서 코드 박힘 + 사용자
      review 후 accepted 전환)
- [x] T-013 `CHANGELOG.md` 초기 엔트리 정리 — PR#10 merged
- [ ] T-014 코드 작성 단계 진입 검토 (사용자 승인 후, Sprint 1 PR로 진입)
  - **Sprint 1 plan** (`docs/sprints/SPRINT-1.md`) — PR#10 merged (provider
    없음 명확화는 본 PR#14)
  - **Sprint 2~5 plan** (`docs/sprints/SPRINT-2.md` ~ `SPRINT-5.md`) —
    **본 PR#14**에서 ADR-034 9단계 순서로 박음
- [x] T-017c ADR-029 npm 패키지 추출 — PR#10 merged (skeleton). 실 코드는
      Sprint 2.
- [x] T-018a `python-knps-api` provider — PR#12 merged (ADR-028 +
      `docs/knps-feature-etl.md`). 외부 repo scaffold `6e36990` 반영.
- [ ] T-018 본체 — `krtour.map.providers.knps` 모듈 신설 + 적재 (Sprint 3)

## 다음 ADR (proposed / 후보)

**proposed (사용자 검토 대기)**:
- **ADR-027** (PR#9, merged) — forest 카테고리/notice_type 확장
  (`LODGING_MOUNTAIN_SHELTER` + `area_kind=hazard_zone` + generic
  `notice_type=access_restriction`/`fire_alert`). WEATHER_MOUNTAIN_STATION /
  NATURE_ECOLOGY / SAFETY Tier 1은 거부.
- **ADR-028** (PR#12 merged) — `python-knps-api` provider 등록. 외부 repo
  scaffold 완료 (`6e36990`). 본 라이브러리 통합 모듈 + ADR-027 코드 적용은
  Sprint 3.
- **ADR-034** (본 PR#14) — Provider 구현 9단계 순서 (축제→날씨→유가→휴게소
  →국립공원/트래킹→국가유산→**MOIS**→휴양림/수목원→박물관/미술관). MOIS
  bulk 전에 dedup 룰을 작은 dataset에서 검증. Sprint 2~5 매핑.
- **ADR-029** (PR#10) — `@krtour/map-marker-react` npm 패키지 추출 (MIT,
  monorepo). skeleton 박힘.
- **ADR-030** (PR#8) — 라이브러리 in-memory 캐시 금지. **본 PR#10에서
  `import-linter` forbidden 계약 코드 박힘**.
- **ADR-031** (PR#8) — 디버그 패키지 OpenAPI export 정책. **본 PR#10에서
  `packages/krtour-map-debug-ui/scripts/export_openapi.py` skeleton 박힘**.
- **ADR-032** (PR#8, 시기 의존) — Coverage 단계적 상향 일정. T-014에
  묶어 accepted 전환. 본 PR#10에서 `pyproject.toml` 주석에 Sprint별 schedule
  명기.
- **ADR-033** (PR#8, 시기 의존) — `feature_consistency_reports` 단계적
  도입. T-014에 묶어 accepted 전환.

**후보 (미작성)**:
- **ADR-034+** — 신규 provider 추가 절차 표준 (체크리스트)
- 후속 maki npm 게시 자동화 ADR

## 차단 사유 / 결정 대기

- (없음) 사용자가 코드 작성 시작 신호를 주기 전까지는 모두 문서 작업.

## v1 산출물 reference

코드 작성 단계에서 v1을 참고할 때:

```bash
git checkout v1                          # v1 브랜치로
ls src/krtour/map/                       # 기존 모듈 구조
cat docs/event-feature-etl.md            # provider 문서 예시
git checkout main                        # 복귀
```

또는 GitHub UI:
- https://github.com/digitie/python-krtour-map/tree/v1

저장소 루트의 `python-krtour-map-spec.docx` (약 80쪽)는 v1 산출물 + SPEC V8
정합 + kraddr-geo 디시플린을 종합한 reference. 새 에이전트가 v1 전체를 파지
않고도 핵심을 빠르게 잡을 수 있다.

## 핵심 메시지

이 단계의 미션은 "**문서가 코드보다 먼저 정확하게 박혀 있어야 한다**"다. 코드
작성이 시작되면 본 문서들의 룰이 자동 강제되어야 하고, 그 강제 수단(import-linter,
EXPLAIN 통합 테스트, fixture 회귀, 커버리지)이 모두 ADR/문서에 박혀 있어야 한다.
