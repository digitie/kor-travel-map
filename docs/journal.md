# journal.md — 작업 일지 (역시간순)

가장 위가 가장 최근. 새 엔트리는 위에 append.

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
- `docs/test-strategy.md` — e2e 코드 예시의 `from krtour_map.api.app import ...`
  → `from krtour_map_debug_ui.app import ...`.
- `packages/krtour-map-debug-ui/pyproject.toml` (신규) — 별도 패키지 pyproject.
- `packages/krtour-map-debug-ui/README.md` (신규) — 패키지 README.

**결정**: **ADR-020** — 디버그 UI는 별도 Python 패키지 `krtour-map-debug-ui`로
분리. monorepo 안 `packages/krtour-map-debug-ui/`에 위치. 메인 라이브러리에서
FastAPI/Uvicorn 의존성 제거. ADR-005의 위치 부분(`krtour_map.api`)은 본 ADR로
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
