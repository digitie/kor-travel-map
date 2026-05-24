# journal.md — 작업 일지 (역시간순)

가장 위가 가장 최근. 새 엔트리는 위에 append.

## 2026-05-24 22:00 (claude)

**작업**: T-002 ~ T-011 — v1 docs를 v2 기준으로 일괄 이전. 총 14개 신규 docs.

**변경 파일** (모두 신규):
- `docs/weather-feature-normalization.md` (T-002) — forecast_style + timeline_bucket
  + 표준 metric_key 30종 + provider 매핑 + build_weather_card helper.
- `docs/feature-files-rustfs.md` (T-003) — S3 호환 객체저장소 + FeatureFileSource
  → FeatureFile 흐름 + boto3 backend swap (ADR-015).
- `docs/feature-opening-hours.md` (T-004) — Google Places 호환 DTO + DB tables
  + 24/7 표기 + 자정 넘는 period.
- `docs/kraddr-base-types.md` (T-005a) — `python-kraddr-base` 주소/좌표/CRS 사용
  기준. category는 ADR-023으로 본 저장소 이전 명시.
- `docs/address-geocoding.md` (T-005b) — reverse geocoder callable + AddressMatchReport
  match_level 13종.
- `docs/dagster-boundary.md` (T-007) — 라이브러리 vs TripMate 책임 매트릭스 +
  표준 asset 패턴 + Dagster 없이도 호출 가능 (단위 테스트).
- `docs/postgres-schema.md` (T-008) — 4 schema × 20 table reference 카탈로그 +
  CHECK + FK CASCADE + 보관 정책 SQL + Alembic 가이드.
- `docs/debug-fixture-workflow.md` (T-009) — fixture JSON 스키마 + 민감정보 자동
  마스킹 + payload_hash drift 감지 + provider별 ≥3 케이스.
- `docs/feature-db-initialization.md` (T-010) — schema 부트스트랩 + Alembic +
  KrtourMapSettings + AsyncKrtourMapClient 생성 + healthz.
- `docs/tripmate-integration.md` (T-011) — TripMate가 본 라이브러리 import해서
  쓰는 패턴 + Dagster asset + FastAPI router + Admin + 권한/인증 경계.
- `docs/event-feature-etl.md` (T-006a, VisitKorea 축제)
- `docs/krmois-license-feature-etl.md` (T-006b, KRMOIS 인허가)
- `docs/opinet-place-price-etl.md` (T-006c, OpiNet 주유소+유가)
- `docs/khoa-beach-info-etl.md` (T-006d, KHOA 해수욕장)
- `docs/krheritage-feature-etl.md` (T-006e, 국가유산청 place/area/event)
- `docs/outdoor-feature-etl.md` (T-006f, 산림청 outdoor)
- `docs/krex-rest-area-feature-etl.md` (T-006g, 도로공사 휴게소+유가+기상)
- `docs/standard-data-feature-etl.md` (T-006h, data.go.kr 표준데이터 5종)
- `docs/notice-feature-etl.md` (T-006i, 4 provider 통합 notice)
- `docs/kma-weather-etl.md` (T-006j, KMA 4종 weather endpoint)
- `docs/place-phone-enrichment.md` (T-006k, Kakao/Naver/Google 전화번호 보강)
- `README.md` — 새 docs 14개 링크 추가.

**결정**: 14개 docs는 v1 패턴을 v2 기준 (krtour.map namespace, async-only, 함수
라이브러리, FastAPI 없음, kraddr-base category 이전)으로 일관 재작성. v1
원문 식별자(`*_DATASET_KEY`, `*_full_scan_job_spec`, `load_*`)는 그대로 유지해
TripMate import 변경 비용 최소화.

**발견**:
- 모든 provider ETL이 같은 패턴: collect → upload → load → sync_state.
  Dagster asset이 동일 5단계 (`docs/dagster-boundary.md` §2).
- v1 산출물은 충실히 검증되어 있고 v2는 namespace + async + 함수 라이브러리
  3 요소만 일관 적용하면 자동으로 정합.
- `notice-feature-etl.md`는 4 provider 통합 단일 doc — provider별 분리 안 함
  (notice_type 정규화가 공통).

**다음**: feature branch `docs/v1-to-v2-feature-ports` push + PR 작성 (PR#1 위
stacked). 사용자 검토 후 squash merge.

