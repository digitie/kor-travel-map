# resume.md — 현재 진척도와 다음 한 작업

## 현재 상태

**v2 설계 단계**. main은 orphan으로 새로 시작. v1은 `v1` 브랜치에 보존.
**코드 작성 금지** — 사용자의 별도 요청이 있을 때까지 본 저장소는 문서/계약/결정의
저장소다.

스택 확정 (ADR-007):
- PostgreSQL 16 + PostGIS 3.5 + pg_trgm + pgcrypto
- SQLAlchemy 2.x async + GeoAlchemy2 + asyncpg + psycopg[binary,pool]>=3.2
- GeoPandas + Shapely 2 + GDAL
- Pydantic v2 / FastAPI + Uvicorn / httpx + tenacity / Alembic

TripMate 연계 (ADR-003): 함수 직접 호출. REST 없음. 라이브러리가 노출하는
디버그 REST는 내부망 전용 + 인증 없음 (ADR-005).

## 다음 한 작업

**T-002** — `docs/weather-feature-normalization.md` 작성.

- v1 docs (`v1` 브랜치의 `docs/weather-feature-normalization.md`)를 v2 기준으로
  옮긴다.
- ADR-010 (`forecast_style + timeline_bucket` 분리)과 정합.
- provider별 weather_domain ↔ forecast_style ↔ timeline_bucket 매핑 표 완성.
- 표준 metric_key 표 (T1H, TMP, REH, WSD, RN1, PTY, SKY, FIRE_RISK, ...).

작업 후 `docs/journal.md` + 이 문서 갱신.

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
- [x] `docs/journal.md` (작업 일지 초기 엔트리)

### v1 → v2 도큐먼트 이관 (다음 작업들)

- [ ] T-002 `docs/weather-feature-normalization.md`
- [ ] T-003 `docs/feature-files-rustfs.md`
- [ ] T-004 `docs/feature-opening-hours.md`
- [ ] T-005 `docs/kraddr-base-types.md` + `docs/address-geocoding.md`
- [ ] T-006 provider별 ETL 문서 (10개 정도)
- [ ] T-007 `docs/dagster-boundary.md`
- [ ] T-008 `docs/postgres-schema.md` (data-model의 표 형식 reference)
- [ ] T-009 `docs/debug-fixture-workflow.md`
- [ ] T-010 `docs/feature-db-initialization.md`
- [ ] T-011 `docs/tripmate-integration.md`

### 코드 작성 단계 진입 전

- [ ] T-012 ADR-020+ 후속 결정 (캐시, OpenAPI 정책 등)
- [ ] T-013 `CHANGELOG.md` 초기 엔트리
- [ ] T-014 코드 작성 단계 진입 검토 (사용자 승인 후)

## 다음 ADR 후보

- **ADR-020** — 라이브러리 캐시 전략 (in-memory 안 두기 vs 두기)
- **ADR-021** — OpenAPI export 정책 (디버그 API 노출 시점부터 활성화)
- **ADR-022** — Coverage 단계적 상향 일정 (Sprint 1 → Sprint 5)
- **ADR-023** — 정합성 검증 (`feature_consistency_reports`) 도입 시점
- **ADR-024** — 신규 provider 추가 절차 표준 (체크리스트)

## 차단 사유 / 결정 대기

- (없음) 사용자가 코드 작성 시작 신호를 주기 전까지는 모두 문서 작업.

## v1 산출물 reference

코드 작성 단계에서 v1을 참고할 때:

```bash
git checkout v1                          # v1 브랜치로
ls src/krtour_map/                       # 기존 모듈 구조
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
