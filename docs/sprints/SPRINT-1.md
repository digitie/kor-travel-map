# SPRINT-1.md — 코드 작성 단계 진입 + scaffolding

> **상태**: ✅ **완료** (PR#17~#27 merged, 2026-05-25). T-014 사용자 승인으로
> 진입(PR#16에서 ADR 027~034 일괄 accepted + `fail_under=50`), scaffolding +
> category 이전 + CI/import-linter 활성화까지 종료. 다음은 Sprint 2 (active).
>
> **목적**: v2 설계 단계 종료 → 실제 코드 작성 단계 진입. 의존 계층 +
> 디렉토리 구조 + dto + category + 첫 통합 테스트 인프라까지.

## 1. 진입 조건 (DoD of 설계 단계)

다음이 모두 완료/확정되어야 Sprint 1 시작:

- [ ] 사용자 승인 ("코드 작성 시작" 명시 발언, ADR-021 PR로 기록)
- [ ] PR#9 (ADR-027 forest 카테고리/notice_type) merge — `LODGING_MOUNTAIN_SHELTER`
      + `area_kind=hazard_zone` + generic notice_type 결정 박힘
- [ ] PR#10 (본 PR 후속) merge — ADR-029 / CHANGELOG / pyproject 강제 /
      `packages/map-marker-react/` skeleton / export_openapi.py skeleton
- [ ] ADR-030 / ADR-031 → accepted 전환 (시기 독립)
- [ ] ADR-032 / ADR-033 → accepted 전환 (본 Sprint 1 PR과 함께)
- [ ] T-018 — `python-knps-api` provider 라이브러리가 GitHub에 첫 commit 이상
      존재 (외부 작업)

## 2. 산출물

### 2.1 디렉토리 scaffolding

```
src/kortravelmap/                  # PEP 420 implicit namespace (ADR-022)
├── __init__.py                  # 공개 API export — AsyncKorTravelMapClient 등
├── py.typed                     # PEP 561
├── category/                    # ADR-023 — kraddr-base로부터 코드 이전
│   ├── __init__.py
│   ├── definitions.py           # PLACE_CATEGORY_DEFINITIONS (144건, ADR-027 적용)
│   ├── maki.py                  # PLACE_CATEGORY_MAPBOX_MAKI_ICONS
│   └── api.py                   # get_category / iter_categories / ...
├── dto/                         # Pydantic v2 — ADR-018
│   ├── __init__.py
│   ├── feature.py               # Feature DTO + 7 detail kinds
│   ├── notice.py                # NoticeDetail + NOTICE_TYPES (14건, ADR-027 적용)
│   ├── area.py                  # AreaDetail (hazard_zone 포함, ADR-027)
│   └── ...
├── core/                        # 순수 함수 + 도메인 룰
│   ├── __init__.py
│   ├── exceptions.py
│   ├── scoring.py               # Record Linkage (ADR-016)
│   └── ...
├── infra/                       # SQL / file_store / sync_state
├── providers/                   # provider 변환 (ADR-006: client wrapper 금지)
├── client/                      # AsyncKorTravelMapClient
└── settings.py                  # KorTravelMapSettings (pydantic-settings)
```

`packages/kor-travel-map-admin/` 도 동일 시기 scaffolding (디버그 UI backend
첫 라우터는 Sprint 2부터).

### 2.2 의존 계층 강제 (ADR-002)

`pyproject.toml`의 `[[tool.importlinter.contracts]]` "layered architecture"가
이미 박혀 있음:
```
kortravelmap.cli
  → kortravelmap.client
  → kortravelmap.providers
  → kortravelmap.infra
  → kortravelmap.core
  → kortravelmap.dto
  → kortravelmap.category
```

Sprint 1 PR에서 `lint-imports` CI green 확인.

### 2.3 ADR-023 카테고리 코드 이전

`python-kraddr-base/src/kraddr/base/categories.py` (~2,072줄, 141 enum)을
`src/kortravelmap/category/`로 이전. ADR-027 적용으로 144건.

- `PLACE_CATEGORY_DEFINITIONS` tuple (144 PlaceCategory)
- `PlaceCategoryCode` Literal (`'00000000' | '01000000' | ...`)
- `PlaceCategoryTier1Code` Literal (8건 — Tier 1 enum 유지, ADR-027)
- `PLACE_CATEGORY_BY_CODE` dict
- `PLACE_CATEGORY_TIER1_NAMES` / `PLACE_CATEGORY_TIER2_NAMES_BY_TIER1` dict
- `PLACE_CATEGORY_MAPBOX_MAKI_ICONS` dict (55+1 unique icons, `shelter` 포함)
- `get_category` / `iter_categories` / `category_path` / `category_label` /
  `mapbox_maki_icon_for_category` / `format_category_tree` /
  `print_category_tree` 함수

### 2.4 NOTICE_TYPES + AreaDetail (ADR-027 코드 적용)

- `src/kortravelmap/dto/notice.py` — `NOTICE_TYPES` tuple 14건 (`access_restriction`,
  `fire_alert` 포함) + `normalize_notice_type` validator + alias 매핑.
- `src/kortravelmap/dto/area.py` — `AreaDetail.area_kind` Literal에 `hazard_zone`
  포함.

### 2.5 ADR-030 narrow 캐시 예외 코드

```python
# src/kortravelmap/category/api.py
from functools import cache

@cache
def get_category(code: PlaceCategoryCode) -> PlaceCategory:
    """ADR-030 narrow 예외 — PlaceCategoryCode는 immutable 카탈로그."""
    ...
```

```python
# src/kortravelmap/infra/crs.py
from functools import cache
from pyproj import Transformer

@cache
def transformer_4326_to_5179() -> Transformer:
    """ADR-030 narrow 예외 — pyproj.Transformer는 thread-safe immutable."""
    return Transformer.from_crs(4326, 5179, always_xy=True)
```

`pyproject.toml`의 `cachetools`/`async_lru`/`aiocache`/`diskcache` 차단 계약
은 `lint-imports`로 자동 검증.

### 2.6 첫 통합 테스트 인프라

- `tests/conftest.py` — testcontainers PostGIS fixture (`postgres_container`,
  `engine`, `session`).
- `tests/unit/test_category.py` — `get_category` smoke + Tier 1~4 count snapshot
  (144).
- `tests/integration/test_dummy_db.py` — testcontainers 기동 + `SELECT 1` 통과
  확인 (인프라 baseline).
- `tests/lint/test_import_linter.py` — `from importlinter.cli import lint_imports;
  lint_imports()` exit 0 확인 (CI에서 별도 job으로도 돌리지만 회귀 방지).

### 2.7 CI 활성화

- `.github/workflows/ci.yml` — unit / integration / fixture_replay 분리 jobs.
- `.github/workflows/lint.yml` — ruff format + mypy --strict + lint-imports.
- `.github/workflows/openapi.yml` — packages/kor-travel-map-admin/scripts/export_openapi.py
  `--check` (디버그 UI 첫 라우터 등장 시점부터 실효성, Sprint 1 시점에는
  spec이 비어 있어도 명령 자체는 작동해야 함).

## 3. Sprint 1 ADR/T 항목 진척

| 항목 | 상태 (진입 시) | DoD (Sprint 1 종료 시) |
|------|---------------|---------------------|
| ADR-023 (category 이전) | accepted (코드 미적용) | `src/kortravelmap/category/` 코드 + 테스트 통과 |
| ADR-027 (forest 카테고리 확장) | proposed (PR#9) | accepted + `PLACE_CATEGORY_DEFINITIONS` 144건 |
| ADR-030 (캐시 금지) | proposed (PR#8) | accepted + `lint-imports` 계약 green |
| ADR-031 (OpenAPI export) | proposed (PR#8) | accepted + 스크립트는 placeholder 동작 (Sprint 2부터 실효) |
| ADR-032 (Coverage schedule) | proposed (PR#8) | accepted + `fail_under=50` |
| ADR-033 (정합성 단계 도입) | proposed (PR#8) | accepted (Phase 1 코드는 Sprint 3) |

## 4. Coverage 목표 (ADR-032 Sprint 1)

| 계층 | Sprint 1 bar |
|------|------|
| 전체 (branch) | 50% |
| `core/` | 60% |
| `providers/` | 50% |
| `infra/`/`client/`/`api/` | 50% |
| `dto/` | (Sprint 2부터 100% branch) |

## 5. 비목표 (Sprint 1) — ADR-034 9단계 순서

**provider 호출은 Sprint 2부터**. ADR-034로 박힌 9단계:
- Sprint 2: ① 축제 → ② 날씨 → ③ 유가 → ④ 휴게소 (MOIS-독립 작은 dataset)
- Sprint 3: ⑤ 국립공원/트래킹 → ⑥ 국가유산 (MOIS-독립 중간 dataset)
- Sprint 4: ⑦ MOIS 인허가 (가장 큰 bulk)
- Sprint 5: ⑧ 휴양림/수목원 → ⑨ 박물관/미술관 (MOIS-sibling)

Sprint 1 비목표 (위 9단계 외에도):
- 디버그 UI backend 라우터 (Sprint 2 첫 라우터부터 ADR-031 활성화)
- bulk insert / advisory lock 실제 운영 (Sprint 4 MOIS bulk 시점)
- Record Linkage scoring 실 검증 (Sprint 2 첫 dedup 후보부터 / Sprint 4
  bulk에서 본격 검증)
- Materialized View 도입 (T-101, Sprint 5 운영 진입 이후 검토)
- streaming ETL (T-103, v2 1차 범위 밖)
- pg_prewarm 운영 정책 (T-102, 운영 진입 후)

## 6. 위험 / 차단 사유

- **kraddr-base와의 fork**: ADR-023으로 본 라이브러리가 category source of
  truth. kraddr-base는 fork point — 동기 PR 의무 없음. 단, kraddr-base 기존
  사용자는 본 라이브러리로 migration 권고 (kraddr-base README 갱신은 별도).
- **테스트 인프라 부담**: testcontainers PostGIS 첫 부팅이 느림 (수 분).
  CI에서는 dind + image cache 권장.

## 7. 종료 조건 (Sprint 1 → Sprint 2) — ✅ 전부 충족

- [x] 위 모든 산출물 merge (PR#17~#22 scaffolding + PR#24~#27 review 보강)
- [x] CI 4개 workflow green
- [x] Coverage bar 50% 통과 (실측 96%까지 상회)
- [x] `docs/journal.md` Sprint 1 종료 회고 entry
- [x] `docs/resume.md` "다음 한 작업" → Sprint 2 진입 갱신
- [x] `docs/sprints/SPRINT-2.md` 작성 — Sprint 2 진입 계획

## 8. 예상 PR 수 (참고)

Sprint 1은 5~8 PR 정도 예상 (작은 PR + 빈번한 review). 한 PR이 multi-task가
되지 않도록 ADR-021 PR-only workflow + 각 산출물별로 분할.