---

## 2026-05-24 20:30 (claude)

**작업**: PR-only 룰 추가 + namespace 재명명 (`krtour_map` → `krtour.map`) +
kraddr-base category 모듈 이전 결정 + kraddr-geo 패턴 보강.

**변경 파일**:
- `docs/decisions.md` — ADR-021 (PR-only), ADR-022 (`krtour` namespace),
  ADR-023 (category 이전) 3건 추가.
- `AGENTS.md` — 식별자 표 (Python import → `krtour.map`, category 모듈 출처
  추가), DO NOT #17/#18/#19 추가 (PR-only, flat import 금지, `src/krtour/
  __init__.py` 금지) → 19개 룰.
- `SKILL.md` — 식별자 표, 디렉토리 지도, DO NOT #19/#20/#21 추가 → 22개 룰.
- `CLAUDE.md` — 5 절대금지를 가장 중요한 5개로 재구성 (PR-only, namespace 1·2위).
- `README.md` — Python import 경로, 디렉토리(`src/krtour/map/` + namespace
  설명), 문서 지도에 `docs/category.md` 추가.
- `pyproject.toml` — `packages.find` (`krtour.map*` + `namespaces=true`),
  `package-data`, `import-linter` root_package + layers + forbidden 계약 갱신,
  coverage source.
- `packages/krtour-map-debug-ui/pyproject.toml` + `README.md` — namespace 정합.
- 일괄 docs 갱신 (rename script): `architecture`, `backend-package`, `decisions`,
  `test-strategy`, `windows-reinstall-recovery`, `dev-environment`, `external-apis`,
  `provider-contract`, `debug-ui-package`, `feature-model`, `resume`, `journal`,
  `CHANGELOG`.
- `docs/category.md` (신규) — `krtour.map.category` 모듈 사양서 11절.
- `docs/agent-guide.md` — §7.5 PR 워크플로 신설 (브랜치 명명, commit format,
  PR 본문 표준 포맷, branch protection, 핸드오프).
- `docs/tasks.md` — Sprint 5 진입 직전 항목 5개 추가 (T-200~T-204: batch DAG,
  consistency_reports, pre-commit hook, CI 워크플로, branch protection 가이드).

**결정**:
- **ADR-021** main 직접 push 금지 — 모든 변경은 feature branch + PR. main에 직접
  들어간 `fc8145f`/`304f2a9`는 ex post facto 인정, 본 ADR 이후 모든 변경은 PR.
- **ADR-022** `krtour` PEP 420 implicit namespace 채택 — `python-krtour-map`은
  `krtour.map`으로 import, `krtour-map-debug-ui`는 `krtour.map_debug_ui`로
  import. 같은 namespace를 share. `src/krtour/__init__.py` 금지.
- **ADR-023** kraddr-base의 category 모듈 (`kraddr.base.categories`, ~2072줄,
  141 enum)을 `krtour.map.category`로 이전. 코드 이전은 코드 작성 단계 진입 시
  별도 PR. 라이선스 호환 (둘 다 GPL-3.0-or-later).

**발견**:
- kraddr-geo ADR-015도 `kraddr` implicit namespace 채택 → 패턴 정합.
- kraddr-geo의 batch DAG + consistency_reports 패턴(ADR-017)이 본 라이브러리의
  Sprint 5 운영에 유용 → T-200/T-201로 백로그 추가.
- 변수 이름 `krtour_map_client`(snake_case)는 변경 안 함 — Python 식별자 명명
  규약과 import path는 별개.

**다음**: feature branch `chore/pr-workflow-namespace-rename-category-migration`
push → PR 작성 (ADR-021 첫 적용 사례). 사용자 리뷰 후 squash merge.

---

## 2026-05-24 19:30 (claude)

**작업**: 디버그 UI를 별도 Python 패키지로 분리 — ADR-020 추가 + 관련 문서/구조
일괄 갱신.

**변경 파일**:
- `docs/decisions.md` — ADR-020 추가. ADR-005 상태에 "위치 부분 superseded" 명시.
- `docs/architecture.md` — 큰 그림 도식에 별도 패키지 블록 추가. `§4 디버그 REST
  API`를 별도 패키지 형태로 재작성. §7 모듈 표에 디버그 패키지 모듈 추가. §8
  ADR-020 추가. §9 v1↔v2 표 갱신.
- `docs/backend-package.md` — 디버그 API 절을 축약하고 `docs/debug-ui-package.md`
  reference로 redirect.
- `docs/debug-ui-package.md` (신규) — 본 패키지 사양서 14절 (정체성/디렉토리/
  의존방향/settings/기동/엔드포인트/응답/OpenAPI/테스트/운영주의/비책임/확장/배포/
  핵심 메시지).
- `AGENTS.md` — 식별자 표 (별도 Python 패키지 명시), TripMate 경계 갱신,
  디버그 API 정책 절 재작성, DO NOT #14 갱신 + #15 신규 (메인 라이브러리 FastAPI
  import 금지) → 총 16개 룰.
- `SKILL.md` — 식별자 표, 디렉토리 지도 (메인 + 별도 패키지 2 block), DO NOT
  목록에 신규 룰 #15 추가 → 총 19개 룰.
- `CLAUDE.md` — 패키지 분리 1줄 요약 + DO NOT 5개 중 #2/#5 갱신.
- `README.md` — TripMate 연계 문구, 빠른 시작 (디버그 UI 별도 install), 의존
  스택 표 (FastAPI는 별도 패키지로 표시), 디렉토리 (monorepo 2 패키지), 문서 지도.
- `pyproject.toml` — `[api]` extra 제거 (ADR-020 §후속). `import-linter`에 두
  번째 계약 추가 (`krtour_map`에서 fastapi/uvicorn/starlette import 금지).
- `.env.example` — `KRTOUR_MAP_DEBUG_API_*` → `KRTOUR_MAP_DEBUG_UI_*` 갱신 +
  주석.
- `docs/test-strategy.md` — e2e 코드 예시의 `from krtour.map.api.app import ...`
  → `from krtour.map_debug_ui.app import ...`.
- `packages/krtour-map-debug-ui/pyproject.toml` (신규) — 별도 패키지 pyproject.
- `packages/krtour-map-debug-ui/README.md` (신규) — 패키지 README.

**결정**: **ADR-020** — 디버그 UI는 별도 Python 패키지 `krtour-map-debug-ui`로
분리. monorepo 안 `packages/krtour-map-debug-ui/`에 위치. 메인 라이브러리에서
FastAPI/Uvicorn 의존성 제거. ADR-005의 위치 부분(`krtour.map.api`)은 본 ADR로
superseded; 인증 없음 + 내부망 전용 정책은 그대로 유지.

**발견**:
- 메인 라이브러리가 FastAPI 의존을 짊어지면 TripMate에 불필요한 의존성이
  딸려간다. 분리로 install footprint 축소.
- `import-linter`의 `forbidden` 계약으로 메인 패키지의 FastAPI import를 CI에서
  자동 차단 가능.
- v1의 `packages/krtour-map-debug-ui/` 디렉토리 패턴(monorepo Python 서브패키지)
  과 일관됨.

**다음**: 사용자 검토 후 commit + push. T-002(weather-feature-normalization.md
v1→v2 정리)로 복귀.

---

## 2026-05-24 19:00 (claude)

**작업**: v2 설계 단계 진입 — main을 orphan으로 새로 시작하고 핵심 문서 일괄 작성.

**변경 파일**:
- 루트:
  - `AGENTS.md` (지시 우선순위, DO NOT 18개, TripMate 함수 라이브러리 경계, 디버그 API 인증 없음)
  - `README.md` (정체성, 빠른 시작, 의존 스택 표, 문서 지도)
  - `SKILL.md` (DO NOT 18개 + 도메인 어휘 + 자주 묻는 작업)
  - `CLAUDE.md` (1쪽 진입 요약)
  - `LICENSE` (GPL-3.0-or-later)
  - `.gitignore`, `.gitattributes`, `.env.example`
  - `pyproject.toml` (스택 placeholder + ruff/mypy/pytest 설정 + import-linter 계약 박힘)
- `docs/`:
  - `architecture.md` (의존 방향 + 데이터 흐름 + 모듈 표 + v1 대비 변경)
  - `decisions.md` (ADR-001 ~ ADR-019)
  - `data-model.md` (4 schema × 16 table 전체 DDL + 인덱스 + CHECK)
  - `performance.md` (인덱스 설계 + 공간 쿼리 가이드 + bulk + 안티패턴 매트릭스)
  - `test-strategy.md` (4단계 테스트 + Fake repo + EXPLAIN 검증 + Coverage 목표)
  - `backend-package.md` (라이브러리 진입점 + 디버그 REST API + 사용 시나리오)
  - `agent-guide.md` (첫 5분 + ADR 형식 + 변경 분류별 체크리스트)
  - `dev-environment.md` (WSL ext4/NTFS + Docker PostGIS + 초기 셋업)
  - `windows-reinstall-recovery.md` (세션 복구 + PR handoff 노트 포맷)
  - `feature-model.md` (Feature DTO + 5 detail + opening hours + weather/price)
  - `provider-contract.md` (wrapper 금지 + canonical name + dataset_key 표 + 변환 함수 골격)
  - `external-apis.md` (provider별 API 키 발급/호출 + 비용 + 모니터링)
  - `tasks.md`, `resume.md`, `journal.md` (운영 docs 초기)

**결정**:
- ADR-001 ~ ADR-019 19건 박음. 핵심:
  - **ADR-003** TripMate ↔ 라이브러리는 함수 직접 호출 (REST 없음).
  - **ADR-005** 디버그 REST API는 인증 없음, 내부망 전용.
  - **ADR-006** provider adapter/wrapper 신규 생성 금지.
  - **ADR-007** 의존 스택 — kraddr-geo와 동일.
  - **ADR-008** PostGIS는 `x_extension` schema 격리.
  - **ADR-012** 공간 쿼리 1회 변환 + `coord_5179` 컬럼.
  - **ADR-013** bulk insert는 `psycopg.copy_*` 우선 (30k 안전 마진).
  - **ADR-014** 4단계 테스트 + Coverage 목표 (core 90+ / infra 80+ / 전체 80+).
  - **ADR-018** `Feature.detail` 자유 dict 금지 (`DETAIL_MODELS` 분기).
  - **ADR-019** KST aware datetime만 허용.
- git: 현재 작업 모두 commit 후 `v1` 브랜치 생성 + origin push, main orphan 재시작
  + force-push origin/main.

**발견**:
- `python-krtour-map-spec.docx` (저장소 루트, 약 80쪽)는 v1 산출물 + SPEC V8 정합 +
  kraddr-geo 디시플린 종합 reference로 유용.
- 사용자가 명시: TripMate 연계는 함수 라이브러리 형태, REST는 디버그 UI + 향후
  내부 활용 (인증 없음). 이를 ADR-003/ADR-005로 박음.
- 사용자 강조: 속도 최적화는 설계 단계부터, 테스트는 촘촘하게.
  → `docs/performance.md` (인덱스 설계 + 안티패턴), `docs/test-strategy.md`
    (4단계 + EXPLAIN 검증)으로 박음.
- kraddr-geo와 동일 스택 (PostgreSQL + PostGIS + SQLAlchemy 2 async + GeoAlchemy2
  + GeoPandas)을 ADR-007로 명시.

**다음**: T-002 — `docs/weather-feature-normalization.md` 작성. v1 docs를
v2 기준으로 정리해 옮긴다.

---

## 2026-05-24 18:00 (claude)

**작업**: v1 작업 보존 — 현재 main의 모든 작업(provider ETL, 디버그 UI,
docs, spec docx)을 `v1` 브랜치로 commit하고 origin/v1로 push.

**변경 파일**: 56 files changed, 2858 insertions(+), 490 deletions(-)
- providers: visitkorea, krmois, krheritage, opinet, krex, krforest, khoa,
  datagokr (standard 5 + extras), notices
- DB 스키마, RustFS file 메타, 전화번호 보강
- Debug UI 패키지 (packages/krtour-map-debug-ui)
- Extensive docs 수정
- `python-krtour-map-spec.docx` (AI 에이전트용 사양 80쪽)

**결정**: 사용자 요청 — v1 보존, main 재시작, orphan 히스토리, origin force-push.

**발견**: `~$python-krtour-map-spec.docx` Word lock 파일을 `.gitignore`에 추가.

**다음**: 새 main(orphan) 시작 후 v2 설계 문서 일괄 작성.
